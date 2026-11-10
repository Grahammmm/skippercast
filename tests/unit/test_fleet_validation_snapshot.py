"""skippercast.fleet.ais.validate.fetch_labels: a broken labels response must not prune the validation copies.

``sync`` removes every trip copy absent from the fetched inventory, and those copies can be the only raw
positions left after retention. So the inventory is admitted whole or the sync fails, before any write.
Synthetic throughout (the validation tests' fictional trips and fake Worker).
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast.fleet.ais import validate
from skippercast.fleet.ais.events import iso_utc
from skippercast.fleet.ais.process import HOUR, WorkerError
from skippercast.fleet.ais.store import AisStore
from tests.unit.test_fleet_process import REGION, T0, track
from tests.unit.test_fleet_validate import LABELS, OTHER, TRIP, LabelWorker, trip_row

NOW = T0 + 8 * HOUR
FIRST, SECOND = sorted((TRIP, OTHER))
A, B, C = "1" * 32, "2" * 32, "3" * 32


class PagesWorker:
    """Serves the given pages in order and fails the test on a request beyond them."""

    def __init__(self, *pages):
        self.pages, self.calls = list(pages), []

    def get(self, path, **params):
        self.calls.append((path, params))
        if len(self.calls) > len(self.pages):
            raise AssertionError("fetch_labels asked for more pages than the response allows")
        return self.pages[len(self.calls) - 1]


def page(trips, next_id=None, region="CA"):
    return {"region": region, "trips": trips, "next": next_id}


def row(trip_id):
    return trip_row(trip_id)


class SnapshotCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "CA" / "ais"
        AisStore(self.root).write(positions=track())
        self.directory = self.root / "validation"

    def seed(self):
        """A real successful sync of two labelled trips, plus report files and a sidecar."""
        validate.sync(REGION, LabelWorker([trip_row(), trip_row(OTHER)]), self.root, now_ms=NOW)
        (self.directory / "report.json").write_text('{"kept": true}')
        (self.directory / "report.md").write_text("kept report")
        (self.directory / f"{OTHER}.sqlite-wal").write_bytes(b"sidecar")
        return self.snapshot()

    def snapshot(self):
        return {str(p.relative_to(self.directory)): p.read_bytes() for p in sorted(self.directory.rglob("*")) if p.is_file()}

    def refuse(self, worker):
        """sync fails with WorkerError and touches nothing: no write, no copy, no prune."""
        with mock.patch.object(validate, "_write_json", wraps=validate._write_json) as write, \
                mock.patch.object(validate, "_copy", wraps=validate._copy) as copy:
            with self.assertRaises(WorkerError) as caught:
                validate.sync(REGION, worker, self.root, now_ms=NOW + HOUR)
        write.assert_not_called()
        copy.assert_not_called()
        return str(caught.exception)


class BadPageTests(SnapshotCase):
    def test_bad_label_page_preserves_last_complete_snapshot(self):
        cases = {
            "malformed-next": PagesWorker(page([row(FIRST)], "not-a-trip-id")),
            "missing-trips": PagesWorker({"region": "CA", "next": None}),
            "repeated-next-on-second-page": PagesWorker(page([row(FIRST)], FIRST), page([row(SECOND)], FIRST)),
            "nonobject-trip": PagesWorker(page([row(FIRST), "oops"])),
            "wrong-region-empty": PagesWorker(page([], None, region="XX")),
        }
        for name, worker in cases.items():
            with self.subTest(name):
                before = self.seed()
                self.refuse(worker)
                self.assertEqual(self.snapshot(), before, "labels.json, copies, sidecars and reports are untouched")
                self.assertEqual(len(validate.read_copy(self.directory / f"{TRIP}.sqlite")), len(track()))

    def test_label_envelope_requires_explicit_members(self):
        good = row(A)
        cases = {
            "nonobject page": ["a list, not a page"],
            "trips missing": {"region": "CA", "next": None},
            "trips null": {"region": "CA", "trips": None, "next": None},
            "trips object": {"region": "CA", "trips": {}, "next": None},
            "trips string": {"region": "CA", "trips": "x", "next": None},
            "next missing": {"region": "CA", "trips": [good]},
            "region missing": {"trips": [good], "next": None},
            "region mismatch": page([good], None, region="XX"),
            "nondict trip": page([good, None]),
            "trip id missing": page([{**good, "id": None}]),
            "trip id nonstring": page([{**good, "id": 7}]),
            "trip id uppercase": page([{**good, "id": "A" * 32}]),
            "trip id newline suffix": page([{**good, "id": A[:31] + "\n"}]),
            "trip id newline after 32": page([{**good, "id": A + "\n"}]),
        }
        for name, response in cases.items():
            with self.subTest(name):
                worker = PagesWorker(response)
                with mock.patch.object(validate, "_write_json") as write:
                    with self.assertRaises(WorkerError) as caught:
                        validate.sync(REGION, worker, self.root, now_ms=NOW)
                write.assert_not_called()
                self.assertFalse(self.directory.exists(), "no validation directory is created for a refused inventory")
                self.assertEqual(len(worker.calls), 1)
                self.assertTrue(str(caught.exception).startswith("labels page 1: "))

    def test_label_cursor_requires_exact_forward_progress(self):
        cases = {   # name: (pages, requests made)
            "malformed next": ([page([row(A)], "xyz")], 1),
            "empty next": ([page([row(A)], "")], 1),
            "numeric next": ([page([row(A)], 5)], 1),
            "uppercase next": ([page([row(A)], "A" * 32)], 1),
            "next with newline": ([page([row(A)], A + "\n")], 1),
            "next beyond the last row": ([page([row(A)], B)], 1),
            "next before the last row": ([page([row(A), row(B)], A)], 1),
            "nonterminal empty page": ([page([], A)], 1),
            "repeated cursor": ([page([row(A)], A), page([row(B)], A)], 2),
            "backward cursor": ([page([row(B)], B), page([row(C)], A)], 2),
            "duplicate id in a page": ([page([row(A), row(A)])], 1),
            "out-of-order ids": ([page([row(B), row(A)])], 1),
            "id repeated across pages": ([page([row(A)], A), page([row(A)])], 2),
            "id behind the cursor": ([page([row(B)], B), page([row(A)])], 2),
        }
        for name, (pages, requests) in cases.items():
            with self.subTest(name):
                worker = PagesWorker(*pages)
                with self.assertRaises(WorkerError) as caught:
                    validate.fetch_labels(worker, "CA")
                self.assertEqual(len(worker.calls), requests)
                self.assertRegex(str(caught.exception), r"^labels page [12]: [a-z ]+$")

    def test_refusal_names_no_trip_id_cursor_or_body(self):
        message = self.refuse(PagesWorker(page([row(FIRST)], "secret-cursor-value")))
        self.assertEqual(message, "labels page 1: next is not the last trip id of the page")
        for private in (FIRST, "secret-cursor-value", iso_utc(T0), "port-a"):
            self.assertNotIn(private, message)


class CompleteInventoryTests(SnapshotCase):
    def test_complete_inventory_and_empty_inventory_keep_existing_semantics(self):
        one = row(FIRST)
        one["extra"] = {"kept": "unchanged"}
        rows = validate.fetch_labels(PagesWorker(page([one], FIRST), page([row(SECOND)])), "CA")
        self.assertEqual([r["id"] for r in rows], [FIRST, SECOND])
        self.assertEqual(rows[0], one, "accepted rows pass through unchanged")
        self.assertEqual([r["id"] for r in validate.fetch_labels(PagesWorker(page([row(A)])), "CA")], [A],
                         "one nonempty terminal page is valid")
        # A valid multipage sync copies both trips and rewrites the snapshot.
        counts = validate.sync(REGION, PagesWorker(page([row(FIRST)], FIRST), page([row(SECOND)])), self.root, now_ms=NOW)
        self.assertEqual((counts["trips"], counts["copied"], counts["removed"]), (2, 2, 0))
        stored = json.loads((self.directory / "labels.json").read_text())
        self.assertEqual([t["id"] for t in stored["trips"]], [FIRST, SECOND])
        # A complete empty inventory intentionally removes the unlabelled copies and their sidecars.
        (self.directory / f"{SECOND}.sqlite-wal").write_bytes(b"")
        counts = validate.sync(REGION, PagesWorker(page([])), self.root, now_ms=NOW)
        self.assertEqual(counts["removed"], 2)
        self.assertEqual(sorted(p.name for p in self.directory.glob("*.sqlite*")), [])
        # A labelled orphan keeps its copy.
        validate.sync(REGION, LabelWorker([trip_row()]), self.root, now_ms=NOW)
        orphan = {"id": TRIP, "mmsi": None, "source": None, "departed_at": None, "orphan": True, "labels": LABELS}
        counts = validate.sync(REGION, PagesWorker(page([orphan])), self.root, now_ms=NOW)
        self.assertEqual((counts["orphaned"], counts["removed"]), (1, 0))
        self.assertTrue((self.directory / f"{TRIP}.sqlite").exists())


class CommandLineTests(SnapshotCase):
    def test_sync_cli_refuses_without_private_details_or_report(self):
        var = Path(self.tmp.name)
        before = self.seed()
        worker = PagesWorker(page([row(FIRST)], "bad-cursor"))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(var)}), \
                mock.patch.object(validate, "job_worker", return_value=worker), \
                mock.patch.object(validate, "report", side_effect=AssertionError("no scoring after a refused sync")), \
                redirect_stdout(out), redirect_stderr(err):
            code = validate.main(["--region", "CA"])
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue(), "fleet ais validate: labels page 1: next is not the last trip id of the page\n")
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(self.snapshot(), before, "snapshot, copies and previous reports are untouched")
        for private in (FIRST, SECOND, "bad-cursor", "port-a"):
            self.assertNotIn(private, err.getvalue())


if __name__ == "__main__":
    unittest.main()
