"""Wrong-shaped shoreline feature objects make the whole land/water product unavailable."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from skippercast.platform import land_water as lw
from tests.unit.test_land_water import REGION, case_shoreline

NONOBJECTS = [None, '', 'x', 0, 7, True, False, [], [1]]
FALSY_AND_TRUTHY = ['x', 'abc', 0, 5, True, False, [], [1], ['a']]


def coast():
    return case_shoreline('coast')


def with_feature(member, first=False):
    shore = coast()
    if first:
        shore['features'].insert(0, member)
    else:
        shore['features'].append(member)
    return shore


def with_field(field, value):
    shore = coast()
    shore['features'][0][field] = value
    return shore


class ShapeTest(unittest.TestCase):
    def assertRefused(self, shore, count=None):
        before = copy.deepcopy(shore)
        with self.assertRaises(lw.Unavailable) as ctx:
            lw.assemble(shore, REGION)
        self.assertIn('malformed lines', str(ctx.exception))
        if count is not None:
            self.assertIn(f'malformed lines {count}', str(ctx.exception))
        self.assertEqual(shore, before)
        index, lines = lw.build_product(shore, REGION)
        self.assertEqual(index['status'], 'unavailable')
        self.assertIsNone(lines)
        self.assertNotIn('tiles', index)
        self.assertTrue(any('malformed lines' in c for c in index['causes']))

    def test_feature_nonobjects_fail_whole_product(self):
        for bad in NONOBJECTS:
            for first in (False, True):
                with self.subTest(bad=bad, first=first):
                    self.assertRefused(with_feature(bad, first), count=1)

    def test_geometry_nonobjects_are_controlled(self):
        for bad in FALSY_AND_TRUTHY:
            with self.subTest(bad=bad):
                self.assertRefused(with_field('geometry', bad), count=1)
        for missing in (None, {}):
            with self.subTest(missing=missing):
                self.assertRefused(with_field('geometry', missing), count=1)

    def test_properties_nonobjects_are_controlled(self):
        for bad in FALSY_AND_TRUTHY:
            with self.subTest(bad=bad):
                self.assertRefused(with_field('properties', bad), count=1)
        for missing in (None, {}):
            with self.subTest(missing=missing):
                with self.assertRaises(lw.Unavailable) as ctx:
                    lw.assemble(with_field('properties', missing), REGION)
                self.assertIn('HOR_ACC missing', str(ctx.exception))
                self.assertNotIn('malformed', str(ctx.exception))

    def test_multiple_rejections_aggregate_without_payload(self):
        shore = with_feature('SECRET-PAYLOAD')
        shore['features'].append([1, 2])
        shore['features'][0]['properties'] = 'SECRET-PAYLOAD'
        with self.assertRaises(lw.Unavailable) as ctx:
            lw.assemble(shore, REGION)
        self.assertIn('malformed lines 3', str(ctx.exception))
        self.assertNotIn('SECRET', str(ctx.exception))

    def test_multipart_member_counts_are_kept(self):
        shore = coast()
        shore['features'][0]['geometry']['coordinates'].append('bad')
        self.assertRefused(shore, count=1)

    def test_local_publisher_replaces_stale_products(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'shoreline.geojson').write_text(json.dumps(coast()))
            good = lw.publish_land_water(Path('.'), REGION, out)
            self.assertEqual(good['status'], 'available')
            self.assertTrue((out / lw.LINES).is_file())
            good_bytes = (out / lw.INDEX).read_bytes()
            (out / 'shoreline.geojson').write_text(json.dumps(with_feature('x')))
            bad = lw.publish_land_water(Path('.'), REGION, out)
            self.assertEqual(bad['status'], 'unavailable')
            self.assertFalse((out / lw.LINES).exists())
            self.assertEqual(json.loads((out / lw.INDEX).read_text()), bad)
            self.assertNotIn('tiles', bad)
            (out / 'shoreline.geojson').write_text(json.dumps(coast()))
            lw.publish_land_water(Path('.'), REGION, out)
            self.assertEqual((out / lw.INDEX).read_bytes(), good_bytes)

    def test_valid_products_unchanged(self):
        shore = coast()
        before = copy.deepcopy(shore)
        index, lines = lw.build_product(shore, REGION)
        self.assertEqual(index['status'], 'available')
        self.assertEqual(shore, before)
        self.assertEqual(lw.build_product(copy.deepcopy(shore), REGION), (index, lines))
        single = coast()
        geometry = single['features'][0]['geometry']
        geometry['type'], geometry['coordinates'] = 'LineString', geometry['coordinates'][0]
        self.assertEqual(lw.build_product(single, REGION)[0]['status'], 'available')


if __name__ == '__main__':
    unittest.main()
