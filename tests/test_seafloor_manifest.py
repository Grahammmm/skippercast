"""Offline M0 inventory acceptance; no survey downloads or local-cache dependency."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'catalog/surveys.json').read_text())
ROWS = MANIFEST['surveys']
SCHEMA = json.loads((ROOT / 'catalog/survey.schema.json').read_text())


def resolve(reference):
    path, pointer = reference.split('#', 1)
    target = (ROOT / path).resolve()
    if not target.is_relative_to(ROOT):
        raise ValueError('Evidence escapes repository')
    value = json.loads(target.read_text())
    for token in pointer.lstrip('/').split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


class InventoryTests(unittest.TestCase):
    def test_inventory_statuses_have_no_null_measurements(self):
        self.assertTrue(ROWS)
        self.assertLessEqual({r['status'] for r in ROWS}, {'candidate', 'usable', 'hold', 'withdrawn'})
        for row in ROWS:
            if row['status'] == 'usable':
                self.assertEqual(row['adapter_review']['source_sha256'], row['sha256'])
                self.assertGreater(row['adapter_review']['nominal_0_300ft_pixels_in_requested_bounds'], 0)
        def visit(value):
            self.assertIsNotNone(value)
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(MANIFEST)

    def test_identity_and_lineage(self):
        ids = {r['id'] for r in ROWS}
        self.assertEqual(len(ids), len(ROWS))
        self.assertEqual(len({(r['url'], r['archive_member'], r['kind']) for r in ROWS}), len(ROWS))
        for row in ROWS:
            self.assertNotIn(row['id'], row['derived_from'])
            self.assertLessEqual(set(row['derived_from']), ids)
            self.assertEqual(row['lineage_status'],
                             'linked-family' if row['derived_from'] else 'unknown')

    def test_evidence_resolves_in_committed_repository(self):
        for path in MANIFEST['inventory_inputs']:
            self.assertTrue((ROOT / path).is_file(), path)
        for row in ROWS:
            self.assertTrue(row['evidence'], row['id'])
            for ref in row['evidence'] + list(row['field_evidence'].values()):
                with self.subTest(id=row['id'], reference=ref):
                    resolve(ref)

    def test_all_native_depth_and_substrate_receipts_are_inventoried(self):
        urls = {r['url'] for r in ROWS}
        for filename, collection, key in [
            ('usgs-depth-datum-ledger.json', 'sources', 'archive_url'),
            ('usgs-ds781-native-character-review.json', 'products', 'archive_url'),
            ('noaa-regular-native-depth-review.json', 'files', 'bag_url'),
            ('noaa-vr-native-depth-expanded-review.json', 'files', 'bag_url'),
        ]:
            receipt = json.loads((ROOT / 'dist/data' / filename).read_text())
            for record in receipt[collection]:
                self.assertIn(record[key], urls, filename)

    def test_primary_inventory_inputs_are_complete(self):
        expected = {'catalog/sources.json', 'dist/data/central-source-acquisition-queue.json'}
        for pattern in ('*review*.json', '*gap*.json'):
            expected.update(str(p.relative_to(ROOT)) for p in (ROOT / 'dist/data').glob(pattern))
        self.assertEqual(set(MANIFEST['inventory_inputs']), expected)

    def test_reference_compilations_never_enter_depth_manifest(self):
        for row in ROWS:
            self.assertNotIn('bluetopo', row['url'].lower())
            self.assertNotIn('/modeling/', row['url'].lower())
            if row['format'] == 'bag' and '_VR_' in row['url'].upper():
                self.assertEqual(row['resolution_m'], 'unknown', 'Overview is not refinement resolution')

    def test_native_resolution_wins_over_metadata_spacing(self):
        for row in ROWS:
            if row['url'].endswith('Bathymetry_OffshoreMorroBay.zip'):
                self.assertEqual(row['resolution_m'], 2)
                self.assertEqual(row['vertical_datum'], 'unknown')
                self.assertIn('native_resolution', row['field_evidence']['resolution_m'])
                break
        else:
            self.fail('Morro Bay original depth missing')


@unittest.skipUnless(Draft202012Validator, 'Install requirements-test.txt; required in survey-science CI')
class SchemaTests(unittest.TestCase):
    def test_runtime_loader_validates_the_same_inventory(self):
        from skippercast.seafloor.manifest import load_manifest
        self.assertEqual(load_manifest(ROOT), MANIFEST)

    def test_usable_receipt_cannot_conflict_with_manifest(self):
        from unittest.mock import patch
        from skippercast.seafloor.manifest import load_manifest
        for field, value in [('sha256', '0'*64), ('resolution_m', 999), ('vertical_datum', 'MSL')]:
            document = deepcopy(MANIFEST)
            row = next(r for r in document['surveys'] if r['status'] == 'usable')
            row[field] = value
            with patch('skippercast.seafloor.manifest.read_json', side_effect=[document, SCHEMA]):
                with self.assertRaisesRegex(ValueError, 'conflicts'):
                    load_manifest(ROOT)

    def test_qualify_requires_rights_matching_source_and_shallow_pixels(self):
        from skippercast.seafloor.manifest import qualify_row
        row = deepcopy(next(r for r in ROWS if r['status'] == 'usable'))
        receipt = dict(row['adapter_review'], source_id=row['id'], source_bytes=row['bytes'],
                       horizontal_crs=row['horizontal_crs'])
        for changes in ({'source_sha256': '0'*64}, {'nominal_0_300ft_pixels_in_requested_bounds': 0},
                        {'valid_pixels_in_requested_bounds': 1}):
            with self.assertRaisesRegex(ValueError, 'receipt'):
                qualify_row(row, dict(receipt, **changes), rights_url=receipt['rights_source_url'])
        with self.assertRaisesRegex(ValueError, 'rights'):
            qualify_row(dict(row, license='unknown'), receipt, rights_url=receipt['rights_source_url'])

    def test_every_manifest_row(self):
        Draft202012Validator.check_schema(SCHEMA)
        validator = Draft202012Validator(SCHEMA)
        for row in ROWS:
            with self.subTest(id=row['id']):
                errors = list(validator.iter_errors(row))
                self.assertEqual(errors, [], '\n'.join(str(e) for e in errors))

    def test_rejects_invalid_types_hashes_and_unexplained_holds(self):
        validator = Draft202012Validator(SCHEMA)
        for changes in ({'resolution_m': None}, {'resolution_m': 0},
                        {'sha256': 'fake'}, {'year': True}, {'bytes': -1},
                        {'status': 'approved'}, {'status': 'hold'},
                        {'evidence': []}, {'url': 'file:///private/grid.tif'}):
            row = deepcopy(ROWS[0])
            row.update(changes)
            with self.subTest(changes=changes):
                self.assertTrue(list(validator.iter_errors(row)))


if __name__ == '__main__':
    unittest.main()
