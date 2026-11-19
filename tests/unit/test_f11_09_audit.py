"""F11-09: schema diagnostics name the failed rule and a safe field path, never the rejected value or a private key.

Protected contract: validate.errors(), the validate CLI and the ContractError raised by validate.check() carry
field-level troubleshooting text but none of the document's own strings. Believable bug: an f-string that puts
`error.message`/`instance` back into a row (jsonschema embeds the rejected value, and the unexpected key names,
in its own messages), which would copy a private note into job logs and exceptions.
"""
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from skippercast import validate

SCHEMA = {
    "$id": "https://example.test/region.schema.json", "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "required": ["id"], "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "note": {"type": "string", "maxLength": 4},
        "count": {"type": "integer"},
        "mode": {"enum": ["a", "b"]},
        "meta": {"type": "string"},
        "labels": {"type": "object", "additionalProperties": {"type": "integer"}},
    },
}
S = "SENTINEL-PRIVATE-9f3a"  # synthetic; stands in for a private field


@unittest.skipUnless(validate.available(), "needs jsonschema")
class RejectedValuesStayOutOfDiagnostics(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / validate.KINDS["region"]).write_text(json.dumps(SCHEMA), encoding="utf-8")

    def bad(self):
        return {"id": "ok", "note": S,                  # scalar too long
                "count": S, "mode": S,                  # scalar of the wrong type / not in enum
                "meta": {"inner": {"deep": S}},         # nested object where a string is required
                f"extra-{S}": 1,                        # unexpected key
                "labels": {f"key-{S}": S}}              # dynamic key with a bad value

    def run_cli(self, document):
        path = self.dir / "doc.json"
        path.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")
        real = validate.errors
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(validate, "errors", lambda kind, doc: real(kind, doc, self.dir)), \
                redirect_stdout(out), redirect_stderr(err):
            status = validate.main(["region", str(path)])
        return status, out.getvalue(), err.getvalue()

    def test_sentinels_absent_from_rows_cli_and_contract_error(self):
        rows = validate.errors("region", self.bad(), self.dir)
        self.assertEqual(len(rows), 6)  # same error count as before the change
        status, out, err = self.run_cli(self.bad())
        with self.assertRaises(validate.ContractError) as caught:
            validate.check("region", self.bad(), directory=self.dir)
        self.assertEqual(status, 1)
        self.assertIn("(6 error(s))", str(caught.exception))
        for text in ("\n".join(rows), out, err, str(caught.exception), repr(caught.exception)):
            self.assertNotIn(S, text)

    def test_field_level_troubleshooting_is_kept(self):
        self.assertEqual(validate.errors("region", self.bad(), self.dir), [
            "(root): additional properties are not allowed (1 unexpected)",
            "count: value is not of type 'integer'",
            "labels/<key>: value is not of type 'integer'",
            "meta: value is not of type 'string'",
            "mode: value is not one of ['a', 'b']",
            "note: value is too long (maximum length 4)",
        ])
        self.assertEqual(validate.errors("region", {"note": "ok"}, self.dir), ["(root): 'id' is a required property"])

    def test_duplicate_key_name_withheld_by_cli(self):
        status, out, err = self.run_cli('{"id": "x", "%s": 1, "%s": 2}' % (S, S))
        self.assertEqual((status, out), (1, ""))
        self.assertIn("Duplicate JSON key", err)
        self.assertNotIn(S, err)

    def test_valid_positive_control(self):
        good = {"id": "ok", "note": "abcd", "count": 3, "mode": "a", "meta": "m", "labels": {"any": 1}}
        self.assertEqual(validate.errors("region", good, self.dir), [])
        self.assertTrue(validate.check("region", good, directory=self.dir))
        self.assertEqual(self.run_cli(good)[:2], (0, f"{self.dir / 'doc.json'}: valid region\n"))


if __name__ == "__main__":
    unittest.main()
