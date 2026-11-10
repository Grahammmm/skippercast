"""A local download root replaces only the transfer: allowlist, pins and catalog hashes all hold."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin

from skippercast.platform.contracts import REPO, read_json
from skippercast.seafloor.draft import add_survey
from skippercast.seafloor.io import sha256
from skippercast.seafloor.local_sources import LocalSourceRoot, import_local, import_manifest

URL = 'https://pubs.usgs.gov/fixture/fixture.tif'
SCHEMA = Path(REPO) / 'catalog/survey.schema.json'


class LocalSourceRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.local = self.base / 'downloads'
        self.tif = self.local / 'family/fixture-id/fixture.tif'
        self.tif.parent.mkdir(parents=True)
        elevation = np.full((64, 64), -50, dtype='float32')
        elevation[30:34, 30:34] = -20
        with rasterio.open(self.tif, 'w', driver='GTiff', width=64, height=64, count=1, dtype='float32',
                           crs='EPSG:32610', transform=from_origin(690000, 3920000, 2, 2), nodata=-9999) as out:
            out.write(elevation, 1)
        self.entry = {'id': 'family-fixture-id', 'url': URL, 'sha256': sha256(self.tif),
                      'size': self.tif.stat().st_size, 'dest': 'family/fixture-id/fixture.tif'}
        self.row = {'id': 'fixture-source', 'url': URL, 'kind': 'bathymetry', 'format': 'usgs-geotiff',
                    'status': 'usable', 'sha256': self.entry['sha256'], 'bytes': self.entry['size'],
                    'archive_member': 'unknown', 'vertical_datum': 'unknown'}
        self.cache = self.base / 'repo/var/seafloor/cache'

    def tearDown(self):
        self.tmp.cleanup()

    def catalog(self, *entries):
        path = self.local / '_geofetch/catalog.jsonl'
        path.parent.mkdir(exist_ok=True)
        path.write_text(''.join(json.dumps(e) + '\n' for e in (entries or [self.entry])))
        return LocalSourceRoot(self.local)

    def assertNothingCached(self):
        self.assertEqual([p for p in self.cache.rglob('*') if p.is_file()] if self.cache.exists() else [], [])

    def test_catalogued_original_is_copied_by_pinned_hash_and_mapped(self):
        entry, cached = import_local(self.row, self.cache, self.catalog())
        self.assertEqual(entry['id'], 'family-fixture-id')
        self.assertEqual(cached, self.cache / self.entry['sha256'] / 'source.tif')
        self.assertEqual(sha256(cached), self.entry['sha256'])
        report = import_manifest([self.row, dict(self.row, id='candidate-row', status='candidate'),
                                  dict(self.row, id='elsewhere', url='https://pubs.usgs.gov/other.tif')],
                                 self.cache, self.catalog())
        self.assertEqual([(r['source_id'], r['catalog_id']) for r in report['imported']],
                         [('fixture-source', 'family-fixture-id')])
        self.assertEqual(report['not_catalogued'], ['elsewhere'])
        self.assertEqual(report['refused'], [])

    def test_catalog_checksum_conflicting_with_repo_pin_refuses_before_copy(self):
        with self.assertRaisesRegex(ValueError, 'conflicts with the pinned'):
            import_local(dict(self.row, sha256='0' * 64), self.cache, self.catalog())
        with self.assertRaisesRegex(ValueError, 'byte count conflicts'):
            import_local(dict(self.row, bytes=1), self.cache, self.catalog())
        report = import_manifest([dict(self.row, sha256='0' * 64)], self.cache, self.catalog())
        self.assertEqual(report['refused'][0]['source_id'], 'fixture-source')
        self.assertNothingCached()

    def test_file_that_no_longer_matches_its_catalog_hash_refuses(self):
        data = bytearray(self.tif.read_bytes())
        data[-1] ^= 1
        self.tif.write_bytes(bytes(data))
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            import_local(dict(self.row, sha256='unknown', bytes='unknown'), self.cache, self.catalog())
        self.assertNothingCached()

    def test_local_bytes_never_bypass_the_reviewed_url_allowlist(self):
        for url in ('https://example.com/fixture.tif',
                    'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/BlueTopo/X/BlueTopo_X.tiff'):
            local = self.catalog(dict(self.entry, url=url))
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'Unreviewed original-source URL'):
                import_local(dict(self.row, url=url), self.cache, local)
        self.assertNothingCached()

    def test_catalog_rows_cannot_escape_the_root_or_disagree(self):
        for dest in ('../outside.tif', '/etc/passwd'):
            with self.subTest(dest=dest), self.assertRaisesRegex(ValueError, 'Invalid local catalog row'):
                self.catalog(dict(self.entry, dest=dest))
        outside = self.base / 'outside.tif'
        outside.write_bytes(self.tif.read_bytes())
        (self.local / 'link.tif').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            import_local(self.row, self.cache, self.catalog(dict(self.entry, dest='link.tif')))
        with self.assertRaisesRegex(ValueError, 'conflicting checksums'):
            import_local(self.row, self.cache, self.catalog(self.entry, dict(self.entry, sha256='1' * 64)))
        with self.assertRaisesRegex(ValueError, 'Local original missing'):
            import_local(self.row, self.cache, self.catalog(dict(self.entry, dest='missing.tif')))
        self.assertNothingCached()

    def test_add_survey_uses_catalog_hash_and_never_falls_back_to_network(self):
        repo = self.base / 'repo'
        (repo / 'catalog').mkdir(parents=True)
        (repo / 'catalog/surveys.json').write_text(json.dumps({'surveys': []}))
        to_wgs = Transformer.from_crs(32610, 4326, always_xy=True).transform
        bounds = [*to_wgs(690010, 3919880), *to_wgs(690118, 3919990)]
        local = self.catalog()
        draft = read_json(add_survey(URL, bounds, ident='fixture-draft', root=repo, local_root=local))
        self.assertEqual(draft['row']['sha256'], self.entry['sha256'])
        self.assertEqual(draft['adapter_review']['source_sha256'], self.entry['sha256'])
        self.assertEqual(draft['local_catalog_id'], 'family-fixture-id')
        self.assertFalse(draft['downloaded'])
        with self.assertRaisesRegex(ValueError, 'not in the local source catalog'):
            add_survey('https://pubs.usgs.gov/fixture/absent.tif', bounds, ident='absent', root=repo, local_root=local)
        with self.assertRaisesRegex(ValueError, 'Use one of'):
            add_survey(URL, bounds, ident='fixture-draft', root=repo, local_root=local, fetch=True)

    def test_reviewed_digital_coast_dem_folders_only(self):
        bucket = 'https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/'
        admitted = bucket + 'dem/USACE_CA_DEM_2009_9488/2009_NCMP_CA_114_BareEarth_1mGrid.tif'
        entry, cached = import_local(dict(self.row, url=admitted), self.cache,
                                     self.catalog(dict(self.entry, url=admitted)))
        self.assertEqual(sha256(cached), self.entry['sha256'])
        for url in (bucket + 'dem/Other_Unreviewed_DEM_1234/tile.tif', bucket + 'laz/geoid18/9488/tile.tif',
                    bucket + 'dem/USACE_CA_DEM_2009_9488_extra/tile.tif'):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'Unreviewed original-source URL'):
                import_local(dict(self.row, url=url, sha256='unknown', bytes='unknown'), self.base / 'other',
                             self.catalog(dict(self.entry, url=url)))

    def fixture_repo(self, surveys=()):
        repo = self.base / 'repo'
        (repo / 'catalog').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SCHEMA, repo / 'catalog/survey.schema.json')
        (repo / 'catalog/surveys.json').write_text(json.dumps({'surveys': list(surveys)}))
        to_wgs = Transformer.from_crs(32610, 4326, always_xy=True).transform
        return repo, [*to_wgs(690010, 3919880), *to_wgs(690118, 3919990)]

    def test_existing_url_pin_holds_for_any_new_id_or_archive_member(self):
        pinned = dict(self.row, id='existing-pinned-source', sha256='0' * 64)
        repo, bounds = self.fixture_repo([pinned])
        local = self.catalog()
        for kwargs in ({'ident': 'existing-pinned-source'}, {'ident': 'new-alias-source'},
                       {'member': 'other-product.tif'}):
            with self.subTest(**kwargs), self.assertRaisesRegex(ValueError, 'conflicts with the pinned'):
                add_survey(URL, bounds, root=repo, local_root=local, **kwargs)
        # The pin also binds the plain --local path under an alias ID.
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            add_survey(URL, bounds, ident='new-alias-source', root=repo, local=self.tif)
        repo, bounds = self.fixture_repo([pinned, dict(self.row, id='other-product', sha256='1' * 64)])
        with self.assertRaisesRegex(ValueError, 'pin conflicting checksums for this URL'):
            add_survey(URL, bounds, ident='new-alias-source', root=repo, local_root=local)
        self.assertNothingCached()
        # Control: a matching existing pin admits the alias, which inherits it.
        repo, bounds = self.fixture_repo([dict(self.row, id='existing-pinned-source')])
        draft = read_json(add_survey(URL, bounds, ident='new-alias-source', root=repo, local_root=local))
        self.assertEqual((draft['row']['sha256'], draft['row']['bytes']), (self.entry['sha256'], self.entry['size']))

    def test_selected_local_file_is_hashed_even_with_a_warm_cache(self):
        local = self.catalog()
        repo, bounds = self.fixture_repo()
        cached = self.cache / self.entry['sha256'] / 'source.tif'
        import_local(self.row, self.cache, local)                      # cold cache
        self.assertEqual(import_local(self.row, self.cache, local)[1], cached)   # warm, intact
        add_survey(URL, bounds, ident='fixture-draft', root=repo, local_root=local)
        data = bytearray(self.tif.read_bytes())
        data[-1] ^= 1                                                  # same length, other bytes
        self.tif.write_bytes(bytes(data))
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            import_local(self.row, self.cache, local)
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            add_survey(URL, bounds, ident='fixture-draft-2', root=repo, local_root=local)
        report = import_manifest([self.row], self.cache, local)
        self.assertEqual((report['imported'], report['refused'][0]['source_id']), ([], 'fixture-source'))
        self.assertEqual(sha256(cached), self.entry['sha256'])        # verified cache kept


if __name__ == '__main__':
    unittest.main()
