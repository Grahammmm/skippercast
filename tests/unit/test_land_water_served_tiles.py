"""Only canonical zoom-12 tile receipts can support a land/water mask."""
import unittest

from skippercast.platform import land_water as lw
from tests.unit.test_land_water import CASES, FIXTURES, REGION, build, case_shoreline


class ServedTilesTest(unittest.TestCase):
    def assertWithheld(self, shore):
        index, lines = lw.build_product(shore, REGION)
        self.assertEqual(index['status'], 'unavailable')
        self.assertEqual(index['causes'], ['invalid served tile receipt (expected zoom-12 z/x/y)'])
        self.assertNotIn('tiles', index)
        self.assertNotIn('lines', index)
        self.assertIsNone(lines)

    def test_one_bad_receipt_invalidates_otherwise_good_coast(self):
        # Dropping a bad receipt, coercing a noncanonical ID, or passing it to
        # the grid parser would falsely accept the evidence or raise a traceback.
        for tile in ('11/1/1', '012/1/1', 'bad', '', '12/1', '12/1/1/1',
                     '12//1', '12/1/', '12/-1/1', '12/1/-1', '12/4096/1',
                     '12/1/4096', '12/+1/1', '12/1/01', '12/1/1\n',
                     '12/ 1/1', '12/１/1', '12/1_0/1', None, 12, ['12/1/1'], {}):
            with self.subTest(tile=tile):
                shore = case_shoreline('coast')
                shore['provenance']['tile_receipts'].append({'tile': tile, 'private': 'fixture-only'})
                self.assertWithheld(shore)

    def test_malformed_receipt_structure_is_not_ignored(self):
        for receipt in (None, '12/1/1', {'not_tile': '12/1/1'}):
            with self.subTest(receipt=receipt):
                shore = case_shoreline('coast')
                shore['provenance']['tile_receipts'].append(receipt)
                self.assertWithheld(shore)
        for container in (None, {}, '12/1/1', 12):
            with self.subTest(container=container):
                shore = case_shoreline('coast')
                shore['provenance']['tile_receipts'] = container
                self.assertWithheld(shore)

    def test_coordinate_limits_are_inclusive(self):
        # A positive control for both ends of both axes, including zero.
        shore = case_shoreline('coast')
        tiles = ('12/0/4095', '12/4095/0')
        shore['provenance']['tile_receipts'].extend({'tile': tile} for tile in tiles)
        index, _ = lw.build_product(shore, REGION)
        self.assertEqual(index['status'], 'available')
        self.assertTrue(set(tiles) <= index['tiles'].keys())

    def test_unchanged_coast_matches_committed_bytes(self):
        # The existing fixture test compares parsed JSON, not index byte order.
        index, lines = build('coast')
        self.assertEqual(lw._dump({**index, 'fixture': CASES['coast'][1]}),
                         (FIXTURES / 'coast.json').read_bytes())
        self.assertEqual(lw._dump(lines), (FIXTURES / 'coast.lines.json').read_bytes())
