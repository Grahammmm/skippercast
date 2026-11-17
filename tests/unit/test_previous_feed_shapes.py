import copy
import json
import unittest

from skippercast.pipeline.settings import previous_for_region

LEGACY = {"schema_version": 1, "sources": {}}


class PreviousFeedShapeTests(unittest.TestCase):
    def test_nonobject_previous_is_refused(self):
        for value in (False, True, 0, 1, "", "x", [], [1], ["a"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                previous_for_region(json.loads(json.dumps(value)), "morro-bay")

    def test_schema_version_is_exact_integer_one(self):
        for version in (True, False, 1.0, "1", None, 0, 2):
            feed = {"schema_version": version, "sources": {}}
            with self.subTest(version=version), self.assertRaises(ValueError):
                previous_for_region(feed, "morro-bay")
        with self.assertRaises(ValueError):
            previous_for_region({"sources": {}}, "morro-bay")
        feed = {"schema_version": 1, "sources": {}}
        self.assertIs(previous_for_region(feed, "morro-bay"), feed)

    def test_bootstrap_sentinels_are_preserved(self):
        self.assertEqual(previous_for_region(None, "morro-bay"), {})
        self.assertEqual(previous_for_region({}, "cambria-san-simeon"), {})

    def test_legacy_and_explicit_region_controls_keep_identity(self):
        legacy = copy.deepcopy(LEGACY)
        self.assertIs(previous_for_region(legacy, "morro-bay"), legacy)
        explicit = {**LEGACY, "region_id": "cambria-san-simeon"}
        before = copy.deepcopy(explicit)
        self.assertIs(previous_for_region(explicit, "cambria-san-simeon"), explicit)
        self.assertEqual(explicit, before)
        for feed, region in ((legacy, "cambria-san-simeon"), (explicit, "morro-bay")):
            with self.assertRaises(ValueError):
                previous_for_region(feed, region)
        self.assertEqual(legacy, LEGACY)
        self.assertEqual(explicit, before)


if __name__ == "__main__":
    unittest.main()
