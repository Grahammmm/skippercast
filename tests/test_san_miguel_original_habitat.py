"""Original San Miguel habitat and bathymetry overlap stays source evidence."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.audit_san_miguel_original_habitat import read_usgs
from scripts.audit_san_miguel_vr_habitat import stable


ROOT = Path(__file__).resolve().parents[1]


class SanMiguelOriginalHabitatTests(unittest.TestCase):
    def test_original_sources_have_distinct_measured_footprints(self):
        regular = json.loads((ROOT / 'dist/data/san-miguel-original-habitat-depth-review.json').read_text())
        variable = json.loads((ROOT / 'dist/data/san-miguel-original-habitat-vr-review.json').read_text())
        self.assertEqual(regular['usgs_original']['polygon_count'], 2871)
        self.assertEqual(regular['substrate_classes']['h']['depth_uncertainty_eligible_cells'], 0)
        self.assertEqual(regular['noaa_measured_cells_in_window'], 257)
        self.assertEqual(variable['counts']['hard_eligible_cells'], 648740)
        self.assertEqual(variable['counts']['hard_cells_after_enc_buffer'], 601603)
        self.assertEqual(variable['counts']['fine_supergrids_in_usgs_bbox'], 5058)
        self.assertEqual(variable['enc_danger_features'], 201)
        self.assertFalse(regular['fishing_target'])
        self.assertFalse(variable['fishing_target'])
        self.assertFalse(variable['exportable'])
        self.assertNotIn('coordinates', str(variable['counts']))

    def test_tampered_usgs_archive_is_rejected_before_read(self):
        manifest = json.loads((ROOT / 'catalog/usgs-ofr0385-san-miguel.json').read_text())
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'smighab.tgz'
            path.write_bytes(b'not a reviewed source')
            with self.assertRaisesRegex(ValueError, 'changed'):
                read_usgs(path, manifest['usgs'])

    def test_fresh_retrieval_times_alone_do_not_change_source_overlap(self):
        report = json.loads((ROOT / 'dist/data/san-miguel-original-habitat-vr-review.json').read_text())
        changed = {**report, 'reviewed_at': 'later', 'enc_danger_checked_at': 'later'}
        self.assertEqual(stable(report), stable(changed))
        changed['counts'] = {**report['counts'], 'hard_eligible_cells': 0}
        self.assertNotEqual(stable(report), stable(changed))


if __name__ == '__main__':
    unittest.main()
