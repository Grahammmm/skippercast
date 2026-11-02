"""fleet ais schedule-precision: --vessels shape is checked before the region loads (RF1520-5).

Synthetic throughout: vessel files in a temporary directory, ``load_region``,
the raw store, ``landing_ports`` and ``precision`` replaced by small fakes.
"""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from skippercast.fleet import config
from skippercast.fleet.ais import process, schedule


class VesselsFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.reports = self.dir / "reports.json"
        self.reports.write_text("[]")

    def run_main(self, vessels: Path, *extra: str):
        argv = ["--region", "CA", "--from", "2026-10-01", "--to", "2026-10-02", "--reports", str(self.reports),
                "--vessels", str(vessels), "--root", str(self.dir), *extra]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = schedule.main(argv)
        return code, out.getvalue(), err.getvalue()

    def write(self, name: str, data: bytes) -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path

    def test_bad_shapes_exit_2_named_before_load_region(self):
        cases = {
            b'{"a": 1}': "expected a list of vessels or an object with vessels[]",
            b'{"vessels": {"id": "v1"}}': "expected a list of vessels or an object with vessels[]",
            b'"text"': "expected a list of vessels or an object with vessels[]",
            b"[1]": "vessel 0 needs an object with a string id",
            b'[{"name": "x"}]': "vessel 0 needs an object with a string id",
            b'[{"id": "v1"}, {"id": ""}]': "vessel 1 needs an object with a string id",
            b'[{"id": 7}]': "vessel 0 needs an object with a string id",
            b'[{"id": "v1"}, "v2"]': "vessel 1 needs an object with a string id",
            b'[{"id": "v1"': "not readable JSON",
            b'[{"id": "\xff"}]': "not readable JSON",
            b"[" * 100000: "not readable JSON",
        }
        for n, (data, message) in enumerate(cases.items()):
            with self.subTest(data=data[:30]):
                path = self.write(f"v{n}.json", data)
                with mock.patch.object(config, "load_region", side_effect=AssertionError("load_region reached")) as lr:
                    code, out, err = self.run_main(path)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith(f"fleet ais schedule-precision: {path}"), err)
                self.assertIn(message, err)
                self.assertNotIn("Traceback", err)
                lr.assert_not_called()

    def test_list_and_object_shapes_reach_report_days_alike(self):
        seen = []

        def spy(rows, vessels, landing):
            seen.append(vessels)
            return {}

        region = SimpleNamespace(id="CA")
        for n, data in enumerate((b'{"vessels": [{"id": "v1"}]}', b'[{"id": "v1"}]')):
            path = self.write(f"ok{n}.json", data)
            with mock.patch.object(config, "load_region", return_value=region), \
                    mock.patch.dict(process.STORES, {"marinecadastre": lambda root: object()}), \
                    mock.patch.object(schedule, "landing_ports", return_value={}), \
                    mock.patch.object(schedule, "report_days", side_effect=spy), \
                    mock.patch.object(schedule, "precision", return_value={"windows": 0}) as precision:
                code, out, err = self.run_main(path)
            self.assertEqual((code, err), (0, ""))
            self.assertIn('"region": "CA"', out)
            self.assertEqual(precision.call_args.args[1], [{"id": "v1"}])
        self.assertEqual(seen, [[{"id": "v1"}], [{"id": "v1"}]])

    def test_missing_vessels_file_exits_2_naming_path(self):
        path = self.dir / "absent.json"
        with mock.patch.object(config, "load_region", side_effect=AssertionError("load_region reached")):
            code, _, err = self.run_main(path)
        self.assertEqual(code, 2)
        self.assertIn(str(path), err)
        self.assertNotIn("Traceback", err)

    def test_to_before_from_is_still_a_parser_error(self):
        argv = ["--region", "CA", "--from", "2026-10-02", "--to", "2026-10-01", "--reports", str(self.reports)]
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            schedule.main(argv)
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--to is before --from", err.getvalue())


if __name__ == "__main__":
    unittest.main()
