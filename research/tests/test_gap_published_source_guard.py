"""Old but internally valid snapshots must not rediscover published surveys."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.scripts.discover_noaa_multibeam_footprints import published_source_guard


class PublishedSourceGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = {'id': 'native-one', 'sha256': 'a' * 64, 'format': 'usgs-geotiff',
                       'archive_member': 'original.tif', 'resolution_m': 2,
                       'vertical_datum': 'NAVD88', 'license': 'unknown',
                       'adapter_review': {'adapter_version': 'original-native-adapters-v1',
                                          'cog_sha256': 'b' * 64,
                                          'raster_identity': {'sha256': 'c' * 64},
                                          'requested_bounds_wgs84': [-122, 35, -121, 36]}}
        self.retained = [self.source]
        self.current = [self.source]
        self.required = ['native-one']
        self.ledger = self.folder / 'ledger.json'
        self.catalog = self.folder / 'catalog.json'

    def files(self):
        self.ledger.write_text(json.dumps({'reaches': [{'id': 'reach', 'surveys_used': self.required}]}))
        self.catalog.write_text(json.dumps({'surveys': self.current}))
        inputs = {'sources': self.retained}
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        (self.folder / 'run.json').write_text(json.dumps({
            'inputs': {**inputs, 'screen': {'old': True}, 'screen_implementation_sha256': 'old'},
            'physical_input_hash': digest}))
        return {'physical_input_hash': digest}

    def check(self):
        return published_source_guard(self.folder, 'reach', self.files(), self.ledger, self.catalog)

    def test_old_single_source_snapshot_omits_new_published_contributors(self):
        self.required += ['native-two']
        self.current += [{**self.source, 'id': 'native-two', 'sha256': 'd' * 64}]
        with self.assertRaisesRegex(ValueError, 'omits published contributors: native-two'):
            self.check()

    def test_changed_original_or_normalized_window_is_not_current(self):
        for change in ({'sha256': 'd' * 64}, {'resolution_m': 5}, {'horizontal_crs': 'EPSG:4326'}, {'vertical_datum': 'unknown'},
                       {'adapter_review': {**self.source['adapter_review'],
                                           'requested_bounds_wgs84': [-122, 34, -121, 36]}},
                       {'adapter_review': {**self.source['adapter_review'], 'cog_sha256': 'e' * 64}}):
            with self.subTest(change=change):
                self.current = [{**self.source, **change}]
                with self.assertRaisesRegex(ValueError, 'changed native bindings'):
                    self.check()

    def test_rights_only_refresh_preserves_native_binding_identity(self):
        before = self.check()
        self.current = [{**self.source, 'license': 'reviewed-noncommercial', 'notes': 'new attribution'}]
        after = self.check()
        self.assertEqual(before['binding_sha256'], after['binding_sha256'])
        self.assertNotEqual(before['catalog_sha256'], after['catalog_sha256'])
        self.assertFalse(after['current_coverage_claim'])

    def test_private_extra_physics_does_not_need_to_be_published_first(self):
        self.retained += [{**self.source, 'id': 'private-new', 'sha256': 'd' * 64}]
        result = self.check()
        self.assertEqual(result['published_contributors_checked'], ['native-one'])
        self.assertEqual(result['retained_extra_source_ids'], ['private-new'])
        self.assertFalse(result['current_coverage_claim'])

    def test_new_published_source_changes_binding_even_if_snapshot_has_it(self):
        other = {**self.source, 'id': 'native-two', 'sha256': 'd' * 64}
        self.retained += [other]; self.current += [other]
        before = self.check()
        self.required += ['native-two']
        self.assertNotEqual(before['binding_sha256'], self.check()['binding_sha256'])

    def test_catalog_and_ledger_must_have_unambiguous_sources_and_reach(self):
        self.current += [self.source]
        with self.assertRaisesRegex(ValueError, 'Duplicate source identities'):
            self.check()
        self.current = []
        with self.assertRaisesRegex(ValueError, 'absent from current catalog'):
            self.check()
        self.current = [self.source]
        checkpoint = self.files()
        self.ledger.write_text('{"reaches": []}')
        with self.assertRaisesRegex(ValueError, 'one matching ledger reach'):
            published_source_guard(self.folder, 'reach', checkpoint, self.ledger, self.catalog)

    def test_unbound_run_cannot_claim_new_sources(self):
        checkpoint = self.files()
        run = json.loads((self.folder / 'run.json').read_text())
        run['inputs']['sources'][0]['sha256'] = 'd' * 64
        (self.folder / 'run.json').write_text(json.dumps(run))
        with self.assertRaisesRegex(ValueError, 'run differs'):
            published_source_guard(self.folder, 'reach', checkpoint, self.ledger, self.catalog)


if __name__ == '__main__':
    unittest.main()
