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
        source, = report['sources']
        self.assertEqual(source['status'], 'held-from-fishing-targets')
        self.assertIn('unresolved', source['rights_status'])
        self.assertEqual(source['native_vertical_datum'], 'NAVD88 Geoid09')
        self.assertEqual(source['bathymetry']['crs'], 'EPSG:26910')
        self.assertEqual(source['bathymetry']['resolution_m'], [2.0, 2.0])
        self.assertGreater(source['bathymetry']['valid_cells'], 600_000)
        self.assertGreater(source['terrain_habitat']['class_counts']['-31'], 0)
        self.assertNotIn('targets', report)

    def test_changed_original_archive_fails_closed(self):
        spec, = json.loads((ROOT / 'catalog/csumb-bss-native-sources.json').read_text())['sources']
        with tempfile.TemporaryDirectory() as cache:
            (Path(cache) / 'BSS_Block12_additional_products.tar.gz').write_bytes(b'incomplete')
            with self.assertRaisesRegex(ValueError, 'pinned original'):
                audit(spec, Path(cache))


if __name__ == '__main__':
    unittest.main()
