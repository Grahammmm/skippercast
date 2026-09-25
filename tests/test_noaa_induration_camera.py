"""The NOAA substrate sample must retain source identity and missing data."""
import unittest
import hashlib
import json

from scripts.audit_noaa_induration_camera import (SERVICE, audit_qualified_context,
    parse_identify, representative_records, validate_service, verify_class_codes)


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

    def test_qualified_context_checks_pinned_source_and_keeps_positions_private(self):
        features = [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-123.7, 39.1]},
                     'properties': {'id': 'window-1', 'survey_id': 'H11967',
                                    'fishing_target': False, 'exportable': False}}]
        context = {'scope': 'unpublished-historical-camera-window-research',
                   'fishing_target': False, 'exportable': False, 'features': features}
        raw = json.dumps(context).encode()
        reconcile = {'original_survey_id': 'H11967', 'fishing_target': False,
                     'comparison': [{'nbs_status': 'locally_qualified_90pct',
                                     'original_bag_status': 'original_locally_qualified_90pct',
                                     'historical_camera_windows': 1}]}
        chart = {'survey_id': 'H11967',
                 'candidate_research_context_sha256': hashlib.sha256(raw).hexdigest(),
                 'original_grid_qualified_historical_camera_windows_checked': 1}
        metadata = {'mapName': 'U.S. West Coast Seafloor Induration (v.2017)',
                    'layers': [{'id': 0, 'name': 'Induration (hard, mixed, soft)'},
                               {'id': 2, 'name': 'Data Quality'}]}
        legend = {'layers': [{'layerId': 0, 'legend': [{'label': x} for x in ('hard', 'mixed', 'soft')]},
                             {'layerId': 2, 'legend': [{'label': x} for x in
                              ('1.0', '1.9', '2.4', '3.3', '4.3', '5.7', '6.2', '7.1', '8.6', '10.0')]}]}
        calls = iter([1, 2, 3, 1])
        def fetch(url):
            if url == SERVICE + '?f=pjson': return metadata, 'm' * 64
            if url == SERVICE + '/legend?f=pjson': return legend, 'l' * 64
            code = next(calls)
            return {'results': [{'layerId': 0, 'attributes': {'Raster.Value': str(code)}},
                                {'layerId': 2, 'attributes': {'Raster.Value': '62'}}]}, 'r' * 64
        result = audit_qualified_context(context, raw, reconcile, chart, fetch=fetch)
        self.assertEqual(result['class_counts'], {'hard': 1})
        self.assertEqual(result['quality_counts'], {'6.2': 1})
        self.assertNotIn('coordinates', json.dumps(result))
        chart['candidate_research_context_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'pinned chart receipt'):
            audit_qualified_context(context, raw, reconcile, chart, fetch=fetch)


if __name__ == "__main__":
    unittest.main()
