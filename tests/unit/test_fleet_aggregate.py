"""Per-kind aggregate resolution (N6, docs/plans/charter-fleet/graph.md; design.md section 11).

``thresholds.aggregate.resolution_by_kind`` gives a fishing kind a coarser grid
(troll-pelagic at 3 km in CA) than ``resolution_m``. Events are synthetic: made-up
vessel ids and positions in open ocean, thresholds from the committed
``regions/CA/fleet.json``.
"""
import json
import math
import unittest

from skippercast.fleet.ais.aggregate import AggregateParams, compute, grid_cell
from tests.unit.test_fleet_classify import T0, region_thresholds
from tests.unit.test_fleet_events import HOUR, event, metres, params

LAT, LON = 34.0, -119.5
NOW = T0 + 10 * HOUR


class ResolutionByKind(unittest.TestCase):
    def test_ca_config_bins_pelagic_at_3_km_and_the_rest_at_1_km(self):
        raw = region_thresholds()['aggregate']
        self.assertEqual(raw['resolution_m'], 1000)
        self.assertEqual(raw['resolution_by_kind'], {'troll-pelagic': 3000})
        p = AggregateParams.from_mapping(raw)
        self.assertEqual({k: p.resolution_for(k) for k in ('drift-anchor', 'troll-slow', 'troll-pelagic')},
                         {'drift-anchor': 1000, 'troll-slow': 1000, 'troll-pelagic': 3000})

    def test_each_kind_is_binned_at_its_own_edge(self):
        events = [event('v1', LAT, LON, kind='drift-anchor'), event('v2', LAT, LON, kind='troll-slow', start=T0 + HOUR),
                  event('v3', LAT, LON, kind='troll-pelagic', start=T0 + 2 * HOUR)]
        cells = {c.kind: c for c in compute(events, params(), now_ms=NOW) if c.season_part is None}
        self.assertEqual(cells['drift-anchor'].cell_id, grid_cell(LAT, LON, 1000)[0])
        self.assertEqual(cells['troll-slow'].cell_id, grid_cell(LAT, LON, 1000)[0])
        pelagic_id, lat, lon = grid_cell(LAT, LON, 3000)
        self.assertEqual(cells['troll-pelagic'].cell_id, pelagic_id)
        self.assertRegex(pelagic_id, r'^g3000:-?\d+:-?\d+$')
        self.assertEqual((cells['troll-pelagic'].lat, cells['troll-pelagic'].lon), (round(lat, 6), round(lon, 6)))
        self.assertLess(metres((LAT, LON), (lat, lon)), 3000 / math.sqrt(2) + 1)

    def test_pelagic_events_a_few_km_apart_share_one_coarse_cell(self):
        # Two pelagic stops 1.2 km apart inside one 3 km cell: one cell of two vessels, where 1 km would split them.
        centre_id, lat, lon = grid_cell(LAT, LON, 3000)
        a, b = (lat - 0.0054, lon), (lat + 0.0054, lon)
        events = [event('v1', *a, kind='troll-pelagic'), event('v2', *b, kind='troll-pelagic', start=T0 + HOUR)]
        coarse = [c for c in compute(events, params(), now_ms=NOW) if c.season_part is None]
        self.assertEqual([(c.cell_id, c.vessels_n, c.events_n) for c in coarse], [(centre_id, 2, 2)])
        fine = [c for c in compute(events, params(resolution_by_kind={}), now_ms=NOW) if c.season_part is None]
        self.assertEqual(len(fine), 2)
        self.assertTrue(all(c.cell_id.startswith('g1000:') for c in fine))

    def test_the_map_is_in_params_json_and_changes_every_id(self):
        events = [event('v1', LAT, LON, kind='drift-anchor'), event('v2', LAT, LON, kind='troll-pelagic')]
        with_map, without = params(), params(resolution_by_kind={})
        self.assertEqual(json.loads(with_map.params_json)['resolution_by_kind'], {'troll-pelagic': 3000})
        self.assertNotEqual(with_map.params_hash, without.params_hash)
        new, old = compute(events, with_map, now_ms=NOW), compute(events, without, now_ms=NOW)
        # Even the drift cell, binned the same, gets a new id: the processor's diff deletes every old one.
        self.assertTrue({c.id for c in new}.isdisjoint({c.id for c in old}))
        self.assertEqual({c.cell_id for c in new if c.kind == 'drift-anchor'},
                         {c.cell_id for c in old if c.kind == 'drift-anchor'})

    def test_bad_maps_are_refused(self):
        for bad, message in (({'troll-pelagic': 2500}, 'whole multiple'), ({'troll-pelagic': 500}, 'whole multiple'),
                             ({'transit': 3000}, 'not a fishing kind'), ({'troll-pelagic': None}, 'must be a number'),
                             ({'troll-pelagic': True}, 'must be a number'), ([3000], 'must be an object')):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, message):
                params(resolution_by_kind=bad)
        self.assertEqual(params(resolution_by_kind={'troll-pelagic': 1000}).resolution_for('troll-pelagic'), 1000)
        self.assertEqual(params(resolution_m=500).resolution_for('troll-pelagic'), 3000)   # 6 x 500
        self.assertEqual(params(resolution_by_kind={}).resolution_for('troll-pelagic'), 1000)


if __name__ == '__main__':
    unittest.main()
