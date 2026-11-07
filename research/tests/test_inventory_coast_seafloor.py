"""COAST-INVENTORY-1: tier, extent and coverage rules of research/scripts/inventory_coast_seafloor.py."""
import unittest

from research.scripts.inventory_coast_seafloor import (
    albers_3310_to_lonlat, classify_shallow, ledger_tier_proxy, sector_of_bbox)


def grid(res, depth, family='CSUMB', extent=None, rng=None):
    return {'family': family, 'id': f'{family}-{res}-{depth}-{rng}', 'name': f'{family} {res}', 'resolution_m': res,
            'resolution_range_m': rng, 'depth': depth, 'extent_km2': extent}


class ShallowTierTest(unittest.TestCase):
    def test_mixed_2m_and_5m_confirmed_takes_finest(self):
        out = classify_shallow([grid(5.0, 'confirmed'), grid(2.0, 'confirmed')])
        self.assertEqual(out['tier'], '2 m')
        self.assertEqual(out['best_confirmed_resolution_m'], 2.0)
        self.assertEqual([e['resolution_m'] for e in out['tier_sources']], [2.0])

    def test_unknown_depth_grid_never_sets_the_tier(self):
        out = classify_shallow([grid(2.0, 'unrecorded', 'USGS DS781'), grid(5.0, 'confirmed')])
        self.assertEqual(out['tier'], '5 m')
        self.assertEqual(out['finest_any_depth_m'], 2.0)
        self.assertEqual([e['family'] for e in out['finer_grids_depth_unrecorded']], ['USGS DS781'])
        alone = classify_shallow([grid(2.0, 'unrecorded', 'USGS DS781')])
        self.assertEqual(alone['tier'], 'none')
        self.assertEqual(alone['finest_any_depth_m'], 2.0)

    def test_zero_shallow_pixels_is_not_shallow_evidence(self):
        self.assertEqual(classify_shallow([grid(2.0, 'none-shallow')])['tier'], 'none')

    def test_small_fine_patch_still_sets_the_tier(self):
        # No area threshold: a 0.03 km2 confirmed 1 m patch beats 100 km2 at 5 m; extent is reported apart.
        out = classify_shallow([grid(1.0, 'confirmed', 'NOAA BAG', 0.03), grid(5.0, 'confirmed', 'NOAA BAG', 100.0)])
        self.assertEqual(out['tier'], '2 m')
        self.assertEqual(out['best_confirmed_resolution_m'], 1.0)

    def test_vr_range_is_a_floor_and_marked_uncertain(self):
        out = classify_shallow([grid(None, 'confirmed', 'NOAA VR BAG', rng=(1.0, 4.0))])
        self.assertEqual(out['tier'], '5 m')
        self.assertTrue(out['tier_uncertain'])
        self.assertIsNone(out['best_confirmed_resolution_m'])
        firm = classify_shallow([grid(None, 'confirmed', 'NOAA VR BAG', rng=(1.0, 4.0)), grid(2.0, 'confirmed', 'NOAA BAG')])
        self.assertEqual(firm['tier'], '2 m')
        self.assertFalse(firm['tier_uncertain'])


class LedgerProxyTest(unittest.TestCase):
    def test_mixed_resolution_reaches_give_a_range_and_crossing_reach_is_left_out(self):
        reaches = [
            {'band_km2': 20, 'selected_km2': 10, 'resolutions_m': [2.0, 1.0], 'crosses': False},
            {'band_km2': 10, 'selected_km2': 6, 'resolutions_m': [2.0, 5.0], 'crosses': False},
            {'band_km2': 10, 'selected_km2': 8, 'resolutions_m': [5.0], 'crosses': False},
            {'band_km2': 5, 'selected_km2': 5, 'resolutions_m': [2.0], 'crosses': True},
        ]
        p = ledger_tier_proxy(reaches, 2.0)
        assert p is not None
        self.assertEqual((p['low_pct'], p['high_pct']), (25.0, 40.0))
        self.assertEqual((p['band_km2'], p['excluded_crossing_band_km2'], p['reaches_crossing']), (40, 5, 1))
        p5 = ledger_tier_proxy(reaches, 5.0)
        assert p5 is not None
        self.assertEqual((p5['low_pct'], p5['high_pct']), (60.0, 60.0))

    def test_only_crossing_reaches_gives_no_proxy(self):
        self.assertIsNone(ledger_tier_proxy([{'band_km2': 5, 'selected_km2': 5, 'resolutions_m': [2.0], 'crosses': True}], 2.0))


class GeometryTest(unittest.TestCase):
    def test_bbox_crossing_a_sector_line_touches_both_boxes(self):
        bounds = {'north': [-123.0, 36.0, -121.0, 37.0], 'south': [-123.0, 35.0, -121.0, 36.0]}
        self.assertEqual(sector_of_bbox([-122.5, 35.9, -122.0, 36.3], bounds), ('north', ['north', 'south']))
        self.assertEqual(sector_of_bbox([-122.5, 36.1, -122.0, 36.3], bounds), ('north', ['north']))

    def test_inverse_california_albers(self):
        lon, lat = albers_3310_to_lonlat(-150000.0, -300000.0)
        self.assertAlmostEqual(lon, -121.651032067, places=6)
        self.assertAlmostEqual(lat, 35.305120961, places=6)


if __name__ == '__main__':
    unittest.main()
