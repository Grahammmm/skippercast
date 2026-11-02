"""``coverage-status --apply`` checks every region.json before it writes any (RF2310-6). Synthetic fixture regions."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from skippercast.fleet import coverage

OLD = {"status": "missing", "reason": coverage.reason(0, 0)}
NEW = {"status": "partial", "reason": coverage.reason(4, 1)}


def region(bound=("fleet-registry",), entry=OLD, twice=False):
    data = {"id": "x", "source_bindings": {"charter-identity": list(bound)}, "coverage": {"charter-identity": dict(entry)}}
    if twice:
        data["notes"] = {"charter-identity": dict(entry)}
    return json.dumps(data, indent=2) + "\n"


class ApplyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.write("a", region())
        self.write("b", region())

    def write(self, ident, text):
        path = self.root / "regions" / ident / "region.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode())

    def raw(self, ident):
        return (self.root / "regions" / ident / "region.json").read_bytes()

    def leftovers(self):
        return sorted(p.name for p in self.root.glob("regions/*/.*.tmp"))

    def assert_fails_on_b(self, message):
        before = self.raw("a")
        with self.assertRaises(ValueError) as caught:
            coverage.apply({"a": NEW, "b": NEW}, self.root)
        self.assertEqual(str(caught.exception), f"b: {message}")
        self.assertEqual(self.raw("a"), before, "a must be byte-identical")
        self.assertEqual(self.leftovers(), [])

    def test_unbound_b_raises_before_a_is_written(self):
        self.write("b", region(bound=("operator-identities",)))
        self.assert_fails_on_b("charter-identity is not bound to fleet-registry")

    def test_missing_b_is_named_and_a_untouched(self):
        (self.root / "regions/b/region.json").unlink()
        self.assert_fails_on_b("region.json unreadable")

    def test_b_without_a_folder_is_named(self):
        before = self.raw("a")
        with self.assertRaisesRegex(ValueError, r"^c: region\.json unreadable$"):
            coverage.apply({"a": NEW, "c": NEW}, self.root)
        self.assertEqual(self.raw("a"), before)

    def test_truncated_b_is_named_and_a_untouched(self):
        self.write("b", region()[:40])
        self.assert_fails_on_b("region.json is not valid JSON")

    def test_invalid_utf8_b_is_named_and_a_untouched(self):
        self.write("b", region().encode()[:20] + b"\xff\xfe" + region().encode()[20:])
        self.assert_fails_on_b("region.json unreadable")

    def test_two_charter_identity_entries_in_b_raise_and_a_untouched(self):
        self.write("b", region(twice=True))
        self.assert_fails_on_b("no single coverage.charter-identity entry to update")

    def test_only_changed_ids_returned_and_unchanged_mtime_kept(self):
        self.write("b", region(entry=NEW))
        path_b = self.root / "regions/b/region.json"
        os.utime(path_b, ns=(1_000_000_000, 1_000_000_000))
        self.assertEqual(coverage.apply({"a": NEW, "b": NEW}, self.root), ["a"])
        self.assertEqual(json.loads(self.raw("a"))["coverage"]["charter-identity"], NEW)
        self.assertEqual(path_b.stat().st_mtime_ns, 1_000_000_000)
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(coverage.apply({"a": NEW, "b": NEW}, self.root), [])

    def test_replace_failing_on_second_file_propagates_no_temp_left_first_may_be_replaced(self):
        real, calls = os.replace, []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("disk full")
            real(src, dst)

        with mock.patch.object(coverage.os, "replace", flaky), self.assertRaisesRegex(OSError, "disk full"):
            coverage.apply({"a": NEW, "b": NEW}, self.root)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(self.raw("b"), region().encode(), "b keeps its old bytes")

    def test_main_apply_with_failing_region_exits_1_with_one_stderr_line(self):
        self.write("b", region(bound=()))
        before = self.raw("a")
        err, out = io.StringIO(), io.StringIO()
        with mock.patch.multiple(coverage, load_region=lambda ident: SimpleNamespace(id=ident), fleet_var=lambda: self.root,
                                 SqliteSink=mock.MagicMock(), load_snapshot=lambda sink, ident: None,
                                 coverage_status=lambda r, s: {"a": NEW, "b": NEW}, repo_root=lambda: self.root), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            self.assertEqual(coverage.main(["--region", "CA", "--apply"]), 1)
        self.assertEqual(err.getvalue(), "coverage-status: b: charter-identity is not bound to fleet-registry\n")
        self.assertEqual(json.loads(out.getvalue()), {"a": NEW, "b": NEW})
        self.assertEqual(self.raw("a"), before)


if __name__ == "__main__":
    unittest.main()
