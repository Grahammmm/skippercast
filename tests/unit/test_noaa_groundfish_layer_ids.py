import unittest
from datetime import datetime, timezone

from scripts import collect_noaa_groundfish_areas as noaa
from tests.unit.test_noaa_groundfish_shapes import LAYERS, fake

INVENTORY = r'^NOAA federal area layer inventory incomplete or revised$'
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def with_ids(**changes):
    """Copy of LAYERS where the layer named by key gets the given id."""
    return [dict(row, id=changes.get(row['name'], row['id'])) for row in LAYERS]


class DuplicateSelectedLayerIdTest(unittest.TestCase):
    def test_selected_layers_rejects_distinct_names_with_same_id(self):
        layers = with_ids(GEA_Example_1=0)
        self.assertEqual(len({row['name'] for row in layers}), len(layers))
        with self.assertRaisesRegex(ValueError, INVENTORY):
            noaa.selected_layers(layers)

    def test_collect_rejects_duplicate_ids_before_layer_requests(self):
        calls = []
        inner = fake(layers=with_ids(GEA_Example_1=0))

        def getter(url):
            calls.append(url)
            return inner(url)

        with self.assertRaisesRegex(ValueError, INVENTORY):
            noaa.collect(getter=getter, now=NOW)
        self.assertEqual(calls, [noaa.SERVICE + '?f=pjson'])

    def test_selected_layers_rejects_cross_category_id_collision(self):
        with self.assertRaisesRegex(ValueError, INVENTORY):
            noaa.selected_layers(with_ids(CCA_Eastern_20231201=0))

    def test_distinct_selected_ids_preserve_collection_and_order(self):
        data = noaa.collect(getter=fake(), now=NOW)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual([s['layer_id'] for s in data['source_layers']], [row['id'] for row in LAYERS])
        ids = [f['properties']['id'] for f in data['features']]
        self.assertEqual(len(set(ids)), 22)
        self.assertEqual(ids, [f'noaa-gca-{row["id"]}-1' for row in LAYERS])
        edge = LAYERS + [{'id': 10000, 'name': 'GEA_Edge'}]
        self.assertEqual(noaa.selected_layers(edge)[-1], (10000, 'GEA_Edge', 'GEA'))
        self.assertEqual(noaa.selected_layers(LAYERS)[0], (0, 'GEA_Example_0', 'GEA'))

    def test_ignored_layer_ids_do_not_participate_in_uniqueness(self):
        ignored = [{'id': 0, 'name': 'GEA_ALL_20231201'}, {'id': 0, 'name': 'CCA_Transit_Corridor'},
                   {'id': 0, 'name': 'Unrelated'}, {'id': 'x', 'name': 'YRCA_All_20231201'}]
        self.assertEqual(noaa.selected_layers(LAYERS + ignored), noaa.selected_layers(LAYERS))
        with self.assertRaisesRegex(ValueError, INVENTORY):
            noaa.selected_layers(LAYERS + [{'id': 99, 'name': 'GEA_Example_0'}])


if __name__ == '__main__':
    unittest.main()
