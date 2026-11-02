"""atlas export builds in a .partial- folder beside --output and renames it into place."""

from contextlib import redirect_stderr
import errno
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from skippercast.atlas import export
from skippercast.atlas.export import main, write_exports
from tests._support import ROOT

DATA = ROOT / "atlas/avila-point-estero-2026-09-20/data/atlas.json"
FILES = ["atlas.geojson", "complete.gpx", "drift-lines.gpx", "manifest.json",
         "reef-outlines.gpx", "spot-notes.html", "waypoints.gpx"]


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def state(path):
    if path.is_symlink():
        return os.readlink(path)
    return {p.name: p.read_bytes() for p in path.iterdir()} if path.is_dir() else path.read_bytes()


class AtomicAtlasExport(unittest.TestCase):
    data = json.loads(DATA.read_text(encoding="utf-8"))

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.output = self.parent / "out"

    def test_success_same_files_and_bytes_no_partial_mode_not_0700(self):
        old = os.umask(0o022)
        try:
            first = write_exports(self.data, self.output)
        finally:
            os.umask(old)
        self.assertEqual(first, write_exports(self.data, self.parent / "again"))
        self.assertEqual(names(self.output), FILES)
        self.assertTrue(state(self.output) == state(self.parent / "again"), "export bytes differ")
        self.assertEqual(names(self.parent), ["again", "out"])
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o755)

    def test_builder_exception_or_interrupt_leaves_nothing(self):
        for error in (RuntimeError("boom"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(export, "notes_document", side_effect=error), \
                        self.assertRaises(type(error)):
                    write_exports(self.data, self.output)
                self.assertEqual(names(self.parent), [])

    def test_disk_full_on_second_gpx_leaves_nothing_and_main_exits_1(self):
        real, calls = Path.write_bytes, []

        def flaky(path, payload):
            calls.append(path.name)
            if len(calls) == 2:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(path, payload)
        with mock.patch.object(Path, "write_bytes", flaky), self.assertRaises(OSError):
            write_exports(self.data, self.output)
        self.assertEqual(names(self.parent), [])
        calls.clear()
        stderr = io.StringIO()
        with mock.patch.object(Path, "write_bytes", flaky), redirect_stderr(stderr), \
                self.assertRaises(SystemExit) as exit_:
            main(["export", "--data", str(DATA), "--output", str(self.output)])
        self.assertEqual(exit_.exception.code, 1)
        self.assertIn("Atlas operation failed:", stderr.getvalue())
        self.assertEqual(names(self.parent), [])

    def test_existing_output_folder_file_or_dangling_symlink_is_untouched(self):
        cases = {"folder": lambda p: (p.mkdir(), (p / "keep.txt").write_text("keep")),
                 "file": lambda p: p.write_text("keep"),
                 "symlink": lambda p: p.symlink_to(self.parent / "missing")}
        for kind, make in cases.items():
            with self.subTest(kind=kind):
                target = self.parent / kind
                make(target)
                before = state(target)
                with self.assertRaises(FileExistsError):
                    write_exports(self.data, target)
                self.assertEqual(state(target), before)
                self.assertEqual([n for n in names(self.parent) if ".partial-" in n], [])

    def test_output_appearing_during_build_is_not_overwritten(self):
        def racer(data):
            self.output.mkdir()
            (self.output / "other.txt").write_text("theirs")
            return "x"
        with mock.patch.object(export, "notes_document", side_effect=racer), \
                self.assertRaises(FileExistsError):
            write_exports(self.data, self.output)
        self.assertEqual(names(self.output), ["other.txt"])
        self.assertEqual(names(self.parent), ["out"])

    def test_missing_parents_are_created(self):
        self.output = self.parent / "a" / "b" / "out"
        write_exports(self.data, self.output)
        self.assertEqual(names(self.output), FILES)
        self.assertEqual(names(self.output.parent), ["out"])
