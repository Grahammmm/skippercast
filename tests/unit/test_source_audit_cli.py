"""The source-audit command parses its arguments before any catalog load or documentation probe."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import importlib
import runpy
import sys
import unittest
from unittest import mock

from skippercast import http
from skippercast.platform import contracts, source_audit

MODULE = "skippercast.platform.source_audit"
SOURCES = {"a": {"id": "a", "documentation_url": "https://docs.example.org/a"},
           "b": {"id": "b", "documentation_url": "https://docs.example.org/b"}}
RESULT = {"schema_version": 1, "checked_at": "t", "sources": [{"status": "accessible"}, {"status": "unavailable"}]}
SUMMARY = "{'checked': 2, 'accessible': 1}\n"


def refuse(name):
    def fail(*args, **kwargs):
        raise AssertionError(f"{name} must not run")
    return fail


class FakeResponse:
    status = 200
    final_url = "https://docs.example.org/a"
    headers = {}
    body = b"documentation"
    receipt = mock.Mock(sha256="0" * 64)


class FakeSession:
    def __init__(self, calls):
        self.calls = calls

    def get(self, url, **kwargs):
        self.calls.append(("get", url))
        return FakeResponse()


def run_main(argv, **patches):
    out, err = StringIO(), StringIO()
    with mock.patch.multiple(source_audit, **patches), redirect_stdout(out), redirect_stderr(err):
        try:
            code = source_audit.main(argv)
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


def run_module(argv, calls, catalog=None):
    """Run the module as `python -m` would, with contracts and transport replaced."""
    out, err = StringIO(), StringIO()
    loads = catalog or (lambda root=None: calls.append("catalog") or ({}, SOURCES))
    with mock.patch.dict(sys.modules), mock.patch.object(sys, "argv", ["source_audit", *argv]), \
            mock.patch.object(contracts, "load_catalogs", loads), \
            mock.patch.object(contracts, "atomic_json", lambda path, value: calls.append(("write", path, len(value["sources"])))), \
            mock.patch.object(http, "default_session", lambda: FakeSession(calls)), \
            redirect_stdout(out), redirect_stderr(err):
        sys.modules.pop(MODULE, None)
        try:
            runpy.run_module(MODULE, run_name="__main__")
            code = 0
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class ParseBeforeAudit(unittest.TestCase):
    sentinels = dict(audit=refuse("audit"), load_catalogs=refuse("catalog"), atomic_json=refuse("writer"))

    def test_help_without_audit_or_catalog(self):
        code, out, _ = run_main(["--help"], **self.sentinels)
        self.assertEqual(code, 0)
        self.assertIn("--output", out)

    def test_usage_errors_before_audit(self):
        for argv in ([], ["--output"], ["--output", "x.json", "--bogus"]):
            with self.subTest(argv=argv):
                code, out, err = run_main(argv, **self.sentinels)
                self.assertEqual(code, 2)
                self.assertIn("usage:", err)
                self.assertEqual(out, "")

    def test_catalog_failure_does_not_mask_usage(self):
        broken = {"load_catalogs": mock.Mock(side_effect=ValueError("catalog unavailable")), "atomic_json": refuse("writer")}
        code, _, err = run_main(["--output"], **broken)
        self.assertEqual(code, 2)
        self.assertIn("usage:", err)
        self.assertNotIn("catalog unavailable", err)
        code, out, _ = run_main(["--help"], **broken)
        self.assertEqual(code, 0)
        self.assertIn("--output", out)
        broken["load_catalogs"].assert_not_called()

    def test_valid_output_audits_once_and_preserves_summary(self):
        order = []
        audit = mock.Mock(side_effect=lambda: order.append("audit") or RESULT)
        writer = mock.Mock(side_effect=lambda path, value: order.append("write"))
        code, out, _ = run_main(["--output", "var/my output.json"], audit=audit, atomic_json=writer)
        self.assertEqual(code, 0)
        audit.assert_called_once_with()
        writer.assert_called_once_with("var/my output.json", RESULT)
        self.assertIs(writer.call_args.args[1], RESULT)
        self.assertEqual(order, ["audit", "write"])
        self.assertEqual(out, SUMMARY)

    def test_audit_and_writer_failures_are_not_success(self):
        writer = mock.Mock()
        out = StringIO()
        with mock.patch.multiple(source_audit, audit=mock.Mock(side_effect=OSError("audit failed")), atomic_json=writer), \
                redirect_stdout(out), self.assertRaises(OSError):
            source_audit.main(["--output", "x.json"])
        writer.assert_not_called()
        self.assertEqual(out.getvalue(), "")
        with mock.patch.multiple(source_audit, audit=mock.Mock(return_value=RESULT),
                                 atomic_json=mock.Mock(side_effect=OSError("write failed"))), \
                redirect_stdout(out), self.assertRaises(OSError):
            source_audit.main(["--output", "x.json"])
        self.assertEqual(out.getvalue(), "")

    def test_import_is_inert(self):
        with mock.patch.object(contracts, "load_catalogs", refuse("catalog")), \
                mock.patch.object(contracts, "atomic_json", refuse("writer")), \
                mock.patch.object(http, "default_session", refuse("transport")), \
                mock.patch.object(sys, "argv", ["source_audit", "--bogus"]), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            importlib.reload(source_audit)
        importlib.reload(source_audit)


class ModuleGuard(unittest.TestCase):
    def test_help_and_usage_errors_touch_nothing(self):
        for argv, expected in ((["--help"], 0), ([], 2), (["--output"], 2), (["--output", "x.json", "--bogus"], 2)):
            with self.subTest(argv=argv):
                calls = []
                code, out, err = run_module(argv, calls, catalog=refuse("catalog"))
                self.assertEqual(code, expected)
                self.assertEqual(calls, [])
                self.assertIn("--output" if expected == 0 else "usage:", out if expected == 0 else err)

    def test_valid_output_audits_each_source_once_then_writes(self):
        calls = []
        code, out, _ = run_module(["--output", "x.json"], calls)
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], "catalog")
        self.assertEqual(sorted(c for c in calls if c[0] == "get"),
                         [("get", "https://docs.example.org/a"), ("get", "https://docs.example.org/b")])
        self.assertEqual(calls[-1], ("write", "x.json", 2))
        self.assertEqual(out, "{'checked': 2, 'accessible': 2}\n")


if __name__ == "__main__":
    unittest.main()
