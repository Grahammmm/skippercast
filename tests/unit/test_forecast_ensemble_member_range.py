"""A GEFS member wind or gust outside the tile builder's physical range is stored as missing (offline, synthetic grids).

Contract: `fetch_member_step` bounds u10, v10 and gust with `build.RANGES` (inclusive ends), the same
bound the tile builder applies, so a GRIB fill value without a bitmap never becomes a published wind.
"""
from datetime import datetime, timezone
import math
import unittest
from unittest.mock import patch

from skippercast.forecast import ensemble
from tests.unit.test_forecast_ensemble import HAS_ECCODES

try:
    import numpy as np
except ImportError:     # the class below is skipped with the shared optional-decoder reason
    np = None

LATS = np.array([35.0, 35.25]) if np else None
LONS = np.array([-121.0, -120.75]) if np else None
SHAPE = (2, 2)
CYCLE = datetime(2026, 11, 20, 0, tzinfo=timezone.utc)
RANGE_OF = {'UGRD': (0, 99), 'VGRD': (1000, 1099), 'GUST': (2000, 2099)}   # not adjacent: one request each
NAMES = ('u10', 'v10', 'gust')
HAIR = 1e-6


def ranges():
    from skippercast.forecast import build      # imports numpy, so only inside the skip-guarded tests
    return {name: build.RANGES[name] for name in NAMES}


def fetch(u, v, gust):
    """fetch_member_step for one cell with the three decoded grids replaced; returns (values, receipts, missing)."""
    grids = iter([u, v, gust])
    http = lambda url, byte_range=None: b'idx' if byte_range is None else b'msg'  # noqa: E731
    with patch.object(ensemble.fetch, 'parse_gfs_idx', lambda text: []), \
            patch.object(ensemble.fetch, 'select_gfs', lambda rows, var, level: RANGE_OF[var]), \
            patch.object(ensemble, 'split_messages', lambda blob: [blob]), \
            patch.object(ensemble, 'decode_one', lambda blob: (np.full(SHAPE, next(grids)), LATS, LONS)):
        return ensemble.fetch_member_step(CYCLE, 0, 3, [(0, 0)], SHAPE, reference_lats=LATS,
                                          reference_lons=LONS, http=http)


@unittest.skipUnless(HAS_ECCODES, 'Optional GRIB decoder not installed')
class MemberRangeTests(unittest.TestCase):
    def test_ranges_are_the_tile_builders(self):
        # Pins the reference: a changed bound in build.RANGES must be a visible decision here.
        self.assertEqual(ranges(), {'u10': (-100, 100), 'v10': (-100, 100), 'gust': (0, 150)})

    def test_healthy_control_is_unchanged(self):
        # Catches a check that rejects or alters ordinary values (3/4 m/s wind is 5.0 m/s, gust 8).
        values, receipts, missing = fetch(3.0, 4.0, 8.0)
        self.assertEqual(values, {'u10': [3.0], 'v10': [4.0], 'gust': [8.0]})
        self.assertEqual(ensemble.speed(values['u10'][0], values['v10'][0]), 5.0)
        self.assertEqual((missing, [r['field'] for r in receipts]), ([], ['u10', 'v10', 'gust']))

    def test_sentinel_fill_is_missing_not_a_wind(self):
        # Catches publishing a 9.999e20 GRIB fill as a 1.4e21 m/s wind and gust.
        values, receipts, missing = fetch(9.999e20, -9.999e20, 9.999e20)
        self.assertEqual(values, {'u10': [None], 'v10': [None], 'gust': [None]})
        self.assertIsNone(ensemble.speed(values['u10'][0], values['v10'][0]))
        self.assertEqual(len(receipts), 3)      # the file was fetched and receipted; only the cell is missing
        self.assertEqual(missing, [])           # not reported as a missing field

    def test_negative_gust_is_missing(self):
        # Catches a lower bound that is not applied to gust (a gust below 0 m/s is not a gust).
        values, _, _ = fetch(3.0, 4.0, -5.0)
        self.assertEqual(values, {'u10': [3.0], 'v10': [4.0], 'gust': [None]})

    def test_each_field_is_bounded_on_its_own(self):
        # Catches a check applied to one field only (here an out-of-range u10 or v10 beside a healthy rest).
        self.assertEqual(fetch(1e21, 4.0, 8.0)[0], {'u10': [None], 'v10': [4.0], 'gust': [8.0]})
        self.assertEqual(fetch(3.0, -1e21, 8.0)[0], {'u10': [3.0], 'v10': [None], 'gust': [8.0]})

    def test_inclusive_ends_are_kept_and_a_hair_beyond_is_missing(self):
        # Catches an exclusive comparison (< / >) or a swapped bound.
        for name, (low, high) in ranges().items():
            for value, kept in ((low, True), (high, True), (low - HAIR, False), (high + HAIR, False)):
                with self.subTest(field=name, value=value):
                    args = {'u10': 3.0, 'v10': 4.0, 'gust': 8.0}
                    args[name] = value
                    got = fetch(args['u10'], args['v10'], args['gust'])[0][name]
                    self.assertEqual(got, [float(value)] if kept else [None])

    def test_nan_and_inf_stay_missing(self):
        # Catches replacing the finite check with a range check alone (NaN compares False both ways).
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(value=bad):
                self.assertEqual(fetch(bad, bad, bad)[0], {'u10': [None], 'v10': [None], 'gust': [None]})

    def test_out_of_range_cell_does_not_touch_its_neighbour_or_receipts(self):
        # Catches bounding a whole field when one cell is bad, or dropping the receipt of a field with a bad cell.
        grids = iter([np.array([[3.0, 9.999e20], [3.0, 3.0]]), np.full(SHAPE, 4.0), np.array([[8.0, 8.0], [-5.0, 8.0]])])
        http = lambda url, byte_range=None: b'idx' if byte_range is None else b'msg'  # noqa: E731
        with patch.object(ensemble.fetch, 'parse_gfs_idx', lambda text: []), \
                patch.object(ensemble.fetch, 'select_gfs', lambda rows, var, level: RANGE_OF[var]), \
                patch.object(ensemble, 'split_messages', lambda blob: [blob]), \
                patch.object(ensemble, 'decode_one', lambda blob: (next(grids), LATS, LONS)):
            values, receipts, missing = ensemble.fetch_member_step(
                CYCLE, 0, 3, [(0, 0), (0, 1), (1, 0), None], SHAPE, reference_lats=LATS,
                reference_lons=LONS, http=http)
        self.assertEqual(values, {'u10': [3.0, None, 3.0, None], 'v10': [4.0, 4.0, 4.0, None],
                                  'gust': [8.0, 8.0, None, None]})
        self.assertEqual(([r['field'] for r in receipts], missing), (['u10', 'v10', 'gust'], []))


if __name__ == '__main__':
    unittest.main()
