"""The wave 2B catalogue records acquisition, never public-display permission."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Wave2BPrivateSourcesTests(unittest.TestCase):
    def test_all_fifty_archives_stay_restricted_and_unbound(self):
        from skippercast.platform.contracts import load_catalogs
        _, sources = load_catalogs(ROOT)
        rows = [s for s in sources.values() if s.get('acquisition_wave') == 'wave2b']
        self.assertEqual(len(rows), 50)
        self.assertEqual(len({s['archive_url'] for s in rows}), 50)
        self.assertEqual(sum(s['expected_archive_bytes'] for s in rows), 24061938106)
        ids = {s['id'] for s in rows}
        for row in rows:
            with self.subTest(source=row['id']):
                self.assertEqual(row['review_status'], 'restricted')
                self.assertEqual(row['rights']['license'], 'unresolved')
                self.assertEqual(row['usage'], 'private-use only')
                self.assertFalse(row['publication_allowed'])
                self.assertFalse(row['rights']['redistribution_reviewed'])
                self.assertEqual(row['rights']['commercial_use'], 'unknown')
                self.assertTrue(row['archive_url'].startswith('https://data.ngdc.noaa.gov/platforms/ocean/ships/'))
        for path in (ROOT / 'regions').glob('*/region.json'):
            region = json.loads(path.read_text())
            # Exact source IDs anywhere in a region remain forbidden.
            def strings(value):
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    for item in value.values():
                        yield from strings(item)
                elif isinstance(value, list):
                    for item in value:
                        yield from strings(item)
            self.assertFalse(ids.intersection(strings(region)), path)
