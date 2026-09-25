"""Deep-water NOAA survey envelopes cannot fill a nearshore fishing-depth gap."""
import json
from pathlib import Path
import unittest

from scripts.screen_noaa_vr_source_depth import acquire, stable


ROOT = Path(__file__).resolve().parents[1]


class NativeVrSourceDepthTests(unittest.TestCase):
    def test_original_depth_screen_excludes_both_broad_catalog_matches(self):
        report = json.loads((ROOT / 'dist/data/noaa-central-deepwater-native-depth-screen.json').read_text())
        self.assertEqual(report['scope'], 'noaa-original-central-coast-vr-depth-band-screen')
        self.assertEqual(report['depth_band_ft_mllw'], [25, 200])
        self.assertEqual({row['survey_id'] for row in report['sources']}, {'H13089', 'H13151'})
        for row in report['sources']:
            self.assertGreater(row['measured_depth_cells'], 100_000)
            self.assertLess(row['shallowest_elevation_m_mllw'], -400)
            self.assertGreater(row['minimum_native_resolution_m'], 30)
            self.assertEqual(row['raw_cells_in_25_to_200_ft_mllw_band'], 0)
            self.assertFalse(row['nearshore_depth_lead'])
            self.assertFalse(row['fishing_target'])
            self.assertFalse(row['exportable'])
        self.assertEqual(stable(report), stable({**report, 'reviewed_at': 'later'}))

    def test_unreviewed_source_url_is_rejected_before_fetch(self):
        manifest = json.loads((ROOT / 'catalog/noaa-central-deepwater-source-screen.json').read_text())
        changed = {**manifest['sources'][0], 'url': 'https://example.com/other.bag'}
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            acquire(changed, ROOT / 'var/noaa-native-cache', False)


if __name__ == '__main__':
    unittest.main()
