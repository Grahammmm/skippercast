"""NOAA seabed sample audit must retain complete paging and source limitations."""
import json
import unittest
from pathlib import Path

from scripts.audit_noaa_seabed_samples import summarize, validate_pages


ROOT = Path(__file__).resolve().parents[1]


def feature(ident, lon=-123.7, lat=38.8, date=None):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': {'OBJECTID': ident, 'NATSUR': None,
                           'DESCRP': 'rock, sand', 'BEGIN_OBSTIM': date,
                           'SORDAT': None, 'SOURCE': 'historical'}}


class NoaaSeabedSamplesTests(unittest.TestCase):
    def test_complete_arcgis_paging_allows_a_full_nonfinal_page_only(self):
        first = {'type': 'FeatureCollection', 'features': [feature(i) for i in range(2000)],
                 'exceededTransferLimit': True}
        last = {'type': 'FeatureCollection', 'features': [feature(2000)]}
        self.assertEqual(len(validate_pages([first, last], 2001)), 2001)
        last['features'] = [feature(1999)]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            validate_pages([first, last], 2001)
        last['features'] = [feature(2000)]
        last['exceededTransferLimit'] = True
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            validate_pages([first, last], 2001)

    def test_future_date_does_not_extend_observation_range(self):
        sectors = json.loads((ROOT / 'dist/data/coastal-sectors.json').read_text())['sectors']
        valid = feature(1, date=946684800000)  # 2000-01-01
        future = feature(2, date=3488140800000)  # Erroneous 2080 source value
        report = summarize([valid, future], sectors, checked_at='2026-09-25T05:00:00+00:00',
                           metadata_sha='m', count_sha='c', page_shas=['p'])
        row = next(x for x in report['sectors'] if x['sector_id'] == 'arena-bodega')
        self.assertEqual(row['historical_sample_count'], 2)
        self.assertEqual(row['observation_year_range'], [2000, 2000])
        self.assertEqual(row['implausible_date_count'], 1)
        self.assertFalse(report['fishing_target'])
        self.assertFalse(report['exportable'])

    def test_public_receipt_has_all_sectors_but_no_sample_positions(self):
        report = json.loads((ROOT / 'dist/data/noaa-seabed-samples-sector-review.json').read_text())
        self.assertEqual(report['bounded_original_sample_count'], 3591)
        self.assertEqual(len(report['sectors']), 19)
        self.assertEqual(sum(x['historical_sample_count'] for x in report['sectors']), 3591)
        self.assertFalse(report['fishing_target'])
        self.assertNotIn('"coordinates"', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
