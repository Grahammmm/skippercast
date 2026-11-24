"""Source ranking and planning-cell IDs in seafloor coverage never crash or mislead.

Contract: `priority` always yields a sortable tuple (finest resolution, newest
year, source id); an unknown or non-numeric resolution ranks behind every
numeric one; a missing or non-integer year counts as -1. `cell_geometry`
refuses any malformed planning-cell ID with one named ValueError.
"""
import math
import unittest

from skippercast.seafloor.coverage import cell_geometry, priority

CELL_ERROR = 'Planning cell ID must be 3310:<x>:<y> with integer x and y'


def row(ident, resolution, **extra):
    return dict({'id': ident, 'resolution_m': resolution}, **extra)


class CoveragePriorityOrderTests(unittest.TestCase):
    def test_numeric_priority_is_unchanged(self):
        # Catches a rewrite that alters the key shape for healthy rows.
        self.assertEqual(priority(row('a', 2, year=2010)), (2, -2010, 'a'))

    def test_mixed_list_sorts_unknown_resolution_last(self):
        # Catches unknown ranking first (inf negated / wrong tuple order) or a
        # str-vs-int TypeError that aborts classify_cells.
        rows = [
            row('unknown-new', 'unknown', year=2020),
            row('coarse', 10, year=2020),
            row('fine-old', 2, year=2005),
            row('fine-new', 2, year=2015),
            row('unknown-old', 'unknown', year=2001),
            row('yearless-fine', 2),
            row('none-res', None, year=2022),
        ]
        ordered = [r['id'] for r in sorted(rows, key=priority)]
        self.assertEqual(ordered, [
            'fine-new', 'fine-old', 'yearless-fine', 'coarse',
            'none-res', 'unknown-new', 'unknown-old'])

    def test_unknown_resolution_key_is_infinite_not_finest(self):
        # Catches an unknown resolution being treated as 0 or -inf.
        for bad in ('unknown', None, '', 'n/a', float('nan'), True):
            with self.subTest(resolution=bad):
                self.assertEqual(priority(row('x', bad, year=2000))[0], math.inf)

    def test_all_unknown_still_sorts_by_year_then_id(self):
        # Catches silent string ranking when every row is unknown.
        rows = [row('b', 'unknown', year=2000), row('a', 'unknown', year=2000),
                row('c', 'unknown', year=2010)]
        self.assertEqual([r['id'] for r in sorted(rows, key=priority)], ['c', 'a', 'b'])

    def test_missing_or_non_integer_year_counts_as_minus_one(self):
        # Catches KeyError on a yearless row and a string year breaking the sort.
        self.assertEqual(priority(row('a', 2)), (2, 1, 'a'))
        self.assertEqual(priority(row('a', 2, year='2010')), (2, 1, 'a'))
        self.assertEqual(priority(row('a', 2, year=None)), (2, 1, 'a'))
        self.assertEqual(priority(row('a', 2, year=1999)), (2, -1999, 'a'))

    def test_yearless_row_ranks_by_resolution_before_year(self):
        # Catches a yearless row jumping ahead of, or behind, rows of other resolution.
        rows = [row('coarse-new', 5, year=2020), row('fine-yearless', 1),
                row('fine-dated', 1, year=2015)]
        self.assertEqual([r['id'] for r in sorted(rows, key=priority)],
                         ['fine-dated', 'fine-yearless', 'coarse-new'])

    def test_source_id_is_final_tiebreak(self):
        rows = [row('z', 2, year=2010), row('a', 2, year=2010)]
        self.assertEqual([r['id'] for r in sorted(rows, key=priority)], ['a', 'z'])

    def test_coarse_profile_still_overrides_row_resolution(self):
        # Existing contract: a mixed grid ranks at its coarser resolution.
        r = row('mixed', 2, year=2008, resolution_profile={'coarse_resolution_m': 5})
        self.assertEqual(priority(r)[0], 5)

    def test_healthy_cell_geometry(self):
        # Control: a valid ID still maps to its 250 m square.
        self.assertEqual(cell_geometry({'id': '3310:2:3'}).bounds, (500.0, 750.0, 750.0, 1000.0))

    def test_malformed_cell_ids_raise_one_named_error(self):
        # Catches bare unpack/int() ValueErrors and AttributeError/KeyError on a missing ID.
        for bad in ('3310:1', '3310:1:2:3', '3310:1.5:2', '3310:a:2', '3310::2', '',
                    'x', None, 3310):
            with self.subTest(cell_id=bad):
                with self.assertRaises(ValueError) as caught:
                    cell_geometry({'id': bad})
                self.assertEqual(str(caught.exception), CELL_ERROR)
        with self.assertRaises(ValueError) as caught:
            cell_geometry({})
        self.assertEqual(str(caught.exception), CELL_ERROR)

    def test_wrong_prefix_keeps_its_own_refusal(self):
        with self.assertRaisesRegex(ValueError, 'must use EPSG:3310'):
            cell_geometry({'id': '4326:1:2'})


if __name__ == '__main__':
    unittest.main()
