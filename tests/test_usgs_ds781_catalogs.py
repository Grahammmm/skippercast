"""Official catalog links remain research leads, including a shared-DOI mismatch."""
import json
from pathlib import Path
import unittest

from scripts.discover_usgs_ds781_catalogs import products, release_products, signature


ROOT = Path(__file__).resolve().parents[1]


class UsgsDs781CatalogTests(unittest.TestCase):
    def test_inventory_keeps_links_and_scope_distinct(self):
        data = json.loads((ROOT / 'catalog/usgs-ds781-source-leads.json').read_text())
        self.assertEqual(len(data['map_areas']), 39)
        self.assertGreaterEqual(sum(len(area.get('products', [])) for area in data['map_areas']), 200)
        by_name = {area['name']: area for area in data['map_areas']}
        self.assertEqual(by_name['Offshore of Eureka']['priority_product_status'], 'index-link-mismatch')
        self.assertEqual(by_name['Offshore of Eureka']['products'], [])
        self.assertEqual(by_name['Offshore of Arcata']['catalog_url'],
                         by_name['Offshore of Eureka']['catalog_url'])
        self.assertTrue(any(p['kind'] == 'seafloor-character'
                            for p in by_name['Offshore of Arcata']['products']))
        for area in data['map_areas']:
            self.assertTrue(area['planning_sector_ids'])
            self.assertNotIn('fishing_target', area)

    def test_statewide_video_link_is_not_local_habitat(self):
        page = b'''<tr><td>Habitat, Offshore Bodega Head</td>
        <td><a href="data/Habitat_Bodega.zip">data</a></td></tr>
        <tr><td>Visual observations of benthic habitat from video USGS Cruise</td>
        <td><a href="/ds/781/video_observations/data/cruise.zip">data</a></td></tr>'''
        found = products(page, 'https://pubs.usgs.gov/ds/781/OffshoreBodegaHead/catalog.html')
        self.assertEqual([item['archive_url'] for item in found],
                         ['https://pubs.usgs.gov/ds/781/OffshoreBodegaHead/data/Habitat_Bodega.zip'])

    def test_shared_release_filters_other_area(self):
        page = b'''<a href="/data-releases/media/Bathymetry_OffshoreArcata.zip">A</a>
        <a href="/data-releases/media/SeafloorCharacter_OffshoreEureka.zip">E</a>'''
        found = release_products(page, 'https://cmgds.marine.usgs.gov/data-releases/datarelease/demo/',
                                 'Offshore of Arcata', True)
        self.assertEqual(len(found), 1)
        self.assertIn('Arcata', found[0]['archive_url'])

    def test_signature_ignores_page_bytes_but_detects_product_change(self):
        data = json.loads((ROOT / 'catalog/usgs-ds781-source-leads.json').read_text())
        changed = json.loads(json.dumps(data))
        changed['index_sha256'] = 'presentation-changed'
        changed['map_areas'][0]['catalog_sha256'] = 'presentation-changed'
        changed['retrieved_at'] = 'later'
        self.assertEqual(signature(data), signature(changed))
        changed['map_areas'][0]['products'].append({'archive_url': 'https://pubs.usgs.gov/new.zip'})
        self.assertNotEqual(signature(data), signature(changed))


if __name__ == '__main__':
    unittest.main()
