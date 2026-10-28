"""Four128 launch receipts record host load and launch latency (audit S4, item 51).

Attempt 3 of the 2026-10-19 trial timed out on a 4.2 s systemd launch under host
load, and the launch receipt could not show why. bounded_command() now records the
1/5/15-minute load average before and after each launch, the wall time of the
launch and when the runner parent first saw its child. An optional run()-level
gate (SKIPPERCAST_FOUR128_MAX_LOAD1) refuses to start the outer clock on a busy host.
Nothing here touches systemd, /proc/loadavg or a live mission.
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._support import ROOT

SCRIPTS = ROOT / "research" / "scripts"
MODULES = ("coastal_four128_runtime", "coastal_four128_resources")
ENV = {
    "SKIPPERCAST_FOUR128_RUN_TAG": "20261019t08",
    "SKIPPERCAST_FOUR128_MISSION_ROOT": "/nonexistent/outputs/t08-four128-20261019",
    "SKIPPERCAST_FOUR128_CODE_ROOT": str(ROOT),
}
# Production roots are under 100 characters; the size bound is proved for 160.
LONG_ROOT = 160


def _load_runtime(env=ENV):
    # Load by file location (no sys.path edits, tests/contract/test_test_layout.py).
    with mock.patch.dict(os.environ, env):
        for module in MODULES:
            sys.modules.pop(module, None)
        spec = importlib.util.spec_from_file_location(MODULES[0], SCRIPTS / (MODULES[0] + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULES[0]] = module
        spec.loader.exec_module(module)
        return module


def _padded(prefix, length):
    path = prefix + "/" + "p" * (length - len(prefix) - 1)
    assert len(path) == length
    return path


class Clock:
    def __init__(self):
        self.mono = 5000.0

    def module(self):
        return SimpleNamespace(monotonic=lambda: self.mono, time=lambda: 1792465765.0 + self.mono,
                               sleep=lambda s: None)


def fake_runner(clock, *, child_after=0.25, total=4.2, status="ok", rc=0, intent_dir=None):
    """A run_bounded stand-in: the child appears child_after s in, the launch takes total s."""
    calls = []

    def run_bounded(argv, *, intent, scratch, identity_callback=None, **kwargs):
        calls.append(dict(argv=argv, intent=intent, scratch=scratch, **kwargs))
        clock.mono += child_after or 0
        if identity_callback is not None and child_after is not None:
            identity_callback({"pid": 4242})
        clock.mono += total - (child_after or 0)
        return SimpleNamespace(status=status, rc=rc, elapsed=total, pid=4242, intent_path=str(intent),
                               stdout_path=str(Path(scratch) / "stdout"), stderr_path=str(Path(scratch) / "stderr"))
    return run_bounded, calls


class LaunchReceipt(unittest.TestCase):
    def setUp(self):
        self.runtime = _load_runtime()
        self.tmp = tempfile.TemporaryDirectory()
        self.mission = Path(self.tmp.name) / "mission"
        (self.mission / "control").mkdir(parents=True)
        self.runtime.N = self.mission
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()
        for module in MODULES:
            sys.modules.pop(module, None)

    def launch(self, name="init-slice", argv=("/usr/bin/true",), *, loads=None, **runner):
        rt = self.runtime
        written = {}
        samples = iter(loads if loads is not None else ([0.52, 0.61, 0.70], [3.95, 1.12, 0.81]))
        run_bounded, calls = fake_runner(self.clock, **runner)

        def put(path, doc, root=None):
            written[path] = doc
            return {}

        with mock.patch.object(rt, "time", self.clock.module()), \
                mock.patch.object(rt, "index", return_value=({}, {})), \
                mock.patch.object(rt, "managed_configuration_for", return_value={}), \
                mock.patch.object(rt, "read_loadavg", side_effect=lambda: next(samples)), \
                mock.patch.object(rt, "put", side_effect=put), \
                mock.patch("skippercast.coastal.runner.run_bounded", run_bounded):
            try:
                receipt = rt.bounded_command(name, list(argv))
                error = None
            except ValueError as exc:
                receipt, error = None, exc
        return receipt, written, calls, error

    def test_receipt_records_loadavg_and_latency(self):
        receipt, written, calls, error = self.launch()
        self.assertIsNone(error)
        self.assertEqual(list(written), [self.mission / "control" / "launch-init-slice.json"])
        doc = written[self.mission / "control" / "launch-init-slice.json"]
        self.assertIs(doc, receipt)
        self.assertEqual(doc["schema"], "coastal-four128-launch-v1")
        self.assertEqual(doc["loadavg_before"], [0.52, 0.61, 0.70])
        self.assertEqual(doc["loadavg_after"], [3.95, 1.12, 0.81])
        self.assertEqual(doc["launch_wall_seconds"], 4.2)
        self.assertEqual(doc["child_observed_seconds"], 0.25)
        # The runner gets an identity callback; nothing else in the launch changed.
        self.assertEqual(calls[0]["timeout_s"], 200)
        self.assertEqual(calls[0]["output_limit_bytes"], 2048)

    def test_v1_fields_are_unchanged(self):
        # Rerun tooling reads status, rc and elapsed_seconds with .get(); keep them.
        doc, _, _, _ = self.launch()
        for key in ("schema", "name", "argv", "status", "rc", "elapsed_seconds", "intent", "stdout", "stderr"):
            self.assertIn(key, doc)
        self.assertEqual((doc["status"], doc["rc"], doc["elapsed_seconds"]), ("ok", 0, 4.2))

    def test_held_launch_still_writes_its_diagnosis(self):
        _, written, _, error = self.launch(status="timeout", rc=None, child_after=None, total=10.0)
        self.assertRegex(str(error), "finite command held; no retry: init-slice")
        doc = written[self.mission / "control" / "launch-init-slice.json"]
        self.assertEqual(doc["status"], "timeout")
        self.assertEqual(doc["launch_wall_seconds"], 10.0)
        self.assertIsNone(doc["child_observed_seconds"])
        self.assertEqual(doc["loadavg_after"], [3.95, 1.12, 0.81])

    def test_unreadable_loadavg_is_recorded_as_null_not_a_failure(self):
        doc, _, _, error = self.launch(loads=(None, None))
        self.assertIsNone(error)
        self.assertIsNone(doc["loadavg_before"])
        self.assertIsNone(doc["loadavg_after"])


class ReadLoadavg(unittest.TestCase):
    def setUp(self):
        self.runtime = _load_runtime()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()
        for module in MODULES:
            sys.modules.pop(module, None)

    def read(self, text):
        path = Path(self.tmp.name) / "loadavg"
        path.write_text(text)
        return self.runtime.read_loadavg(path)

    def test_parses_the_proc_format(self):
        self.assertEqual(self.read("0.52 0.61 0.70 2/1234 98765\n"), [0.52, 0.61, 0.70])

    def test_malformed_or_absent_is_none(self):
        for text in ("", "0.5 0.6\n", "a b c 1/2 3\n", "nan 0.1 0.1 1/2 3\n", "-1 0 0 1/2 3\n", "1e9 0 0 1/2 3\n"):
            with self.subTest(text=text):
                self.assertIsNone(self.read(text))
        self.assertIsNone(self.runtime.read_loadavg(Path(self.tmp.name) / "absent"))


class LaunchReceiptSize(unittest.TestCase):
    """The largest receipt bounded_command can write stays under the 4096-byte cap."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {
            # Longest run tag coastal_four128_resources admits ([0-9]{8}[a-z0-9]{0,8}).
            "SKIPPERCAST_FOUR128_RUN_TAG": "20261019zzzzzzzz",
            "SKIPPERCAST_FOUR128_MISSION_ROOT": _padded(self.tmp.name + "/m", LONG_ROOT),
            "SKIPPERCAST_FOUR128_CODE_ROOT": _padded("/nonexistent/code", LONG_ROOT),
            "SKIPPERCAST_FOUR128_PYTHON": _padded("/nonexistent/python", LONG_ROOT),
        }
        # Load once from this checkout first: the long code root below does not exist,
        # so skippercast.coastal must already be importable from the real one.
        _load_runtime()
        self.runtime = _load_runtime(env)

    def tearDown(self):
        self.tmp.cleanup()
        for module in MODULES:
            sys.modules.pop(module, None)

    def candidates(self):
        """Every unit argv bounded_command launches, with its longest extra arguments."""
        rt = self.runtime
        descriptor = lambda name: str(rt.R / ("metadata/" + name + "-descriptor.json"))
        for label in "ABCD":
            yield label + "-acquire", rt.unit_command(label + "-acquire")
            yield label + "-qualify", rt.unit_command(label + "-qualify",
                                                     ["--request", descriptor("qualify-" + label)])
            yield label + "-map", rt.unit_command(label + "-map",
                                                 ["--mapping-plan", descriptor("map-plan-" + label)])
            for phase in ("acquire", "qualify"):
                yield label + "-review-" + phase, rt.unit_command(
                    label + "-review-" + phase, [descriptor("result-" + label + "-" + phase)])
        yield "probe", rt.unit_command("probe")
        yield "watchdog-start", rt.unit_command("watchdog", runtime=3600, wait=False)
        yield "driver-start", rt.unit_command("driver", runtime=3600)

    def test_maximal_receipt_fits_the_launch_cap(self):
        rt = self.runtime
        clock = Clock()
        # Widest values each new field can take: six-digit load, long latencies.
        worst_load = [999999.99, 999999.99, 999999.99]
        sizes = {}
        with mock.patch.object(os, "sched_getaffinity", return_value={1022, 1023}):
            candidates = list(self.candidates())
        self.assertEqual(len(candidates), 23)
        for name, argv in candidates:
            run_bounded, _ = fake_runner(clock, child_after=3599.123456, total=3599.987654,
                                         status="failed_uncertain", rc=-9)
            written = {}

            def put(path, doc, root=None):
                written[path] = doc

            with mock.patch.object(rt, "time", clock.module()), \
                    mock.patch.object(rt, "index", return_value=({}, {})), \
                    mock.patch.object(rt, "managed_configuration_for", return_value={}), \
                    mock.patch.object(rt, "read_loadavg", return_value=worst_load), \
                    mock.patch.object(rt, "put", side_effect=put), \
                    mock.patch("skippercast.coastal.runner.run_bounded", run_bounded), \
                    self.assertRaises(ValueError):
                rt.bounded_command(name, argv)
            (path, doc), = written.items()
            # elapsed_seconds comes straight from the runner: give it full float width.
            doc["elapsed_seconds"] = 3599.9876543210987
            raw = rt.control_bytes(doc)
            self.assertEqual(rt.control_ceiling(path), 4096)
            sizes[name] = len(raw)
        worst = max(sizes, key=sizes.get)
        self.assertLess(sizes[worst], 4096, (worst, sizes[worst]))


class QuiescenceGate(unittest.TestCase):
    """run() refuses to start the outer clock above SKIPPERCAST_FOUR128_MAX_LOAD1."""

    def setUp(self):
        self.runtime = _load_runtime()
        self.tmp = tempfile.TemporaryDirectory()
        self.mission = Path(self.tmp.name) / "mission"
        (self.mission / "control").mkdir(parents=True)
        self.runtime.N = self.mission
        self.runtime.SCRATCH = Path(self.tmp.name) / "absent-scratch"

    def tearDown(self):
        self.tmp.cleanup()
        for module in MODULES:
            sys.modules.pop(module, None)

    def run_with(self, threshold, load):
        """Run run() up to the clock; returns (exception, names written, launches)."""
        rt = self.runtime
        written, launched = [], []

        def put(path, doc, root=None):
            # A real file, so "no clock file" is checked on disk as well as by call.
            path.write_text("{}")
            written.append(path.name)

        env = {k: v for k, v in os.environ.items() if k != rt.QUIESCENCE_ENV}
        if threshold is not None:
            env[rt.QUIESCENCE_ENV] = threshold
        limits = dict(source_prior_bytes=1, source_limit_bytes=2)
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(rt, "fresh_run_identity", return_value=True), \
                mock.patch.object(rt, "native_worker_ready", return_value="bootstrap"), \
                mock.patch.object(rt, "index", return_value=({}, {})), \
                mock.patch.object(rt, "limits_for", return_value=limits), \
                mock.patch.object(rt, "audit", return_value={}), \
                mock.patch.object(rt, "initial_capacity", return_value={}), \
                mock.patch.object(rt, "read_loadavg", return_value=load) as reader, \
                mock.patch.object(rt, "put", side_effect=put), \
                mock.patch.object(rt, "stop_trial", return_value={}) as stop, \
                mock.patch.object(rt, "bounded_command", side_effect=lambda name, *a, **k: launched.append(name)):
            try:
                rt.run()
                error = None
            except ValueError as exc:
                error = exc
        return error, written, launched, reader, stop

    def assert_no_clock(self, written, launched, stop):
        self.assertEqual(written, [])
        self.assertEqual(launched, [])
        stop.assert_not_called()
        for name in ("outer-clock.json", "run-started.json", "finite-capacity-preflight.json"):
            self.assertFalse((self.mission / "control" / name).exists(), name)
        self.assertFalse(self.runtime.SCRATCH.exists())

    def test_refuses_above_threshold_and_writes_no_clock(self):
        error, written, launched, _, stop = self.run_with("2.0", [2.01, 0.5, 0.5])
        self.assertRegex(str(error), "host not quiescent: 1-minute load average 2.01 above "
                                     "SKIPPERCAST_FOUR128_MAX_LOAD1=2.0")
        self.assert_no_clock(written, launched, stop)

    def test_unreadable_loadavg_refuses_when_the_gate_is_set(self):
        error, written, launched, _, stop = self.run_with("2.0", None)
        self.assertRegex(str(error), "loadavg is unreadable")
        self.assert_no_clock(written, launched, stop)

    def test_malformed_threshold_refuses(self):
        for value in ("high", "0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                error, written, launched, _, stop = self.run_with(value, [0.1, 0.1, 0.1])
                self.assertRegex(str(error), "SKIPPERCAST_FOUR128_MAX_LOAD1 must be")
                self.assert_no_clock(written, launched, stop)

    def test_at_or_below_threshold_starts_the_clock(self):
        error, written, launched, _, stop = self.run_with("2.0", [2.0, 3.0, 3.0])
        # Past the gate: the clock is written and the slice launch begins.
        self.assertRegex(str(error), "no completed finite batch marker")
        self.assertEqual(written[:3], ["outer-clock.json", "finite-capacity-preflight.json", "run-started.json"])
        self.assertEqual(launched, ["init-slice", "driver-start"])
        stop.assert_called_once()

    def test_gate_is_off_by_default(self):
        error, written, _, reader, _ = self.run_with(None, [99.0, 99.0, 99.0])
        self.assertRegex(str(error), "no completed finite batch marker")
        self.assertIn("outer-clock.json", written)
        reader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
