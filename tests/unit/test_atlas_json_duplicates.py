"""The atlas CLI refuses repeated JSON member names instead of keeping only the last."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from skippercast.atlas import export
from skippercast.atlas.export import main
from tests._support import ROOT

DATA = ROOT / "atlas/avila-point-estero-2026-09-20/data/atlas.json"
TEXT = DATA.read_text(encoding="utf-8")
SCHEMA = '"schema_version": 1,'
DEPTH = '"native_center_depth_ft": '
FAILURE = "Atlas operation failed: Duplicate atlas JSON key\n"


def run(action, text, base, output=None, raw=None):
    path = base / "in.json"
    path.write_bytes(raw if raw is not None else text.encode("utf-8"))
    argv = [action, "--data", str(path)] + (["--output", str(output)] if output else [])
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            main(argv)
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


def dup_schema(first="999", last="1"):
    return TEXT.replace(SCHEMA, f'"schema_version": {first}, "schema_version": {last},', 1)


def dup_depth(first="999"):
    return TEXT.replace(DEPTH, f'{DEPTH}{first}, {DEPTH}', 1)


class DuplicateAtlasMembers(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.output = self.base / "nested" / "out"

    def refused(self, text, extra=None):
        for action in ("validate", "export"):
            with self.subTest(action=action), \
                    mock.patch.object(export, "validate") as check, \
                    mock.patch.object(export, "write_exports") as write:
                output = self.output if action == "export" else None
                code, out, err = run(action, text, self.base, output)
                self.assertEqual((code, out, err), (1, "", FAILURE))
                check.assert_not_called()
                write.assert_not_called()
                self.assertFalse(self.output.parent.exists())

    def test_root_duplicates_are_refused_in_either_order(self):
        self.refused(dup_schema("999", "1"))
        self.refused(dup_schema("1", "999"))
        self.refused(dup_schema("1", "1"))
        self.refused(TEXT.replace('"fishing_depth_limit_ft": 200,',
                                  '"fishing_depth_limit_ft": 500, "fishing_depth_limit_ft": 200,', 1))

    def test_nested_and_falsy_first_values_are_refused(self):
        self.refused(dup_depth("999"))
        self.refused(dup_depth("0"))
        self.refused(TEXT.replace(SCHEMA, '"extra": null, "extra": 1, ' + SCHEMA, 1))
        self.refused(TEXT.replace(SCHEMA, '"extra": [{"a": false, "a": true}], ' + SCHEMA, 1))

    def test_escaped_spelling_is_the_same_name(self):
        self.refused(TEXT.replace(SCHEMA, '"schema_\\u0076ersion": 999, ' + SCHEMA, 1))

    def test_late_duplicate_after_valid_data_is_refused(self):
        self.refused(TEXT.rstrip().rstrip("}") + ', "late": 1, "late": 2}')

    def test_unique_keys_still_succeed_with_identical_output(self):
        data = json.loads(TEXT)
        expected = export.validate(data)
        code, out, err = run("validate", TEXT, self.base)
        self.assertEqual((code, json.loads(out), err), (0, expected, ""))
        direct = self.base / "direct"
        summary = export.write_exports(data, direct)
        code, out, err = run("export", TEXT, self.base, self.output)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), summary)
        files = sorted(p.name for p in direct.iterdir())
        self.assertEqual(files, sorted(p.name for p in self.output.iterdir()))
        self.assertTrue(all((direct / n).read_bytes() == (self.output / n).read_bytes() for n in files))

    def test_same_name_in_separate_objects_and_empty_containers_are_valid(self):
        text = TEXT.replace(SCHEMA, '"extra": {"id": 1, "o": {}, "l": []}, "other": {"id": 2}, ' + SCHEMA, 1)
        code, _, err = run("validate", text, self.base)
        self.assertEqual((code, err), (0, ""))

    def test_existing_output_is_untouched(self):
        self.output.mkdir(parents=True)
        (self.output / "keep.txt").write_bytes(b"sentinel")
        code, out, err = run("export", dup_schema(), self.base, self.output)
        self.assertEqual((code, out, err), (1, "", FAILURE))
        self.assertEqual([p.name for p in self.output.iterdir()], ["keep.txt"])
        self.assertEqual((self.output / "keep.txt").read_bytes(), b"sentinel")
        self.assertEqual([p.name for p in self.output.parent.iterdir()], ["out"])

    def test_other_errors_keep_their_existing_diagnostics(self):
        for raw in (b"", b"{", b"\xff\xfe"):
            code, out, err = run("validate", "", self.base, raw=raw)
            self.assertEqual((code, out), (1, ""))
            self.assertTrue(err.startswith("Atlas operation failed: "))
            self.assertNotIn("Duplicate", err)
        code, _, err = run("validate", TEXT.replace(SCHEMA, '"schema_version": 999,', 1), self.base)
        self.assertEqual((code, err), (1, "Atlas operation failed: Unsupported atlas schema\n"))
        deep = TEXT.replace(DEPTH + "139.50182696965734", DEPTH + "999", 1)
        for action, output in (("validate", None), ("export", self.output)):
            code, _, err = run(action, deep, self.base, output)
            self.assertEqual((code, err), (1, "Atlas operation failed: Target exceeds source-depth ceiling\n"))
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
