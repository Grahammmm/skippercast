"""FSC-01: the committed Morro Bay daily-evidence snapshot carries no Open-Meteo data.

``dist/data/daily-evidence.json`` is a byte copy of one published ``data``-branch
``latest.json`` (register B1). These checks keep a refresh from bringing an
Open-Meteo response, an uncalibrated score or an uncleared runtime host back in.
"""
import copy
import json
import unittest

from skippercast.pipeline import collect
from tests._support import ROOT
from tests.contract.test_commercial_sources import catalog, commercial_use, runtime_sources

SNAPSHOT = ROOT / 'dist/data/daily-evidence.json'


def strings(value):
    """Every key and string value in a JSON document, walked recursively."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def problems(snapshot, sources):
    """Reasons the snapshot may not ship; empty when it is clean."""
    found = [f'Open-Meteo text: {text[:80]}' for text in strings(snapshot) if 'open-meteo' in text.lower()]
    for ident, source in snapshot['sources'].items():
        for host in sorted(runtime_sources(source.get('url') or '')):
            if commercial_use(host, sources) != 'allowed':
                found.append(f'host: {ident} -> {host}')
    return found


class DailyEvidenceSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot, cls.sources = json.loads(SNAPSHOT.read_bytes()), catalog()

    def test_snapshot_is_a_valid_published_feed_without_scores(self):
        collect.validate(self.snapshot)
        self.assertTrue(self.snapshot['run_id'])
        self.assertIsInstance(self.snapshot['published_at'], str)
        self.assertIsNone(self.snapshot.get('catch_probability'))
        self.assertIsNone(self.snapshot.get('bite_score'))

    def test_no_open_meteo_text_and_every_source_host_cleared(self):
        self.assertEqual(problems(self.snapshot, self.sources), [])

    def test_injected_open_meteo_or_uncleared_host_is_rejected(self):
        first = next(iter(self.snapshot['sources']))
        for url, kinds in (('https://api.open-meteo.com/v1/forecast?models=gfs_global', {'Open-Meteo text', 'host'}),
                           # The runtime-host patterns are case-sensitive; the text walk still catches it.
                           ('https://marine-api.Open-Meteo.com/v1/marine', {'Open-Meteo text'}),
                           ('https://tile.openstreetmap.org/1/2/3.png', {'host'})):
            with self.subTest(url=url):
                crafted = copy.deepcopy(self.snapshot)
                crafted['sources'][first]['url'] = url
                self.assertEqual({p.split(':', 1)[0] for p in problems(crafted, self.sources)}, kinds)
        crafted = {**self.snapshot, 'injected': {'Data via OPEN-METEO': 1}}
        self.assertEqual(problems(crafted, self.sources), ['Open-Meteo text: Data via OPEN-METEO'])


if __name__ == '__main__':
    unittest.main()
