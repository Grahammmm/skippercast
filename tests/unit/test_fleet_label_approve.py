"""label approve: a second agent's approval of an agent's label set, and the agent-approved labeller kind.

Synthetic trip ids, agent names and times only.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast.fleet.ais import label as labelling
from skippercast.fleet.ais.process import WorkerError
from skippercast.fleet.ais.validate import LabelledTrip

FIRST, SECOND = "a" * 32, "b" * 32
SPAN = {"started_at": "2026-10-05T10:00Z", "ended_at": "2026-10-05T10:30:00Z", "label": "drift-anchor"}


class FakeWorker:
    def __init__(self, refuse_at=None):
        self.calls, self.refuse_at = [], refuse_at

    def post(self, path, body):
        if len(self.calls) == self.refuse_at:
            raise WorkerError("HTTP 409: the labeller's labels on this trip differ from the reviewed set")
        self.calls.append((path, body))
        return {"ok": True, "approved": len(body["labels"])}


def entry(trip=FIRST, **extra):
    return {"trip_id": trip, "labeller": "agent:proposer", "approver": "agent:checker", "labels": [dict(SPAN)], **extra}


class LabelApproveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def file(self, entries):
        path = self.dir / "approve.json"
        path.write_text(json.dumps(entries))
        return path

    def test_posts_the_normalised_reviewed_set_per_trip(self):
        worker = FakeWorker()
        counts = labelling.approve_labels(self.file([entry(), entry(SECOND)]), worker)
        self.assertEqual(counts, {"trips": 2, "labels": 2, "approved": 2, "posted": 2})
        self.assertEqual([p for p, _ in worker.calls], ["labels/approve", "labels/approve"])
        self.assertEqual(worker.calls[0][1], {"trip_id": FIRST, "labeller": "agent:proposer", "approver": "agent:checker",
                                              "labels": [{"started_at": "2026-10-05T10:00:00.000Z",
                                                          "ended_at": "2026-10-05T10:30:00.000Z", "label": "drift-anchor"}]})

    def test_refuses_locally_and_posts_nothing(self):
        cases = [
            (entry(approver="agent:proposer"), "different agent"),        # an agent never approves itself
            (entry(approver="admin-1"), "must be agent:<name>"),
            ({**entry(), "region": "CA"}, "only"),
            (entry(labels=[]), "1 to 200"),
            (entry(labels=[{**SPAN, "basis": "x y"}]), "label 1"),         # the reviewed set carries no basis
            (entry(labels=[{**SPAN, "label": "fishing"}]), "label 1"),
            (entry(labels=[{**SPAN, "started_at": "2026-02-30T10:00Z"}]), "label 1"),
            ([entry(), entry()], "once per file"),
        ]
        for entries, message in cases:
            worker = FakeWorker()
            with self.subTest(message=message), self.assertRaises(ValueError) as error:
                labelling.approve_labels(self.file(entries), worker)
            self.assertIn(message, str(error.exception))
            self.assertEqual(worker.calls, [], "a failed check posts nothing")
            self.assertNotIn(FIRST, str(error.exception), "errors never name a trip id")

    def test_a_worker_refusal_stops_at_that_trip_without_its_id(self):
        worker = FakeWorker(refuse_at=1)
        with self.assertRaises(WorkerError) as error:
            labelling.approve_labels(self.file([entry(), entry(SECOND)]), worker)
        self.assertIn("at entry 2; 1 of 2 trips approved", str(error.exception))
        self.assertNotIn(SECOND, str(error.exception))

    def test_cli_dry_run_checks_only(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = labelling.main(["approve", str(self.file([entry()])), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), {"trips": 1, "labels": 1, "approved": 0, "posted": 0})
        worker = FakeWorker()
        with redirect_stderr(io.StringIO()) as err, mock.patch.object(labelling, "job_worker", return_value=worker):
            self.assertEqual(labelling.main(["approve", str(self.file([entry(approver="agent:proposer")]))]), 2)
        self.assertIn("different agent", err.getvalue())
        self.assertEqual(worker.calls, [], "a refused file posts nothing")


class LabellerKindTests(unittest.TestCase):
    def test_agent_approved_labels_are_their_own_kind(self):
        def lab(start, labeller):
            return {"started_at": f"2026-10-05T{start}:00Z", "ended_at": f"2026-10-05T{start}:30Z", "label": "transit",
                    "labeller": labeller}
        trip = LabelledTrip.from_row({"id": FIRST, "mmsi": 999000001, "source": "aisstream",
                                      "departed_at": "2026-10-05T09:00Z", "returned_at": "2026-10-05T13:00Z",
                                      "labels": [lab("10", "admin-1"), lab("11", "agent:proposer"),
                                                 lab("12", "agent-approved:checker")]})
        starts = {kind: [i.start for i in trip.intervals(kind)] for kind in ("admin", "agent", "agent-approved", "all")}
        self.assertEqual([len(starts[k]) for k in ("admin", "agent", "agent-approved", "all")], [1, 1, 1, 3])
        self.assertNotEqual(starts["admin"], starts["agent-approved"], "an agent-approved label never counts as an admin's")


if __name__ == "__main__":
    unittest.main()
