"""Label import measures ``basis`` in the Worker's UTF-16 code units (labels.ts ``basis.length``), offline."""
from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast.fleet.ais import label as labelling

FIRST, SECOND = "a" * 32, "b" * 32
WAVE = "\U0001F30A"   # one scalar, two UTF-16 units
OVER = "basis is required (2 to 500 characters)"


class FakeWorker:
    def __init__(self):
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))


class LabelBasisUnitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        window = {"window": {"from": "2026-10-05T09:00:00.000Z", "to": "2026-10-05T12:00:00.000Z"}}
        for tid in (FIRST, SECOND):
            (self.dir / f"{tid}.json").write_text(json.dumps(window))

    @staticmethod
    def entry(basis, trip=FIRST):
        label = {"started_at": "2026-10-05T10:00:00.000Z", "ended_at": "2026-10-05T10:30:00.000Z", "label": "transit"}
        if basis is not None:
            label["basis"] = basis
        return {"trip_id": trip, "labeller": "agent:synthetic", "labels": [label]}

    def write(self, *entries):
        path = self.dir / "proposals.json"
        path.write_text(json.dumps(list(entries)))   # ensure_ascii: lone surrogates stay escaped
        return path

    def refused(self, basis, first_valid=True):
        entries = ([self.entry("ordinary basis")] if first_valid else []) + [self.entry(basis, SECOND)]
        worker = FakeWorker()
        with self.assertRaises(ValueError) as caught:
            labelling.import_labels(self.write(*entries), worker)
        self.assertEqual(worker.calls, [], "nothing is posted when any entry fails")
        message = str(caught.exception)
        self.assertEqual(message, f"entry {len(entries)} label 1: {OVER}")
        self.assertNotIn(SECOND, message)
        self.assertNotIn("2026-", message)
        return message

    def accepted(self, basis):
        worker = FakeWorker()
        counts = labelling.import_labels(self.write(self.entry(basis)), worker)
        self.assertEqual(counts, {"trips": 1, "labels": 1, "posted": 1})
        (path, body), = worker.calls
        self.assertEqual(path, "labels")
        self.assertEqual(body["labels"][0]["basis"], basis.strip())

    def test_astral_upper_limit_refuses_before_any_post(self):
        basis = WAVE * 251   # 251 code points, 502 units
        self.refused(basis)
        _, errors = labelling.check([self.entry("ordinary basis"), self.entry(basis, SECOND)], self.dir)
        self.assertEqual(errors, [f"entry 2 label 1: {OVER}"])

    def test_exact_maximum_mixed_text_is_preserved(self):
        for basis in (WAVE * 250, "a" * 498 + WAVE, "a" * 500, "  " + WAVE * 250 + "\t"):
            with self.subTest(units=len(basis.encode("utf-16-le", "surrogatepass")) // 2):
                self.accepted(basis)

    def test_one_unit_over_maximum_refuses_after_trimming(self):
        for basis in ("a" * 499 + WAVE, "a" * 501, "\u00e9" * 501, WAVE * 251, "  " + WAVE * 251 + "  "):
            with self.subTest(units=len(basis.encode("utf-16-le", "surrogatepass")) // 2):
                self.refused(basis)

    def test_minimum_counts_worker_units(self):
        for basis in ("", "   ", "a", " a ", "\u00e9"):
            with self.subTest(refused=repr(basis)):
                self.refused(basis)
        for basis in ("ab", " ab ", WAVE, "e\u0301"):   # a combining sequence is two units, not one grapheme
            with self.subTest(accepted=repr(basis)):
                self.accepted(basis)

    def test_dry_run_uses_same_bounds_and_no_worker(self):
        bad = self.write(self.entry("ordinary basis"), self.entry(WAVE * 251, SECOND))
        err = io.StringIO()
        with mock.patch.object(labelling, "job_worker", side_effect=AssertionError("no Worker")), redirect_stderr(err):
            self.assertEqual(labelling.main(["import", str(bad), "--dry-run"]), 2)
            self.assertEqual(err.getvalue(), f"fleet ais label: entry 2 label 1: {OVER}\n")
            good = self.write(self.entry(WAVE * 250))
            self.assertEqual(labelling.main(["import", str(good), "--dry-run"]), 0)
            self.assertEqual(labelling.import_labels(good), {"trips": 1, "labels": 1, "posted": 0})

    def test_bad_type_and_surrogate_input_do_not_crash(self):
        for basis in (None, 7, ["ab"], {"a": "b"}):
            with self.subTest(basis=repr(basis)):
                self.refused(basis)
        for basis in ("\ud800\ud800", "\udc00" * 500):   # lone surrogate code units: one unit each
            with self.subTest(units=len(basis.encode("utf-16-le", "surrogatepass")) // 2):
                self.accepted(basis)
        self.refused("\ud800" * 501)
        self.refused("\ud800" * 250 + WAVE * 126)   # 250 + 252 units

    def test_other_validation_and_ascii_body_are_unchanged(self):
        worker = FakeWorker()
        labelling.import_labels(self.write(self.entry("  slow track  "), {**self.entry("fine", SECOND), "labels": []}), worker)
        self.assertEqual([b for _, b in worker.calls], [
            {"trip_id": FIRST, "labeller": "agent:synthetic", "labels": [
                {"started_at": "2026-10-05T10:00:00.000Z", "ended_at": "2026-10-05T10:30:00.000Z",
                 "label": "transit", "basis": "slow track"}]},
            {"trip_id": SECOND, "labeller": "agent:synthetic", "labels": []}])
        late = self.entry("ok")
        late["labels"][0]["ended_at"] = "2026-10-05T13:00:00.000Z"
        for entry, message in ((late, "within the trip's export window"),
                               (self.entry("ok", FIRST + "\n"), "trip_id must be 32 hex characters")):
            with self.subTest(message):
                _, errors = labelling.check([entry], self.dir)
                self.assertEqual(len(errors), 1)
                self.assertIn(message, errors[0])
        label = self.entry("ok")["labels"][0]
        overlap = {**self.entry("ok"), "labels": [label, {**label, "started_at": "2026-10-05T10:10:00.000Z"}]}
        self.assertIn("labels 1 and 2 overlap", labelling.check([overlap], self.dir)[1][0])


if __name__ == "__main__":
    unittest.main()
