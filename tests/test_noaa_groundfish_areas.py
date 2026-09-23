import unittest
from urllib.parse import urlsplit, parse_qs

from scripts.collect_noaa_groundfish_areas import collect, polygon_valid, selected_layers


class FederalAreaSourceTest(unittest.TestCase):
    def test_inventory_requires_current_cordell_gea_and_fishery_layers(self):
        rows = [{'id': i, 'name': f'GEA_Example_{i}'} for i in range(10)]
        rows += [{'id': 18, 'name': 'GEA_Cordell_Bank_20260623'}]
        rows += [{'id': 20 + i, 'name': f'YRCA_Example_{i}'} for i in range(10)]
        rows += [{'id': 31, 'name': 'CCA_Eastern_20231201'},
                 {'id': 32, 'name': 'CCA_Western_20231201'},
                 {'id': 33, 'name': 'CCA_Transit_Corridor_20231201'},
                 {'id': 34, 'name': 'GEA_ALL_20231201'}]
        selected = selected_layers(rows)
        self.assertEqual(len(selected), 23)
        self.assertFalse(any('ALL' in name or 'Transit_Corridor' in name for _, name, _ in selected))
        with self.assertRaisesRegex(ValueError, 'incomplete or revised'):
            selected_layers([row for row in rows if row['id'] != 18])

    def test_polygon_must_be_complete_bounded_wgs84(self):
        good = {'type': 'Polygon', 'coordinates': [[[-123, 38], [-122.9, 38],
                                                   [-122.9, 38.1], [-123, 38]]]}
        self.assertTrue(polygon_valid(good))
        self.assertFalse(polygon_valid({'type': 'Polygon', 'coordinates': [[[-123, 38], [-122.9, 38],
                                                                           [-122.9, 38.1]]] }))
        self.assertFalse(polygon_valid({'type': 'Polygon', 'coordinates': [[[20, 38], [21, 38],
                                                                           [21, 39], [20, 38]]]}))

    def test_collector_rejects_truncated_layer_even_when_geometry_looks_valid(self):
        layers = [{'id': i, 'name': f'GEA_Example_{i}'} for i in range(9)]
        layers += [{'id': 18, 'name': 'GEA_Cordell_Bank_20260623'}]
        layers += [{'id': 20 + i, 'name': f'YRCA_Example_{i}'} for i in range(10)]
        layers += [{'id': 40, 'name': 'CCA_Eastern_20231201'}, {'id': 41, 'name': 'CCA_Western_20231201'}]
        polygon = {'type': 'Polygon', 'coordinates': [[[-123, 38], [-122.9, 38],
                                                      [-122.9, 38.1], [-123, 38]]]}
        def fetch(url):
            if url.endswith('?f=pjson'):
                return {'layers': layers}, 'service-hash'
            ident = int(urlsplit(url).path.split('/')[-2])
            name = next(row['name'] for row in layers if row['id'] == ident)
            category = name.split('_')[0]
            query = parse_qs(urlsplit(url).query)
            if 'returnCountOnly' in query:
                return {'count': 2 if ident == 18 else 1}, 'count-hash'
            return {'type': 'FeatureCollection', 'features': [{
                'type': 'Feature', 'geometry': polygon, 'properties': {
                    'AREA_GROUP': category, 'OBJECTID': 1, 'SITE_NAME': name,
                    'CFR_BOUNDARY_URL': 'https://www.ecfr.gov/current/title-50/section-660.70'}}]}, 'geometry-hash'
        with self.assertRaisesRegex(ValueError, 'Incomplete NOAA geometry'):
            collect(getter=fetch)


if __name__ == '__main__':
    unittest.main()
