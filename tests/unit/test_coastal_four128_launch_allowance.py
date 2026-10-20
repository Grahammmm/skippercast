"""Driver and watchdog units leave LAUNCH_ALLOWANCE_S (15 s) for their own launch.

Attempt 3 of the 2026-10-19 four128 trial sized the driver unit's RuntimeMaxSec at
floor(deadline - now) - 2. control_envelope() requires the unit's actual start plus
that runtime to stay 0.5 s inside the outer deadline, so the bounded runner and
systemd-run had 1.5 s to start the unit; under host load the launch took 4.2 s and
the driver refused its own envelope. Both units are now sized at
floor(deadline - now) - 15, which tolerates launch latency up to 14.5 s.
"""
import importlib.util
import inspect
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


def _load_runtime():
    # Load by file location (no sys.path edits, tests/contract/test_test_layout.py).
    with mock.patch.dict(os.environ, ENV):
        for module in MODULES:
            sys.modules.pop(module, None)
        spec = importlib.util.spec_from_file_location(MODULES[0], SCRIPTS / (MODULES[0] + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULES[0]] = module
        spec.loader.exec_module(module)
        return module


class SimulatedClock:
    """Monotonic/epoch clock the test advances; sleep() moves it forward."""

    def __init__(self, monotonic=10000.0, epoch=1792465765.0):
        self.mono = monotonic
        self.epoch = epoch
        self.on_sleep = None

    def advance(self, seconds):
        self.mono += seconds
        self.epoch += seconds

    def module(self):
        def sleep(seconds):
            self.advance(seconds)
            if self.on_sleep:
                self.on_sleep()
        return SimpleNamespace(monotonic=lambda: self.mono, time=lambda: self.epoch, sleep=sleep)


def runtime_max(argv):
    values = [a.split("=", 2)[2] for a in argv if a.startswith("--property=RuntimeMaxSec=")]
    assert len(values) == 1, argv
    return int(values[0])


class LaunchAllowance(unittest.TestCase):
    def setUp(self):
        self.runtime = _load_runtime()

    def tearDown(self):
        for module in MODULES:
            sys.modules.pop(module, None)

    def admitted(self, remaining, latency):
        """Would control_envelope's deadline check admit a unit launched with this latency?"""
        deadline = 4096.0
        now = deadline - remaining
        runtime = self.runtime.unit_runtime_for(deadline, now)
        return self.runtime.hard_deadline_within(now + latency, runtime, deadline)

    def test_allowance_equals_cleanup_reserve(self):
        self.assertEqual(self.runtime.LAUNCH_ALLOWANCE_S, 15)
        self.assertIn("cleanup_reserve_seconds=15", inspect.getsource(self.runtime.run))

    def test_runtime_is_remaining_minus_allowance(self):
        self.assertEqual(self.runtime.unit_runtime_for(4096.0, 4096.0 - 3590.0), 3575)
        self.assertEqual(self.runtime.unit_runtime_for(4096.0, 4096.0 - 3590.75), 3575)
        self.assertEqual(self.runtime.unit_runtime_for(4096.0, 4096.0 - 16.0), 1)

    def test_no_runtime_left_is_refused(self):
        for remaining in (15.75, 15.0, 3.0, 0.0, -2.0):
            with self.subTest(remaining=remaining), self.assertRaisesRegex(ValueError, "launch allowance"):
                self.runtime.unit_runtime_for(4096.0, 4096.0 - remaining)

    def test_simulated_launch_latency(self):
        # Whole-second remainder: the tightest case, tolerance exactly 14.5 s.
        for latency in (0, 4.2, 14, 14.5):
            with self.subTest(latency=latency):
                self.assertTrue(self.admitted(3590.0, latency))
        for latency in (14.75, 15, 20):
            with self.subTest(latency=latency):
                self.assertFalse(self.admitted(3590.0, latency))

    def test_tolerance_holds_for_any_fractional_remainder(self):
        for fraction in (0.0, 0.25, 0.5, 0.75, 0.9375):
            for latency in (0, 4.2, 14, 14.5):
                with self.subTest(fraction=fraction, latency=latency):
                    self.assertTrue(self.admitted(3590.0 + fraction, latency))
            with self.subTest(fraction=fraction, latency=15.5):
                self.assertFalse(self.admitted(3590.0 + fraction, 15.5))

    def test_attempt3_latency_failed_under_old_sizing(self):
        # Old sizing remaining-2 with the observed 4.2 s launch overshoots the 0.5 s margin.
        deadline, now = 4096.0, 4096.0 - 3590.0
        self.assertFalse(self.runtime.hard_deadline_within(now + 4.2, 3590 - 2, deadline))
        self.assertTrue(self.admitted(3590.0, 4.2))

    def test_control_envelope_uses_the_shared_check(self):
        source = inspect.getsource(self.runtime.control_envelope)
        self.assertIn("hard_deadline_within(started,actual_runtime,clock['deadline_monotonic'])", source)
        self.assertNotIn("actual_deadline>clock", source)


class ControlUnitArgv(unittest.TestCase):
    """run() and start() launch the driver/watchdog with RuntimeMaxSec = remaining - 15."""

    def setUp(self):
        self.runtime = _load_runtime()
        self.tmp = tempfile.TemporaryDirectory()
        self.mission = Path(self.tmp.name) / "mission"
        (self.mission / "control").mkdir(parents=True)
        self.runtime.N = self.mission
        self.runtime.SCRATCH = Path(self.tmp.name) / "absent-scratch"
        self.clock = SimulatedClock()
        self.launched = []

    def tearDown(self):
        self.tmp.cleanup()
        for module in MODULES:
            sys.modules.pop(module, None)

    def test_driver_argv_carries_remaining_minus_allowance(self):
        rt = self.runtime
        captured = {}

        def bounded(name, argv, *, seconds=200):
            self.launched.append(name)
            if name == "init-slice":
                self.clock.advance(3.46)  # attempt 3's observed init-slice duration
            elif name == "driver-start":
                captured.update(argv=argv, seconds=seconds, now=self.clock.mono)

        def put(path, doc, root=None):
            if path.name == "outer-clock.json":
                captured["clock"] = doc

        limits = dict(source_prior_bytes=1, source_limit_bytes=2, scratch_prior_bytes=3, scratch_limit_bytes=4)
        with mock.patch.object(rt, "time", self.clock.module()), \
                mock.patch.object(rt, "fresh_run_identity", return_value=True), \
                mock.patch.object(rt, "native_worker_ready", return_value="bootstrap"), \
                mock.patch.object(rt, "index", return_value=({}, {})), \
                mock.patch.object(rt, "limits_for", return_value=limits), \
                mock.patch.object(rt, "audit", return_value={}), \
                mock.patch.object(rt, "initial_capacity", return_value={}), \
                mock.patch.object(rt, "put", side_effect=put), \
                mock.patch.object(rt, "stop_trial", return_value={}) as stop, \
                mock.patch.object(rt, "bounded_command", side_effect=bounded):
            with self.assertRaisesRegex(ValueError, "no completed finite batch marker"):
                rt.run()
        stop.assert_called_once()
        self.assertEqual(self.launched, ["init-slice", "driver-start"])
        remaining = int(captured["clock"]["deadline_monotonic"] - captured["now"])
        self.assertEqual(remaining, 3596)
        self.assertEqual(runtime_max(captured["argv"]), remaining - 15)
        self.assertEqual(captured["seconds"], remaining - 15)
        self.assertIn("--unit=skippercast-four128approved-driver20261019t08.service", captured["argv"])

    def start(self, envelope_after):
        """Run start() with the watchdog envelope appearing envelope_after simulated seconds
        after the watchdog launch (None: never)."""
        rt = self.runtime
        deadline = self.clock.mono + 3590.0
        clock = dict(deadline_monotonic=deadline, start_monotonic=deadline - 3600)
        captured = {}
        envelope = self.mission / "control" / "parent-envelope.json"

        def bounded(name, argv, *, seconds=200):
            self.launched.append(name)
            if name == "watchdog-start":
                captured.update(argv=argv, now=self.clock.mono, seconds=seconds)
                if envelope_after is not None:
                    due = self.clock.mono + envelope_after

                    def appear():
                        if self.clock.mono >= due and not envelope.exists():
                            envelope.write_text("{}")
                    self.clock.on_sleep = appear
            elif name == "probe":
                (self.mission / "control" / "resource-probe.json").write_text("{}")

        with mock.patch.object(rt, "time", self.clock.module()), \
                mock.patch.object(rt, "index", return_value=({}, {})), \
                mock.patch.object(rt, "audit", return_value={}), \
                mock.patch.object(rt, "load_clock", return_value=clock), \
                mock.patch.object(rt, "control_envelope", return_value={}), \
                mock.patch.object(rt, "put", return_value={}), \
                mock.patch.object(rt, "live_watchdog", return_value=True), \
                mock.patch.object(rt, "bounded_command", side_effect=bounded):
            try:
                rt.start()
            finally:
                if "now" in captured:
                    captured["remaining"] = int(deadline - captured["now"])
                    captured["waited"] = self.clock.mono - captured["now"]
        return captured

    def test_watchdog_argv_carries_remaining_minus_allowance(self):
        captured = self.start(envelope_after=0.5)
        self.assertEqual(self.launched, ["watchdog-start", "probe"])
        self.assertEqual(captured["remaining"], 3590)
        self.assertEqual(runtime_max(captured["argv"]), 3590 - 15)
        self.assertIn("--unit=skippercast-four128approved-watchdog20261019t08.service", captured["argv"])
        self.assertNotIn("--wait", captured["argv"])

    def test_slow_watchdog_envelope_within_30_s_is_accepted(self):
        captured = self.start(envelope_after=20.0)
        self.assertEqual(self.launched, ["watchdog-start", "probe"])
        self.assertGreaterEqual(captured["waited"], 20.0)

    def test_absent_watchdog_envelope_holds_after_30_s(self):
        launched_at = self.clock.mono
        with self.assertRaisesRegex(ValueError, "actual watchdog envelope absent"):
            self.start(envelope_after=None)
        self.assertEqual(self.launched, ["watchdog-start"])
        waited = self.clock.mono - launched_at
        self.assertGreaterEqual(waited, 30.0)
        self.assertLess(waited, 30.5)


if __name__ == "__main__":
    unittest.main()
