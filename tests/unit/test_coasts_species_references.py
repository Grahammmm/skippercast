"""RF1940-1: compile_coasts refuses unknown source-species references instead of dropping them."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skippercast.platform import coasts
from skippercast.platform.contracts import REPO

CATALOG = ('coasts.json', 'targets.json', 'species.json', 'data-needs.json', 'sources.json')


class SpeciesReferenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'catalog').mkdir()
        for name in CATALOG:
            shutil.copy(REPO / 'catalog' / name, self.root / 'catalog' / name)
        self.directory = json.loads((self.root / 'catalog/coasts.json').read_text())
        for ident in {p for r in self.directory['regions'] for p in r['packages']}:
            (self.root / 'regions' / ident).mkdir(parents=True)
            shutil.copy(REPO / 'regions' / ident / 'region.json', self.root / 'regions' / ident / 'region.json')
        self.targets = json.loads((self.root / 'catalog/targets.json').read_text())
        self.species = [s['id'] for s in json.loads((self.root / 'catalog/species.json').read_text())['species']]
        self.out = self.root / 'dist/data/coasts.json'

    def compile_with(self, ident, **fields):
        """Compile with target ident's fields replaced in the temp catalog."""
        self.targets['targets'][ident] = {**self.targets['targets'][ident], **fields}
        (self.root / 'catalog/targets.json').write_text(json.dumps(self.targets))
        return coasts.compile_coasts(self.root)

    def used(self, key='targets', region=0):
        return self.directory['regions'][region][key][0]

    def test_unknown_species_refuses_before_output(self):
        ident = self.used()
        known = self.species[0]
        cases = (['typo-fish'], [known, 'typo-fish'], ['typo-fish', known])
        for refs in cases:
            for extra in ({}, {'note': 'explicit note'}, {'source_url': 'https://example.org/x'},
                          {'note': 'n', 'source_url': 'https://example.org/x'}):
                with self.subTest(refs=refs, extra=extra), patch.object(coasts, 'atomic_json') as writer:
                    with self.assertRaises(ValueError) as caught:
                        self.compile_with(ident, source_species=refs, **extra)
                    self.assertEqual(str(caught.exception), f'Unknown coastal target source species: {ident} source_species')
                    self.assertNotIn('typo-fish', str(caught.exception))
                    writer.assert_not_called()

    def test_watch_reference_and_late_region_refuse_without_write(self):
        last = len(self.directory['regions']) - 1
        ident = self.used('watch', last)
        self.out.parent.mkdir(parents=True)
        self.out.write_text('sentinel')
        with self.assertRaises(ValueError):
            self.compile_with(ident, source_species=['typo-fish'])
        self.assertEqual(self.out.read_text(), 'sentinel')
        self.assertEqual(sorted(p.name for p in self.out.parent.iterdir()), ['coasts.json'])

    def test_non_string_reference_is_controlled(self):
        ident = self.used()
        for bad in (None, True, 7, ['x'], {'id': 'x'}):
            with self.subTest(bad=bad), patch.object(coasts, 'atomic_json') as writer:
                with self.assertRaises(ValueError):
                    self.compile_with(ident, source_species=[bad])
                writer.assert_not_called()

    def test_valid_species_projection_control(self):
        ident = self.used()
        by_id = {s['id']: s for s in json.loads((REPO / 'catalog/species.json').read_text())['species']}
        a, b = self.species[0], self.species[1]
        first = by_id[a]['claims'][0]
        out = self.compile_with(ident, source_species=[a, b, a], note='')
        option = next(t for r in out['regions'] for t in r['target_options'] + r['watch_options'] if t['id'] == ident)
        self.assertEqual(option['note'], ' '.join(by_id[s]['claims'][0]['claim'] for s in (a, b, a)))
        self.assertEqual(option['sources'], list(dict.fromkeys(c['source_url'] for s in (a, b, a) for c in by_id[s]['claims'])))
        self.assertIn(first['source_url'], option['sources'])
        out = self.compile_with(ident, source_species=[a], note='mine', source_url='https://example.org/x')
        option = next(t for r in out['regions'] for t in r['target_options'] + r['watch_options'] if t['id'] == ident)
        self.assertEqual((option['note'], option['sources']), ('mine', ['https://example.org/x']))
        out = self.compile_with(ident, source_species=[], note='n', source_url='https://example.org/y')
        option = next(t for r in out['regions'] for t in r['target_options'] + r['watch_options'] if t['id'] == ident)
        self.assertEqual((option['note'], option['sources']), ('n', ['https://example.org/y']))
        self.assertTrue(self.out.is_file())


if __name__ == '__main__':
    unittest.main()
