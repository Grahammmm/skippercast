"""MAPLAYER-CURRENT-1: HF-radar fetcher quality rules and packing, on a synthetic DAP response (no network)."""
import json
from pathlib import Path
import tempfile
import unittest

from research.scripts.map_style import fetch_hfr_currents as fh

DDS = 'Dataset { Int16 u[time = 4][lat = 3][lon = 3]; Float32 lat[lat = 3]; Float32 lon[lon = 3]; Int32 time[time = 4]; }'
DAS = 'time { String units "seconds since 1970-01-01"; } u { Int16 _FillValue -32767; Float32 scale_factor 0.01; }'


def block(name, values, dims, plain=False):
    shape = ''.join(f'[{d}]' for d in dims)
    return f'{name if plain else name + "." + name}{shape}\n' + ', '.join(str(v) for v in values) + '\n\n'


def ascii_response(parts):
    return 'Dataset {...}\n' + fh.RULE + '\n' + ''.join(parts)


def fake_fetch(hours):
    """hours: per time step, a dict of cell index -> (u, v, hdop, sites); other cells are fill."""
    times = [1794060000 + 3600 * i for i in range(len(hours))]

    def fetch(url):
        if url.endswith('.dds'):
            return DDS.replace('time = 4', f'time = {len(hours)}')
        if url.endswith('.das'):
            return DAS
        if '.ascii?time' in url:
            return ascii_response([block('time', times, [len(times)], plain=True), block('lat', [35.0, 35.1, 35.2], [3], plain=True),
                                   block('lon', [-121.0, -120.9, -120.8], [3], plain=True)])
        flat = {k: [] for k in ('u', 'v', 'hdop', 'number_of_sites')}
        for hour in hours:
            for i in range(9):
                u, v, hd, s = hour.get(i, (fh.FILL, fh.FILL, fh.FILL, -127))
                flat['u'].append(u); flat['v'].append(v); flat['hdop'].append(hd); flat['number_of_sites'].append(s)
        return ascii_response([block(k, flat[k], [len(hours), 3, 3]) for k in flat])
    return fetch


GOOD = {i: (20, -10, 50, 3) for i in range(9)}
SECTOR = {'name': 'test', 'bounds': [-121.05, 34.95, -120.75, 35.25]}


class HfrFetch(unittest.TestCase):
    def test_cell_rule_matches_the_pipeline(self):
        self.assertTrue(fh.keep_cell(20, -10, 50, 3))
        self.assertFalse(fh.keep_cell(fh.FILL, -10, 50, 3), 'fill value')
        self.assertFalse(fh.keep_cell(20, -10, 250, 3), 'HDOP above 2')
        self.assertFalse(fh.keep_cell(20, -10, 50, 1), 'one radar')
        self.assertFalse(fh.keep_cell(20, -10, 50, 21), 'too many radars means a corrupt count')
        self.assertFalse(fh.keep_cell(600, 100, 50, 3), 'faster than 5 m/s')

    def test_newest_populated_hour_is_used_and_gaps_stay_null(self):
        partial = dict(GOOD)
        partial[4] = (fh.FILL, fh.FILL, fh.FILL, -127)
        # the newest hour is empty, the one before has 8 of 9 cells
        doc = fh.build('t', SECTOR, 6, fetch=fake_fetch([GOOD, partial, {}]), minimum=1)
        self.assertEqual(doc['hours_behind_latest'], 1)
        self.assertEqual(doc['sample_at'], fh.iso(1794060000 + 3600))
        self.assertEqual(doc['latest_grid_time'], fh.iso(1794060000 + 7200))
        self.assertEqual((doc['valid_cells'], doc['total_cells']), (8, 9))
        self.assertIsNone(doc['u'][1][1])
        self.assertIsNone(doc['v'][1][1])
        self.assertEqual(doc['u'][0][0], 0.2)
        self.assertEqual(doc['v'][0][0], -0.1)
        self.assertEqual(doc['sites'][1][1], 0)

    def test_no_usable_hour_is_an_error_not_an_empty_map(self):
        with self.assertRaises(ValueError):
            fh.build('t', SECTOR, 6, fetch=fake_fetch([{}, {}]), minimum=1)

    def test_changed_packing_is_refused(self):
        def fetch(url):
            return DAS.replace('0.01', '0.1') if url.endswith('.das') else DDS
        with self.assertRaises(ValueError):
            fh.build('t', SECTOR, 6, fetch=fetch)

    def test_document_is_self_describing_and_written_under_var(self):
        doc = fh.build('t', SECTOR, 6, fetch=fake_fetch([GOOD]), minimum=1)
        self.assertEqual(doc['schema'], fh.SCHEMA)
        self.assertIn('NOT FOR NAVIGATION', doc['limitations'])
        self.assertEqual(doc['unit'], 'm s-1')
        with tempfile.TemporaryDirectory() as directory:
            path = fh.write(doc, Path(directory))
            self.assertEqual(path.name, 'hfr-t-6km.json')
            self.assertEqual(json.loads(path.read_text())['sample_at'], doc['sample_at'])
        self.assertEqual(fh.OUT_DIR, fh.ROOT / 'var/currents', 'default output is the private var/ tree')

    def test_sectors_file_has_the_central_coast_and_valid_boxes(self):
        sectors = json.loads(fh.SECTORS.read_text())
        self.assertIn('central-coast', sectors)
        for sector in sectors.values():
            west, south, east, north = sector['bounds']
            self.assertTrue(west < east and south < north)


if __name__ == '__main__':
    unittest.main()
