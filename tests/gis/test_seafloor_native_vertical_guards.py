"""Synthetic acceptance/negative controls for the conservative native reader.

Audit #1 permits refusal rather than conversion. These tests require that path
explicitly, and pair it with accepted metre/elevation and real BAG controls in
test_seafloor_adapters.py. No sample sign is used to infer source semantics.
"""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest

import numpy as np
from pyproj import Transformer
from pyproj.crs import CompoundCRS
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.windows import Window

from skippercast.seafloor.ingest import ingest
from skippercast.seafloor.io import sha256
from skippercast.seafloor.raster import read_native


ROW = {'vertical_datum': 'NAVD88', 'id': 'synthetic', 'sha256': '0' * 64}


@contextmanager
def source(*, units=None, scale=1, offset=0, tags=None, band_tags=None,
           crs='EPSG:32610', uncertainty=False):
    data = np.array([[-25, -9999], [3, -10]], dtype='float32')
    with MemoryFile() as memory:
        with memory.open(driver='GTiff', width=2, height=2, count=2 if uncertainty else 1,
                         dtype='float32', crs=crs, nodata=-9999,
                         transform=from_origin(600000, 4000000, 2, 2)) as out:
            out.write(data, 1)
            if uncertainty:
                out.write(np.full((2, 2), .5, dtype='float32'), 2)
            out.scales = (1, scale) if uncertainty else (scale,)
            out.offsets = (0, offset) if uncertainty else (offset,)
            if units is not None:
                out.units = (None, units) if uncertainty else (units,)
            if tags:
                out.update_tags(**tags)
            if band_tags:
                out.update_tags(2 if uncertainty else 1, **band_tags)
        with memory.open() as dataset:
            yield dataset


class NativeVerticalGuardTests(unittest.TestCase):
    def read(self, dataset, **kwargs):
        return read_native(dataset, Window(0, 0, 2, 2), ROW, **kwargs)

    def test_legacy_and_explicit_metre_elevations_keep_masks_and_sign(self):
        for options in ({}, {'units': 'm'}, {'units': 'metres'},
                        {'units': 'meters', 'tags': {'z_units': 'm', 'positive': 'up'},
                         'band_tags': {'vertical_sign': 'positive_up', 'z_positive': 'up'}},
                        {'crs': CompoundCRS('synthetic NAVD88', ['EPSG:32610', 'EPSG:5703'])}):
            with self.subTest(options=options), source(**options) as dataset:
                native = self.read(dataset)
                np.testing.assert_allclose(native.depth_m, [[25, np.nan], [-3, 10]], equal_nan=True)
                np.testing.assert_array_equal(native.valid, [[True, False], [True, True]])
                self.assertEqual(native.depth_m.dtype, np.dtype('float32'))
                self.assertEqual(native.vertical_datum, 'NAVD88')
                self.assertEqual(native.transform, dataset.transform)

    def test_packing_is_refused_even_if_tags_claim_already_applied(self):
        for options in ({'scale': .01}, {'offset': 5}, {'scale': 2, 'offset': -3},
                        {'scale': -1}, {'scale': .01, 'tags': {'scale_offset_applied': 'true'}}):
            with self.subTest(options=options), source(**options) as dataset:
                with self.assertRaisesRegex(ValueError, 'unpacked'):
                    self.read(dataset)

    def test_non_metre_band_and_dataset_units_are_refused(self):
        for units in ('ft', 'feet', 'US survey foot', 'cm', 'unknown'):
            for options in ({'units': units}, {'tags': {'z_units': units}},
                            {'band_tags': {'z_units': units}},
                            {'units': 'm', 'tags': {'z_units': units}}):
                with self.subTest(options=options), source(**options) as dataset:
                    with self.assertRaisesRegex(ValueError, 'units in metres'):
                        self.read(dataset)

    def test_sign_aliases_and_conflicts_are_refused_at_either_tag_level(self):
        for key in ('vertical_sign', 'z_positive', 'positive'):
            for value in ('down', 'positive_down', 'unknown', 'north'):
                for options in ({'tags': {key: value}}, {'band_tags': {key: value}},
                                {'tags': {key: 'up'}, 'band_tags': {key: value}}):
                    with self.subTest(options=options), source(**options) as dataset:
                        with self.assertRaisesRegex(ValueError, 'positive-up'):
                            self.read(dataset)
        with source(tags={'vertical_sign': 'up', 'positive': 'down'}) as dataset:
            with self.assertRaisesRegex(ValueError, 'positive-up'):
                self.read(dataset)

    def test_vertical_crs_cannot_hide_feet_or_positive_down_axis(self):
        for code, message in (('EPSG:6360', 'units in metres'), ('EPSG:5715', 'positive-up')):
            crs = CompoundCRS('synthetic vertical CRS', ['EPSG:32610', code])
            with self.subTest(code=code), source(crs=crs) as dataset:
                with self.assertRaisesRegex(ValueError, message):
                    self.read(dataset)

    def test_uncertainty_must_also_be_unpacked_metres_when_requested(self):
        for options, message in (({'units': 'ft'}, 'units in metres'),
                                 ({'scale': .01}, 'unpacked'), ({'offset': 1}, 'unpacked'),
                                 ({'band_tags': {'z_units': 'ft'}}, 'units in metres')):
            with self.subTest(options=options), source(uncertainty=True, **options) as dataset:
                # An unused ancillary band must not change the elevation read.
                self.assertEqual(self.read(dataset).depth_m[0, 0], 25)
                with self.assertRaisesRegex(ValueError, message):
                    self.read(dataset, uncertainty_band=2)
        with source(uncertainty=True, units='m') as dataset:
            native = self.read(dataset, uncertainty_band=2)
            self.assertEqual(native.uncertainty_m[0, 0], .5)
            self.assertTrue(np.isnan(native.uncertainty_m[0, 1]))

    def test_ingest_refusal_leaves_no_normalized_cog_or_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'synthetic.tif'
            with rasterio.open(path, 'w', driver='GTiff', width=2, height=2, count=1,
                               dtype='float32', crs='EPSG:32610', nodata=-9999,
                               transform=from_origin(600000, 4000000, 2, 2)) as out:
                out.write(np.full((2, 2), -100, dtype='float32'), 1)
                out.units = ('ft',)
            row = dict(ROW, url='https://pubs.usgs.gov/synthetic.tif', kind='bathymetry',
                       format='usgs-geotiff', sha256=sha256(path), bytes=path.stat().st_size,
                       archive_member='unknown', resolution_m=2)
            tr = Transformer.from_crs(32610, 4326, always_xy=True)
            bounds = [*tr.transform(599990, 3999990), *tr.transform(600010, 4000010)]
            with self.assertRaisesRegex(ValueError, 'units in metres'):
                ingest(row, bounds, root=root, local=path)
            cache = root / 'var/seafloor/cache'
            # fetch_source retains its verified original-source receipt. A
            # normalized output receipt must never be emitted for a refusal.
            self.assertEqual([p.name for p in cache.rglob('*.json')], ['source.json'])
            self.assertEqual(list(cache.rglob('*.working.tif')), [])
            self.assertEqual(list(cache.rglob('*.part.tif')), [])
            # The byte-verified cached original is retained, never relabelled.
            self.assertEqual([sha256(p) for p in cache.rglob('*.tif')], [row['sha256']])


if __name__ == '__main__':
    unittest.main()
