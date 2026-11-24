"""resolve_bindings states what is missing instead of raising a bare KeyError.

Contract: the reviewed substrate rules join the survey manifest by source ID;
a malformed rules file or a catalog row missing from the full manifest is a
named ValueError, while the scoped path and held/withdrawn rows still skip.
In-memory fixtures only: no raster, no network.
"""
from copy import deepcopy
import unittest

from skippercast.seafloor.substrate import resolve_bindings


def rules():
    return {'substrate_bindings': [{
        'source_id': 's', 'source_sha256': 'h', 'review_status': 'reviewed',
        'metadata_sha256': 'a' * 64, 'metadata_url': 'https://example.org/m',
        'classes': {'1': {'normalized_code': 1}}, 'depth_source_ids': ['d']}]}


def manifest(status='usable'):
    return {'surveys': [{'id': 's', 'status': status, 'kind': 'substrate',
                         'format': 'usgs-geotiff', 'sha256': 'h',
                         'license': 'public-domain-us-gov'}]}


class SubstrateBindingRefusalTests(unittest.TestCase):
    def test_healthy_rules_resolve_unchanged(self):
        # Protects the output shape: a refusal rewrite that reshapes the
        # result would break every reach run.
        result = resolve_bindings(rules(), manifest())
        self.assertEqual(sorted(result), ['d'])
        self.assertEqual(result['d']['binding'], rules()['substrate_bindings'][0])
        self.assertEqual(result['d']['row'], manifest()['surveys'][0])

    def test_rules_without_bindings_key_are_named(self):
        # Bug caught: bare KeyError 'substrate_bindings' from an empty rules file.
        with self.assertRaisesRegex(ValueError, 'substrate_bindings'):
            resolve_bindings({}, manifest())

    def test_unscoped_missing_source_is_an_error_naming_it(self):
        # Bug caught: the missing-catalog-row error softened into a skip,
        # hiding a missing source (the deciding case for this change).
        with self.assertRaisesRegex(ValueError, "'s'"):
            resolve_bindings(rules(), {'surveys': []})

    def test_class_without_normalized_code_names_source_and_class(self):
        # Bug caught: bare KeyError 'normalized_code' with no clue which class.
        bad = deepcopy(rules())
        bad['substrate_bindings'][0]['classes'] = {'7': {}}
        with self.assertRaisesRegex(ValueError, "'7'.*normalized_code"):
            resolve_bindings(bad, manifest())

    def test_binding_without_depth_source_ids_is_named(self):
        # Bug caught: bare KeyError 'depth_source_ids'; or a missing list read
        # as "no depth products" and silently dropped.
        bad = deepcopy(rules())
        del bad['substrate_bindings'][0]['depth_source_ids']
        with self.assertRaisesRegex(ValueError, 'depth_source_ids'):
            resolve_bindings(bad, manifest())

    def test_existing_refusals_keep_their_messages(self):
        # Bug caught: the new key checks swallowing the older named guards.
        bad = deepcopy(rules())
        bad['substrate_bindings'][0]['classes'] = {'1': {'normalized_code': 9}}
        with self.assertRaisesRegex(ValueError, 'Unreviewed normalized substrate class'):
            resolve_bindings(bad, manifest())
        bad = deepcopy(rules())
        bad['substrate_bindings'][0]['source_sha256'] = 'other'
        with self.assertRaisesRegex(ValueError, 'matching original-source review'):
            resolve_bindings(bad, manifest())

    def test_scoped_resolution_skips_an_absent_source(self):
        # Bug caught: the scoped skip lost while adding the unscoped refusal.
        self.assertEqual(resolve_bindings(rules(), {'surveys': []}, scoped=True), {})

    def test_held_and_withdrawn_rows_are_still_skipped(self):
        # Bug caught: the new key checks running before the hold/withdrawn skip
        # would reject a held row whose binding is incomplete.
        incomplete = {'substrate_bindings': [{'source_id': 's', 'classes': {'1': {}}}]}
        for status in ('hold', 'withdrawn'):
            with self.subTest(status=status):
                self.assertEqual(resolve_bindings(rules(), manifest(status)), {})
                self.assertEqual(resolve_bindings(incomplete, manifest(status)), {})


if __name__ == '__main__':
    unittest.main()
