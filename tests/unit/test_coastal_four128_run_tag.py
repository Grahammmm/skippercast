"""The four128 harness names its slice, units and scratch from one run tag.

A fresh trial must not reuse the 2026-10-11 attempt's transient names or scratch,
and a name collision must hold the run before any clock or receipt is written.
"""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._support import ROOT

SCRIPTS = ROOT / "research" / "scripts"


def _load(name, env):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    with mock.patch.dict(os.environ, env):
        for module in ("coastal_four128_runtime", "coastal_four128_resources"):
            sys.modules.pop(module, None)
        return importlib.import_module(name)


class RunTagNaming(unittest.TestCase):
    def tearDown(self):
        for module in ("coastal_four128_runtime", "coastal_four128_resources"):
            sys.modules.pop(module, None)

    def test_default_keeps_historical_names(self):
        env = {k: v for k, v in os.environ.items() if k != "SKIPPERCAST_FOUR128_RUN_TAG"}
        with mock.patch.dict(os.environ, env, clear=True):
            resources = _load("coastal_four128_resources", {})
        self.assertEqual(resources.SLICE, "skippercast-four128approved20261011.slice")
        self.assertEqual(resources.UNITS["A-map"], "skippercast-four128approved-a-map-20261011.service")
        self.assertEqual(resources.CONTROL_UNITS["watchdog"], "skippercast-four128approved-watchdog20261011.service")

    def test_fresh_tag_renames_every_unit_and_slice(self):
        resources = _load("coastal_four128_resources", {"SKIPPERCAST_FOUR128_RUN_TAG": "20261019"})
        names = [resources.SLICE, *resources.UNITS.values(), *resources.CONTROL_UNITS.values()]
        self.assertTrue(all("20261019" in name and "20261011" not in name for name in names))
        self.assertNotIn("watchdog", resources.UNITS)
        command = resources.launch_command("A-acquire", "/usr/bin/python3", "/tmp/wrapper.py")
        self.assertIn("--slice=skippercast-four128approved20261019.slice", command)

    def test_malformed_tag_is_refused(self):
        for tag in ("", "2026-10-19", "20261019/../x", "20261019ABC", "20261019abcdefghi"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                _load("coastal_four128_resources", {"SKIPPERCAST_FOUR128_RUN_TAG": tag})


class FreshRunIdentity(unittest.TestCase):
    def tearDown(self):
        for module in ("coastal_four128_runtime", "coastal_four128_resources"):
            sys.modules.pop(module, None)

    def runtime(self, tag, mission):
        return _load("coastal_four128_runtime", {
            "SKIPPERCAST_FOUR128_RUN_TAG": tag,
            "SKIPPERCAST_FOUR128_MISSION_ROOT": str(mission),
            "SKIPPERCAST_FOUR128_CODE_ROOT": str(ROOT),
        })

    def test_fresh_mission_requires_fresh_tag(self):
        runtime = self.runtime("20261011", "/nonexistent/outputs/t08-four128-20261019")
        with self.assertRaisesRegex(ValueError, "own SKIPPERCAST_FOUR128_RUN_TAG"):
            runtime.fresh_run_identity()

    def test_existing_scratch_holds_before_any_receipt(self):
        runtime = self.runtime("20261019t08", "/nonexistent/outputs/t08-four128-20261019")
        self.assertTrue(str(runtime.SCRATCH).endswith("/scratch/four128-approved-20261019t08"))
        with tempfile.TemporaryDirectory() as tmp:
            runtime.SCRATCH = Path(tmp)
            with self.assertRaisesRegex(ValueError, "trial scratch already exists"):
                runtime.fresh_run_identity()
            runtime.SCRATCH = Path(tmp) / "absent"
            self.assertTrue(runtime.fresh_run_identity())

    def test_run_checks_identity_first(self):
        runtime = self.runtime("20261011", "/nonexistent/outputs/t08-four128-20261019")
        with mock.patch.object(runtime, "index", side_effect=AssertionError("index reached")), \
                mock.patch.object(runtime, "put", side_effect=AssertionError("receipt written")):
            with self.assertRaisesRegex(ValueError, "own SKIPPERCAST_FOUR128_RUN_TAG"):
                runtime.run()

    def test_units_inherit_the_run_tag(self):
        runtime = self.runtime("20261019t08", "/nonexistent/outputs/t08-four128-20261019")
        argv = runtime.unit_command("driver", runtime=600, wait=False)
        self.assertIn("--setenv=SKIPPERCAST_FOUR128_RUN_TAG=20261019t08", argv)
        self.assertIn("--unit=skippercast-four128approved-driver20261019t08.service", argv)
        self.assertIn("--slice=skippercast-four128approved20261019t08.slice", argv)


class NativeWorkerPreflight(unittest.TestCase):
    """preflight() and run() refuse a code root whose native stages cannot start,
    before any clock or receipt: missing or linked worker bootstrap (attempt 2) or
    project bytecode the supervisor's source guard refuses (attempt 1)."""

    def setUp(self):
        self.runtime = _load("coastal_four128_runtime", {
            "SKIPPERCAST_FOUR128_RUN_TAG": "20261019t08",
            "SKIPPERCAST_FOUR128_MISSION_ROOT": "/nonexistent/outputs/t08-four128-20261019",
            "SKIPPERCAST_FOUR128_CODE_ROOT": str(ROOT),
        })
        self.tmp = tempfile.TemporaryDirectory()
        code = Path(self.tmp.name) / "code"
        package = code / "src" / "skippercast"
        lane = package / "coastal" / "authenticated_v1"
        lane.mkdir(parents=True)
        source = ROOT / "src" / "skippercast" / "coastal"
        for relative in ("_source_bootstrap.py", "authenticated_v1/bootstrap.py",
                         "coordinator/authenticated.py"):
            target = package / "coastal" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source / relative).read_bytes())
        self.code, self.package, self.bootstrap = code, package, lane / "bootstrap.py"
        self.runtime.W = code
        self.runtime.SCRATCH = Path(self.tmp.name) / "absent-scratch"
        coordinator = sys.modules["skippercast.coastal.coordinator.authenticated"]
        self.pinned = mock.patch.object(coordinator, "__file__",
                                        str(package / "coastal" / "coordinator" / "authenticated.py"))

    def tearDown(self):
        self.tmp.cleanup()
        for module in ("coastal_four128_runtime", "coastal_four128_resources"):
            sys.modules.pop(module, None)

    def test_source_only_tree_with_bootstrap_is_ready(self):
        with self.pinned:
            self.assertEqual(self.runtime.native_worker_ready(), str(self.bootstrap))

    def test_missing_bootstrap_is_refused(self):
        self.bootstrap.unlink()
        with self.pinned, self.assertRaisesRegex(ValueError, "native worker bootstrap missing"):
            self.runtime.native_worker_ready()

    def test_linked_bootstrap_is_refused(self):
        real = self.bootstrap.with_name("real-bootstrap.txt")
        self.bootstrap.rename(real)
        self.bootstrap.symlink_to(real)
        with self.pinned, self.assertRaisesRegex(ValueError, "must be a regular file"):
            self.runtime.native_worker_ready()

    def test_project_bytecode_is_refused(self):
        (self.package / "coastal" / "__pycache__").mkdir()
        with self.pinned, self.assertRaisesRegex(ValueError, "compiled bytecode"):
            self.runtime.native_worker_ready()

    def test_coordinator_outside_code_root_is_refused(self):
        with mock.patch.object(sys.modules["skippercast.coastal.coordinator.authenticated"], "__file__",
                               str(Path(self.tmp.name) / "elsewhere/skippercast/coastal/coordinator/authenticated.py")):
            with self.assertRaisesRegex(ValueError, "outside the pinned code root"):
                self.runtime.native_worker_ready()

    def test_run_and_preflight_check_the_worker_before_any_receipt(self):
        self.bootstrap.unlink()
        runtime = self.runtime
        with self.pinned, mock.patch.object(runtime, "index", side_effect=AssertionError("index reached")), \
                mock.patch.object(runtime, "put", side_effect=AssertionError("receipt written")):
            with self.assertRaisesRegex(ValueError, "native worker bootstrap missing"):
                runtime.run()
            with self.assertRaisesRegex(ValueError, "native worker bootstrap missing"):
                runtime.preflight()
        self.assertFalse(runtime.SCRATCH.exists())


if __name__ == "__main__":
    unittest.main()
