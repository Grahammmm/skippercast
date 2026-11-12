"""Oversized JSON integers must be refused by the land/water numeric admission helpers, not raise OverflowError."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from skippercast.platform import land_water as lw
from tests._support import ROOT
from tests.unit.test_land_water import FIXTURES, REGION, case_shoreline

HUGE = json.loads('1' + '0' * 400)
HUGE_NEG = -HUGE
HUGER = json.loads('9' * 4000)
SIGNED = [HUGE, HUGE_NEG, HUGER]


def build(shore, region=REGION):
    return lw.build_product(shore, region)


class HelperTest(unittest.TestCase):
    def test_numeric_helper_refuses_unrepresentable_json_integers(self):
        for value in SIGNED:
            with self.subTest(value=str(value)[:6]):
                self.assertIs(lw._number(value), False)
                self.assertIsNone(lw._acc(value))

    def test_ordinary_numeric_semantics_unchanged(self):
        for value in (0, 1, -1, 7, -7, 0.5, -0.5, 4.31, 10 ** 300):
            self.assertIs(lw._number(value), True, value)
        for value in (True, False, None, '1', 'x', math.nan, math.inf, -math.inf, [], {}):
            self.assertIs(lw._number(value), False, value)
        self.assertEqual(lw._acc(0), 0.0)
        self.assertEqual(lw._acc(4.31), 4.31)
        self.assertEqual(lw._acc('4.5'), 4.5)
        self.assertEqual(lw._acc(True), 1.0)
        self.assertEqual(lw._acc(10 ** 300), 1e300)
        for value in (-1, None, 'x', math.nan, math.inf, '1' + '0' * 400, '-1', []):
            self.assertIsNone(lw._acc(value), value)

    def test_valid_product_bytes_unchanged(self):
        index, lines = lw.build_product(case_shoreline('coast'), REGION, {'path': 'fixture/coast', 'sha256': 'fixture-coast'})
        control = json.loads((FIXTURES / 'coast.json').read_text())
        control.pop('fixture')
        self.assertEqual(lw._dump(index), lw._dump(control))
        self.assertEqual(lw._dump(lines), (FIXTURES / 'coast.lines.json').read_bytes())


class FieldPathTest(unittest.TestCase):
    def assertRefused(self, shore, cause, region=REGION):
        before = copy.deepcopy((shore, region))
        index, lines = build(shore, region)
        self.assertEqual(index['status'], 'unavailable')
        self.assertTrue(any(cause in c for c in index['causes']), index['causes'])
        self.assertIsNone(lines)
        self.assertNotIn('tiles', index)
        self.assertEqual((shore, region), before)

    def test_oversized_coordinate_refuses_whole_product(self):
        for value in SIGNED[:2]:
            for member in (0, 1):
                for feature in (0, 1, 2):
                    with self.subTest(value=value > 0, member=member, feature=feature):
                        shore = case_shoreline('coast')
                        shore['features'][feature]['geometry']['coordinates'][0][1][member] = value
                        self.assertRefused(shore, 'malformed lines')

    def test_oversized_coordinate_in_linestring_refuses(self):
        shore = case_shoreline('coast')
        geometry = shore['features'][1]['geometry']
        geometry['type'] = 'LineString'
        geometry['coordinates'] = geometry['coordinates'][0]
        geometry['coordinates'][0][0] = HUGE
        with self.assertRaises(lw.Unavailable) as raised:
            lw.assemble(shore, REGION)
        self.assertIn('malformed lines', str(raised.exception))
        self.assertRefused(shore, 'malformed lines')

    def test_oversized_bounds_use_region_bounds_missing(self):
        for value in SIGNED:
            for i in range(4):
                with self.subTest(value=value > 0, index=i):
                    region = copy.deepcopy(REGION)
                    region['bounds'][i] = value
                    self.assertRefused(case_shoreline('coast'), 'region bounds missing', region)

    def test_oversized_quantisation_uses_existing_cause(self):
        for value in SIGNED:
            with self.subTest(value=value > 0):
                shore = case_shoreline('coast')
                shore['provenance']['display_quantisation_m'] = value
                self.assertRefused(shore, 'invalid display quantisation')

    def test_oversized_hor_acc_uses_missing_accuracy_refusal(self):
        for value in SIGNED:
            for feature in (0, 2):
                with self.subTest(value=value > 0, feature=feature):
                    shore = case_shoreline('coast')
                    shore['features'][feature]['properties']['HOR_ACC'] = value
                    self.assertRefused(shore, 'HOR_ACC missing')

    def test_representable_numeric_string_accuracy_still_accepted(self):
        shore = case_shoreline('coast')
        for feature in shore['features']:
            feature['properties']['HOR_ACC'] = '4.31'
        self.assertEqual(build(shore)[0]['status'], 'available')
        shore['features'][0]['properties']['HOR_ACC'] = '1' + '0' * 400
        self.assertRefused(shore, 'HOR_ACC missing')


class PublisherTest(unittest.TestCase):
    def test_local_publisher_writes_unavailable_and_removes_stale_companion(self):
        def huge_coordinate(s):
            s['features'][0]['geometry']['coordinates'][0][1][0] = HUGE

        def huge_quantisation(s):
            s['provenance']['display_quantisation_m'] = HUGE

        def huge_accuracy(s):
            s['features'][0]['properties']['HOR_ACC'] = HUGE

        for name, mutate in (('coordinate', huge_coordinate), ('quantisation', huge_quantisation), ('accuracy', huge_accuracy)):
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                shore = case_shoreline('coast')
                mutate(shore)
                raw = json.dumps(shore).encode()
                (out / 'shoreline.geojson').write_bytes(raw)
                (out / lw.INDEX).write_text('{"stale": true}')
                (out / lw.LINES).write_text('{"stale": true}')
                index = lw.publish_land_water(ROOT, REGION, out)
                self.assertEqual(index['status'], 'unavailable')
                self.assertEqual(index, json.loads((out / lw.INDEX).read_text()))
                self.assertFalse((out / lw.LINES).exists())
                self.assertEqual((out / 'shoreline.geojson').read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
