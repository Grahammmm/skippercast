"""Regression gates for the held Point St. George original-survey lead."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_pinned_original_vr_source import audit as audit_pinned
from scripts.audit_vr_camera_hazard_gate import audit as audit_hazards
from scripts.compile_original_vr_camera_lead import compile_review


ROOT = Path(__file__).resolve().parents[1]


def packet(name):
    return json.loads((ROOT / name).read_text())


class OriginalLeadGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        public = packet('dist/data/noaa-h11983-native-source-review.json')
        digest = public['original_bag_sha256']
        survey = public['survey_id']
        common = {'survey_id': survey, 'bag_sha256': digest, 'fishing_target': False}
        cls.parts = [
            {'health': {'status': 'ok'}, 'files': [{
                'survey_id': survey, 'file_sha256': digest, 'status': 'ok',
                'metadata_status': 'mllw-product-uncertainty-reviewed-by-adapter',
                'vertical_datum': 'MLLW', 'uncertainty_type': 'productUncert',
                'url': public['original_bag_url'], 'source_report_url': public['original_report_url'],
                'refinement_resolution_range_m': public['native_resolution_m_range'],
                'refinement_grids_at_most_4m': public['native_fine_grids']}]},
            {'status': 'ok', 'files': [{'status': 'ok', 'survey_id': survey,
                'bag_sha256': digest, 'counts': {'measured_native_cells': public['measured_native_cell_associations'],
                'depth_uncertainty_eligible_cells': public['depth_uncertainty_eligible_cell_associations']}}]},
            {**common, 'counts': public['regional_mpa_grid_screen']},
            {**common, 'counts': public['historical_camera_window_screen'],
                'matched_bottom_classes': {'native_grid_interior': public['historical_camera_interior_bottom_classes']}},
            {'original_survey_id': survey, 'original_bag_sha256': digest,
                'tile': public['selected_nbs_tile'], 'fishing_target': False,
                'counts': {'rocky_camera_windows_in_tile_envelope': public['selected_nbs_rocky_camera_windows']},
                'comparison': [{'nbs_status': 'locally_qualified_90pct',
                    'original_bag_status': 'original_locally_qualified_90pct',
                    'historical_camera_windows': 3}]},
            {'survey_id': survey, 'original_bag_sha256': digest, 'fishing_target': False,
                'present_chart_and_route_cleared': False,
                'original_qualified_historical_camera_windows': 3,
                'historical_report_dangers': public['report_danger_count'],
                'enc_query_layers': public['enc_danger_layers_queried'],
                'enc_features': public['enc_danger_features_in_scope'],
                'minimum_historical_danger_distance_m_range': public['minimum_historical_danger_distance_m_range'],
                'minimum_charted_danger_distance_m_range': public['minimum_charted_danger_distance_m_range'],
                'minimum_mpa_distance_m_range': public['minimum_mpa_distance_m_range'],
                'cdfw_mpa_retrieved_at': public['cdfw_mpa_retrieved_at']}]

    def test_coordinate_free_held_receipt(self):
        review = compile_review(*self.parts)
        self.assertEqual(review['nbs_and_original_bag_qualified_rocky_windows'], 3)
        self.assertFalse(review['fishing_target'])
        self.assertFalse(review['exportable'])
        self.assertFalse(review['present_chart_and_route_cleared'])
        self.assertNotIn('coordinates', json.dumps(review))

    def test_inconsistent_hazard_count_fails(self):
        altered = copy.deepcopy(self.parts)
        altered[-1]['original_qualified_historical_camera_windows'] = 4
        with self.assertRaisesRegex(ValueError, 'counts disagree'):
            compile_review(*altered)

    def test_incomplete_mpa_accounting_fails(self):
        altered = copy.deepcopy(self.parts)
        altered[2]['counts']['outside_mpa'] -= 1
        with self.assertRaisesRegex(ValueError, 'MPA accounting'):
            compile_review(*altered)

    def test_pinned_digest_fails_before_grid_inspection(self):
        spec = copy.deepcopy(packet('catalog/original-vr-camera-review-sources.json')['sources'][0])
        spec['bag_bytes'] = 3
        spec['bag_sha256'] = '0' * 64
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            import hashlib
            path = cache / (spec['survey_id'] + '-' + hashlib.sha256(spec['bag_url'].encode()).hexdigest()[:16] + '.bag')
            path.write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'digest changed'):
                audit_pinned(spec, cache)

    def test_report_digest_or_mpa_snapshot_change_fails(self):
        context_path = ROOT / 'var/review/h11983-qualified-camera-context.geojson'
        if not context_path.exists():
            self.skipTest('Private coordinate fixture absent in CI')
        context_raw = context_path.read_bytes()
        args = [json.loads(context_raw), context_raw,
                packet('var/noaa-h11983-nbs-original-camera-reconciliation.json'),
                packet('var/review/enc-hazards-h11983-point-st-george.geojson'),
                packet('catalog/noaa-survey-hazards.json'),
                packet('var/review-20260925/coastal/latest.json'),
                (ROOT / 'var/review/H11983.pdf').read_bytes()]
        bad_report = list(args)
        bad_report[-1] = b'wrong original report'
        with self.assertRaisesRegex(ValueError, 'report is missing or changed'):
            audit_hazards(*bad_report)
        bad_mpa = copy.deepcopy(args)
        bad_mpa[-2]['sources']['mpas']['data_retrieved_at'] = '2000-01-01T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'different MPA snapshots'):
            audit_hazards(*bad_mpa)


if __name__ == '__main__':
    unittest.main()
