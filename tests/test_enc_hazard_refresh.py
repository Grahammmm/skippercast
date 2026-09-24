"""Fail-closed checks for bounded NOAA ENC danger snapshots."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.refresh_enc_hazards import LAYERS, main, query_layer, refresh
from scripts.audit_enc_context_overlap import audit


class EncHazardRefreshTests(unittest.TestCase):
    def test_research_scope_cannot_write_to_a_public_or_default_path(self):
        for arguments in (
            ['refresh_enc_hazards.py', '--scope', 'cape-mendocino-hard-context'],
            ['refresh_enc_hazards.py', '--scope', 'cape-mendocino-hard-context',
             '--output', 'var/published/enc-hazards-cape-mendocino.geojson'],
        ):
            with self.subTest(arguments=arguments), patch('sys.argv', arguments):
                with self.assertRaisesRegex(ValueError, 'Research-only ENC'):
                    main()

    def test_context_audit_holds_charted_danger_and_preserves_historical_hold(self):
        enc = {'scope_id': 'point-reyes-tomales', 'bounds': [-123.18, 38.02, -122.92, 38.26],
               'checked_at': '2026-09-24T00:00:00Z', 'source_url': 'https://encdirect.noaa.gov/arcgis/rest/services/encdirect',
               'query_receipts': [{'count': 1}] + [{'count': 0}] * 17,
               'features': [{'geometry': {'type': 'Point', 'coordinates': [-122.98, 38.17]}}]}
        context = {'features': [{'properties': {'id': 'outline-1', 'survey_id': 'H11735'},
                    'geometry': {'type': 'Polygon', 'coordinates': [[[-122.981, 38.169],
                        [-122.979, 38.169], [-122.979, 38.171], [-122.981, 38.171],
                        [-122.981, 38.169]]]}}]}
        historical = {'surveys': [{'survey_id': 'H11735', 'hazards': [
            {'id': 'old-dton', 'longitude': -122.98, 'latitude': 38.17}]}]}
        result = audit(enc, context, historical)
        self.assertEqual(result['outlines_near_charted_dangers'][0]['context_id'], 'outline-1')
        self.assertFalse(result['historical_report_dangers'][0]['reconciled_with_current_chart'])
        enc['query_receipts'][0]['count'] = 0
        with self.assertRaisesRegex(ValueError, 'count does not match'):
            audit(enc, context, historical)

    def test_count_disagreement_cannot_be_published_as_empty_hazard_water(self):
        responses = iter([({"count": 1}, "a" * 64),
                          ({"type": "FeatureCollection", "features": []}, "b" * 64)])
        with patch("scripts.refresh_enc_hazards.fetch_json", side_effect=lambda _: next(responses)):
            with self.assertRaisesRegex(ValueError, "Incomplete or changed ENC"):
                query_layer("enc_approach", "Underwater_Awash_Rock_point", 37,
                            [-119.12, 33.33, -118.98, 33.54])

    def test_missing_scale_layer_aborts_the_entire_refresh(self):
        metadata = {"layers": [{"name": "Harbor." + name, "id": i}
                               for i, name in enumerate(LAYERS) if name != "Wreck_area"]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hazards.geojson"
            with patch("scripts.refresh_enc_hazards.fetch_json", return_value=(metadata, "a" * 64)):
                with self.assertRaisesRegex(ValueError, "Required NOAA ENC layer missing"):
                    refresh({"id": "test", "region_id": "southern-california",
                             "bounds": [-119.12, 33.33, -118.98, 33.54]}, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
