"""build_primary_strategies validates the catalog and every published region before writing any packet."""
import json
import tempfile
import unittest
from pathlib import Path

from research.scripts import build_primary_strategies as bps


def strategy(**extra):
    base = {'priority': 'p', 'find': ['f1', 'f2'], 'rig': 'r', 'steps': ['s1', 's2', 's3'], 'adjust': 'a'}
    return {**base, **extra}


class BuildPrimaryStrategiesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.species = {'x': strategy(), 'y': strategy(method_sources=[{'title': 't', 'url': 'https://e.org'}])}
        self.regions = {'a': {'id': 'a', 'status': 'published', 'species': ['x']},
                        'b': {'id': 'b', 'status': 'published', 'species': ['x', 'y']}}

    def write_tree(self, catalog=None):
        catalog = catalog or {'schema_version': 1, 'reviewed_at': '2026-11-02', 'scope': 'boat', 'species': self.species}
        (self.root / 'catalog').mkdir(exist_ok=True)
        (self.root / 'catalog/primary-strategies.json').write_text(json.dumps(catalog))
        for region_id, region in self.regions.items():
            (self.root / 'regions' / region_id).mkdir(parents=True, exist_ok=True)
            (self.root / 'regions' / region_id / 'region.json').write_text(json.dumps(region))

    def target(self, region_id):
        return self.root / 'dist/regions' / region_id / 'strategies.json'

    def assert_refused(self, message):
        self.write_tree()
        with self.assertRaises(ValueError) as caught:
            bps.build(self.root)
        self.assertEqual(str(caught.exception), message)
        self.assertEqual(list(self.root.glob('dist/regions/*/*')), [])

    def test_later_region_missing_methods_writes_nothing(self):
        self.regions['b']['species'] = ['x', 'z']
        self.assert_refused("b lacks starter methods for ['z']")

    def test_pre_existing_packet_keeps_its_bytes_when_a_later_region_fails(self):
        self.regions['b']['species'] = ['x', 'z']
        self.write_tree()
        self.target('a').parent.mkdir(parents=True)
        self.target('a').write_bytes(b'old\n')
        with self.assertRaisesRegex(ValueError, r"^b lacks starter methods for \['z'\]$"):
            bps.build(self.root)
        self.assertEqual(self.target('a').read_bytes(), b'old\n')
        self.assertFalse(self.target('a').with_suffix('.json.tmp').exists())

    def test_non_object_strategy_is_named(self):
        self.species['y'] = 'text'
        self.assert_refused('Incomplete strategy: y')

    def test_string_find_with_list_steps_is_named(self):
        self.species['y'] = strategy(find='abc')
        self.assert_refused('Empty strategy step: y')

    def test_string_steps_with_list_find_is_named(self):
        self.species['x'] = strategy(steps='abcd')
        self.assert_refused('Empty strategy step: x')

    def test_non_object_method_source_is_named(self):
        self.species['y'] = strategy(method_sources=['https://x'])
        self.assert_refused('Invalid method source: y')

    def test_non_list_method_sources_is_named(self):
        self.species['y'] = strategy(method_sources={'title': 't', 'url': 'https://e.org'})
        self.assert_refused('Invalid method source: y')

    def test_non_string_method_url_is_named(self):
        self.species['y'] = strategy(method_sources=[{'title': 't', 'url': 5}])
        self.assert_refused('Invalid method source: y')

    def test_species_list_in_catalog_is_invalid(self):
        self.write_tree({'schema_version': 1, 'reviewed_at': '2026-11-02', 'scope': 'boat', 'species': []})
        with self.assertRaisesRegex(ValueError, '^Invalid strategy catalog$'):
            bps.build(self.root)
        self.assertFalse((self.root / 'dist').exists())

    def test_region_species_not_a_list_of_strings_is_named(self):
        for bad in ('x', ['x', 5], None):
            with self.subTest(bad=bad):
                self.regions['b']['species'] = bad
                self.assert_refused('b species list invalid')

    def test_draft_region_with_missing_methods_is_skipped(self):
        self.regions['c'] = {'id': 'c', 'status': 'draft', 'species': ['nope']}
        self.write_tree()
        self.assertEqual(bps.build(self.root), ['dist/regions/a/strategies.json', 'dist/regions/b/strategies.json'])
        self.assertFalse(self.target('c').parent.exists())

    def test_clean_tree_writes_both_packets_and_no_temp_files(self):
        self.write_tree()
        written = bps.build(self.root)
        self.assertEqual(written, ['dist/regions/a/strategies.json', 'dist/regions/b/strategies.json'])
        self.assertEqual(sorted(p.name for p in self.root.glob('dist/regions/*/*')), ['strategies.json'] * 2)
        packet = json.loads(self.target('b').read_text())
        self.assertEqual(packet['region_id'], 'b')
        self.assertEqual(packet['strategies'], {'x': self.species['x'], 'y': self.species['y']})
        self.assertTrue(self.target('a').read_text().endswith('}\n'))


if __name__ == '__main__':
    unittest.main()
