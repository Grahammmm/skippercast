"""Deepwater source cannot leak into the shallow bottom target catalog."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_usgs_caldig_v2 import acquire


ROOT = Path(__file__).resolve().parents[1]


class CalDigV2AuditTest(unittest.TestCase):
    def test_exact_original_scan_has_no_200_or_300_foot_candidates(self):
        report = json.loads((ROOT / 'dist/data/usgs-caldig-v2-native-review.json').read_text())
        self.assertEqual(report['source_use'], 'deepwater habitat research context only')
        self.assertEqual(report['bottom_target_status'], 'not-qualified')
        self.assertEqual(report['bathymetry']['candidate_200ft_cells'], 0)
        self.assertEqual(report['bathymetry']['candidate_300ft_cells'], 0)
        self.assertGreater(report['bathymetry']['valid_cells'], 90_000_000)
        self.assertGreater(report['cmecs']['bedrock_polygons'], 40_000)
        self.assertEqual(report['cmecs']['source_crs'], 'EPSG:4269')
        self.assertEqual(len(report['cmecs']['bounds_wgs84']), 4)
        self.assertNotIn('targets', report)

    def test_changed_archive_cannot_be_silently_used(self):
        manifest = json.loads((ROOT / 'catalog/usgs-caldig-v2.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / 'Cal_DIG_I_v2_Bathymetry.zip').write_bytes(b'incomplete')
            with self.assertRaisesRegex(ValueError, 'pinned original'):
                acquire('bathymetry', manifest['archives']['bathymetry'], cache, False)


if __name__ == '__main__':
    unittest.main()
