"""Original Big Sur grid receipt remains a research hold."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_csumb_bss_native import audit


ROOT = Path(__file__).resolve().parents[1]


class BigSurSouthNativeReviewTest(unittest.TestCase):
    def test_measured_grid_receipt_cannot_become_a_target(self):
        report = json.loads((ROOT / 'dist/data/csumb-bss-native-source-review.json').read_text())
        self.assertEqual(report['publication_status'], 'source-evidence-only')
        by_id = {source['source_id']: source for source in report['sources']}
        self.assertEqual(set(by_id), {'csumb-bss-block01', 'csumb-bss-block02', 'csumb-bss-block03', 'csumb-bss-block12', 'csumb-bss-block13'})
        shallow = by_id['csumb-bss-block01']
        self.assertEqual(shallow['bathymetry']['resolution_m'], [2.0, 2.0])
        self.assertEqual(shallow['native_depth_screen']['cells_within_limit'], 3_773_386)
        self.assertEqual(shallow['native_depth_screen']['derived_rough_class_cells_within_limit'], 166_433)
        self.assertIn('no chart-datum conversion', shallow['native_depth_screen']['basis'])
        block02 = by_id['csumb-bss-block02']
        self.assertEqual(block02['bathymetry']['valid_cells'], 5_021_485)
        self.assertEqual(block02['native_depth_screen']['cells_within_limit'], 3_033_938)
        self.assertEqual(block02['native_depth_screen']['derived_rough_class_cells_within_limit'], 17_169)
        self.assertEqual(block02['status'], 'held-from-fishing-targets')
        block03 = by_id['csumb-bss-block03']
        self.assertEqual(block03['bathymetry']['valid_cells'], 5_630_223)
        self.assertEqual(block03['native_depth_screen']['cells_within_limit'], 2_732_539)
        self.assertEqual(block03['native_depth_screen']['derived_rough_class_cells_within_limit'], 62_734)
        self.assertEqual(block03['status'], 'held-from-fishing-targets')
        source = by_id['csumb-bss-block12']
        self.assertEqual(source['status'], 'held-from-fishing-targets')
        self.assertIn('unresolved', source['rights_status'])
        self.assertEqual(source['native_vertical_datum'], 'NAVD88 Geoid09')
        self.assertEqual(source['bathymetry']['crs'], 'EPSG:26910')
        self.assertEqual(source['bathymetry']['resolution_m'], [2.0, 2.0])
        self.assertGreater(source['bathymetry']['valid_cells'], 600_000)
        self.assertGreater(source['terrain_habitat']['class_counts']['-31'], 0)
        deep = by_id['csumb-bss-block13']
        self.assertEqual(deep['bathymetry']['resolution_m'], [5.0, 5.0])
        self.assertGreater(deep['bathymetry']['valid_cells'], 750_000)
        self.assertLess(deep['bathymetry']['maximum'], -78)
        self.assertEqual(deep['native_depth_screen']['cells_within_limit'], 0)
        self.assertIn('No shallow-water target', deep['reason'])
        self.assertNotIn('targets', report)

    def test_changed_original_archive_fails_closed(self):
        spec = next(s for s in json.loads((ROOT / 'catalog/csumb-bss-native-sources.json').read_text())['sources']
                    if s['survey_id'] == 'BSS_Block12')
        with tempfile.TemporaryDirectory() as cache:
            (Path(cache) / 'BSS_Block12_additional_products.tar.gz').write_bytes(b'incomplete')
            with self.assertRaisesRegex(ValueError, 'pinned original'):
                audit(spec, Path(cache))


if __name__ == '__main__':
    unittest.main()
