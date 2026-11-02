"""import_cusp checks every region id and its bounds before any fetch, and writes through a temp file (RF2310-12)."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.shoreline import import_cusp as cusp
from tests._support import ROOT

MORRO = [-121.95, 34.95, -120.55, 35.85]


def collection(region_id):
    return {'type': 'FeatureCollection', 'features': [], 'provenance': {
        'region_id': region_id, 'features': 0, 'tile_receipts': [], 'requested_tiles': 0,
        'source_dates': [], 'held_creators': {}}}


def box_of(cols, rows, x=1000, y=1600):
    """A box covering exactly cols x rows z12 tiles, its corners just inside the corner tiles."""
    eps = 1e-6
    return [cusp.tile_lon(x, 12) + eps, cusp.tile_lat(y + rows, 12) + eps,
            cusp.tile_lon(x + cols - 1, 12) + eps, cusp.tile_lat(y, 12) - eps]


class CheckedBounds(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def region(self, region_id, body):
        folder = self.root / 'regions' / region_id
        folder.mkdir(parents=True)
        (folder / 'region.json').write_bytes(body if isinstance(body, bytes) else json.dumps(body).encode())

    def refused(self, region_id):
        with self.assertRaises(ValueError) as caught:
            cusp.checked_bounds(region_id, root=self.root)
        return str(caught.exception)

    def test_ids_outside_the_pattern_are_refused_before_any_file_read(self):
        for region_id in ('../x', 'a/b', 'Morro', '', 'a' * 65, '-x', 'x\n'):
            with self.subTest(region_id=region_id), patch.object(Path, 'read_text', side_effect=AssertionError):
                self.assertEqual(self.refused(region_id),
                                 f'{region_id}: region id must match [a-z0-9][a-z0-9-]{{0,63}}')
        self.region('a' * 64, {'bounds': MORRO})
        self.assertEqual(cusp.checked_bounds('a' * 64, root=self.root), MORRO)

    def test_unreadable_region_json_is_named(self):
        self.region('bad-json', b'{"bounds": [')
        self.region('bad-utf8', b'{"bounds": "\xff"}')
        self.region('deep', b'[' * 100000 + b']' * 100000)
        for region_id in ('missing', 'bad-json', 'bad-utf8', 'deep'):
            with self.subTest(region_id=region_id):
                self.assertEqual(self.refused(region_id), f'{region_id}: region.json unreadable')

    def test_each_bad_bounds_has_its_reason(self):
        shape = 'bounds must be [W, S, E, N]'
        lon, lat = 'bounds need finite -180 <= W < E <= 180', 'bounds need finite -85 <= S < N <= 85'
        cases = {'not-dict': ([1, 2, 3, 4], shape), 'no-bounds': ({}, shape), 'three': ({'bounds': [1, 2, 3]}, shape),
                 'text': ({'bounds': ['a', 0, 1, 1]}, shape), 'bool': ({'bounds': [True, 0, 1, 1]}, shape),
                 'nested': ({'bounds': [[0], 0, 1, 1]}, shape), 'nan': ({'bounds': [float('nan'), 0, 1, 1]}, lon),
                 'inf': ({'bounds': [0, 0, 1, float('inf')]}, lat), 'w-eq-e': ({'bounds': [1, 0, 1, 1]}, lon),
                 'w-gt-e': ({'bounds': [2, 0, 1, 1]}, lon), 'west-181': ({'bounds': [-181, 0, 1, 1]}, lon),
                 's-eq-n': ({'bounds': [0, 1, 1, 1]}, lat), 's-gt-n': ({'bounds': [0, 2, 1, 1]}, lat),
                 'north-86': ({'bounds': [0, 0, 1, 86]}, lat), 'huge-int': ({'bounds': [0, 0, 10 ** 400, 1]}, lon)}
        for region_id, (body, reason) in cases.items():
            self.region(region_id, body)
            with self.subTest(region_id=region_id):
                self.assertEqual(self.refused(region_id), f'{region_id}: {reason}')

    def test_tile_cap_refuses_2049_and_accepts_exactly_2048(self):
        for region_id, cols, rows in (('at-cap', 32, 64), ('one-row', 2048, 1), ('over', 2049, 1), ('over-2', 41, 50)):
            self.assertEqual(len(cusp.tiles_for(box_of(cols, rows))), cols * rows)
            self.region(region_id, {'bounds': box_of(cols, rows)})
        self.assertEqual(cusp.checked_bounds('at-cap', root=self.root), box_of(32, 64))
        self.assertEqual(cusp.checked_bounds('one-row', root=self.root), box_of(2048, 1))
        self.assertEqual(self.refused('over'), 'over: bounds need 2049 tiles (max 2048)')
        self.assertEqual(self.refused('over-2'), 'over-2: bounds need 2050 tiles (max 2048)')

    def test_committed_imports_pass_with_their_recorded_tile_counts(self):
        imports = sorted((ROOT / 'catalog/shoreline').glob('*.geojson'))
        self.assertTrue(imports)
        for path in imports:
            with self.subTest(region=path.stem):
                box = cusp.checked_bounds(path.stem)
                self.assertEqual(len(cusp.tiles_for(box)), json.loads(path.read_text())['provenance']['requested_tiles'])
                self.assertEqual(cusp.region_bounds(path.stem), box)


class Main(unittest.TestCase):
    def setUp(self):
        self.out = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.extract = self.enterContext(patch.object(cusp, 'extract', side_effect=lambda rid, box: collection(rid)))

    def run_main(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cusp.main([*argv, '--out', str(self.out)])
        return code, stderr.getvalue()

    def test_a_bad_region_anywhere_stops_the_run_before_any_fetch(self):
        for argv in (('morro-bay', 'nope'), ('nope', 'morro-bay'), ('morro-bay', '../morro-bay')):
            with self.subTest(argv=argv):
                code, stderr = self.run_main(*argv)
                self.assertEqual(code, 2)
                bad = [rid for rid in argv if rid != 'morro-bay'][0]
                self.assertTrue(stderr.startswith(f'import_cusp: {bad}: '), stderr)
                self.extract.assert_not_called()
                self.assertEqual(os.listdir(self.out), [])

    def test_duplicate_ids_are_one_region_and_a_good_run_leaves_no_temp_file(self):
        self.assertEqual(self.run_main('morro-bay', 'morro-bay', 'cambria-san-simeon'), (0, ''))
        self.assertEqual([call.args[0] for call in self.extract.call_args_list], ['morro-bay', 'cambria-san-simeon'])
        self.assertEqual(self.extract.call_args_list[0].args[1], MORRO)
        self.assertEqual(sorted(os.listdir(self.out)), ['cambria-san-simeon.geojson', 'morro-bay.geojson'])
        self.assertEqual(json.loads((self.out / 'morro-bay.geojson').read_text()), collection('morro-bay'))

    def test_a_failed_replace_keeps_the_old_file_byte_identical_and_removes_the_temp(self):
        target = self.out / 'morro-bay.geojson'
        target.write_bytes(b'{"old": "import"}\n')
        with patch.object(cusp.os, 'replace', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.run_main('morro-bay')
        self.assertEqual(target.read_bytes(), b'{"old": "import"}\n')
        self.assertEqual(os.listdir(self.out), ['morro-bay.geojson'])


if __name__ == '__main__':
    unittest.main()
