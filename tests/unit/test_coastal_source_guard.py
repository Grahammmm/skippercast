"""The coastal source guard and the test harness agree on project bytecode.

src/skippercast/coastal/_source_bootstrap.py refuses any __pycache__ or .pyc/.pyo
under the code root before a coastal runner imports the project. Attempt 1 of the
2026-10-19 four128 trial died there because an earlier pytest run had written
src/skippercast/**/__pycache__ into the worktree. The repository conftest.py now
turns bytecode writing off for test sessions, and a refusal names the offending
entry and the remedy.
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from skippercast.coastal._source_bootstrap import guard_project_source


class PytestSessionWritesNoBytecode(unittest.TestCase):
    def test_bytecode_writing_is_off_for_the_session_and_its_subprocesses(self):
        self.assertIs(sys.dont_write_bytecode, True)
        # python -B does not set the variable, so this shows the root conftest ran.
        self.assertEqual(os.environ.get("PYTHONDONTWRITEBYTECODE"), "1")

    def test_importing_a_source_module_leaves_no_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "probe_module.py"
            source.write_text("VALUE = 46\n", encoding="utf-8")
            spec = importlib.util.spec_from_file_location("probe_module_sc8a", source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.VALUE, 46)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["probe_module.py"])


class SourceGuardRefusals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "skippercast"
        (self.root / "coastal").mkdir(parents=True)
        (self.root / "__init__.py").write_text("", encoding="utf-8")
        (self.root / "coastal" / "runner.py").write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def refusal(self):
        with self.assertRaises(ValueError) as caught:
            guard_project_source(self.root)
        return str(caught.exception)

    def test_source_only_tree_passes(self):
        self.assertEqual(guard_project_source(self.root), os.path.abspath(self.root))

    def test_pycache_refusal_names_the_relative_path_and_the_remedy(self):
        (self.root / "coastal" / "__pycache__").mkdir()
        message = self.refusal()
        relative = os.path.join("coastal", "__pycache__")
        self.assertTrue(message.startswith(f"project compiled bytecode forbidden: {relative};"), message)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", message)
        self.assertIn("python -B", message)
        self.assertIn(f"remove every __pycache__ directory and .pyc/.pyo file under {os.path.abspath(self.root)}",
                      message)

    def test_stray_compiled_files_are_refused_by_relative_path(self):
        for name in ("runner.cpython-312.pyc", "runner.pyo"):
            with self.subTest(name=name):
                stray = self.root / "coastal" / name
                stray.write_bytes(b"")
                message = self.refusal()
                self.assertIn(f"compiled bytecode forbidden: {os.path.join('coastal', name)};", message)
                self.assertIn("python -B", message)
                stray.unlink()

    def test_symlink_is_refused_by_relative_path(self):
        (self.root / "coastal" / "linked.py").symlink_to(self.root / "coastal" / "runner.py")
        self.assertEqual(self.refusal(), "project source symlink/compiled bytecode forbidden: "
                                         + os.path.join("coastal", "linked.py"))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs os.mkfifo")
    def test_special_file_is_refused_by_relative_path(self):
        os.mkfifo(self.root / "coastal" / "pipe")
        self.assertEqual(self.refusal(), "project source special file forbidden: "
                                         + os.path.join("coastal", "pipe"))

    def test_root_must_be_a_real_directory(self):
        linked = Path(self.tmp.name) / "linked-root"
        linked.symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, "must be a regular directory"):
            guard_project_source(linked)


if __name__ == "__main__":
    unittest.main()
