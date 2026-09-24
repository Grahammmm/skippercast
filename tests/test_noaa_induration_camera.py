"""The NOAA substrate sample must retain source identity and missing data."""
import unittest

from scripts.audit_noaa_induration_camera import parse_identify, representative_records, validate_service, verify_class_codes


class IndurationCameraTests(unittest.TestCase):
    def test_identify_requires_both_known_layers(self):
        response = {"results": [
            {"layerId": 0, "attributes": {"Raster.Value": "1"}},
            {"layerId": 2, "attributes": {"Raster.Value": "62"}},
        ]}
        self.assertEqual(parse_identify(response), {"induration_code": 1, "induration": "hard",
                                                   "data_quality_code": 62, "data_quality_of_10": 6.2})
        self.assertIsNone(parse_identify({"results": []}))
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            parse_identify({"results": response["results"][:1]})
        response["results"][0]["attributes"]["Raster.Value"] = "99"
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            parse_identify(response)

    def test_representative_record_deduplicates_bag_variants(self):
        base = {"scope": "statewide-original-camera-regular-bag-discovery-review",
                "fishing_target": False, "exportable": False,
                "pair_reviews": [{"cruise": "f208nc", "camera_archive_sha256": "a" * 64,
                                  "transects": [{"date": "2008-09-07", "line": "115",
                                                 "window_count": 2, "camera_record_indices": [3, 4]}]},
                                 {"cruise": "f208nc", "camera_archive_sha256": "a" * 64,
                                  "transects": [{"date": "2008-09-07", "line": "115",
                                                 "window_count": 2, "camera_record_indices": [4, 5]}]}]}
        reps, archives = representative_records(base)
        self.assertEqual(reps, [("f208nc", "2008-09-07", "115", 4)])
        self.assertEqual(archives, {"f208nc": "a" * 64})

    def test_service_identity_and_legend_are_pinned(self):
        metadata = {"mapName": "U.S. West Coast Seafloor Induration (v.2017)",
                    "layers": [{"id": 0, "name": "Induration (hard, mixed, soft)"},
                               {"id": 2, "name": "Data Quality"}]}
        legend = {"layers": [
            {"layerId": 0, "legend": [{"label": x} for x in ["hard", "mixed", "soft"]]},
            {"layerId": 2, "legend": [{"label": x} for x in
                                      ["1.0", "1.9", "2.4", "3.3", "4.3", "5.7", "6.2", "7.1", "8.6", "10.0"]]},
        ]}
        validate_service(metadata, legend)
        metadata["mapName"] = "Different source"
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_service(metadata, legend)

    def test_class_code_probes_reject_changed_raster_values(self):
        calls = iter([1, 2, 3])
        def fetch(_url):
            code = next(calls)
            return {"results": [{"layerId": 0, "attributes": {"Raster.Value": str(code)}},
                                {"layerId": 2, "attributes": {"Raster.Value": "62"}}]}, "a" * 64
        self.assertEqual(len(verify_class_codes(fetch)), 3)
        with self.assertRaisesRegex(ValueError, "no longer match"):
            verify_class_codes(lambda _url: ({"results": [
                {"layerId": 0, "attributes": {"Raster.Value": "1"}},
                {"layerId": 2, "attributes": {"Raster.Value": "62"}}]}, "a" * 64))


if __name__ == "__main__":
    unittest.main()
