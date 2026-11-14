"""Exercise the supported CLI and reject the retired personal-monitor commands."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from skippercast import __version__
from skippercast.__main__ import main
from tests._support import ROOT


class CommandHelp(unittest.TestCase):
    def test_subcommand_help_reaches_its_parser(self):
        for command, flag in (("validate", "paths"), ("atlas", "--data")):
            with self.subTest(command=command):
                stream = StringIO()
                with redirect_stdout(stream), self.assertRaises(SystemExit) as raised:
                    main([command, "--help"])
                self.assertEqual(raised.exception.code, 0)
                self.assertIn(flag, stream.getvalue())

    def test_removed_commands_are_rejected(self):
        for command in ("demo", "collect"):
            with self.subTest(command=command):
                stream = StringIO()
                with redirect_stderr(stream), self.assertRaises(SystemExit) as raised:
                    main([command])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("invalid choice", stream.getvalue())

    def test_root_help_and_version(self):
        for flag, expected in (("--help", "{atlas,validate}"), ("--version", __version__)):
            with self.subTest(flag=flag):
                stream = StringIO()
                with redirect_stdout(stream), self.assertRaises(SystemExit) as raised:
                    main([flag])
                self.assertEqual(raised.exception.code, 0)
                self.assertIn(expected, stream.getvalue())
                if flag == "--help":
                    self.assertNotIn("demo", stream.getvalue())
                    self.assertNotIn("collect", stream.getvalue())

    def test_validate_dispatches_and_preserves_failure_status(self):
        with redirect_stdout(StringIO()) as stream:
            status = main(["validate", "sources-catalog", str(ROOT / "catalog/sources.json")])
        self.assertEqual(status, 0)
        self.assertIn("valid sources-catalog", stream.getvalue())
        with TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text("{}", encoding="utf-8")
            with redirect_stderr(StringIO()):
                self.assertEqual(main(["validate", "sources-catalog", str(invalid)]), 1)

    def test_atlas_validate_and_export(self):
        data = str(ROOT / "atlas/avila-point-estero-2026-09-20/data/atlas.json")
        with redirect_stdout(StringIO()) as stream:
            self.assertEqual(main(["atlas", "validate", "--data", data]), 0)
        validated = json.loads(stream.getvalue())
        with TemporaryDirectory() as directory:
            output = Path(directory) / "export"
            with redirect_stdout(StringIO()) as stream:
                self.assertEqual(main(["atlas", "export", "--data", data,
                                       "--output", str(output)]), 0)
            exported = json.loads(stream.getvalue())
            for key, value in validated.items():
                self.assertEqual(exported[key], value)
            for name in ("complete.gpx", "atlas.geojson", "spot-notes.html", "manifest.json"):
                self.assertGreater((output / name).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
