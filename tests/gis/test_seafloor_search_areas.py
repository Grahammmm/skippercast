"""Ungraded measured search outlines must not become ranked/exported spots."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import timedelta

from skippercast.platform.contracts import REPO, atomic_json, read_json
from skippercast.seafloor import publish
from skippercast.seafloor.search_areas import assessment, published_contract
from skippercast.seafloor.screen import screen_candidates
from tests.gis.test_seafloor_screen import candidate, state, geo
from tests._support import NOW


def rough_patch():
    c = candidate()
    c['properties'].update(terrain='unknown', fit={'lingcod': 'unknown', 'rockfish-reef': 'unknown'},
        source_ids=['native'], rule_version=read_json(REPO/'catalog/habitat-rules.json')['rule_version'],
        metric_support_fraction=.65, hold_reasons=['legal-screen-pending', 'metric-support-incomplete'])
    return c


class SearchAreaTests(unittest.TestCase):
    def test_missing_grade_can_display_without_rank_area_credit_or_geometry_change(self):
        c = rough_patch()
        passed, held, summary = screen_candidates({'features': [c]}, state())
        self.assertFalse(held['features'])
        f = passed['features'][0]; p = f['properties']
        self.assertEqual(f['geometry'], c['geometry'])
        self.assertEqual(c['properties']['hold_reasons'], ['legal-screen-pending', 'metric-support-incomplete'])
        self.assertTrue(published_contract(p))
        self.assertEqual((p['tier'], p['terrain'], p['fit']['lingcod'], p['exportable']), (1, 'unknown', 'unknown', False))
        self.assertEqual((summary['habitat_count'], summary['tier2_km2']), (0, 0))
        self.assertEqual(summary['search_area_count'], 1)
        self.assertAlmostEqual(summary['search_area_km2'], .0025, places=8)
        flat = publish.flat_properties(p)
        self.assertEqual(flat['terrain_grade'], 'unknown')
        self.assertEqual(flat['fit_lingcod'], 'unknown')
        again, _, _ = screen_candidates(passed, state())
        self.assertTrue(published_contract(again['features'][0]['properties']))

    def test_restrictions_quality_holds_and_bad_depth_still_hold(self):
        for hold in ('derived-multibeam-source-review', 'source-habitat-quality-review', 'habitat-threshold-quality-review'):
            c = rough_patch(); c['properties']['hold_reasons'].append(hold)
            passed, held, _ = screen_candidates({'features': [c]}, state())
            self.assertFalse(passed['features'])
            self.assertIn(hold, held['features'][0]['properties']['hold_reasons'])
        for s in (state(geo(49, 0)), {'status': 'held', 'reasons': ['screen-stale'], 'layers': []}):
            passed, held, _ = screen_candidates({'features': [rough_patch()]}, s)
            self.assertFalse(passed['features']); self.assertTrue(held['features'])
        c = rough_patch(); c['properties']['depth_max_ft'] = 301
        self.assertIsNone(assessment(c['properties']))
        self.assertFalse(screen_candidates({'features': [c]}, state())[0]['features'])

    def test_no_invented_targets_ranks_or_search_profile_for_bad_inputs(self):
        for change in ({'fit': {'tuna': 'unknown'}}, {'fit': {'lingcod': 3}},
                       {'source_ids': []}, {'metric_support_fraction': .8},
                       {'metric_support_fraction': float('nan')}, {'rule_version': 'stale'}):
            c = rough_patch(); c['properties'].update(change)
            self.assertIsNone(assessment(c['properties']))
        c = rough_patch(); c['properties'].update(depth_min_ft=40, depth_max_ft=50)
        self.assertEqual(assessment(c['properties'])['target_species'], ['lingcod'])
        c = rough_patch(); c['properties']['hold_reasons'] = ['legal-screen-pending']
        self.assertFalse(screen_candidates({'features': [c]}, state())[0]['features'])

    def test_search_polygon_is_in_archive_but_not_precise_waypoint_export(self):
        passed, _, _ = screen_candidates({'features': [rough_patch()]}, state())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            atomic_json(root/'catalog/surveys.json', {'surveys': [{'id': 'native', 'url': 'https://example.test/source'}]})
            atomic_json(root/'dist/data/seafloor-ledger.json', {'reference': {}, 'reaches': []})
            layers = {'cells': [], 'habitat': [{'type': 'Feature', 'geometry': passed['features'][0]['geometry'],
                'properties': publish.flat_properties(passed['features'][0]['properties'])}]}
            def archive(tool, values, path, **kwargs):
                self.assertEqual(len(values['habitat']), 1)
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'PMTiles\x03fixture')
            with patch.object(publish, 'region_layers', return_value=(layers, {}, NOW+timedelta(days=1))), \
                    patch('scripts.build_map_tiles.build_vector_archive', side_effect=archive):
                folder, manifest = publish.build('morro-bay', root=root, tool='fixture', now=NOW)
            exported = json.loads(gzip.decompress((folder/manifest['export_file']).read_bytes()))
            self.assertEqual(exported['features'], [])
            self.assertEqual(manifest['layers']['habitat'], 1)


if __name__ == '__main__':
    unittest.main()
