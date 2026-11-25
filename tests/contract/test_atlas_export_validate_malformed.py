"""atlas export validate refuses a structurally malformed atlas document by name.

Contract: `validate` raises a named ValueError (never a bare KeyError/TypeError) for a
document that is not an object, lacks an integer schema_version, or whose sources,
targets, areas or drifts are not lists of objects with a string id, and it does so
before any row is indexed. The committed atlas and the existing named refusals are
unchanged.
"""

from collections import Counter
import copy
import json
import unittest

from skippercast.atlas.export import validate
from tests._support import ROOT

COMMITTED = ROOT / "dist/data/atlas.json"
ROW_KEYS = ("sources", "targets", "areas", "drifts")


def healthy():
    return json.loads(COMMITTED.read_text(encoding="utf-8"))


class MalformedAtlasDocument(unittest.TestCase):
    def refuses(self, data, message):
        with self.assertRaises(ValueError) as caught:
            validate(data)
        self.assertEqual(str(caught.exception), message)

    def test_committed_atlas_validates_with_unchanged_summary(self):
        # Bug caught: the new type check rejects the real atlas because a row field
        # (id, schema_version) has a different type than assumed, or alters the summary.
        data = healthy()
        targets = data["targets"]
        self.assertEqual(validate(data), {
            "targets": len(targets), "areas": len(data["areas"]), "drifts": len(data["drifts"]),
            "grades": dict(sorted(Counter(t["habitat_grade"] for t in targets).items())),
            "validation_scope": "Structure and recorded survey evidence only; no current "
                                "legal, depth, or navigation clearance."})
        self.assertGreater(len(targets), 0)
        for key in ROW_KEYS:
            self.assertTrue(all(isinstance(r["id"], str) for r in data[key]), key)

    def test_document_that_is_not_an_object(self):
        # Bug caught: a list/None/string atlas raises TypeError from data["schema_version"].
        for bad in ([], [healthy()], None, "atlas", 1):
            with self.subTest(bad=type(bad).__name__):
                self.refuses(bad, "Atlas document must be a JSON object")

    def test_missing_or_non_integer_schema_version(self):
        # Bug caught: {} raises bare KeyError; a string/float/bool version slips through
        # the equality check (True == 1, 1.0 == 1) instead of being named.
        data = healthy()
        del data["schema_version"]
        self.refuses(data, "Atlas schema_version must be an integer")
        self.refuses({}, "Atlas schema_version must be an integer")
        for bad in ("1", 1.0, True, None, [1]):
            with self.subTest(bad=repr(bad)):
                self.refuses({**healthy(), "schema_version": bad},
                             "Atlas schema_version must be an integer")

    def test_missing_row_collection(self):
        # Bug caught: a document without sources/targets/areas/drifts raises bare KeyError.
        for key in ROW_KEYS:
            with self.subTest(key=key):
                data = healthy()
                del data[key]
                self.refuses(data, f"Atlas {key} must be a list")

    def test_row_collection_that_is_not_a_list(self):
        # Bug caught: targets: "x" or a dict indexes characters/keys and raises TypeError.
        for key in ROW_KEYS:
            for bad in ("x", {"a": {"id": "a"}}, None, 3):
                with self.subTest(key=key, bad=type(bad).__name__):
                    self.refuses({**healthy(), key: bad}, f"Atlas {key} must be a list")

    def test_rows_that_are_not_objects(self):
        # Bug caught: a string or null row raises "string indices must be integers".
        for key in ROW_KEYS:
            for bad in ("row", None, ["id"], 7):
                with self.subTest(key=key, bad=type(bad).__name__):
                    data = healthy()
                    data[key] = [*data[key][:1], bad, *data[key][1:]]
                    self.refuses(data, f"Atlas {key} must be a list of objects")

    def test_rows_without_a_string_id(self):
        # Bug caught: a row lacking id raises KeyError; a list/dict id raises an unhashable
        # TypeError; an int id is silently accepted as a different key type.
        for key in ROW_KEYS:
            for bad in ("missing", 5, None, ["a"]):
                with self.subTest(key=key, bad=repr(bad)):
                    data = healthy()
                    row = copy.deepcopy(data[key][0])
                    if bad == "missing":
                        del row["id"]
                    else:
                        row["id"] = bad
                    data[key][0] = row
                    self.refuses(data, f"Atlas {key} rows must each have a string id")

    def test_existing_named_refusals_keep_their_messages(self):
        # Bug caught: the shape gate swallows or reorders the two older named refusals
        # (the unsupported-schema check must still win for an integer version).
        self.refuses({**healthy(), "schema_version": 2}, "Unsupported atlas schema")
        self.refuses({**healthy(), "targets": []}, "An atlas must contain targets")
        data = healthy()
        data["sources"].append(copy.deepcopy(data["sources"][0]))
        self.refuses(data, "Duplicate source IDs")


if __name__ == "__main__":
    unittest.main()
