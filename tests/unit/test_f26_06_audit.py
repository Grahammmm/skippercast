"""F26-06: select native cell centers within 25 m of the actual camera point."""
from math import dist
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.gis


@pytest.fixture
def terrain():
    import numpy as np
    from pyproj import Transformer
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    from research.scripts import audit_camera_native_terrain as audit

    # Unique depths identify the actual selected cells, not just their count.
    elevation = -10 - np.arange(31 * 31, dtype='float32').reshape(31, 31) / 128
    elevation[15, 12] = -20
    elevation[15, 21] = -40  # 24 m east of the center of the containing cell.
    uncertainty = np.full_like(elevation, 0.5)
    with MemoryFile() as memory, memory.open(
        driver='GTiff', width=31, height=31, count=2, dtype='float32',
        transform=from_origin(100, 200, 4, 4),
    ) as raster:
        raster.write(elevation, 1)
        raster.write(uncertainty, 2)
        yield audit, raster, Transformer.from_pipeline('+proj=noop')


def _circle_cells(raster, point):
    # Independent full-grid oracle: no window, padding, or pixel-index distances.
    return [(row, col) for row in range(raster.height) for col in range(raster.width)
            if dist(point, raster.xy(row, col)) <= 25]


@pytest.mark.parametrize(('dx', 'deepest_m'), [(-1.75, 20), (1.75, 40)])
def test_same_pixel_camera_positions_select_different_cells(terrain, dx, deepest_m):
    import numpy as np

    audit, raster, projector = terrain
    cx, cy = raster.xy(15, 15)
    point = (cx + dx, cy + 1.25)
    assert raster.index(*point) == (15, 15)
    cells = _circle_cells(raster, point)
    depth = -raster.read(1)[tuple(zip(*cells))]
    assert depth.max() == deepest_m

    # Observe the selected cells and offsets without replacing the real fit.
    with patch.object(audit, 'fit_terrain', wraps=audit.fit_terrain) as fit:
        result = audit.sample(raster, *point, projector)
    assert result['local_depth_m_mllw_range'] == [round(float(depth.min()), 2), deepest_m]
    assert result['qualified_native_cells'] == len(cells)
    assert result['qualified_fraction'] == 1.0
    elevation, _, east, north, within = fit.call_args.args
    np.testing.assert_array_equal(-elevation[within], depth)
    expected_offsets = np.array([raster.xy(*cell) for cell in cells]) - point
    np.testing.assert_allclose(np.column_stack((east[within], north[within])), expected_offsets)


def test_camera_circle_retains_ninety_percent_support_gate(terrain):
    audit, raster, projector = terrain
    point = raster.xy(15, 15)
    cells = _circle_cells(raster, point)
    uncertainty = raster.read(2)
    # One invalid native cell separates the two sides of the unchanged gate.
    max_missing = len(cells) // 10
    for cell in cells[:max_missing]:
        uncertainty[cell] = 2
    raster.write(uncertainty, 2)
    result = audit.sample(raster, *point, projector)
    assert result['qualified_native_cells'] == len(cells) - max_missing
    assert result['qualified_fraction'] == round((len(cells) - max_missing) / len(cells), 4)

    uncertainty[cells[max_missing]] = 2
    raster.write(uncertainty, 2)
    with pytest.raises(ValueError, match='depth/uncertainty neighborhood is incomplete'):
        audit.sample(raster, *point, projector)
