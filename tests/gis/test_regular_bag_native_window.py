"""Original BAG window reads retain source values and reject unsafe inputs."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin
from rasterio.windows import Window

from skippercast.seafloor.adapters import regular_bag_window as native_bag
from skippercast.seafloor.io import sha256


class OriginalBagWindowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bag = self.root/'H11879_MB_2m_MLLW_1of5.bag'
        self.xml = self._make_original_bag(self.bag)
        self.row = {'id': 'fixture-source', 'title': self.bag.name,
                    'url': 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/' + self.bag.name,
                    'format': 'bag', 'kind': 'bathymetry', 'sha256': sha256(self.bag),
                    'horizontal_crs': 'EPSG:26911', 'vertical_datum': 'MLLW', 'resolution_m': 2}
        self.metadata_hash = hashlib.sha256(self.xml.encode()).hexdigest()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _make_original_bag(destination, spacing=2):
        tif = destination.with_suffix('.tif')
        elevation = np.full((6, 6), -10, dtype='float32')
        uncertainty = np.full((6, 6), .25, dtype='float32')
        elevation[0, 1] = -7.0
        elevation[0, 2] = -92.0
        uncertainty[0, 3] = 0
        uncertainty[0, 4] = 1.2
        elevation[0, 5] = -9999
        uncertainty[0, 5] = -9999
        with rasterio.open(tif, 'w', driver='GTiff', width=6, height=6, count=2,
                           dtype='float32', crs='EPSG:26911',
                           transform=from_origin(432000, 3702000, spacing, spacing), nodata=-9999) as writer:
            writer.write(elevation, 1)
            writer.write(uncertainty, 2)
        raster_copy(tif, destination, driver='BAG')
        vertical = ('VERT_CS["MLLW depth", VERT_DATUM["Mean Lower Low Water",2005, '
                    'AUTHORITY["EPSG","1089"]], UNIT["metre",1,AUTHORITY["EPSG","9001"]]]')
        with h5py.File(destination, 'r+') as original:
            root = original['BAG_root']
            metadata = root['metadata']
            xml = metadata[:].tobytes().decode().rstrip('\0')
            xml = xml.replace('VERT_CS["unknown", VERT_DATUM["unknown", 2000]]', vertical)
            xml = xml.replace('<gco:CharacterString>unknown</gco:CharacterString>',
                              '<gco:CharacterString>H11879 synthetic metadata</gco:CharacterString>', 1)
            xml = xml.replace('codeListValue="unknown">unknown</bag:BAG_VertUncertCode>',
                              'codeListValue="productUncert">productUncert</bag:BAG_VertUncertCode>')
            xml = xml.replace('</gmi:MI_Metadata>',
                '<gml:beginPosition>2020-01-01</gml:beginPosition>'
                '<gml:endPosition>2020-01-02</gml:endPosition></gmi:MI_Metadata>')
            encoded = np.frombuffer(xml.encode(), dtype='S1')
            del root['metadata']
            root.create_dataset('metadata', data=encoded, dtype='S1',
                                maxshape=(None,), chunks=True)
        return xml

    def read(self, window=Window(0, 0, 6, 6), **kwargs):
        kwargs.setdefault('expected_metadata_sha256', self.metadata_hash)
        return native_bag.read_original_regular_bag_window(
            self.bag, self.row, window, **kwargs)

    def test_direct_window_preserves_original_pairs_affine_and_absolute_cell_ids(self):
        result = self.read(Window(2, 1, 3, 4))
        self.assertEqual(result.spacing_m, (2, 2))
        self.assertEqual(result.horizontal_crs.to_epsg(), 26911)
        self.assertEqual(result.vertical_datum, 'MLLW')
        self.assertEqual(result.transform.c, 432004)
        self.assertEqual(result.transform.f, 3701998)
        self.assertEqual(result.cell_id(0, 0), 'H11879:2m:1of5:1:2')
        self.assertEqual(result.elevation_m[0, 0], -10)
        self.assertEqual(result.depth_m_positive_down[0, 0], 10)
        self.assertEqual(result.product_uncertainty_m[0, 0], .25)
        self.assertTrue(result.qualifies_25_300ft_uncertainty_0_1m[0, 0])

    def test_depth_and_product_uncertainty_rules_are_direct_per_cell(self):
        result = self.read()
        np.testing.assert_array_equal(result.qualifies_25_300ft_uncertainty_0_1m[0],
                                      [True, False, False, False, False, False])
        self.assertFalse(result.source_pair_valid[0, 5])
        self.assertTrue(result.source_pair_valid[0, 3])
        self.assertEqual(result.product_uncertainty_m[0, 3], 0)

    def test_original_sha_metadata_datum_and_product_uncertainty_are_required(self):
        with self.assertRaisesRegex(ValueError, 'source hash'):
            native_bag.read_original_regular_bag_window(
                self.bag, dict(self.row, sha256='0'*64), Window(0, 0, 2, 2),
                expected_metadata_sha256=self.metadata_hash)
        with self.assertRaisesRegex(ValueError, 'metadata hash'):
            self.read(expected_metadata_sha256='0'*64)
        with self.assertRaisesRegex(ValueError, 'datum must be MLLW'):
            native_bag.read_original_regular_bag_window(
                self.bag, dict(self.row, vertical_datum='NAVD88'), Window(0, 0, 2, 2),
                expected_metadata_sha256=self.metadata_hash)

    def test_unknown_embedded_uncertainty_semantics_are_rejected(self):
        with h5py.File(self.bag, 'r+') as original:
            root = original['BAG_root']
            xml = root['metadata'][:].tobytes().decode().rstrip('\0')
            xml = xml.replace('productUncert', 'unknown')
            encoded = np.frombuffer(xml.encode(), dtype='S1')
            del root['metadata']
            root.create_dataset('metadata', data=encoded, dtype='S1',
                                maxshape=(None,), chunks=True)
        self.row['sha256'] = sha256(self.bag)
        metadata_hash = hashlib.sha256(xml.encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'productUncert semantics'):
            native_bag.read_original_regular_bag_window(
                self.bag, self.row, Window(0, 0, 2, 2),
                expected_metadata_sha256=metadata_hash)

    def test_unproved_spacing_or_crs_and_variable_resolution_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'reviewed metre CRS'):
            native_bag.read_original_regular_bag_window(
                self.bag, dict(self.row, horizontal_crs='EPSG:32610'), Window(0, 0, 2, 2),
                expected_metadata_sha256=self.metadata_hash)
        with self.assertRaisesRegex(ValueError, 'native spacing'):
            native_bag.read_original_regular_bag_window(
                self.bag, dict(self.row, resolution_m=4), Window(0, 0, 2, 2),
                expected_metadata_sha256=self.metadata_hash)
        false_spacing_name = dict(
            self.row,
            title='H11879_MB_4m_MLLW_1of5.bag',
            url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/H11879_MB_4m_MLLW_1of5.bag',
        )
        with self.assertRaisesRegex(ValueError, 'native spacing'):
            native_bag.read_original_regular_bag_window(
                self.bag, false_spacing_name, Window(0, 0, 2, 2),
                expected_metadata_sha256=self.metadata_hash)
        with h5py.File(self.bag, 'r+') as original:
            original['BAG_root'].create_dataset('varres_refinements', data=np.ones((1, 2)))
        self.row['sha256'] = sha256(self.bag)
        with self.assertRaisesRegex(ValueError, 'Variable-resolution'):
            self.read()

    def test_coarse_original_spacing_and_repackaged_tiff_are_rejected(self):
        coarse = self.root/'H11879_MB_5m_MLLW_1of5.bag'
        coarse_xml = self._make_original_bag(coarse, spacing=5)
        coarse_row = dict(self.row, title=coarse.name,
                          url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/' + coarse.name,
                          sha256=sha256(coarse), resolution_m=5)
        with self.assertRaisesRegex(ValueError, 'native spacing'):
            native_bag.read_original_regular_bag_window(
                coarse, coarse_row, Window(0, 0, 2, 2),
                expected_metadata_sha256=hashlib.sha256(coarse_xml.encode()).hexdigest())

        repackaged = self.root/'cached-product.bag'
        with rasterio.open(repackaged, 'w', driver='GTiff', width=6, height=6, count=2,
                           dtype='float32', crs='EPSG:26911',
                           transform=from_origin(432000, 3702000, 2, 2)) as writer:
            writer.write(np.full((6, 6), -10, dtype='float32'), 1)
            writer.write(np.full((6, 6), .25, dtype='float32'), 2)
        repackaged_row = dict(self.row, sha256=sha256(repackaged))
        with self.assertRaisesRegex(ValueError, 'authenticate original BAG structure'):
            native_bag.read_original_regular_bag_window(
                repackaged, repackaged_row, Window(0, 0, 2, 2),
                expected_metadata_sha256=self.metadata_hash)

    def test_over_cap_window_is_rejected_before_any_pixel_read(self):
        with patch.object(rasterio.io.DatasetReader, 'read', side_effect=AssertionError('pixel read occurred')):
            with self.assertRaisesRegex(ValueError, '262144 full-cell slots'):
                self.read(Window(0, 0, 513, 512))


if __name__ == '__main__':
    unittest.main()
