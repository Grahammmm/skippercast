"""RF0420-5: bag_metadata and fresh_closures fail closed as ValueError."""
from datetime import datetime, timezone
import hashlib
import unittest

from skippercast.platform.bottom_targets import bag_metadata, fresh_closures


def metadata(survey="H13323"):
    return f'''<root><CharacterString>PROJCS["NAD83 / UTM zone 11N"]</CharacterString>
    <CharacterString>VERT_CS["MLLW",VERT_DATUM["MLLW",2000]]</CharacterString><CharacterString>{survey}</CharacterString>
    <BAG_VertUncertCode>productUncert</BAG_VertUncertCode>
    <beginPosition>2019-10-04T00:00:00</beginPosition><endPosition>2019-10-21T00:00:00</endPosition></root>'''


NOW = datetime(2026, 9, 22, 18, tzinfo=timezone.utc)
POLYGON = {"geometry": {"type": "Polygon", "coordinates": [[[-119, 33], [-119, 34], [-118, 34], [-118, 33], [-119, 33]]]}}


def closures(features):
    return {"region_id": "southern-california", "checked_at": NOW.isoformat(), "features": features}


class BagMetadataFailsClosed(unittest.TestCase):
    def assert_value_error(self, message, call):
        with self.assertRaises(ValueError) as caught:
            call()
        self.assertIs(type(caught.exception), ValueError)
        self.assertEqual(str(caught.exception), message)

    def test_malformed_xml_is_unsupported_metadata(self):
        for xml in ["<root><unclosed>", "", "not xml"]:
            for strict in (True, False):
                with self.subTest(xml=xml, strict=strict):
                    self.assert_value_error("Unsupported BAG metadata",
                                            lambda: bag_metadata(xml, "H13323", strict=strict))

    def test_empty_blank_or_missing_survey_id_is_required(self):
        for survey_id in ["", "   ", "\t\n", None]:
            for strict in (True, False):
                with self.subTest(survey_id=survey_id, strict=strict):
                    self.assert_value_error("A survey id is required",
                                            lambda: bag_metadata(metadata(), survey_id, strict=strict))

    def test_survey_id_checked_before_xml_is_parsed(self):
        self.assert_value_error("A survey id is required", lambda: bag_metadata("<root><unclosed>", ""))

    def test_wrong_survey_id_still_refused(self):
        self.assert_value_error("Survey identity does not match the reviewed source",
                                lambda: bag_metadata(metadata(), "H13093"))

    def test_valid_metadata_unchanged(self):
        xml = metadata()
        self.assertEqual(bag_metadata(xml, "H13323"), {
            "horizontal_wkt": 'PROJCS["NAD83 / UTM zone 11N"]',
            "vertical_wkt": 'VERT_CS["MLLW",VERT_DATUM["MLLW",2000]]',
            "vertical_datum": "MLLW", "uncertainty_type": "productUncert",
            "survey_start": "2019-10-04T00:00:00", "survey_end": "2019-10-21T00:00:00",
            "metadata_sha256": hashlib.sha256(xml.encode()).hexdigest()})
        self.assertEqual(bag_metadata(xml, "H13323", strict=False)["vertical_datum"], "MLLW")


class FreshClosuresFailsClosed(unittest.TestCase):
    def assert_value_error(self, message, features):
        with self.assertRaises(ValueError) as caught:
            fresh_closures(closures(features), minimum_features=8, now=NOW)
        self.assertIs(type(caught.exception), ValueError)
        self.assertEqual(str(caught.exception), message)

    def test_non_list_features_refused(self):
        for features in [{f"k{i}": POLYGON for i in range(8)}, "abcdefgh", tuple([POLYGON] * 8)]:
            with self.subTest(features=type(features).__name__):
                self.assert_value_error("Incomplete or wrong-region closure geometry", features)

    def test_non_object_feature_or_geometry_refused(self):
        for bad in ["feature", None, 7, ["geometry"], {"geometry": "x"}, {"geometry": None}, {"geometry": []}]:
            with self.subTest(bad=bad):
                self.assert_value_error("Closure geometry must contain full polygons", [POLYGON] * 7 + [bad])

    def test_list_of_strings_refused(self):
        self.assert_value_error("Closure geometry must contain full polygons", ["x"] * 8)

    def test_valid_fresh_closures_accepted(self):
        self.assertIsNone(fresh_closures(closures([POLYGON] * 8), minimum_features=8, now=NOW))


if __name__ == "__main__":
    unittest.main()
