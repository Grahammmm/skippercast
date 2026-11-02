"""import_cusp main: every region checked before any fetch; no-tile or emptied runs never replace a file (RF2320-3)."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.shoreline import import_cusp as cusp
from tests.unit.test_cusp_shoreline import NOAA, tile

BOX = [-120.9, 35.3, -120.8, 35.4]
TILES = cusp.tiles_for(BOX)
GOOD = tile([(NOAA, [(100, 100), (4000, 4000)])])
HELD = tile([({**NOAA, 'DAT_SET_CR': 'County'}, [(100, 100), (4000, 4000)])])


class MainTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root, self.calls = Path(temp.name), []

    def region(self, region_id, bounds=BOX, text=None, folder=None):
        folder = folder or self.root / 'regions' / region_id
        folder.mkdir(parents=True)
        (folder / 'region.json').write_text(text if text is not None else json.dumps({'id': region_id, 'bounds': bounds}))

    def existing(self, region_id, features):
        path = self.root / 'catalog/shoreline' / f'{region_id}.geojson'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}) if isinstance(features, list)
                        else features)
        return path, path.read_bytes()

    def run_main(self, argv, body=None):
        def get(t):
            self.calls.append(t)
            return body if t == TILES[0] else None
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cusp.main(argv, root=self.root, get=get)
        return code, out.getvalue(), err.getvalue()

    def test_bad_ids_exit_2_before_any_fetch(self):
        self.region('x', folder=self.root / 'x')  # what regions/../x would reach
        for region_id in ('../x', 'Morro', 'no-such-region', 'a', 'x/..'):
            code, out, err = self.run_main([region_id], GOOD)
            self.assertEqual((code, out), (2, ''), region_id)
            self.assertTrue(err.startswith(f'import_cusp: {region_id}: '), err)
        self.assertEqual(self.calls, [])

    def test_bad_bounds_are_each_named_and_nothing_is_fetched(self):
        bad = {'three': [-120.9, 35.3, -120.8], 'text': ['a', 35.3, -120.8, 35.4], 'bool': [True, 35.3, -120.8, 35.4],
               'nan': [float('nan'), 35.3, -120.8, 35.4], 'inf': [-120.9, 35.3, float('inf'), 35.4],
               'reversed': [-120, 36, -121, 35], 'south-north': [-120.9, 35.4, -120.8, 35.3],
               'off-globe': [-190, 35.3, -120.8, 35.4], 'not-list': {'w': 1}}
        for region_id, bounds in bad.items():
            self.region(region_id, bounds)
        self.region('no-bounds', text='{"id": "no-bounds"}')
        self.region('not-json', text='{')
        self.region('array', text='[]')
        ids = [*bad, 'no-bounds', 'not-json', 'array']
        code, out, err = self.run_main(ids, GOOD)
        self.assertEqual((code, out, self.calls), (2, '', []))
        self.assertEqual([line.split(': ')[1] for line in err.splitlines()], ids)

    def test_one_bad_region_stops_the_good_one_before_it_too(self):
        self.region('good')
        self.region('bad', [-120, 36, -121, 35])
        code, out, err = self.run_main(['good', 'bad'], GOOD)
        self.assertEqual((code, out, self.calls), (2, '', []))
        self.assertIn('import_cusp: bad: ', err)
        self.assertFalse((self.root / 'catalog/shoreline').exists())

    def test_no_tile_served_leaves_the_file_and_exits_1(self):
        self.region('good')
        path, before = self.existing('good', [{'id': 'a'}])
        code, out, err = self.run_main(['good'], None)
        self.assertEqual((code, out, path.read_bytes()), (1, '', before))
        self.assertEqual(err, f'import_cusp: good: NOAA served none of {len(TILES)} tiles; {path} left unchanged\n')
        path.unlink()
        self.assertEqual(self.run_main(['good'], None)[0], 1)
        self.assertFalse(path.exists(), 'a run with no tile served writes no new file either')

    def test_zero_features_over_a_file_with_some_is_refused_unless_allowed(self):
        self.region('good')
        path, before = self.existing('good', [{'id': 'a'}, {'id': 'b'}])
        code, out, err = self.run_main(['good'], HELD)
        self.assertEqual((code, out, path.read_bytes()), (1, '', before))
        self.assertIn('good: 0 features where the current file has 2; ', err)
        path, before = self.existing('good', 'not json')
        code, _, err = self.run_main(['good'], HELD)
        self.assertEqual((code, path.read_bytes()), (1, before))
        self.assertIn('has unreadable content; ', err)
        code, out, err = self.run_main(['good', '--allow-empty'], HELD)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(path.read_text())['provenance']['held_creators'], {'County': 1})
        self.existing('good', [])
        self.assertEqual(self.run_main(['good'], HELD)[0], 0, 'an empty file may be replaced by an empty run')

    def test_a_normal_run_writes_atomically_in_order(self):
        self.region('good')
        self.region('next-one')
        path, _ = self.existing('good', [{'id': 'old'}])
        code, out, err = self.run_main(['good', 'next-one'], GOOD)
        self.assertEqual((code, err), (0, ''))
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith(f'{path}: 1 features, 1/{len(TILES)} tiles served, source dates '), lines)
        self.assertTrue(lines[1].startswith(f'{path.parent / "next-one.geojson"}: 1 features'), lines)
        self.assertEqual(json.loads(path.read_text())['features'][0]['properties']['source_date'], '2010-05-09')
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ['good.geojson', 'next-one.geojson'])

    def test_a_failed_replace_keeps_the_old_file_and_no_temp(self):
        self.region('good')
        path, before = self.existing('good', [{'id': 'old'}])
        with patch.object(cusp.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.run_main(['good'], GOOD)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([p.name for p in path.parent.iterdir()], ['good.geojson'])


if __name__ == '__main__':
    unittest.main()
