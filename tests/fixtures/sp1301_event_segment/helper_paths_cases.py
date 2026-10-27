"""SP1301-EVENT-SEGMENT: synthetic regressions for the acceptance helper's --output preflight.

Run by `scripts/accept_sp1301_event_segment.py --suite helper-paths` as a child of the staged
.venv interpreter:

    helper_paths_cases.py --scratch DIR --report FILE

Every case builds its own invented candidate root under DIR (a fresh directory inside the
helper's run directory) and calls the helper's make_run_dir with that root. Negative cases
assert a Gate refusal AND that the whole case tree, symlinks included, is byte-for-byte the same
set of entries afterwards, so nothing was created through a link or outside <candidate>/out.
No network, no real records, no paths outside DIR.
"""
import sys

sys.dont_write_bytecode = True

import socket  # noqa: E402


def _tripwire(*_args, **_kwargs):
    raise RuntimeError("SP1301_TRIPWIRE: network access attempted in helper-paths cases")


socket.socket.connect = _tripwire
socket.socket.connect_ex = _tripwire
socket.create_connection = _tripwire
socket.getaddrinfo = _tripwire

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
HELPER_PATH = REPO / "scripts" / "accept_sp1301_event_segment.py"
SCRATCH = None


def load_helper():
    spec = importlib.util.spec_from_file_location("sp1301_accept_helper", HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != HELPER_PATH or HELPER_PATH.parents[1] != REPO:
        raise RuntimeError(f"helper loaded from an unexpected location: {module.__file__}")
    return module


helper = load_helper()


def tree(root):
    """Every entry under root (symlinks listed, never followed) with its kind and link target."""
    entries = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                entries[os.path.relpath(p, root)] = ("link", os.readlink(p))
            elif os.path.isdir(p):
                entries[os.path.relpath(p, root)] = ("dir", None)
            else:
                with open(p, "rb") as fh:
                    entries[os.path.relpath(p, root)] = ("file", fh.read())
    return entries


class OutputPreflight(unittest.TestCase):
    def setUp(self):
        base = Path(SCRATCH) / self._testMethodName
        os.mkdir(base)
        self.case = base
        self.cand = base / "cand"
        os.mkdir(self.cand)
        self.out = self.cand / "out"

    def refuse(self, output, fragment):
        before = tree(self.case)
        with self.assertRaises(helper.Gate) as caught:
            helper.make_run_dir(output, self.cand)
        self.assertIn(fragment, str(caught.exception))
        self.assertEqual(tree(self.case), before, "a refused --output changed the filesystem")

    def test_symlink_parent_nonexistent_child_creates_nothing_through_link(self):
        os.mkdir(self.out)
        os.mkdir(self.out / "symlink-target")
        os.symlink(self.out / "symlink-target", self.out / "symlink-parent")
        self.refuse(self.out / "symlink-parent" / "must-not-be-created", "symlink in output ancestry")
        self.assertFalse(os.path.lexists(self.out / "symlink-target" / "must-not-be-created"))
        self.assertEqual(os.listdir(self.out / "symlink-target"), [])

    def test_symlink_intermediate_deeper_creates_nothing(self):
        os.mkdir(self.out)
        os.makedirs(self.out / "real" / "target")
        os.symlink(self.out / "real" / "target", self.out / "real" / "hop")
        self.refuse(self.out / "real" / "hop" / "a" / "b", "symlink in output ancestry")
        self.assertEqual(os.listdir(self.out / "real" / "target"), [])

    def test_symlink_leaf_refused(self):
        os.mkdir(self.out)
        os.mkdir(self.out / "leaf-target")
        os.symlink(self.out / "leaf-target", self.out / "leaf-link")
        self.refuse(self.out / "leaf-link", "symlink in output ancestry")
        self.assertEqual(os.listdir(self.out / "leaf-target"), [])

    def test_symlinked_out_root_refused(self):
        os.mkdir(self.cand / "elsewhere")
        os.symlink(self.cand / "elsewhere", self.out)
        self.refuse(self.out / "child", "symlink in output ancestry")
        self.assertEqual(os.listdir(self.cand / "elsewhere"), [])

    def test_dangling_symlink_parent_refused(self):
        os.mkdir(self.out)
        os.symlink(self.case / "never-created", self.out / "dangling")
        self.refuse(self.out / "dangling" / "child", "symlink in output ancestry")
        self.assertFalse(os.path.lexists(self.case / "never-created"))

    def test_traversal_out_dotdot_refused(self):
        os.mkdir(self.out)
        self.refuse(str(self.out) + "/../outside/x", "must not contain '..'")
        self.assertFalse(os.path.lexists(self.cand / "outside"))

    def test_traversal_inside_out_refused(self):
        os.mkdir(self.out)
        os.mkdir(self.out / "a")
        self.refuse(str(self.out) + "/a/../b", "must not contain '..'")
        self.assertFalse(os.path.lexists(self.out / "b"))

    def test_relative_traversal_refused(self):
        self.refuse("../escape", "must not contain '..'")

    def test_escaping_absolute_path_refused(self):
        os.mkdir(self.out)
        self.refuse(self.cand / "sibling" / "x", "must be under")
        self.assertFalse(os.path.lexists(self.cand / "sibling"))

    def test_out_root_itself_refused(self):
        os.mkdir(self.out)
        self.refuse(self.out, "not the out directory itself")

    def test_file_in_ancestry_refused(self):
        os.mkdir(self.out)
        (self.out / "afile").write_bytes(b"synthetic\n")
        self.refuse(self.out / "afile" / "x", "not a directory")

    def test_fresh_outputs_get_unique_children_and_preserve_receipts(self):
        output = self.out / "fresh" / "deeper"
        first = helper.make_run_dir(output, self.cand)
        receipt = first / "receipt.txt"
        receipt.write_bytes(b"earlier receipt\n")
        second = helper.make_run_dir(output, self.cand)
        self.assertNotEqual(first, second)
        for run in (first, second):
            self.assertEqual(run.parent, output)
            self.assertTrue(run.name.startswith("run-"))
            self.assertEqual(run.resolve(), run)
            self.assertTrue((run / "tmp" / "home").is_dir())
        self.assertEqual(receipt.read_bytes(), b"earlier receipt\n")
        self.assertEqual(sorted(p.name for p in output.iterdir()), sorted([first.name, second.name]))
        self.assertFalse(any(os.path.islink(p) for p in tree(self.case)))


class Recording(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes[test.id()] = "pass"

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes[test.id()] = "fail"

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes[test.id()] = "error"

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes[test.id()] = "skip"

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.outcomes[test.id()] = "expected_failure"

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.outcomes[test.id()] = "unexpected_success"


def main():
    global SCRATCH
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    SCRATCH = Path(args.scratch)
    if SCRATCH.resolve() != SCRATCH or not SCRATCH.is_dir() or any(SCRATCH.iterdir()):
        print(f"scratch must be an existing, empty, real directory: {SCRATCH}", file=sys.stderr)
        return 2
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OutputPreflight)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2, resultclass=Recording).run(suite)
    report = {"helper": str(HELPER_PATH.relative_to(REPO)), "helper_file": helper.__file__,
              "python": sys.version.split()[0], "python_executable": sys.executable,
              "tests_run": result.testsRun,
              "tests": [{"name": name.rsplit(".", 1)[-1], "outcome": outcome} for name, outcome in result.outcomes.items()]}
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    sys.exit(main())
