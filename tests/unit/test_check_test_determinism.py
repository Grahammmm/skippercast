"""Deterministic-test lint (SC-CI-5): what it flags, what it lets through, and that only ADDED lines fail.

The sample lines are assembled from pieces so this file does not trip the lint it tests.
"""
import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._support import ROOT

SCRIPT = ROOT / "scripts" / "check_test_determinism.py"
spec = importlib.util.spec_from_file_location("check_test_determinism", SCRIPT)
assert spec is not None and spec.loader is not None
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)

NOW = "stamp = datetime" + ".now(timezone.utc)"
TODAY = "day = date" + ".today()"
EPOCH = "t0 = time" + ".time()"
BIND = "srv.bind(('127.0.0.1', " + "8080))"
HTTP = "srv = HTTPServer(('127.0.0.1', " + "8080), Handler)"
PORT_KW = "start(port=" + "8080)"
PORT_FLAG = "cmd = ['serve', '--port', '" + "8080']"
PY_ASSERT = "assert sys.version.startswith('3" + ".11')"
PY_ASSERT_NAME = "self.assertEqual(python_label, 'python 3" + ".11')"
PRAGMA = "  # determinism-ok: pins the real clock on purpose"
PORT_NUMBER = "80" + "80"


def classify_spans(lines):
    return lint.classify_spans(list(lines))


def kinds(*lines):
    return [kind for _, kind in lint.classify(list(lines))]


class ClassifyTest(unittest.TestCase):
    def test_wall_clock_reads_are_flagged(self):
        for line in (NOW, TODAY, EPOCH):
            self.assertEqual(kinds(line), ["clock"], line)

    def test_durations_and_comments_are_not_clock_reads(self):
        self.assertEqual(kinds("start = time.monotonic()", "# " + NOW, ""), [])

    def test_a_frozen_clock_in_the_file_allows_clock_reads(self):
        for freeze in ("from freezegun import freeze_time", "import time_machine",
                       "monkeypatch.setattr(module.time, 'time', lambda: 1.0)",
                       "with mock.patch('pkg.mod.datetime') as fake:",
                       "with mock.patch.object(time, \"time\", return_value=123):",
                       "with mock.patch.object(module.datetime, 'now', return_value=fixed):"):
            self.assertEqual(kinds(freeze, NOW), [], freeze)

    def test_patch_object_of_the_clock_freezes_it_but_other_attributes_do_not(self):
        self.assertEqual(kinds('with mock.patch.object(time, "time", return_value=123):', EPOCH), [])
        self.assertEqual(kinds('with mock.patch.object(time, "sleep"):', EPOCH), ["clock"])

    def test_pragma_on_the_line_or_the_line_above(self):
        self.assertEqual(kinds(NOW + PRAGMA), [])
        self.assertEqual(kinds("#" + PRAGMA.lstrip(" #"), NOW), [])
        self.assertEqual(kinds(NOW + "  # determinism-ok:"), ["clock"])  # a reason is required

    def test_fixed_ports_are_flagged_and_port_zero_is_not(self):
        for line in (BIND, HTTP, PORT_KW, PORT_FLAG):
            self.assertEqual(kinds(line), ["port"], line)
        self.assertEqual(kinds("srv.bind(('127.0.0.1', 0))", "start(port=0)", "url = 'http://127.0.0.1:%d' % port"), [])

    def test_python_version_assertion_needs_a_guard(self):
        for line in (PY_ASSERT, PY_ASSERT_NAME):
            self.assertEqual(kinds(line), ["version"], line)
            self.assertEqual(kinds("if sys.version_info >= (3, 12):", line), [], line)
        self.assertEqual(kinds("assert area == 3.14", "assert python_ok", "python = 'x'"), [])

    def test_patched_python_version_is_not_a_version_assumption(self):
        self.assertEqual(kinds("monkeypatch.setattr(platform, 'python_version', lambda: '3.13.0')", PY_ASSERT), [])

    def test_patching_something_else_on_the_time_module_does_not_freeze_the_clock(self):
        for other in ('with patch("time.sleep"):', "monkeypatch.setattr(module.time, 'sleep', lambda s: None)",
                      'with mock.patch.object(time, "sleep"):'):
            self.assertEqual(kinds(other, EPOCH), ["clock"], other)
        self.assertEqual(kinds('with patch("time.time", return_value=1.0):', EPOCH), [])
        self.assertEqual(kinds("monkeypatch.setattr('time.time', lambda: 1.0)", EPOCH), [])

    def test_a_comment_or_docstring_or_string_naming_a_freezer_is_not_a_freeze(self):
        self.assertEqual(kinds("# Do not use freezegun here.", EPOCH), ["clock"])
        self.assertEqual(kinds("EPOCH = 1  # freeze_time would hide this", EPOCH), ["clock"])
        self.assertEqual(kinds('"""freezegun is not used', 'in this module."""', EPOCH), ["clock"])
        self.assertEqual(kinds("pytest.skip('needs freezegun')", EPOCH), ["clock"])
        self.assertEqual(kinds("from freezegun import freeze_time  # a real freezer", EPOCH), [])

    def test_a_wrapped_patch_call_still_freezes(self):
        self.assertEqual(kinds("with mock.patch.object(", '    time, "time", return_value=123', "):", EPOCH), [])

    def test_a_wrapped_fixed_port_is_flagged_and_port_zero_is_not(self):
        wrapped = ["with socket.socket() as s:", "    s.bind((", '        "127.0.0.1",', "        " + PORT_NUMBER + ",", "    ))"]
        self.assertEqual(classify_spans(wrapped), [(2, 5, "port")])
        self.assertEqual(kinds(*wrapped[:3], "        0,", "    ))"), [])
        self.assertEqual(kinds("srv = HTTPServer(", "    ('127.0.0.1', " + PORT_NUMBER + "),", "    Handler,", ")"), ["port"])

    def test_a_wrapped_python_version_assertion_needs_a_guard(self):
        wrapped = ["assert platform.python_version() == (", '    "3.' + '11.0"', ")"]
        self.assertEqual(classify_spans(wrapped), [(1, 3, "version")])
        self.assertEqual(kinds("if sys.version_info >= (3, 12):", *wrapped), [])
        self.assertEqual(kinds("assert area == (", "    3.14", ")"), [])

    def test_every_clock_read_in_a_long_string_statement_is_its_own_hit(self):
        self.assertEqual(classify_spans(["SCRIPT = '''", EPOCH, "x = 1", EPOCH, "'''"]), [(2, 2, "clock"), (4, 4, "clock")])

    def test_a_pragma_anywhere_on_a_wrapped_statement_passes(self):
        self.assertEqual(kinds("s.bind((", "    '127.0.0.1', " + PORT_NUMBER + ",", "))" + PRAGMA), [])
        self.assertEqual(kinds("# determinism-ok: fixed on purpose", "s.bind((", "    '127.0.0.1', " + PORT_NUMBER + ",", "))"), [])


class DiffModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.git("init", "-q", "-b", "main")
        self.write("tests/unit/test_old.py", ["import datetime", NOW, "x = 1"])
        self.write("tests/unit/test_other.py", [NOW])
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def write(self, name, lines):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")

    def run_lint(self, *argv):
        out = io.StringIO()
        with mock.patch.object(lint, "ROOT", str(self.root)), contextlib.redirect_stdout(out):
            code = lint.main(list(argv))
        return code, out.getvalue()

    def commit_change(self):
        self.write("tests/unit/test_old.py", ["import datetime", NOW, "x = 1", TODAY])  # one added line
        self.write("tests/unit/test_new.py", [BIND, "ok = 1"])                          # a new file
        self.write("tests/unit/test_fine.py", ["srv.bind(('127.0.0.1', 0))"])
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "change")

    def test_only_added_lines_fail(self):
        self.commit_change()
        code, out = self.run_lint("--base", "HEAD^1")
        self.assertEqual(code, 1, out)
        self.assertIn("new=2 existing=2", out)
        self.assertIn("::error file=tests/unit/test_old.py,line=4", out)
        self.assertIn("::error file=tests/unit/test_new.py,line=1", out)
        self.assertNotIn("::error file=tests/unit/test_other.py", out)  # untouched file: warning only

    def test_warn_only_and_whole_tree_modes_pass(self):
        self.commit_change()
        code, out = self.run_lint("--base", "HEAD^1", "--warn-only")
        self.assertEqual(code, 0, out)
        self.assertIn("::warning file=tests/unit/test_new.py", out)
        code, out = self.run_lint()
        self.assertEqual(code, 0, out)
        self.assertIn("new=0 existing=4", out)

    def test_pragma_on_an_added_line_passes(self):
        self.write("tests/unit/test_new.py", [NOW + PRAGMA])
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "pragma")
        code, out = self.run_lint("--base", "HEAD^1")
        self.assertEqual(code, 0, out)

    def test_a_pure_rename_adds_no_lines(self):
        self.git("mv", "tests/unit/test_old.py", "tests/unit/test_renamed.py")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "rename")
        code, out = self.run_lint("--base", "HEAD^1")
        self.assertEqual(code, 0, out)
        self.assertIn("new=0 existing=2", out)

    def test_editing_a_wrapped_statement_fails_but_editing_beside_it_does_not(self):
        wrapped = ["import socket", "", "def test_port():", "    s = socket.socket()", "    s.bind((",
                   '        "127.0.0.1",', "        " + PORT_NUMBER + ",", "    ))", "    s.close()"]
        self.write("tests/unit/test_wrapped.py", wrapped)
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "wrapped")
        self.write("tests/unit/test_wrapped.py", wrapped[:-1] + ["    s.shutdown(0)"])  # beside the statement
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "beside")
        code, out = self.run_lint("--base", "HEAD^1")
        self.assertEqual(code, 0, out)
        self.assertIn("new=0 existing=3", out)
        edited = wrapped[:5] + ['        "0.0.0.0",'] + wrapped[6:]  # one argument line of the statement changes
        self.write("tests/unit/test_wrapped.py", edited)
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "argument")
        code, out = self.run_lint("--base", "HEAD^1")
        self.assertEqual(code, 1, out)
        self.assertIn("::error file=tests/unit/test_wrapped.py,line=5,title=Deterministic-test lint (port)", out)

    def test_an_unresolvable_base_fails_closed(self):
        code, out = self.run_lint("--base", "no-such-ref")
        self.assertEqual(code, 2, out)
        self.assertIn("::error::", out)


class WiringTest(unittest.TestCase):
    def test_ci_runs_the_lint_on_pull_requests_and_merge_queue(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("python scripts/check_test_determinism.py --base HEAD^1", text)
        self.assertIn("python scripts/check_test_determinism.py\n", text)  # push/nightly: count only

    def test_the_repository_itself_has_no_new_line_problems_to_report(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(lint.main([]), 0)  # whole tree: warnings only, never fails


if __name__ == "__main__":
    unittest.main()
