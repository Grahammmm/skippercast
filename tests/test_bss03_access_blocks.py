"""Block 03 partial closure screen remains private and fail-closed."""
import json
from pathlib import Path
import unittest

from research.scripts.audit_bss03_access_blocks import screen


ROOT = Path(__file__).resolve().parents[1]


class Bss03AccessTest(unittest.TestCase):
    def test_published_receipt_contains_no_geometry_or_fishing_mark(self):
        result = json.loads((ROOT / 'dist/data/bss03-camera-access-triage.json').read_text())
        self.assertEqual(result['totals']['blocks'], 3)
        self.assertEqual(result['totals']['rock_boulder_cobble_windows'], 11)
        self.assertEqual(result['noaa_enc_query_layers'], 18)
        self.assertEqual(result['totals']['all_three_clear_margin_blocks'], 3)
        self.assertEqual(result['qualified_waypoints'], 0)
        self.assertFalse(result['fishing_target'])
        self.assertFalse(result['exportable'])
        self.assertNotIn('features', result)
        self.assertNotIn('coordinates', json.dumps(result))

    def test_missing_official_source_fails_closed(self):
        mpas = {'status': 'stale', 'features': []}
        federal = {'status': 'ok'}
        enc = {'status': 'charted-danger-screen-only'}
        with self.assertRaisesRegex(ValueError, 'incomplete or changed'):
            screen({}, mpas, federal, enc)

    def test_fresh_cached_originals_reproduce_private_screen(self):
        paths = [ROOT / 'var/review/csumb-bss-cache/BSS_Block03_additional_products.tar.gz',
                 ROOT / 'var/usgs-video-cache/c0212sc_video_observations.zip',
                 ROOT / 'var/review/bss03-cdfw-mpas.geojson',
                 ROOT / 'var/review/bss03-federal-areas.json',
                 ROOT / 'var/review/enc-hazards-bss03-original-camera.geojson']
        if not all(path.exists() for path in paths):
            self.skipTest('Original archives or fresh official snapshots unavailable locally')
        from research.scripts.audit_bss03_access_blocks import source_blocks, stable
        bss = next(source for source in json.loads((ROOT / 'catalog/csumb-bss-native-sources.json').read_text())['sources']
                   if source['survey_id'] == 'BSS_Block03')
        video = json.loads((ROOT / 'catalog/usgs-video-cruises.json').read_text())
        blocks = source_blocks(bss, video, ROOT / 'var/review/csumb-bss-cache', ROOT / 'var/usgs-video-cache')
        official = [json.loads(path.read_text()) for path in paths[2:]]
        result, private = screen(blocks, *official)
        expected = json.loads((ROOT / 'dist/data/bss03-camera-access-triage.json').read_text())
        for key in ('original_source_sha256', 'raw_snapshot_sha256'):
            expected.pop(key, None)
        self.assertEqual(stable(result), stable(expected))
        self.assertEqual(len(private['features']), 3)
        self.assertTrue(all(not feature['properties']['fishing_target'] for feature in private['features']))


if __name__ == '__main__':
    unittest.main()
