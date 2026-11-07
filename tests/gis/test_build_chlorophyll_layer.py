"""Chlorophyll overlay builder (MAPLAYER-CHLR-1): style-4 colours, gaps stay empty, georeference, private output."""
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts import build_chlorophyll_layer as cl

ROOT = Path(cl.__file__).resolve().parents[1]
BOUNDS = (-122.0, 35.0, -121.0, 36.0)


def axes():
    return np.arange(34.9, 36.11, 0.0375), np.arange(-122.1, -120.89, 0.0375)


def pixel_of(lon, lat, shape):
    height, width = shape[:2]
    west, south, east, north = BOUNDS
    x = (math.radians(lon) - math.radians(west)) / (math.radians(east) - math.radians(west))
    y = (cl.mercator_y(north) - cl.mercator_y(lat)) / (cl.mercator_y(north) - cl.mercator_y(south))
    return int(y * height), int(x * width)


class RenderTest(unittest.TestCase):
    def test_value_maps_to_style_4_turbo_on_a_log_scale_with_opacity(self):
        lats, lons = axes()
        rgba = cl.render(lats, lons, np.full((len(lats), len(lons)), 1.0), BOUNDS, px_m=2000)
        row, col = rgba.shape[0] // 2, rgba.shape[1] // 2
        position = (math.log10(1.0) - math.log10(cl.VMIN)) / (math.log10(cl.VMAX) - math.log10(cl.VMIN))
        expected = np.round(cl.turbo(np.array(position))).astype(int)
        self.assertEqual(rgba[row, col, :3].tolist(), expected.tolist())
        self.assertEqual(rgba[row, col, 3], round(cl.OPACITY * 255))

    def test_scale_ends_use_the_first_and_last_colour(self):
        self.assertEqual(np.round(cl.turbo(np.array(0.0))).astype(int).tolist(), [48, 18, 59])
        self.assertEqual(np.round(cl.turbo(np.array(1.0))).astype(int).tolist(), [122, 4, 3])

    def test_a_gap_is_transparent_and_never_filled(self):
        lats, lons = axes()
        values = np.full((len(lats), len(lons)), 0.5)
        values[8:24, 8:24] = np.nan     # a cloud hole well inside the box
        rgba = cl.render(lats, lons, values, BOUNDS, px_m=1000)
        row, col = pixel_of(float(lons[16]), float(lats[16]), rgba.shape)
        self.assertEqual(rgba[row, col].tolist(), [0, 0, 0, 0])
        self.assertTrue((rgba[..., 3] > 0).any())

    def test_isolated_missing_cell_stays_transparent(self):
        values = np.full((2, 2), 0.5)
        values[0, 0] = np.nan
        lats, lons = np.array([35.0, 36.0]), np.array([-122.0, -121.0])
        rgba = cl.render(lats, lons, values, BOUNDS, px_m=20000)
        h, w = rgba.shape[:2]
        # pixel nearest the missing node (fractional index ~0.4 from it, other three neighbours valid)
        self.assertEqual(rgba[int(h * .6), int(w * .4)].tolist(), [0, 0, 0, 0])
        self.assertGreater(rgba[int(h * .2), int(w * .8)][3], 0)

    def test_cells_are_placed_by_web_mercator_position(self):
        lats, lons = axes()
        values = np.full((len(lats), len(lons)), np.nan)
        i, j = 14, 14                    # a 2x2 valid block, so it survives the half-weight edge
        values[i:i + 2, j:j + 2] = 8.0
        rgba = cl.render(lats, lons, values, BOUNDS, px_m=500)
        rows, cols = np.nonzero(rgba[..., 3])
        lat_mid = float(lats[i:i + 2].mean())
        lon_mid = float(lons[j:j + 2].mean())
        want_row, want_col = pixel_of(lon_mid, lat_mid, rgba.shape)
        self.assertLess(abs(rows.mean() - want_row), 3)
        self.assertLess(abs(cols.mean() - want_col), 3)

    def test_all_gaps_make_an_empty_image(self):
        lats, lons = axes()
        rgba = cl.render(lats, lons, np.full((len(lats), len(lons)), np.nan), BOUNDS, px_m=2000)
        self.assertFalse(rgba.any())


class BuildTest(unittest.TestCase):
    def receipt(self):
        samples = []
        for lat in np.arange(35.0, 36.0, 0.0375):
            for lon in np.arange(-122.0, -121.0, 0.0375):
                samples.append({'time': '2026-11-04T12:00:00Z', 'latitude': round(float(lat), 5), 'longitude': round(float(lon), 5),
                                'chlorophyll': None if lon > -121.5 else 0.3})
        return {'sample_at': '2026-11-04T12:00:00Z', 'samples': samples, 'dataset': 'x/V2026308.nc', 'title': 'T',
                'license': 'NOAA public data; attribute NOAA CoastWatch', 'native_resolution_degrees': [.0375, .0375], 'query_url': 'u'}

    def test_receipt_rebuild_writes_a_png_and_honest_metadata_to_the_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'source.json'
            src.write_text(json.dumps(self.receipt()))
            saved = dict(cl.SECTORS)
            cl.SECTORS['test'] = BOUNDS
            try:
                meta = cl.build('test', Path(tmp) / 'out', receipt=src, px_m=2000, log=lambda *_: None)
            finally:
                cl.SECTORS.clear()
                cl.SECTORS.update(saved)
            out = Path(tmp) / 'out' / 'test'
            self.assertEqual((out / 'chlorophyll.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
            on_disk = json.loads((out / 'chlorophyll.json').read_text())
            self.assertEqual(on_disk, meta)
            self.assertEqual(meta['sample_at'], '2026-11-04T12:00:00Z')
            self.assertEqual(meta['max_age_hours'], 96)
            self.assertEqual(meta['units'], 'mg m-3')
            self.assertLess(meta['valid_cells'], meta['total_cells'])
            self.assertIn('NOT FOR NAVIGATION', meta['label'])
            self.assertEqual(len(meta['style']['legend']), 13)

    def test_pilot_sector_exists_and_default_output_is_the_private_var_dir(self):
        self.assertIn('central-coast', cl.SECTORS)
        self.assertEqual(cl.DEFAULT_OUTPUT, ROOT / 'var' / 'chlorophyll')
        ignore = (ROOT / '.gitignore').read_text().splitlines()
        self.assertIn('var/', ignore)


if __name__ == '__main__':
    unittest.main()
