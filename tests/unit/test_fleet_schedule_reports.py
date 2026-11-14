"""fleet ais schedule-precision: --reports is admitted before any registry access (RF0345-8).

Synthetic throughout: report files in a temporary directory; region loading, the Worker
snapshot, the raw store and ``precision`` are replaced by fakes that fail if reached.
"""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from skippercast.fleet import config
from skippercast.fleet.ais import match, process, schedule


class ReportsFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.vessels = self.dir / "vessels.json"
        self.vessels.write_text("[]")

    def run_main(self, reports: Path, with_vessels: bool, *, region_side_effect=None):
        argv = ["--region", "CA", "--from", "2026-10-01", "--to", "2026-10-02", "--reports", str(reports),
                "--root", str(self.dir)]
        if with_vessels:
            argv += ["--vessels", str(self.vessels)]
        spies = SimpleNamespace(
            region=mock.patch.object(config, "load_region", side_effect=region_side_effect or AssertionError("region reached")),
            worker=mock.patch.object(process, "Worker", side_effect=AssertionError("Worker reached")),
            snapshot=mock.patch.object(match, "read_snapshot", side_effect=AssertionError("snapshot reached")),
        )
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                spies.region as lr, spies.worker as wk, spies.snapshot as sn, \
                mock.patch.dict(process.STORES, {"marinecadastre": mock.Mock(side_effect=AssertionError("store reached"))}), \
                mock.patch.object(schedule, "precision", side_effect=AssertionError("precision reached")):
            code = schedule.main(argv)
        self.assertEqual((lr.call_count, wk.call_count, sn.call_count), (1 if region_side_effect else 0, 0, 0))
        return code, out.getvalue(), err.getvalue()

    def write(self, name: str, data: bytes) -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path

    def assert_refused(self, path: Path, message: str):
        for with_vessels in (True, False):
            code, out, err = self.run_main(path, with_vessels)
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertTrue(err.startswith(f"fleet ais schedule-precision: {path}: {message}"), err[:200])
            self.assertNotIn("Traceback", err)

    def test_deep_reports_json_refuses_before_registry_access(self):
        self.assertRaisesRegex(ValueError, "not readable JSON",
                               schedule._read_reports, self.write("deep.json", b"[" * 10000 + b"]" * 10000))
        self.assert_refused(self.write("deep.json", b"[" * 10000 + b"]" * 10000), "not readable JSON")
        self.assert_refused(self.write("deep2.json", b"[" * 10000), "not readable JSON")

    def test_reports_decode_failures_are_named_and_early(self):
        self.assert_refused(self.write("bad.json", b'[{"id": '), "not readable JSON")
        self.assert_refused(self.write("utf.json", b'[{"id": "\xff"}]'), "not readable JSON")
        for with_vessels in (True, False):
            code, out, err = self.run_main(self.dir / "missing.json", with_vessels)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("missing.json", err)
            self.assertNotIn("not readable JSON", err)

    def test_reports_top_level_shapes_keep_existing_contract(self):
        for n, data in enumerate((b"3", b"null", b"{}", b'{"reports": {"a": 1}}')):
            self.assert_refused(self.write(f"s{n}.json", data), "expected a list of report rows")
        rows = [{"id": "r1", "date": "2026-10-01"}]
        self.assertEqual(schedule._read_reports(self.write("l.json", b'[{"id": "r1", "date": "2026-10-01"}, 5, "x"]')), rows)
        self.assertEqual(schedule._read_reports(self.write("o.json", b'{"reports": [{"id": "r1", "date": "2026-10-01"}, null]}')), rows)

    def test_valid_reports_are_read_once_and_filtered_as_before(self):
        body = (b'[{"id": "a", "date": "2026-10-01"}, {"id": "b", "date": "2026-10-02"}, {"id": "c", "date": "2026-10-03"},'
                b' {"id": "d", "date": 5}, {"id": "e"}, 7]')
        for name, data in (("list.json", body), ("obj.json", b'{"reports": ' + body + b"}")):
            seen = {}

            def fake_days(rows, vessels, ports, seen=seen):
                seen["ids"] = [r["id"] for r in rows]
                return {}

            region = SimpleNamespace(id="CA", ports=[])
            with mock.patch.object(config, "load_region", return_value=region), \
                    mock.patch.object(schedule, "report_days", side_effect=fake_days), \
                    mock.patch.object(schedule, "landing_ports", return_value=[]), \
                    mock.patch.object(schedule, "_history_windows", return_value=[]), \
                    mock.patch.object(schedule, "precision", return_value={"k": 1}), \
                    mock.patch.dict(process.STORES, {"marinecadastre": mock.Mock()}), \
                    mock.patch.object(schedule, "_read_reports", wraps=schedule._read_reports) as read:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = schedule.main(["--region", "CA", "--from", "2026-10-01", "--to", "2026-10-02", "--reports",
                                          str(self.write(name, data)), "--vessels", str(self.vessels), "--root", str(self.dir)])
            self.assertEqual(code, 0)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(seen["ids"], ["a", "b"])
            self.assertEqual(out.getvalue().strip(), '{"from": "2026-10-01", "k": 1, "region": "CA", "report_rows": 2, "to": "2026-10-02"}')

    def test_vessels_and_argument_refusal_precedence_stays(self):
        self.vessels.write_text("[1]")
        bad = self.write("deep.json", b"[" * 10000)
        code, _, err = self.run_main(bad, True)
        self.assertEqual(code, 2)
        self.assertIn("vessel 0 needs an object with a string id", err)
        self.vessels.write_text("[]")
        good = self.write("good.json", b"[]")
        code, _, err = self.run_main(good, True, region_side_effect=config.FleetConfigError("no such region", []))
        self.assertEqual(code, 2)
        self.assertIn("no such region", err)
