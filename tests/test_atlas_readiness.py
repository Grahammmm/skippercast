"""Keep the statewide promotion queue complete and honest."""
import json
import unittest
from pathlib import Path

from skippercast.platform.readiness import compile_readiness


ROOT = Path(__file__).resolve().parents[1]


class AtlasReadinessTests(unittest.TestCase):
    def test_every_discovery_sector_has_a_non_promotion_queue_entry(self):
        compile_readiness(ROOT)
        report = json.loads((ROOT / 'dist/data/california-atlas-readiness.json').read_text())
        source = json.loads((ROOT / 'catalog/coastal-sectors.json').read_text())
        self.assertEqual({row['sector_id'] for row in report['sectors']},
                         {row['id'] for row in source['sectors']})
        self.assertEqual(len(report['sectors']), 19)
        by_sector = {row['sector_id']: row for row in report['sectors']}
        self.assertEqual(by_sector['del-norte']['native_variable_depth_file_leads'], 2)
        self.assertEqual(by_sector['del-norte']['historical_noaa_seabed_samples'], 0)
        self.assertEqual(by_sector['reyes-pigeon']['historical_noaa_seabed_samples'], 881)
        self.assertIn('F00789', by_sector['reyes-pigeon']['held_variable_depth_survey_ids'])
        self.assertEqual(by_sector['reyes-pigeon']['native_variable_depth_file_leads'],
                         by_sector['reyes-pigeon']['held_variable_depth_file_leads']
                         + by_sector['reyes-pigeon']['unheld_variable_depth_file_leads'])
        self.assertEqual(by_sector['north-mendocino']['native_variable_depth_file_leads'], 3)
        self.assertIn('BSS_Block13', by_sector['big-sur']['csumb_catalog_survey_lead_ids'])
        self.assertIn('csumb-bss-block13-native-candidate', by_sector['big-sur']['native_depth_excluded_source_candidate_ids'])
        self.assertNotIn('csumb-bss-block13-native-candidate', by_sector['big-sur']['accessible_inspected_fine_source_candidate_ids'])
        self.assertIn('SCC_Block01', by_sector['sur-san-simeon']['csumb_catalog_survey_lead_ids'])
        self.assertIn('SCC_Block08', by_sector['cambria-morro']['csumb_catalog_survey_lead_ids'])
        self.assertTrue(any(a['name'] == 'Offshore of Ventura'
                            for a in by_sector['conception-ventura']['usgs_ds781_map_area_leads']))
        self.assertTrue(any(a['priority_product_status'] == 'index-link-mismatch'
                            for a in by_sector['humboldt-cape']['usgs_ds781_map_area_leads']))
        self.assertTrue(any('instantaneous sea level' in a['bathymetry_datum_declarations']
                            for a in by_sector['humboldt-cape']['usgs_ds781_map_area_leads']))
        self.assertEqual(by_sector['san-diego-border']['usgs_ds781_map_area_leads'], [])
        self.assertEqual(by_sector['big-sur']['published_candidate_points_in_band'], 0)
        self.assertIn('H13151', by_sector['sur-san-simeon']['native_depth_excluded_survey_ids'])
        self.assertEqual(by_sector['morro-conception']['native_depth_excluded_survey_ids'], ['H13089', 'H13151'])
        self.assertIn('noaa-h11971-bear-landing-original-camera',
                      by_sector['north-mendocino']['accessible_inspected_fine_source_candidate_ids'])
        for sector_id in ('pigeon-monterey', 'monterey-sur'):
            row = by_sector[sector_id]
            self.assertIn('usgs-offshore-monterey-original-grids',
                          row['accessible_inspected_fine_source_candidate_ids'])
            self.assertEqual(row['published_candidate_points_in_band'], 0)
            self.assertIn('chart datum and uncertainty', row['next_source_step'])
        self.assertIn('usgs-offshore-aptos-original-grids',
                      by_sector['pigeon-monterey']['accessible_inspected_fine_source_candidate_ids'])
        for row in report['sectors']:
            self.assertIn(row['status'], {'source-review-only', 'partial-local-targets'})
            self.assertEqual(bool(row['published_candidate_points_in_band']),
                             row['status'] == 'partial-local-targets')
            self.assertGreaterEqual(len(row['remaining_promotion_gates']), 6)
            self.assertNotIn('latitude', row)
            self.assertNotIn('longitude', row)

    def test_missing_source_sector_fails_closed(self):
        from tempfile import TemporaryDirectory
        import shutil
        with TemporaryDirectory() as work:
            root = Path(work)
            for relative in ('dist/data/coastal-sectors.json',
                             'dist/data/noaa-native-sector-review.json',
                             'dist/data/noaa-vr-native-depth-expanded-review.json',
                             'dist/data/noaa-regular-native-depth-review.json',
                             'dist/data/noaa-survey-discovery.json',
                             'dist/data/noaa-seabed-samples-sector-review.json',
                             'dist/data/noaa-central-deepwater-native-depth-screen.json',
                             'catalog/csumb-scc-source-leads.json',
                             'catalog/csumb-bss-source-leads.json',
                             'catalog/usgs-ds781-source-leads.json',
                             'catalog/usgs-ds781-metadata-review.json',
                             'catalog/noaa-survey-lead-holds.json',
                             'dist/regions/index.json'):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            path = root / 'dist/data/noaa-native-sector-review.json'
            packet = json.loads(path.read_text())
            packet['sectors'].pop()
            path.write_text(json.dumps(packet))
            with self.assertRaisesRegex(ValueError, 'missing or has duplicate'):
                compile_readiness(root)
