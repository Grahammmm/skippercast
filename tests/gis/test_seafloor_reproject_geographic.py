"""Geographic lon/lat originals are projected on their own datum before the native adapter."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.transform import from_origin

from skippercast.seafloor import reproject_geographic as rg
from skippercast.seafloor.source_ingest import ingest
from skippercast.seafloor.io import sha256
from skippercast.seafloor.manifest import qualify_row

# Synthetic NCMP-like tile: 1e-5 degree pixels near Morro Bay, NAD83 + NAVD88 height.
WEST, NORTH, RES = -120.8900, 35.4100, 1e-5
ROWS, COLS = 240, 300
# Elevation (m, NAVD88, up) is affine in lon/lat, so bilinear interpolation of the
# source samples reproduces it exactly; only float32 storage remains as error.
A, B, C = -20.0, 3000.0, 2000.0      # m, m/degree latitude, m/degree longitude


def ramp(lon, lat):
    return A + B * (lat - NORTH) + C * (lon - WEST)


def write_tile(path, *, crs='EPSG:5498', units=None, hole=True, nodata=-3.4028234663852886e38):
    rows, cols = np.mgrid[0:ROWS, 0:COLS]
    lon, lat = WEST + (cols + .5) * RES, NORTH - (rows + .5) * RES
    values = ramp(lon, lat).astype('float32')
    if hole:
        values[100:130, 140:175] = nodata          # a NoData hole inside the tile
        values[:, :7] = nodata                     # and a NoData margin on the west edge
    profile = dict(driver='GTiff', width=COLS, height=ROWS, count=1, dtype='float32',
                   transform=from_origin(WEST, NORTH, RES, RES), nodata=nodata)
    if crs:
        profile['crs'] = CRS.from_user_input(crs).to_wkt()
    with rasterio.open(path, 'w', **profile) as out:
        out.write(values, 1)
        if units:
            out.units = (units,)
    return path


class ReprojectGeographicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tif = write_tile(self.root / 'tile.tif')

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, path=None, directory=None):
        directory = Path(directory or self.root / 'out')
        directory.mkdir(exist_ok=True)
        with rasterio.open(path or self.tif) as ds:
            return rg.prepare(ds, sha256(path or self.tif), directory)

    def test_ramp_matches_analytic_answer_within_stated_bound(self):
        receipt = self.project()
        with rasterio.open(receipt['path']) as out:
            values = out.read(1)
            rows, cols = np.mgrid[0:out.height, 0:out.width]
            x, y = out.transform * (cols + .5, rows + .5)
        lon, lat = Transformer.from_crs(3310, 4269, always_xy=True).transform(x, y)
        valid = np.isfinite(values)
        error = np.abs(values.astype('float64') - ramp(lon, lat))
        fx, fy = (lon - WEST) / RES - .5, (NORTH - lat) / RES - .5
        # Bilinear pixels: exact for an affine field; bound = float32 rounding of |z| <= 21 m.
        interior = valid & (fx >= 8) & (fx <= COLS - 2) & (fy >= 0) & (fy <= ROWS - 2) \
            & ~((fy > 98) & (fy < 131) & (fx > 138) & (fx < 176))
        self.assertGreater(interior.sum(), 40_000)
        self.assertLess(error[interior].max(), 1e-5)
        # Edge pixels keep their containing source value: bound = half a source pixel of slope.
        edge_bound = (B + C) * RES / 2 + 1e-5
        self.assertLess(error[valid].max(), edge_bound)
        self.assertEqual(receipt['output_pixels']['valid'], int(valid.sum()))
        self.assertEqual(receipt['output_pixels']['bilinear'] + receipt['output_pixels']['nearest_edge'],
                         int(valid.sum()))

    def test_nodata_mask_is_exactly_the_containing_source_pixel_image(self):
        receipt = self.project()
        with rasterio.open(self.tif) as src:
            source_valid = src.read_masks(1) > 0
        with rasterio.open(receipt['path']) as out:
            values = out.read(1)
            rows, cols = np.mgrid[0:out.height, 0:out.width]
            x, y = out.transform * (cols + .5, rows + .5)
        lon, lat = Transformer.from_crs(3310, 4269, always_xy=True).transform(x, y)
        ic, jc = np.floor((lon - WEST) / RES).astype(int), np.floor((NORTH - lat) / RES).astype(int)
        inside = (ic >= 0) & (ic < COLS) & (jc >= 0) & (jc < ROWS)
        expected = np.zeros(values.shape, bool)
        expected[inside] = source_valid[jc[inside], ic[inside]]
        np.testing.assert_array_equal(np.isfinite(values), expected)
        # Equal-area target: valid area matches the source's ellipsoidal valid area closely.
        geod = CRS.from_epsg(4269).get_geod()
        source_area = sum(abs(geod.polygon_area_perimeter(
            [WEST, WEST + RES, WEST + RES, WEST], [NORTH - (r + 1) * RES] * 2 + [NORTH - r * RES] * 2)[0])
            * source_valid[r].sum() for r in range(ROWS))
        output_area = np.isfinite(values).sum() * receipt['cell_m'] ** 2
        self.assertLess(abs(output_area / source_area - 1), 0.02)

    def test_datum_vertical_crs_units_and_cell_rule_are_recorded(self):
        receipt = self.project()
        self.assertEqual(receipt['target_crs'], 'EPSG:3310')
        self.assertEqual(receipt['source_crs']['horizontal'], 'EPSG:4269')
        self.assertEqual(receipt['source_crs']['datum'], 'North American Datum 1983')
        self.assertEqual(receipt['datum_transformation'], 'none: same geodetic datum, projection only')
        self.assertNotIn('helmert', receipt['operation'])
        self.assertEqual(receipt['vertical_crs'], 'NAVD88 height (EPSG:5703)')
        self.assertEqual(receipt['vertical_units'], 'metre')
        self.assertEqual(receipt['resampling'], 'bilinear')
        self.assertGreaterEqual(receipt['cell_m'], receipt['source_spacing_m']['max'])
        self.assertLess(receipt['cell_m'], receipt['source_spacing_m']['max'] + rg.CELL_STEP_M + 1e-9)
        self.assertEqual(receipt['cell_m'], 1.2)    # 1e-5 deg latitude is about 1.11 m here
        with rasterio.open(receipt['path']) as out:
            self.assertEqual(out.crs.to_epsg(), 3310)
            self.assertEqual(out.tags()['vertical_crs'], 'NAVD88 height (EPSG:5703)')
            self.assertEqual(out.tags(1)['units'], 'metre')
            self.assertEqual(out.res, (1.2, 1.2))
            self.assertEqual(out.transform.c % 1.2 < 1e-6 or 1.2 - out.transform.c % 1.2 < 1e-6, True)
        # NAD83(2011) stays on NAD83(2011): California Albers EPSG:6414, still no datum step.
        realized = write_tile(self.root / 'nad83-2011.tif', crs='EPSG:6318')
        self.assertEqual(self.project(realized, self.root / 'o2')['target_crs'], 'EPSG:6414')
        self.assertEqual(self.project(realized, self.root / 'o2')['vertical_crs'], 'undeclared in source')

    def test_refusals_never_guess_or_convert(self):
        refusals = {
            'no-crs.tif': dict(crs=None),
            'wgs84.tif': dict(crs='EPSG:4326'),                       # needs a datum change
            'feet.tif': dict(crs=CRS.from_wkt(CRS.from_epsg(4269).to_wkt()).to_wkt()),
        }
        for name, kwargs in refusals.items():
            with self.subTest(name=name):
                path = write_tile(self.root / name, **kwargs, units='ft' if name == 'feet.tif' else None)
                with rasterio.open(path) as ds, self.assertRaises(ValueError) as caught:
                    rg.plan(ds)
                if name == 'no-crs.tif':
                    self.assertIn('no CRS', str(caught.exception))
        compound_feet = CRS.from_user_input('EPSG:4269+6360')     # NAVD88 height (ftUS)
        path = write_tile(self.root / 'vfeet.tif', crs=compound_feet)
        with rasterio.open(path) as ds, self.assertRaisesRegex(ValueError, 'not metres'):
            rg.plan(ds)
        with rasterio.open(self.tif) as ds, patch.object(rg, 'MAX_OUTPUT_PIXELS', 1000), \
                self.assertRaisesRegex(ValueError, 'huge tile'):
            rg.plan(ds)

    def test_two_runs_give_the_same_hashes(self):
        first = self.project(directory=self.root / 'a')
        second = self.project(directory=self.root / 'b')
        self.assertEqual(first['product_sha256'], second['product_sha256'])
        self.assertEqual(first['product_content_sha256'], second['product_content_sha256'])
        self.assertEqual(first['product_sha256'], sha256(Path(second['path'])))
        self.assertEqual(rg.provenance(first), rg.provenance(self.project(directory=self.root / 'a')))
        Path(first['path']).write_bytes(Path(first['path']).read_bytes() + b'x')
        with self.assertRaisesRegex(ValueError, 'cache failed verification'):
            self.project(directory=self.root / 'a')

    def test_geographic_usgs_geotiff_passes_the_native_adapter_and_records_provenance(self):
        row = {'id': 'geo-fixture', 'url': 'https://pubs.usgs.gov/geo-fixture.tif', 'kind': 'bathymetry',
               'format': 'usgs-geotiff', 'sha256': sha256(self.tif), 'bytes': self.tif.stat().st_size,
               'archive_member': 'unknown', 'vertical_datum': 'unknown', 'resolution_m': 'unknown',
               'status': 'candidate', 'license': 'unknown'}
        bounds = [WEST + 20 * RES, NORTH - 200 * RES, WEST + 260 * RES, NORTH - 20 * RES]
        # The unchanged native path still refuses a geographic grid: reprojection is explicit.
        with self.assertRaisesRegex(ValueError, 'projected raster in meters'):
            ingest(row, bounds, root=self.root, local=self.tif)
        row['format'] = 'geographic-geotiff'
        receipt, _, reused = ingest(row, bounds, root=self.root, local=self.tif)
        self.assertFalse(reused)
        self.assertEqual(receipt['horizontal_crs'], 'EPSG:3310')
        self.assertEqual(receipt['native_resolution_m'], [1.2, 1.2])
        self.assertEqual(receipt['source_sha256'], row['sha256'])
        self.assertEqual(receipt['adapter_version'], 'original-native-adapters-v1')
        projected = receipt['reprojection']
        self.assertEqual(projected['source_sha256'], row['sha256'])
        self.assertNotIn('path', projected)
        self.assertGreater(receipt['nominal_0_300ft_pixels_in_requested_bounds'], 0)
        cog = Path(self.root / 'var/seafloor/cache', row['sha256'])
        normalized = list(cog.glob('geographic-*.tif'))
        self.assertEqual(len(normalized), 1)
        self.assertEqual(sha256(normalized[0]), receipt['cog_sha256'])
        with rasterio.open(normalized[0]) as out:
            depth = out.read(1, masked=True)
        self.assertGreater(float(depth.min()), 0)         # positive-down depth of a -27.2..-14 m ramp
        self.assertLess(float(depth.max()), 27.3)
        again, _, reused = ingest(row, bounds, root=self.root)
        self.assertTrue(reused)
        self.assertEqual(again, receipt)
        qualified = qualify_row(dict(row, url='https://pubs.usgs.gov/geo-fixture.tif'), receipt,
                                rights_url='https://pubs.usgs.gov/rights', physical_only=True)
        self.assertEqual(qualified['adapter_review']['reprojection'], projected)
        self.assertIn('projected on its own datum to EPSG:3310', qualified['notes'])
        self.assertEqual(qualified['resolution_m'], 1.2)

    def test_integer_elevation_raster_with_nodata_projects_like_float(self):
        # Centimetre int16 elevations with a -32768 NoData hole and margin (same holes as the float tile).
        rows, cols = np.mgrid[0:ROWS, 0:COLS]
        lon, lat = WEST + (cols + .5) * RES, NORTH - (rows + .5) * RES
        values = np.round(ramp(lon, lat) * 100).astype('int16')
        values[100:130, 140:175] = -32768
        values[:, :7] = -32768
        int_tif = self.root / 'tile-int16.tif'
        with rasterio.open(int_tif, 'w', driver='GTiff', width=COLS, height=ROWS, count=1, dtype='int16',
                           transform=from_origin(WEST, NORTH, RES, RES), nodata=-32768,
                           crs=CRS.from_user_input('EPSG:5498').to_wkt()) as out:
            out.write(values, 1)
        as_int = self.project(int_tif, self.root / 'int')
        as_float = self.project(self.tif, self.root / 'float')
        with rasterio.open(as_int['path']) as out:
            got = out.read(1)
        with rasterio.open(as_float['path']) as out:
            expected = out.read(1)
        self.assertEqual(got.dtype, np.float32)
        self.assertTrue(np.isfinite(got).any())
        np.testing.assert_array_equal(np.isfinite(got), np.isfinite(expected))
        valid = np.isfinite(got)
        # int16 rounding is at most 0.5 cm; bilinear of rounded samples cannot exceed it.
        self.assertLess(np.abs(got[valid] / 100.0 - expected[valid]).max(), 0.006)
        self.assertEqual(as_int['output_pixels'], as_float['output_pixels'])

    def zip_row(self, members, member):
        archive = self.root / 'archive.zip'
        with zipfile.ZipFile(archive, 'w') as out:
            for name, path in members.items():
                out.write(path, name)
        return archive, {'id': 'geo-zip', 'url': 'https://pubs.usgs.gov/geo-fixture.zip', 'kind': 'bathymetry',
                         'format': 'geographic-geotiff', 'sha256': sha256(archive), 'bytes': archive.stat().st_size,
                         'archive_member': member, 'vertical_datum': 'unknown', 'resolution_m': 'unknown',
                         'status': 'candidate', 'license': 'unknown'}

    def test_geographic_archive_member_is_projected_as_a_tiff_not_reopened_as_a_zip(self):
        archive, row = self.zip_row({'a/tile.tif': self.tif}, 'a/tile.tif')
        bounds = [WEST + 20 * RES, NORTH - 200 * RES, WEST + 260 * RES, NORTH - 20 * RES]
        receipt, _, reused = ingest(row, bounds, root=self.root, local=archive)
        self.assertFalse(reused)
        self.assertEqual(receipt['source_sha256'], row['sha256'])
        self.assertEqual(receipt['horizontal_crs'], 'EPSG:3310')
        projected = receipt['reprojection']
        native = self.root / 'var/seafloor/cache' / projected['product_sha256']
        self.assertTrue((native / 'source.tif').is_file())
        self.assertFalse((native / 'source.zip').exists())

    def test_projection_is_keyed_by_the_selected_member_not_only_the_archive(self):
        other = write_tile(self.root / 'other.tif')
        with rasterio.open(other) as src:
            values = src.read(1)
            profile = src.profile
        values = np.where(values == profile['nodata'], values, values + np.float32(5))
        with rasterio.open(other, 'w', **profile) as out:
            out.write(values, 1)
        archive, row = self.zip_row({'a/tile.tif': self.tif, 'b/tile.tif': other}, 'a/tile.tif')
        bounds = [WEST + 20 * RES, NORTH - 200 * RES, WEST + 260 * RES, NORTH - 20 * RES]
        first, _, _ = ingest(row, bounds, root=self.root, local=archive)
        second, _, _ = ingest(dict(row, archive_member='b/tile.tif'), bounds, root=self.root)
        self.assertEqual(first['source_sha256'], second['source_sha256'])
        self.assertNotEqual(first['reprojection']['product_sha256'], second['reprojection']['product_sha256'])
        self.assertNotEqual(first['cog_sha256'], second['cog_sha256'])
        # Same archive hash and identical header, different bytes: prepare itself must not reuse.
        directory = self.root / 'keyed'
        directory.mkdir()
        with rasterio.open(self.tif) as ds:
            one = rg.prepare(ds, 'a' * 64, directory)
        with rasterio.open(other) as ds:
            two = rg.prepare(ds, 'a' * 64, directory)
        self.assertNotEqual(one['path'], two['path'])
        self.assertNotEqual(one['product_content_sha256'], two['product_content_sha256'])

    def test_projected_rasters_are_untouched(self):
        projected = self.root / 'utm.tif'
        with rasterio.open(projected, 'w', driver='GTiff', width=8, height=8, count=1, dtype='float32',
                           crs='EPSG:32610', transform=from_origin(690000, 3920000, 2, 2)) as out:
            out.write(np.full((8, 8), -30, 'float32'), 1)
        with rasterio.open(projected) as ds:
            self.assertFalse(rg.geographic(ds))
            with self.assertRaisesRegex(ValueError, 'only for geographic'):
                rg.plan(ds)


if __name__ == '__main__':
    unittest.main()
