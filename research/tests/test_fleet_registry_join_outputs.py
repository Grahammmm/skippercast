"""RF2330-10: join_fleet_registries keeps its private outputs private and refuses a bad resolved.jsonl line.

Synthetic inputs only (the builders of ``test_fleet_registry_join``); every file lives in a temporary directory.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from research.scripts import join_fleet_registries as J
from research.tests.test_fleet_registry_join import US, ship_zip, state_db, vessel

FIXED = MagicMock()
FIXED.now.return_value.strftime.return_value = "2026-01-01T00:00:00Z"


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@US
class OutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.resolved = self.tmp / "resolved.jsonl"
        self.resolved.write_text(json.dumps(vessel("Test Wave", "morro-bay")) + "\n")
        self.state = state_db(self.tmp / "state.sqlite", [(999000001, "TEST WAVE", "ZZZ9001", 30, 12.0)],
                              [(999000001, "morro-bay", "2026-10-01")])
        self.fcc = ship_zip(self.tmp / "l_ship.zip", [{"name": "Test Wave", "call": "ZZZ9001", "mmsi": "999000001",
                                                       "zip": "93499", "entity": "Example Fishing LLC"}])

    def run_main(self, out: Path) -> tuple:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch.object(J, "datetime", FIXED):
            try:
                code = J.main(["--resolved", str(self.resolved), "--state", str(self.state), "--fcc", str(self.fcc),
                               "--out", str(out)])
            except SystemExit as exc:
                code = exc.code
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_private(self, out: Path):
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["join.json", "join.md"])
        for name in ("join.json", "join.md"):
            self.assertEqual(mode(out / name), 0o600)

    def test_fresh_out_is_0700_with_0600_files_identical_to_the_old_writes(self):
        out = self.tmp / "private" / "out"
        code, stdout, stderr = self.run_main(out)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(mode(out), 0o700)
        self.assert_private(out)
        old = self.tmp / "old"
        old.mkdir()
        with patch.object(J, "_write_private", lambda path, text: path.write_text(text)):
            self.assertEqual(self.run_main(old)[:2], (0, stdout))
        for name in ("join.json", "join.md"):
            self.assertEqual((out / name).read_bytes(), (old / name).read_bytes(), name)

    def test_failed_write_leaves_no_tmp_and_no_target(self):
        with patch.object(J.os, "replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            J._write_private(self.tmp / "join.json", "{}")
        self.assertEqual(list(self.tmp.glob("join.json*")), [])

    def test_symlinked_or_file_out_is_refused(self):
        target = self.tmp / "target"
        target.mkdir()
        for link, dest in ((self.tmp / "link", target), (self.tmp / "dangling", self.tmp / "missing")):
            link.symlink_to(dest)
            code, _, stderr = self.run_main(link)
            self.assertEqual(code, 2)
            self.assertIn("--out must not be a symlink", stderr)
        self.assertEqual(list(target.iterdir()), [])
        self.assertFalse((self.tmp / "missing").exists())
        afile = self.tmp / "afile"
        afile.write_text("keep")
        code, _, stderr = self.run_main(afile)
        self.assertEqual(code, 2)
        self.assertIn("--out must be a folder", stderr)
        self.assertEqual(afile.read_text(), "keep")

    def test_loose_existing_out_is_kept_with_one_note_and_0600_files(self):
        out = self.tmp / "loose"
        out.mkdir()
        out.chmod(0o755)
        code, _, stderr = self.run_main(out)
        self.assertEqual(code, 0)
        self.assertEqual(stderr.splitlines(), ["note: --out is readable by others (mode 0755)"])
        self.assertEqual(mode(out), 0o755)
        self.assert_private(out)

    def test_bad_resolved_line_is_refused_by_number_before_any_other_input(self):
        good = json.dumps(vessel("Test Wave", "morro-bay"))
        for bad in ('{"name": "Test Wa', "[1, 2]", '{"id": 5}', '{"name": ""}', '{"name": 7}', "null"):
            with self.subTest(bad=bad):
                self.resolved.write_text(f"{good}\n\n{bad}\n{good}\n")
                out = self.tmp / "never"
                with patch.object(J, "load_ais", side_effect=AssertionError("load_ais called")), \
                        patch.object(J, "load_fcc", side_effect=AssertionError("load_fcc called")):
                    code, stdout, stderr = self.run_main(out)
                self.assertEqual((code, stdout), (2, ""))
                self.assertIn("--resolved line 3: not a JSON object with a name", stderr)
                self.assertNotIn(bad, stderr)
                self.assertFalse(out.exists())

    def test_blank_lines_are_still_skipped(self):
        self.resolved.write_text("\n" + json.dumps(vessel("Test Wave", "morro-bay")) + "\n   \n\n"
                                 + json.dumps(vessel("Sea Example", "morro-bay")) + "\n\n")
        code, stdout, _ = self.run_main(self.tmp / "out")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["inputs"]["registry"], 2)


if __name__ == "__main__":
    unittest.main()
