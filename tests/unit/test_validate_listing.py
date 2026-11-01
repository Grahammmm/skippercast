"""skippercast.validate lists errors in numeric array order and the CLI says how many it did not print."""
from collections import deque
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest import mock

from skippercast import validate

SCHEMA = {"$id": "https://example.test/region.schema.json", "$schema": "https://json-schema.org/draft/2020-12/schema",
          "type": "object", "required": ["id"],
          "properties": {"sources": {"type": "array", "items": {"type": "string", "minLength": 5, "pattern": "^z"}}}}


@unittest.skipUnless(validate.available(), "needs jsonschema")
class ValidateListingTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / validate.KINDS["region"]).write_text(json.dumps(SCHEMA), encoding="utf-8")

    def errors(self, document):
        return validate.errors("region", document, self.dir)

    def test_array_positions_sort_as_numbers(self):
        sources: list = ["zzzzz"] * 12
        sources[2] = sources[10] = sources[11] = 7
        self.assertEqual([row.split(":")[0] for row in self.errors({"id": 1, "sources": sources})],
                         ["sources/2", "sources/10", "sources/11"])

    def test_ints_before_keys_at_one_depth_then_next_key(self):
        found = [SimpleNamespace(absolute_path=deque(path), message="bad") for path in (["b"], ["a", "x"], ["a", 0])]
        with mock.patch.object(validate, "validator", return_value=SimpleNamespace(iter_errors=lambda doc: found)):
            self.assertEqual(validate.errors("region", {}), ["a/0: bad", "a/x: bad", "b: bad"])

    def test_two_errors_at_one_location_ordered_by_message(self):
        document = {"id": 1, "sources": ["zzzzz", "zzzzz", "ab"]}
        first = self.errors(document)
        self.assertEqual(first, ["sources/2: 'ab' does not match '^z'", "sources/2: 'ab' is too short"])
        self.assertEqual(self.errors(document), first)

    def test_root_error_listed_first(self):
        rows = self.errors({"sources": ["zzzzz", 3]})
        self.assertEqual(rows[0], "(root): 'id' is a required property")
        self.assertEqual(rows[1:], ["sources/1: 3 is not of type 'string'"])

    def run_cli(self, *documents):
        paths = []
        for number, document in enumerate(documents):
            if isinstance(document, Path):  # used as given, e.g. a file that does not exist
                paths.append(document)
                continue
            path = self.dir / f"doc{number}.json"
            path.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")
            paths.append(path)
        real = validate.errors
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(validate, "errors", lambda kind, doc: real(kind, doc, self.dir)), \
                redirect_stdout(out), redirect_stderr(err):
            status = validate.main(["region", *map(str, paths)])
        return status, paths, out.getvalue().splitlines(), err.getvalue().splitlines()

    def test_cli_more_line_only_beyond_fifty(self):
        for count, more in ((50, None), (51, "  ... 1 more"), (120, "  ... 70 more")):
            with self.subTest(count=count):
                status, paths, out, err = self.run_cli({"id": 1, "sources": [0] * count})
                self.assertEqual(status, 1)
                self.assertEqual(out, [])
                self.assertEqual(err[0], f"{paths[0]}: {count} schema error(s)")
                self.assertEqual(len([line for line in err if line.startswith("  sources/")]), 50)
                self.assertEqual(err[1:51], [f"  sources/{n}: 0 is not of type 'string'" for n in range(50)])
                self.assertEqual(err[51:], [more] if more else [])

    def test_cli_valid_file(self):
        status, paths, out, err = self.run_cli({"id": 1, "sources": ["zzzzz"]})
        self.assertEqual((status, out, err), (0, [f"{paths[0]}: valid region"], []))

    def test_cli_bad_json_then_valid_file_still_reported(self):
        status, paths, out, err = self.run_cli("{not json", {"id": 1})
        self.assertEqual(status, 1)
        self.assertEqual(len(err), 1)
        self.assertTrue(err[0].startswith(f"{paths[0]}: ") and "Error" in err[0], err[0])
        self.assertEqual(out, [f"{paths[1]}: valid region"])

    def test_cli_missing_file_then_valid_file_still_reported(self):
        missing = self.dir / "absent.json"
        status, paths, out, err = self.run_cli(missing, {"id": 1})
        self.assertEqual(status, 1)
        self.assertEqual(len(err), 1)
        self.assertTrue(err[0].startswith(f"{missing}: FileNotFoundError: "), err[0])
        self.assertEqual(out, [f"{paths[1]}: valid region"])


if __name__ == "__main__":
    unittest.main()
