"""Synthetic originals exercise native orientation, masks, metadata and cache reuse."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from zipfile import ZipFile

import h5py
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin
from rasterio.windows import Window

from skippercast.seafloor.adapters import bag, usgs_geotiff
from skippercast.http import FakeSession
from skippercast.seafloor.fetch import PREFIXES, fetch_source, restore_private, upload_private
from skippercast.seafloor.ingest import ingest
from skippercast.seafloor.io import sha256
from skippercast.seafloor.raster import bounds_window, read_native


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tif = self.root / 'fixture.tif'
        elevation = np.full((64, 64), -50, dtype='float32')
        elevation[20:24, 20:24] = -9999
        elevation[30:34, 30:34] = -20
        uncertainty = np.full_like(elevation, .5)
        uncertainty[4:8, 4:8] = -9999
        self.elevation = elevation
        with rasterio.open(self.tif, 'w', driver='GTiff', width=64, height=64, count=2,
                           dtype='float32', crs='EPSG:32610', transform=from_origin(690000, 3920000, 2, 2),
                           nodata=-9999) as output:
            output.write(elevation, 1)
            output.write(uncertainty, 2)
        self.row = {'id': 'fixture', 'url': 'https://pubs.usgs.gov/fixture.tif',
                    'kind': 'bathymetry', 'format': 'usgs-geotiff', 'sha256': sha256(self.tif),
                    'bytes': self.tif.stat().st_size, 'archive_member': 'unknown',
                    'vertical_datum': 'unknown', 'resolution_m': 2}

    def tearDown(self):
        self.tmp.cleanup()

    def test_native_window_retains_sign_hole_uncertainty_and_affine(self):
        with rasterio.open(self.tif) as source:
            native = read_native(source, Window(16, 16, 24, 24), self.row, uncertainty_band=2)
            self.assertEqual(native.depth_m.shape, (24, 24))
            self.assertEqual(native.depth_m[0, 0], 50)
            self.assertTrue(np.isnan(native.depth_m[4, 4]))
            self.assertFalse(native.valid[4, 4])
            self.assertTrue(np.isnan(native.uncertainty_m[4, 4]))
            self.assertEqual(native.uncertainty_m[0, 0], .5)
            self.assertEqual(native.transform.c, 690032)
            self.assertEqual(native.vertical_datum, 'unknown')
            self.assertIsNone(native.interpolated)
            with self.assertRaisesRegex(ValueError, 'bounded'):
                read_native(source, Window(0, 0, 2000, 2000), self.row)

    def test_window_clips_to_source_and_adds_seam_margin(self):
        with rasterio.open(self.tif) as source:
            exact = bounds_window(source, [690040, 3919940, 690060, 3919960], bounds_crs=32610, margin_m=0)
            margin = bounds_window(source, [690040, 3919940, 690060, 3919960], bounds_crs=32610)
            self.assertEqual(exact.width, 10)
            self.assertEqual(margin, Window(0, 0, 64, 64))

    def make_bag(self):
        path = self.root / 'TEST_MB_2m.bag'
        raster_copy(self.tif, path, driver='BAG', VAR_ABSTRACT='TEST synthetic fixture',
                    VAR_DATE='2020-01-01', VAR_DATETIME='2020-01-01T00:00:00')
        row = dict(self.row, url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/TEST/BAG/TEST_MB_2m.bag',
                   format='bag', sha256=sha256(path), bytes=path.stat().st_size)
        return path, row

    def test_real_bag_format_orientation_and_unknown_datum(self):
        path, row = self.make_bag()
        metadata = bag.inspect_metadata(path, 'TEST')
        self.assertEqual(metadata['vertical_datum'], 'unknown')
        with bag.open_source(path, row) as source:
            native = read_native(source, Window(0, 0, 64, 64), row, uncertainty_band=2)
            self.assertEqual(native.depth_m[30, 30], 20)
            self.assertTrue(np.isnan(native.depth_m[20, 20]))
            self.assertTrue(np.isnan(native.uncertainty_m[4, 4]))
            self.assertEqual(native.resolution_m, 2)

    def test_vr_overview_is_never_accepted_as_native_depth(self):
        path, row = self.make_bag()
        with h5py.File(path, 'r+') as source:
            source['BAG_root'].create_dataset('varres_refinements', data=np.zeros((1, 2)))
        with self.assertRaisesRegex(ValueError, 'overview rejected'):
            bag.open_source(path, row)

    def test_archive_requires_exact_member_for_multiple_resolutions(self):
        path = self.root / 'fixture.zip'
        with ZipFile(path, 'w') as archive:
            archive.write(self.tif, '2m.tif')
            archive.write(self.tif, '5m.tif')
        with self.assertRaisesRegex(ValueError, 'exact'):
            usgs_geotiff.source_path(path, self.row)
        selected = usgs_geotiff.source_path(path, dict(self.row, archive_member='2m.tif'))
        self.assertEqual(sha256(selected), sha256(self.tif))
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            usgs_geotiff.source_path(path, dict(self.row, archive_member='../escape.tif'))

    def test_cached_original_is_reused_offline_and_corruption_fails(self):
        cache = self.root / 'cache'
        source, downloaded = fetch_source(self.row, cache, local=self.tif)
        self.assertFalse(downloaded)
        session = FakeSession()
        self.assertEqual(fetch_source(self.row, cache, fetch=True, session=session), (source, False))
        self.assertEqual(session.calls, [])
        source.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            fetch_source(self.row, cache, fetch=True, session=session)

    def test_failed_import_does_not_cache_wrong_bytes(self):
        row = dict(self.row, sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            fetch_source(row, self.root / 'cache', local=self.tif)
        self.assertFalse(list((self.root / 'cache').glob('*.part')))

    def test_normalized_bag_is_native_cog_and_second_run_is_noop(self):
        path, row = self.make_bag()
        tr = Transformer.from_crs(32610, 4326, always_xy=True)
        west, south = tr.transform(689990, 3919860)
        east, north = tr.transform(690140, 3920010)
        bounds = [west, south, east, north]
        first, downloaded, reused = ingest(row, bounds, root=self.root, local=path)
        self.assertFalse(downloaded or reused)
        self.assertEqual(first['nominal_0_300ft_pixels_in_requested_bounds'], 64*64-16)
        with patch('skippercast.http.default_session', side_effect=AssertionError('no network')) as request:
            second, downloaded, reused = ingest(row, bounds, root=self.root, fetch=True)
            self.assertEqual(first, second)
            self.assertTrue(reused)
            self.assertFalse(downloaded)
            request.assert_not_called()
        # A new-format gateway must reuse the legacy normalized pair verbatim,
        # rather than changing every native COG key just to add a dispatch.
        from skippercast.seafloor.source_ingest import ingest as ingest_source
        with patch('skippercast.seafloor.ingest.raster_copy',side_effect=AssertionError('No rebuild')):
            self.assertEqual(ingest_source(row,bounds,root=self.root),(first,False,True))
        cogs = list((self.root / 'var/seafloor/cache').glob('*/*.tif'))
        self.assertEqual(len(cogs), 1)
        with rasterio.open(cogs[0]) as source:
            self.assertEqual(source.tags(ns='IMAGE_STRUCTURE')['LAYOUT'], 'COG')
            self.assertEqual(source.read(1)[30, 30], 20)
            self.assertEqual(source.read_masks(1)[20, 20], 0)
            self.assertEqual(source.res, (2, 2))
            self.assertTrue(np.isnan(source.read(2)[4, 4]))


    def test_usgs_single_band_zip_normalizes_without_invented_uncertainty(self):
        single = self.root / 'single.tif'
        with rasterio.open(self.tif) as source:
            profile = dict(source.profile, count=1)
            with rasterio.open(single, 'w', **profile) as output:
                output.write(source.read(1), 1)
        archive = self.root / 'single.zip'
        with ZipFile(archive, 'w') as output:
            output.write(single, 'native.tif')
        row = dict(self.row, url='https://pubs.usgs.gov/single.zip', archive_member='native.tif',
                   sha256=sha256(archive), bytes=archive.stat().st_size)
        tr = Transformer.from_crs(32610, 4326, always_xy=True)
        bounds = [*tr.transform(689990, 3919860), *tr.transform(690140, 3920010)]
        result, _, _ = ingest(row, bounds, root=self.root, local=archive)
        self.assertEqual(result['vertical_datum'], 'unknown')
        self.assertEqual(result['interpolation_mask'], 'unknown')
        self.assertEqual(result['uncertainty_type'], 'unknown')
        self.assertEqual(result['nominal_0_300ft_pixels_in_requested_bounds'], 4080)
        cog = next((self.root / 'var/seafloor/cache').glob('*/*.tif'))
        with rasterio.open(cog) as output:
            self.assertEqual(output.count, 1)
            self.assertEqual(output.read_masks(1)[20, 20], 0)

    def test_first_download_and_second_fetch_uses_hash_cache(self):
        session = FakeSession({self.row['url']: self.tif.read_bytes()})
        first, downloaded = fetch_source(self.row, self.root / 'download', fetch=True, session=session)
        self.assertTrue(downloaded)
        second, downloaded = fetch_source(self.row, self.root / 'download', fetch=True, session=session)
        self.assertEqual(first, second)
        self.assertFalse(downloaded)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][2]['allowed_prefixes'], PREFIXES)

    def test_private_cache_streams_and_rejects_corruption_and_oversize(self):
        destination = self.root / 'restore/source.tif'
        client = Mock()
        client.get_object.return_value = {'Body': BytesIO(self.tif.read_bytes())}
        restore_private(client, 'private', destination, self.row['sha256'])
        self.assertEqual(sha256(destination), self.row['sha256'])
        upload_private(client, 'private', self.tif)
        self.assertEqual(client.put_object.call_args.kwargs['CacheControl'], 'private, no-store')
        self.assertEqual(client.put_object.call_args.kwargs['Key'],
                         'seafloor-cache/' + self.row['sha256'] + '/fixture.tif')
        client.get_object.return_value = {'Body': BytesIO(b'bad')}
        with self.assertRaisesRegex(ValueError, 'checksum'):
            restore_private(client, 'private', destination, self.row['sha256'])
        self.assertEqual(sha256(destination), self.row['sha256'])
        client.get_object.return_value = {'Body': BytesIO(self.tif.read_bytes())}
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            restore_private(client, 'private', destination, self.row['sha256'], max_bytes=8)
        self.assertFalse(destination.with_suffix('.tif.part').exists())


if __name__ == '__main__':
    unittest.main()
