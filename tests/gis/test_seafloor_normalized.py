"""Lossless encoding can change; scientific pixels and metadata cannot."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin

from skippercast.seafloor.io import sha256
from skippercast.seafloor.normalized import raster_identity, verify_review


class NormalizedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.first = self.root/'reviewed.tif'
        with rasterio.open(self.first, 'w', driver='GTiff', width=96, height=128,
                           count=2, dtype='float32', crs='EPSG:32610',
                           transform=from_origin(690000, 3920000, 2, 2),
                           nodata=np.nan, tiled=True, blockxsize=16, blockysize=16) as ds:
            depth = np.full((128, 96), 50, dtype='float32')
            depth[10:20, 10:20] = np.nan
            ds.write(depth, 1)
            uncertainty = np.full_like(depth, .5); uncertainty[30:40, 30:40] = np.nan
            ds.write(uncertainty, 2)
            ds.set_band_description(1, 'depth_m_positive_down')
            ds.set_band_description(2, 'producer_uncertainty_m')
            ds.update_tags(vertical_datum='MLLW', depth_basis='nominal')
        self.second = self.root/'encoded.tif'
        raster_copy(self.first, self.second, driver='GTiff', compress='DEFLATE',
                    tiled=True, blockxsize=32, blockysize=32)
        self.review = {'source_sha256': 'a'*64, 'cog_sha256': sha256(self.first),
                       'requested_bounds_wgs84': [-121, 35, -120, 36],
                       'native_resolution_m': [2, 2], 'vertical_datum': 'MLLW',
                       'valid_pixels_in_requested_bounds': 100,
                       'nominal_0_300ft_pixels_in_requested_bounds': 100,
                       'raster_identity': raster_identity(self.first)}
        self.receipt = deepcopy(self.review); self.receipt['cog_sha256'] = sha256(self.second)

    def tearDown(self):
        self.tmp.cleanup()

    def test_different_lossless_encodings_have_identical_reviewed_science(self):
        self.assertNotEqual(sha256(self.first), sha256(self.second))
        self.assertEqual(raster_identity(self.first), raster_identity(self.second))
        verify_review(self.receipt, self.review, self.second)

    def test_changed_depth_uncertainty_mask_grid_or_datum_is_rejected(self):
        for kind in ('depth', 'uncertainty', 'mask', 'grid', 'datum'):
            with self.subTest(kind=kind):
                target = self.root/(kind+'.tif')
                raster_copy(self.second, target)
                with rasterio.open(target, 'r+') as ds:
                    if kind in ('depth', 'uncertainty'):
                        band = 1 if kind == 'depth' else 2
                        a = ds.read(band); a[0, 0] += .125; ds.write(a, band)
                    elif kind == 'mask':
                        a = np.full((128, 96), 255, dtype='uint8'); a[0, 0] = 0
                        ds.write_mask(a)
                    elif kind == 'grid':
                        ds.transform = from_origin(690002, 3920000, 2, 2)
                    else:
                        ds.update_tags(vertical_datum='NAVD88')
                with self.assertRaisesRegex(ValueError, 'scientific raster'):
                    verify_review(self.receipt, self.review, target)

    def test_changed_original_or_counts_fail_even_when_raster_is_identical(self):
        for field in ('source_sha256', 'valid_pixels_in_requested_bounds', 'vertical_datum'):
            receipt = deepcopy(self.receipt); receipt[field] = 'different'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'reviewed '+field):
                verify_review(receipt, self.review, self.second)

    def test_legacy_review_requires_exact_encoded_bytes(self):
        review = deepcopy(self.review); review.pop('raster_identity')
        with self.assertRaisesRegex(ValueError, 'content review required'):
            verify_review(self.receipt, review, self.second)
        verify_review(self.review, review, self.first)
