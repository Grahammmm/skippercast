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
                                 coverage_status=lambda r, s, c: {"a": NEW, "b": NEW}, repo_root=lambda: self.root), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            self.assertEqual(coverage.main(["--region", "CA", "--apply"]), 1)
        self.assertEqual(err.getvalue(), "coverage-status: b: charter-identity is not bound to fleet-registry\n")
        self.assertEqual(json.loads(out.getvalue()), {"a": NEW, "b": NEW})
        self.assertEqual(self.raw("a"), before)

    def run_main(self, *argv, statuses=None):
        """coverage.main with every store mocked; (exit code, stdout, stderr, the confirmations coverage_status got)."""
        seen, err, out = [], io.StringIO(), io.StringIO()

        def status(region, snapshot, confirmations):
            seen.append(list(confirmations))
            return statuses or {"a": NEW, "b": NEW}

        with mock.patch.multiple(coverage, load_region=lambda ident: SimpleNamespace(id=ident), fleet_var=lambda: self.root,
                                 SqliteSink=mock.MagicMock(), load_snapshot=lambda sink, ident: None,
                                 coverage_status=status, repo_root=lambda: self.root), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = coverage.main(["--region", "CA", *argv])
        return code, out.getvalue(), err.getvalue(), seen

    def ledger(self, text, sink="staging"):
        path = self.root / "CA" / "confirmations" / f"{sink}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_main_passes_the_selected_sinks_confirmations_and_an_absent_ledger_is_none(self):
        self.assertEqual(self.run_main("--apply")[3], [[]])
        row = {"vessel_id": "v1", "mmsi": "999000001", "method": "operator-statement", "confirmed_on": "2026-11-01",
               "evidence_ref": "ref-1", "withdrawn_on": None}
        self.ledger(json.dumps({"version": 1, "entries": [row]}))
        self.assertEqual(self.run_main()[3], [[row]])

    def test_main_with_a_corrupt_ledger_exits_1_before_any_store_or_apply(self):
        before = self.raw("a")
        for label, text in (("not json", "{"), ("wrong version", '{"version": 2, "entries": []}'),
                            ("duplicate pair", json.dumps({"version": 1, "entries": [
                                {"vessel_id": "v1", "mmsi": "999000001", "method": "operator-statement",
                                 "confirmed_on": "2026-11-01", "evidence_ref": "r", "withdrawn_on": None}] * 2}))):
            with self.subTest(label):
                self.ledger(text)
                code, out, err, seen = self.run_main("--apply")
                self.assertEqual((code, out, seen), (1, "", []))
                self.assertEqual(err, "coverage-status: the confirmation ledger is unreadable or invalid\n")
                self.assertEqual(self.raw("a"), before)
                self.assertEqual(self.leftovers(), [])

    def legacy(self):
        return self.root / "regions" / "a" / f".region.json.{os.getpid()}.tmp"

    def test_apply_ignores_planted_legacy_temp_symlink(self):
        sentinel = self.root / "sentinel.txt"
        sentinel.write_bytes(b"keep")
        self.legacy().symlink_to(sentinel)
        self.assertEqual(coverage.apply({"a": NEW}, self.root), ["a"])
        final = self.root / "regions/a/region.json"
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertTrue(self.legacy().is_symlink())
        self.assertEqual(os.readlink(self.legacy()), str(sentinel))
        self.assertFalse(final.is_symlink())
        self.assertEqual(final.read_bytes(), region(entry=NEW).encode())

    def test_apply_ignores_stale_regular_dangling_and_directory_entries(self):
        gone = self.root / "gone.txt"
        for kind in ("regular", "dangling", "directory"):
            with self.subTest(kind=kind):
                self.write("a", region())
                legacy = self.legacy()
                if legacy.is_symlink() or legacy.is_file():
                    legacy.unlink()
                elif legacy.is_dir():
                    legacy.rmdir()
                if kind == "regular":
                    legacy.write_bytes(b"stale")
                elif kind == "dangling":
                    legacy.symlink_to(gone)
                else:
                    legacy.mkdir()
                self.assertEqual(coverage.apply({"a": NEW}, self.root), ["a"])
                self.assertEqual(self.raw("a"), region(entry=NEW).encode())
                if kind == "regular":
                    self.assertEqual(legacy.read_bytes(), b"stale")
                elif kind == "dangling":
                    self.assertTrue(legacy.is_symlink())
                else:
                    self.assertTrue(legacy.is_dir() and not legacy.is_symlink())
                self.assertFalse(gone.exists())

    def test_apply_fresh_temp_is_same_directory_and_closed_before_replace(self):
        path = self.root / "regions/a/region.json"
        path.chmod(0o640)
        real_mkstemp, real_replace, seen = tempfile.mkstemp, os.replace, {}

        def mkstemp(**kw):
            fd, name = real_mkstemp(**kw)
            seen["name"] = name
            return fd, name

        def replace(src, dst):
            seen["src"] = str(src)
            self.assertEqual(Path(src).read_bytes(), region(entry=NEW).encode(), "fully written before replace")
            real_replace(src, dst)

        with mock.patch.object(coverage.tempfile, "mkstemp", mkstemp), mock.patch.object(coverage.os, "replace", replace):
            coverage.apply({"a": NEW}, self.root)
        self.assertEqual(seen["src"], seen["name"])
        self.assertEqual(Path(seen["name"]).parent, path.parent)
        self.assertNotEqual(Path(seen["name"]), self.legacy())
        self.assertFalse(path.is_symlink())
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertFalse(Path(seen["name"]).exists())
        self.assertEqual(self.leftovers(), [])

    def _failure(self, attr, replacement):
        sentinel = self.root / "sentinel.txt"
        sentinel.write_bytes(b"keep")
        self.legacy().symlink_to(sentinel)
        closed, real_close = [], os.close
        with mock.patch.object(coverage.os, "close", lambda fd: (closed.append(fd), real_close(fd))[1]), \
                mock.patch.object(coverage.os, attr, replacement), self.assertRaisesRegex(OSError, "boom"):
            coverage.apply({"a": NEW}, self.root)
        self.assertEqual(self.raw("a"), region().encode())
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertTrue(self.legacy().is_symlink())
        self.assertEqual([p.name for p in self.root.glob("regions/a/.*.tmp")], [self.legacy().name])
        return closed

    def test_apply_write_failure_closes_descriptor_and_only_cleans_own_temp(self):
        files, real = [], os.fdopen

        def fdopen(fd, *a, **k):
            f = real(fd, *a, **k)
            files.append(f)
            f.write = mock.Mock(side_effect=OSError("boom"))
            return f

        self._failure("fdopen", fdopen)
        self.assertTrue(files and files[0].closed)

    def test_apply_failure_before_fdopen_owns_descriptor_closes_it(self):
        closed = self._failure("fdopen", mock.Mock(side_effect=OSError("boom")))
        self.assertEqual(len(closed), 1)
        with self.assertRaises(OSError):
            os.fstat(closed[0])

    def test_apply_replace_failure_preserves_old_destination_and_stale_entries(self):
        self._failure("replace", mock.Mock(side_effect=OSError("boom")))


if __name__ == "__main__":
    unittest.main()
