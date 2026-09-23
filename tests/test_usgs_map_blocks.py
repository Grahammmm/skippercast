import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location('map_blocks', Path(__file__).resolve().parents[1] / 'scripts' / 'discover_usgs_map_blocks.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class UsgsMapBlockTests(unittest.TestCase):
    def test_extracts_only_original_reviewable_products(self):
        index = b'<a href="OffshoreX/data_catalog_OffshoreX.html">X</a><a href="https://bad.example/data_catalog_fake.html">bad</a>'
        self.assertEqual(mod.catalog_urls(index), ['https://pubs.usgs.gov/ds/781/OffshoreX/data_catalog_OffshoreX.html'])
        html = b'''<table><tr><td>Bathymetry (2m/pixel), offshore X</td><td><a href="/ds/781/OffshoreX/metadata/Bathymetry_X.xml">xml</a></td><td><a href="/ds/781/OffshoreX/data/Bathymetry_X.zip">zip</a></td><td></td><td></td></tr>
        <tr><td>Seafloor Character (2m/pixel), offshore X</td><td><a href="/ds/781/OffshoreX/metadata/SeafloorCharacter_X.xml">xml</a></td><td><a href="/ds/781/OffshoreX/data/SeafloorCharacter_X.zip">zip</a></td><td></td><td></td></tr></table>'''
        row = mod.inspect_catalog('https://pubs.usgs.gov/ds/781/OffshoreX/data_catalog_OffshoreX.html', html, now=datetime(2026, 9, 23, tzinfo=timezone.utc))
        self.assertEqual(set(row['products']), {'bathymetry', 'seafloor_character'})
        self.assertEqual(row['status'], 'ok')

    def test_no_third_party_url(self):
        self.assertFalse(mod.approved('https://example.com/ds/781/OffshoreX'))
        self.assertFalse(mod.approved('http://pubs.usgs.gov/ds/781/OffshoreX'))

    def test_failed_catalog_is_visible_and_retains_review_history(self):
        index = b'<a href="OffshoreX/data_catalog_OffshoreX.html">X</a>'
        def fetcher(url):
            if url == mod.INDEX:
                return index
            raise OSError('offline')
        result = mod.discover(now=datetime(2026, 9, 23, tzinfo=timezone.utc), fetcher=fetcher)
        self.assertEqual(result['health']['status'], 'degraded')
        self.assertEqual(result['blocks'][0]['status'], 'failed')
        self.assertEqual(result['bathymetry_blocks'], 0)


if __name__ == '__main__':
    unittest.main()
