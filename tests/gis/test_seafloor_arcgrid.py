"""Real tiny AIG fixture and malicious archives exercise the original-grid adapter."""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tarfile
import tempfile
import stat
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import rasterio
from rasterio.warp import transform_bounds

from tests._support import FIXTURES
from skippercast.seafloor.adapters import arcgrid
from skippercast.seafloor.ingest import ingest
from skippercast.seafloor.fetch import fetch_source
from skippercast.seafloor.io import sha256
from skippercast.seafloor.state_cache import allowed
from skippercast.seafloor.raster import bounds_window

FIXTURE = FIXTURES/'seafloor-arcgrid/abc3x1.json'


class ArcGridTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original = self.root/'original.tgz'
        files = json.loads(FIXTURE.read_text())['files']
        self.members = []
        for name, record in files.items():
            data = base64.b64decode(record['base64'], validate=True)
            self.assertEqual(hashlib.sha256(data).hexdigest(), record['sha256'])
            self.members.append(('package/grid/'+name, data))
        self.archive(self.members)
        self.row = {'id': 'real-aig-fixture', 'kind': 'bathymetry', 'format': 'arcgrid',
                    'url': 'https://pubs.usgs.gov/fixture.tgz', 'archive_member': 'package/grid',
                    'sha256': sha256(self.original), 'bytes': self.original.stat().st_size,
                    'vertical_datum': 'unknown', 'resolution_m': 'unknown'}

    def tearDown(self):
        self.tmp.cleanup()

    def archive(self, members):
        with tarfile.open(self.original, 'w:gz') as out:
            for name, data in members:
                info = tarfile.TarInfo(name); info.size = len(data)
                out.addfile(info, BytesIO(data))

    def test_actual_aig_decoder_and_native_normalization_preserve_values(self):
        with arcgrid.open_source(self.original, self.row) as native:
            self.assertEqual(native.driver, 'AIG')
            self.assertEqual(native.shape, (1, 3))
            values = native.read(1, masked=True)
            spacing = native.res
            bounds = transform_bounds(native.crs, 4326, *native.bounds)
        row = dict(self.row, resolution_m=max(spacing))
        result, _, reused = ingest(row, bounds, root=self.root, local=self.original)
        self.assertFalse(reused)
        paths = list((self.root/'var/seafloor/cache'/row['sha256']).glob('*.tif'))
        self.assertEqual(len(paths), 1)
        with rasterio.open(paths[0]) as normalized:
            self.assertEqual(normalized.res, spacing)
            self.assertEqual(normalized.shape, values.shape)
            np.testing.assert_array_equal(normalized.read(1), -values.data.astype('float32'))
        self.assertEqual(result['valid_pixels_in_requested_bounds'], 3)
        # Positive land elevations must not turn into invented positive depths.
        self.assertEqual(result['nominal_0_300ft_pixels_in_requested_bounds'], 0)
        again, _, reused = ingest(row, bounds, root=self.root)
        self.assertTrue(reused)
        self.assertEqual(again['raster_identity'], result['raster_identity'])

    def test_changed_or_extra_extracted_member_fails_verification(self):
        grid = arcgrid.source_path(self.original, self.row)
        (grid/'w001001.adf').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            arcgrid.source_path(self.original, self.row)

    def test_reviewed_noaa_ship_tar_gz_uses_same_native_decoder(self):
        archive = self.root/'original.tar.gz'
        archive.write_bytes(self.original.read_bytes())
        row = dict(self.row, url='https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block03/multibeam/data/version2/products/original.tar.gz')
        cached, downloaded = fetch_source(row, self.root/'cache', local=archive)
        self.assertFalse(downloaded)
        self.assertEqual(cached.name, 'source.tar.gz')
        with arcgrid.open_source(cached, row) as native, arcgrid.open_source(self.original, self.row) as original:
            self.assertEqual(native.crs, original.crs)
            self.assertEqual(native.transform, original.transform)
            np.testing.assert_array_equal(native.read(1, masked=True), original.read(1, masked=True))
        self.assertTrue(allowed('big-sur-coast-r02', f'cache/{row["sha256"]}/source.tar.gz'))
        self.assertFalse(allowed('shared', f'cache/{row["sha256"]}/source.tar.gz'))
        self.assertTrue(allowed('big-sur-coast-r02', 'private-reaches/big-sur-coast-r02/physical.json'))
        self.assertFalse(allowed('big-sur-coast-r01', 'private-reaches/big-sur-coast-r02/physical.json'))

    def nested_archive(self, extra=()):
        payload = BytesIO()
        with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as zipped:
            for name, data in self.members:
                zipped.writestr(name, data)
            for name, data in extra:
                zipped.writestr(name, data)
        self.archive([('products/bathy.zip', payload.getvalue())])
        return dict(self.row, archive_member='products/bathy.zip/package/grid',
                    sha256=sha256(self.original), bytes=self.original.stat().st_size)

    def test_nested_original_zip_preserves_native_values_mask_and_depth_counts(self):
        with arcgrid.open_source(self.original, self.row) as native:
            values, spacing, transform = native.read(1, masked=True), native.res, native.transform
            bounds = transform_bounds(native.crs, 4326, *native.bounds)
        direct, _, _ = ingest(self.row, bounds, root=self.root, local=self.original)
        row = self.nested_archive()
        with arcgrid.open_source(self.original, row) as nested:
            self.assertEqual(nested.res, spacing)
            self.assertEqual(nested.transform, transform)
            np.testing.assert_array_equal(nested.read(1, masked=True), values)
        receipt, _, _ = ingest(row, bounds, root=self.root, local=self.original)
        self.assertEqual(receipt['raster_identity'], direct['raster_identity'])
        self.assertEqual(receipt['nominal_0_300ft_pixels_in_requested_bounds'],
                         direct['nominal_0_300ft_pixels_in_requested_bounds'])
        # Only the exact reviewed grid is extracted; the ZIP remains private scratch.
        grid = arcgrid.source_path(self.original, row)
        self.assertFalse(list(grid.rglob('*.zip')))
        (grid/'unexpected').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            arcgrid.source_path(self.original, row)

    def test_nested_traversal_duplicate_links_and_expansion_fail_before_extract(self):
        link = zipfile.ZipInfo('package/grid/link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for extra in [[('../escape', b'x')], [('/escape', b'x')],
                      [('package/grid/hdr.adf', b'x')], [(link, b'../escape')]]:
            with self.subTest(extra=extra):
                row = self.nested_archive(extra)
                with self.assertRaises(ValueError):
                    arcgrid.source_path(self.original, row)
                self.assertFalse(list(self.root.glob('grid-*')))
        row = self.nested_archive([('unselected', b'x'*20_000)])
        with patch.object(arcgrid, 'MAX_EXTRACTED_BYTES', self.original.stat().st_size+100), \
                self.assertRaisesRegex(ValueError, 'byte bound'):
            arcgrid.source_path(self.original, row)
        self.assertFalse(list(self.root.glob('grid-*')))

    def test_nested_member_bound_and_missing_grid_are_not_guessed(self):
        row = self.nested_archive()
        with patch.object(arcgrid, 'MAX_MEMBERS', 2), self.assertRaisesRegex(ValueError, 'member bound'):
            arcgrid.source_path(self.original, row)
        for member in ['wrong.zip/package/grid', 'products/bathy.zip/package/other',
                       'products/bathy.zip/other.zip/grid', 'products/bathy.zip']:
            with self.subTest(member=member), self.assertRaises(ValueError):
                arcgrid.source_path(self.original, dict(row, archive_member=member))
        self.assertFalse(list(self.root.glob('grid-*')))

    def test_reviewed_ventresca_archive_is_allowed_only_for_arcgrid(self):
        row = dict(self.row, url='https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/BigCreek/multibeam/data/version2/products/original.tar.gz')
        cached, _ = fetch_source(row, self.root/'cache', local=self.original)
        self.assertEqual(cached.name, 'source.tar.gz')
        with self.assertRaisesRegex(ValueError, 'container'):
            fetch_source(dict(row, format='bag'), self.root/'cache', local=self.original)

    def test_reviewed_point_lobos_original_is_allowed_with_native_guards(self):
        url = ('https://data.ngdc.noaa.gov/platforms/ocean/ships/macginitie/'
               'PointLobos/multibeam/data/version2/products/PointLobos_additional_products.tar.gz')
        row = dict(self.row, url=url)
        cached, downloaded = fetch_source(row, self.root/'cache', local=self.original)
        self.assertEqual(cached.read_bytes(), self.original.read_bytes())
        self.assertFalse(downloaded)
        with self.assertRaisesRegex(ValueError, 'container'):
            fetch_source(dict(row, format='bag'), self.root/'cache', local=self.original)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            fetch_source(dict(row, sha256='0'*64), self.root/'cache', local=self.original)
        with self.assertRaisesRegex(ValueError, 'byte count'):
            fetch_source(dict(row, bytes=row['bytes']+1), self.root/'cache', local=self.original)
        for bad in (url.replace('/PointLobos/', '/OtherSurvey/'),
                    url.replace('/PointLobos/', '/PointLobos/../OtherSurvey/'),
                    url.replace('/PointLobos/', '/PointLobos/%2e%2e/OtherSurvey/'),
                    url.replace('/PointLobos/', '/PointLobos/%252e%252e/OtherSurvey/'),
                    url + '/../OtherSurvey/original.tar.gz',
                    url + '?redirect=OtherSurvey',
                    url.replace('PointLobos_additional_products.tar.gz', 'another.tar.gz'),
                    url.replace('/PointLobos/', '/PointLobos-other/'),
                    url.replace('data.ngdc.noaa.gov/', 'data.ngdc.noaa.gov.evil.test/'),
                    url.replace('https:', 'http:')):
            with self.subTest(url=bad), self.assertRaisesRegex(ValueError, 'Unreviewed'):
                fetch_source(dict(row, url=bad), self.root/'cache', local=self.original)

    def test_tar_gz_does_not_grant_other_hosts_paths_or_formats(self):
        for url, format_name in [
            ('https://pubs.usgs.gov/original.tar.gz', 'arcgrid'),
            ('https://data.ngdc.noaa.gov/platforms/ocean/ships/other/original.tar.gz', 'arcgrid'),
            ('https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/original.tar.gz', 'bag'),
            ('https://example.com/original.tar.gz', 'arcgrid'),
        ]:
            with self.subTest(url=url, format_name=format_name), self.assertRaises(ValueError):
                fetch_source(dict(self.row, url=url, format=format_name), self.root/'cache', local=self.original)

    def test_unknown_or_wrong_grid_is_never_guessed(self):
        for name in ['unknown', 'package/other']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                arcgrid.source_path(self.original, dict(self.row, archive_member=name))

    def test_traversal_duplicate_link_and_expansion_bombs_fail_before_extract(self):
        cases = [('traversal', [('../escape', b'x')]),
                 ('absolute', [('/escape', b'x')]),
                 ('duplicate', [('package/grid/hdr.adf', b'x')])]
        for label, extra in cases:
            with self.subTest(case=label):
                self.archive(self.members+extra)
                with self.assertRaises(ValueError):
                    arcgrid.source_path(self.original, self.row)
                self.assertFalse(list(self.root.glob('grid-*')))
        self.archive(self.members)
        with tarfile.open(self.original, 'w:gz') as out:
            info = tarfile.TarInfo('package/grid/link'); info.type = tarfile.SYMTYPE; info.linkname = '../escape'
            out.addfile(info)
        with self.assertRaises(ValueError):
            arcgrid.source_path(self.original, self.row)
        self.archive(self.members+[('unselected-large', b'x'*100)])
        with patch.object(arcgrid, 'MAX_EXTRACTED_BYTES', 50), self.assertRaisesRegex(ValueError, 'byte bound'):
            arcgrid.source_path(self.original, self.row)
        self.assertFalse(list(self.root.glob('grid-*')))

    def test_nonmetric_projected_grid_is_rejected(self):
        from types import SimpleNamespace
        # Native state-plane feet cannot be silently interpreted as metres.
        with self.assertRaisesRegex(ValueError, 'meters'):
            bounds_window(SimpleNamespace(crs='EPSG:2227'), [-122, 36, -121, 37])

    def test_archive_member_bound_applies_before_extract(self):
        with patch.object(arcgrid, 'MAX_MEMBERS', 2), self.assertRaisesRegex(ValueError, 'member bound'):
            arcgrid.source_path(self.original, self.row)
        self.assertFalse(list(self.root.glob('grid-*')))

    def test_private_state_restores_original_container_not_arbitrary_paths(self):
        name = 'monterey-point-sur-r03'
        digest = 'a'*64
        self.assertTrue(allowed(name, f'cache/{digest}/source.tgz'))
        self.assertFalse(allowed(name, f'cache/{digest}/source.exe'))
        self.assertFalse(allowed('shared', f'cache/{digest}/source.tgz'))
