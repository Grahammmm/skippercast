"""RF1520-6: ``fleet ais validate --thresholds FILE`` is checked key by key before any Worker sync.

Unknown keys, wrong shapes and non-finite values exit 2 naming the key path, with no traceback and no
``sync``/``job_worker`` call; ``--sync-only`` never reads the file. ``sync`` and ``job_worker`` are patched
to record calls, so nothing here reaches a Worker.
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
from skippercast.fleet.ais.segment import ActivityThresholds
from skippercast.fleet.config import load_region


class ThresholdsFileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(self.dir / "var")})
        env.start()
        self.addCleanup(env.stop)
        self.calls = []
        for name, value in (("job_worker", "worker"), ("sync", {"trips": 0})):
            patcher = mock.patch.object(validate, name, side_effect=lambda *a, _n=name, _v=value, **k: self.calls.append(_n) or _v)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, content, *flags):
        path = self.dir / "th.json"
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            code = validate.main(["--region", "CA", "--thresholds", str(path), *flags])
        return code, err.getvalue()

    def assert_refused(self, content, message):
        code, err = self.run_main(content)
        self.assertEqual((code, err), (2, f"fleet ais validate: --thresholds: {message}\n"), content)
        self.assertEqual(self.calls, [], "a bad file is found before any Worker sync")

    def test_unknown_and_misspelt_keys_are_named(self):
        self.assert_refused({"drift": {"max_sog_kts": 1}}, "unknown key drift.max_sog_kts")
        self.assert_refused({"bogus": 1}, "unknown key bogus")
        self.assert_refused({"activity": {"drift": {"max_sog_kn": 1}}}, "unknown key activity")
        self.assert_refused({"troll_slow": {"min_sog_kn": 2, "nope": 1}}, "unknown key troll_slow.nope")

    def test_wrong_shapes_and_non_finite_values_are_named(self):
        self.assert_refused({"drift": 5}, "drift must be an object of thresholds")
        self.assert_refused({"max_open_trip_hours": 12}, "max_open_trip_hours must be an object of thresholds")
        self.assert_refused({"window_min": {"a": 1}}, "window_min must be a finite number")
        self.assert_refused({"window_min": True}, "window_min must be a finite number")
        self.assert_refused({"window_min": "5"}, "window_min must be a finite number")
        self.assert_refused({"window_min": None}, "window_min must be a finite number")
        self.assert_refused('{"window_min": NaN}', "window_min must be a finite number")
        self.assert_refused('{"drift": {"max_sog_kn": Infinity}}', "drift.max_sog_kn must be a finite number")
        self.assert_refused('{"drift": {"min_minutes": -Infinity}}', "drift.min_minutes must be a finite number")
        self.assert_refused('{"window_min": 1e999}', "window_min must be a finite number")
        self.assert_refused('{"window_min": 1' + "0" * 400 + "}", "window_min must be a finite number")

    def test_new_vessel_classes_are_allowed_but_still_numbers(self):
        self.assert_refused({"max_open_trip_hours": {"x": "12"}}, "max_open_trip_hours.x must be a finite number")
        self.assert_refused({"max_open_trip_hours": {"six-pack": False}}, "max_open_trip_hours.six-pack must be a finite number")
        th = validate._thresholds(load_region("CA"), self._file({"max_open_trip_hours": {"new_class": 12}}))
        self.assertEqual(th.max_open_trip_hours["new_class"], 12.0)

    def test_a_valid_override_changes_only_its_key(self):
        with mock.patch.object(validate, "report", wraps=validate.report) as report:
            code, err = self.run_main({"drift": {"max_sog_kn": 1.2}})
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.calls, ["job_worker", "sync"])
        base = json.loads(json.dumps(ActivityThresholds.from_region(load_region("CA")).raw))
        used = report.call_args.kwargs["thresholds"]
        self.assertEqual(used.drift_max_sog_kn, 1.2)
        base["drift"]["max_sog_kn"] = 1.2
        self.assertEqual(json.loads(json.dumps(used.raw)), base, "only drift.max_sog_kn differs")

    def test_unreadable_files_exit_2_without_a_traceback(self):
        self.assert_refused(b"\xff\xfe{\x00", "not readable JSON")
        self.assert_refused("{", "not readable JSON")
        self.assert_refused("[" * 100000, "not readable JSON")
        code, err = self.run_main([{"drift": {"max_sog_kn": 1}}])
        self.assertEqual((code, err), (2, "fleet ais validate: --thresholds takes a JSON object of activity thresholds\n"))
        err_io = io.StringIO()
        with redirect_stderr(err_io):
            self.assertEqual(validate.main(["--region", "CA", "--offline", "--thresholds", str(self.dir / "missing.json")]), 2)
        self.assertTrue(err_io.getvalue().startswith("fleet ais validate: "), err_io.getvalue())
        self.assertEqual(self.calls, [])

    def test_sync_only_never_reads_the_file(self):
        code, err = self.run_main("[" * 100000, "--sync-only")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.calls, ["job_worker", "sync"])
        with mock.patch.object(validate, "_thresholds", side_effect=AssertionError("read")):
            self.assertEqual(self.run_main({"bogus": 1}, "--sync-only")[0], 0)

    def _file(self, document):
        path = self.dir / "ok.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return str(path)


if __name__ == "__main__":
    unittest.main()
