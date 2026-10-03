"""Geographic/native grid inspection preserves values; qualification stays held."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from pyproj import CRS, Transformer
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

from research.scripts.inspect_native_grid_units import geometry, inspect, main
from skippercast.seafloor.raster import bounds_window

def fixture(path, *, crs='EPSG:5498', transform=None, values=None):
    values = np.array([[-4., -91.44, -92., 0.], [-9999., -20., 1., -7.]], dtype='float64') if values is None else values
    transform = from_origin(-121.75, 36.15, .000009, .000009) if transform is None else transform
    with rasterio.open(path, 'w', driver='GTiff', crs=crs, transform=transform,
                       width=values.shape[1], height=values.shape[0], count=1,
                       dtype=values.dtype, nodata=-9999) as output:
        output.write(values, 1)
    return values


def run(path, bounds, **kwargs):
    return inspect(path, bounds, value_convention='elevation-m-positive-up', vertical_datum='NAVD88 (caller-reviewed)', **kwargs)


class NativeGridTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, source, output):
        with patch('sys.argv', ['inspect', '--source', str(source), '--output', str(output),
                               '--bounds', '-121.751', '36.149', '-121.749', '36.151',
                               '--value-convention', 'elevation-m-positive-up',
                               '--vertical-datum', 'unknown']):
            main()

    def test_cli_predictable_temporary_collision_preserves_original(self):
        path = self.root/'receipt.json.tmp'
        fixture(path)
        original = path.read_bytes()
        output = self.root/'receipt.json'
        self.cli(path, output)
        assert path.read_bytes() == original
        import json
        assert json.loads(output.read_text())['source_sha256'] == hashlib.sha256(original).hexdigest()
        assert not list(self.root.glob('.receipt.json.*.tmp'))

    def test_cli_refuses_output_source_and_existing_file_aliases(self):
        path = self.root/'source.tif'
        fixture(path)
        original = path.read_bytes()
        symlink, hardlink = self.root/'symlink.json', self.root/'hardlink.json'
        symlink.symlink_to(path)
        hardlink.hardlink_to(path)
        for output in (path, symlink, hardlink):
            with self.subTest(output=output), pytest.raises(SystemExit) as failure:
                self.cli(path, output)
            assert failure.value.code == 2
            assert path.read_bytes() == original

    def test_geographic_compound_crs_spacing_depth_and_masks_stay_native(self):
        tmp_path = self.root
        path = tmp_path/'original.tif'
        values = fixture(path)
        original = path.read_bytes()
        bounds = [-121.751, 36.149, -121.749, 36.151]
        receipt = run(path, bounds)
        assert path.read_bytes() == original
        assert receipt['horizontal_axis_units'] == ['degree', 'degree']
        assert receipt['native_coordinate_spacing'] == [.000009, .000009]
        assert 'native_resolution_m' not in receipt
        assert 'projected_grid_spacing_m' not in receipt
        dx, dy = receipt['ellipsoidal_pixel_spacing_m_range']
        assert .80 < dx[0] <= dx[1] < .82
        assert .99 < dy[0] <= dy[1] < 1.01
        assert receipt['valid_pixels_in_requested_bounds'] == 7
        assert receipt['nominal_0_300ft_valid_grid_pixels'] == 4
        assert receipt['native_values_sha256'] == hashlib.sha256(values.tobytes()).hexdigest()
        assert receipt['native_masks_sha256'] == hashlib.sha256(np.where(values == -9999, 0, 255).astype('uint8').tobytes()).hexdigest()
        assert receipt['measured_support'] == 'unverified'
        assert not any(receipt[k] for k in ('terrain_eligible', 'exportable', 'coverage_credit'))
        with rasterio.open(path) as source:
            assert receipt['native_window_affine'] == list(source.transform)
            # The production safeguard is untouched: this is NOT a terrain adapter.
            with pytest.raises(ValueError, match='projected raster in meters'):
                bounds_window(source, bounds)

    def test_half_open_center_bounds_and_adjacent_windows_do_not_double_count(self):
        tmp_path = self.root
        path = tmp_path/'native.tif'
        fixture(path)
        tr = from_origin(-121.75, 36.15, .000009, .000009)
        left, bottom = tr*(.5, 1.5)
        right, top = tr*(2.5, .5)
        whole = run(path, [left, bottom, right, top])
        seam = tr*(1.5, .5)
        a = run(path, [left, bottom, seam[0], top])
        b = run(path, [seam[0], bottom, right, top])
        assert whole['valid_pixels_in_requested_bounds'] == 1
        assert a['valid_pixels_in_requested_bounds'] + b['valid_pixels_in_requested_bounds'] == 1
        assert a['nominal_0_300ft_valid_grid_pixels'] + b['nominal_0_300ft_valid_grid_pixels'] == whole['nominal_0_300ft_valid_grid_pixels']

    def test_projected_units_are_explicitly_converted_not_assumed(self):
        tmp_path = self.root
        for crs, spacing in [('EPSG:32610', 2.), ('EPSG:2227', 6.)]:
            path = tmp_path/'projected.tif'
            transform = from_origin(690000, 3920000, spacing, spacing) if crs.endswith('32610') else from_origin(6100000, 2100000, spacing, spacing)
            fixture(path, crs=crs, transform=transform)
            with rasterio.open(path) as source:
                bounds = Transformer.from_crs(crs, 4326, always_xy=True).transform_bounds(*source.bounds, densify_pts=41)
                window, _, result = geometry(source, bounds, 100)
                factor = CRS.from_user_input(crs).axis_info[0].unit_conversion_factor
                assert result['projected_grid_spacing_m'] == [spacing*factor]*2
                assert window == Window(0, 0, 4, 2)
                assert 'ellipsoidal_pixel_spacing_m_range' not in result

    def test_pixel_bound_disjoint_window_and_rotated_grid_refused(self):
        tmp_path = self.root
        path = tmp_path/'grid.tif'
        fixture(path)
        with pytest.raises(ValueError, match='pixel bound'):
            run(path, [-121.751, 36.149, -121.749, 36.151], max_pixels=7)
        with pytest.raises(ValueError, match='does not intersect'):
            run(path, [-120., 35., -119., 36.])
        from affine import Affine
        fixture(path, transform=Affine(.000009, .000001, -121.75, 0, -.000009, 36.15))
        with pytest.raises(ValueError, match='north-up'):
            run(path, [-121.751, 36.149, -121.749, 36.151])

    def test_spacing_samples_large_row_windows_in_bounded_blocks(self):
        tmp_path = self.root
        path = tmp_path/'tall.tif'
        fixture(path, values=np.full((9000, 1), -10., dtype='float32'))
        with rasterio.open(path) as source:
            window, crs, result = geometry(source, list(source.bounds), 10_000)
            assert window.height == 9000
            dx = result['ellipsoidal_pixel_spacing_m_range'][0]
            geod = crs.get_geod()
            expected = sorted(abs(geod.inv(-121.75, lat, -121.749991, lat)[2]) for lat in (source.bounds.bottom, source.bounds.top))
            assert np.allclose(dx, expected, rtol=1e-8)
