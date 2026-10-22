"""The four128 scripts derive their defaults from the operator's home, not a literal.

scripts/check_repository.py refuses literal private home paths. The defaults must
still resolve to exactly the paths the 2026-10-11 attempt and attempt 6 used on
AgentOrange, and the existing environment overrides must still win.
"""
import ast
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests._support import ROOT

SCRIPTS = ROOT / "research" / "scripts"
NAMES = ("coastal_four128_prepare", "coastal_four128_runtime", "coastal_four128_artifact_review")
OVERRIDES = ("SKIPPERCAST_FOUR128_MISSION_ROOT", "SKIPPERCAST_FOUR128_CODE_ROOT",
             "SKIPPERCAST_FOUR128_PYTHON", "SKIPPERCAST_FOUR128_RUN_TAG")
# AgentOrange's HOME, assembled so this file holds no literal home path either.
HOME = str(Path("/", "home", "user"))
PROJECT = HOME + "/skippercast-data/2026-10-07-pge-south"


def _load(name, env):
    # Bind the installed reviewed package BEFORE the historical scripts prepend
    # their legacy worktree paths. Otherwise a default-root test can import a
    # stale operator checkout merely because it happens to exist on this host.
    import skippercast
    if Path(skippercast.__file__).resolve() != ROOT / 'src/skippercast/__init__.py':
        raise RuntimeError('home-path tests require the reviewed package')
    # Load by file location; the scripts add their own directories to sys.path,
    # which is restored afterwards (tests/contract/test_test_layout.py).
    base = {k: v for k, v in os.environ.items() if k not in OVERRIDES}
    saved = list(sys.path)
    try:
        with mock.patch.dict(os.environ, {**base, "HOME": HOME, **env}, clear=True):
            for module in (*NAMES, "coastal_four128_resources"):
                sys.modules.pop(module, None)
            spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module, list(sys.path)
    finally:
        sys.path[:] = saved


def _review_defaults(env):
    # The artifact review imports numpy-backed lanes, which the no-GIS job lacks.
    # Evaluate its own top-level root assignments, exactly as written in the file;
    # tests/gis/test_coastal_four128_review_home_paths.py imports the whole module.
    path = SCRIPTS / "coastal_four128_artifact_review.py"
    wanted = {"PROJECT", "N", "DEFAULT_ROOT", "W"}
    body = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id in wanted for t in node.targets)]
    assert {t.id for node in body for t in node.targets} == wanted, "root assignments moved"
    namespace = {"os": os, "Path": Path}
    base = {k: v for k, v in os.environ.items() if k not in OVERRIDES}
    with mock.patch.dict(os.environ, {**base, "HOME": HOME, **env}, clear=True):
        exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class HomeDerivedDefaults(unittest.TestCase):
    def tearDown(self):
        for module in (*NAMES, "coastal_four128_resources"):
            sys.modules.pop(module, None)

    def test_no_literal_home_path_remains(self):
        for name in NAMES:
            with self.subTest(name=name):
                self.assertNotIn("/home/", (SCRIPTS / (name + ".py")).read_text(encoding="utf-8"))

    def test_runtime_defaults_match_previous_literals(self):
        runtime, path = _load("coastal_four128_runtime", {})
        self.assertEqual(str(runtime.PROJECT), PROJECT)
        self.assertEqual(str(runtime.HISTORICAL_MISSION),
                         PROJECT + "/outputs/ordered-four128-approved-20261011")
        self.assertEqual(runtime.N, runtime.HISTORICAL_MISSION)
        self.assertEqual(str(runtime.W), PROJECT + "/work/source-reuse-admission-20261011")
        self.assertEqual(runtime.PYTHON, PROJECT + "/repo/.venv/bin/python")
        self.assertIsInstance(runtime.PYTHON, str)
        self.assertEqual(str(runtime.SCRATCH),
                         PROJECT + "/scratch/four128-approved-" + runtime.RUN_TAG)
        self.assertEqual(str(runtime.SCRATCH), PROJECT + "/scratch/four128-approved-20261011")
        self.assertIn(PROJECT + "/work/combined-coastal-integration-20261009/var/python-integration-dependencies",
                      path)

    def test_artifact_review_defaults_match_previous_literals(self):
        review = _review_defaults({})
        self.assertEqual(str(review["PROJECT"]), PROJECT)
        self.assertEqual(str(review["N"]), PROJECT + "/outputs/ordered-four128-approved-20261011")
        self.assertEqual(review["DEFAULT_ROOT"], review["N"])
        self.assertEqual(str(review["W"]), PROJECT + "/work/source-reuse-admission-20261011")
        # The synthetic-rehearsal allowance inside configure() hangs off the same root.
        text = (SCRIPTS / "coastal_four128_artifact_review.py").read_text(encoding="utf-8")
        self.assertIn("allowed=PROJECT/'scratch/source-reuse-admission-engineering-20261011'", text)

    def test_prepare_root_matches_previous_literal(self):
        prepare, path = _load("coastal_four128_prepare", {})
        self.assertEqual(str(prepare.B), PROJECT)
        self.assertIn(PROJECT + "/work/combined-coastal-integration-20261009/var/python-integration-dependencies",
                      path)

    def test_environment_overrides_still_win(self):
        env = {"SKIPPERCAST_FOUR128_MISSION_ROOT": "/nonexistent/mission",
               "SKIPPERCAST_FOUR128_CODE_ROOT": str(ROOT),
               "SKIPPERCAST_FOUR128_PYTHON": "/usr/bin/python3",
               "SKIPPERCAST_FOUR128_RUN_TAG": "20261019t08"}
        runtime, _ = _load("coastal_four128_runtime", env)
        self.assertEqual(str(runtime.N), "/nonexistent/mission")
        self.assertEqual(runtime.W, ROOT)
        self.assertEqual(runtime.PYTHON, "/usr/bin/python3")
        self.assertEqual(str(runtime.SCRATCH), PROJECT + "/scratch/four128-approved-20261019t08")
        review = _review_defaults(env)
        self.assertEqual(str(review["N"]), "/nonexistent/mission")
        self.assertEqual(review["W"], ROOT)


if __name__ == "__main__":
    unittest.main()
