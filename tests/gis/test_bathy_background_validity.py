"""Background validity must reach both the tile pipeline and coverage output."""
import json
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin

from scripts import build_bathy_tiles as bt


def test_build_excludes_masked_background_cells(tmp_path):
    source = tmp_path / 'background.tif'
    coverage = tmp_path / 'coverage.json'
    values = np.array([[-12, -12, -100, np.nan, np.inf, 4]], dtype=np.float32)
    with rasterio.open(source, 'w', driver='GTiff', width=6, height=1, count=1,
                       dtype='float32', crs='EPSG:3310',
                       transform=from_origin(-122000, -288000, 100, 100), nodata=-100) as ds:
        ds.write(values, 1)
        # A real mask hides the second shallow cell but marks even numeric nodata
        # as valid. Reading only the values or only the mask would leak a cell.
        ds.write_mask(np.array([[255, 0, 255, 255, 255, 255]], dtype=np.uint8))

    with patch.object(bt, 'zoom_windows', wraps=bt.zoom_windows) as render_input:
        bt.build(source, tmp_path / 'background.pmtiles', minzoom=13, maxzoom=13,
                 coverage_json=coverage)

    assert json.loads(coverage.read_text())['background']['cells'] == 1
    elevation = render_input.call_args.args[0]
    np.testing.assert_array_equal(elevation, [[-12, *([bt.NODATA] * 5)]])
