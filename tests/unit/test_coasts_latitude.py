"""RF2100-10: compile_coasts refuses malformed latitude bands before any seam check or write."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skippercast.platform import coasts
from skippercast.platform.coasts import _band_ok, compile_coasts
from skippercast.platform.contracts import REPO

CATALOG = ('coasts.json', 'targets.json', 'species.json', 'data-needs.json', 'sources.json')
IDS = ['northern', 'mendocino', 'san-francisco', 'central', 'southern']
MISSING = object()


class LatitudeBandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = json.loads((REPO / 'catalog/coasts.json').read_text())

    def make_root(self, edits=None):
        directory = copy.deepcopy(self.directory)
        for ident, band in (edits or {}).items():
            region = next(r for r in directory['regions'] if r['id'] == ident)
            if band is MISSING:
                region.pop('latitude')
            else:
                region['latitude'] = band
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'catalog').mkdir()
        for name in CATALOG:
            shutil.copy(REPO / 'catalog' / name, root / 'catalog' / name)
        (root / 'catalog/coasts.json').write_text(json.dumps(directory))
        for ident in {p for r in directory['regions'] for p in r['packages']}:
            (root / 'regions' / ident).mkdir(parents=True)
            shutil.copy(REPO / 'regions' / ident / 'region.json', root / 'regions' / ident / 'region.json')
        return root

    def refuse(self, edits, message, raw=None):
        root = self.make_root(edits)
        if raw is not None:
            text = (root / 'catalog/coasts.json').read_text()
            (root / 'catalog/coasts.json').write_text(text.replace('"latitude": ' + raw[0], '"latitude": ' + raw[1], 1))
        with mock.patch.object(coasts, 'atomic_json') as writer:
            with self.assertRaises(ValueError) as caught:
                compile_coasts(root)
        self.assertEqual(str(caught.exception), message)
        writer.assert_not_called()
        self.assertFalse((root / 'dist').exists())

    def test_bad_northern_north_cannot_publish(self):
        south = self.directory['regions'][0]['latitude'][0]
        for north in (south - 1, south, True, '42'):
            with self.subTest(north=north):
                self.refuse({'northern': [south, north]}, 'Invalid coastal latitude band: northern latitude')

    def test_band_shape_and_numeric_matrix(self):
        bad = [MISSING, None, 5, '40', {'a': 1}, [], [40], [40, 41, 42], [None, 41], [40, None], ['40', 41],
               [[40], 41], [True, 41], [40, False], [10 ** 400, 10 ** 401], [-10 ** 400, 41], [40, 10 ** 400],
               [-91, 41], [40, 91], [41, 40], [40, 40]]
        for band in bad:
            with self.subTest(band=repr(band)[:40]):
                self.refuse({'northern': band}, 'Invalid coastal latitude band: northern latitude')
        for band in bad + [[float('nan'), 41], [40, float('inf')], [float('-inf'), 41]]:  # read_json refuses these literals
            self.assertFalse(_band_ok(None if band is MISSING else band))

    def test_serialized_exponent_overflow_refused(self):
        lat = json.dumps(self.directory['regions'][0]['latitude'])
        self.refuse(None, 'Invalid coastal latitude band: northern latitude', raw=(lat, '[40.1, 1e309]'))

    def test_all_bands_preflight_before_seams(self):
        for ident in IDS[1:]:
            with self.subTest(ident=ident):
                self.refuse({ident: [50, 49]}, f'Invalid coastal latitude band: {ident} latitude')
        self.refuse({'central': [1, 0], 'mendocino': None}, 'Invalid coastal latitude band: mendocino latitude')

    def test_valid_nonmeeting_seam_keeps_old_refusal(self):
        regions = self.directory['regions']
        for delta in (0.5, -0.5):
            with self.subTest(delta=delta):
                lo, hi = regions[1]['latitude']
                self.refuse({'mendocino': [lo + delta, hi]}, 'Coastal latitude boundaries must meet exactly')

    def test_refusal_keeps_existing_output(self):
        root = self.make_root({'southern': [30, 30]})
        out = root / 'dist/data'
        out.mkdir(parents=True)
        (out / 'coasts.json').write_bytes(b'sentinel')
        (out / 'other.json').write_bytes(b'keep')
        with self.assertRaises(ValueError):
            compile_coasts(root)
        self.assertEqual((out / 'coasts.json').read_bytes(), b'sentinel')
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['coasts.json', 'other.json'])

    def test_valid_control_preserves_values(self):
        root = self.make_root()
        result = compile_coasts(root)
        self.assertEqual([r['latitude'] for r in result['regions']], [r['latitude'] for r in self.directory['regions']])
        self.assertEqual(json.loads((root / 'dist/data/coasts.json').read_text())['regions'][0]['latitude'],
                         self.directory['regions'][0]['latitude'])
        for band in ([-90, 90], [-90.0, 0], [1, 2.5]):
            self.assertTrue(_band_ok(band))
        self.assertFalse(_band_ok((1, 2)))
