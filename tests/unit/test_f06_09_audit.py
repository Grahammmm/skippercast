"""F06-09: alignment controls must be four distinct, consistently paired locations.

Contract protected: the numerical gate counts distinct terrain/imagery control
locations, so a repeated row cannot stand in for a fourth correspondence.
Believable bug: len(control_points) >= 4 plus matrix rank 3 passes three
noncollinear points with one row repeated. The stubs below replace only the
raster stack (absent from the non-GIS job); the gate and its ordering before
the residual step are the real code.
"""
import sys
import types

import pytest

from skippercast.coastal.render import align

SQUARE = [[1, 1], [9, 1], [9, 9], [1, 9]]
THREE = SQUARE[:3]


def rows(terrain, imagery):
    return [{"terrain_pixel": list(a), "imagery_pixel": list(b)} for a, b in zip(terrain, imagery)]


class ResidualReached(Exception):
    """Raised by the stubbed reprojection, the first step after the control gate."""


class Grid(tuple):
    a, b, d, e = 1.0, 0, 0, -1.0

    def __matmul__(self, pixel):
        return pixel


class Dataset:
    driver, width, height, files = "GTiff", 20, 20, ["x"]
    crs = types.SimpleNamespace(is_projected=True, linear_units="metre")
    transform = Grid((1.0, 0, 0, 0, -1.0, 0))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Index:
    def __getitem__(self, key):
        return key


@pytest.fixture
def stubbed_raster_stack(monkeypatch):
    def reproject(*args):
        raise ResidualReached

    modules = {
        "numpy": types.SimpleNamespace(
            c_=Index(), ones=lambda n: [1] * n,
            linalg=types.SimpleNamespace(matrix_rank=lambda matrix: 3)),
        "rasterio": types.SimpleNamespace(open=lambda path: Dataset()),
        "rasterio.warp": types.SimpleNamespace(transform=reproject),
        "shapely": types.ModuleType("shapely"),
        "shapely.geometry": types.SimpleNamespace(Polygon=object),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(align, "check_geotiff", lambda path: None)
    monkeypatch.setattr(align, "identity", lambda path: {"sha256": "0" * 64, "bytes": 1})


def measure(controls):
    return align.measure_alignment("terrain.tif", "imagery.tif", controls)


def test_repeated_row_does_not_count_as_fourth_control(stubbed_raster_stack):
    with pytest.raises(ValueError, match="four_distinct_control_pairs_required"):
        measure(rows(THREE + [THREE[0]], THREE + [THREE[0]]))


def test_four_distinct_noncollinear_pairs_still_reach_residual_step(stubbed_raster_stack):
    with pytest.raises(ResidualReached):
        measure(rows(SQUARE, [[x + 0.5, y] for x, y in SQUARE]))


def test_repeat_beside_four_distinct_pairs_is_allowed_but_not_counted(stubbed_raster_stack):
    with pytest.raises(ResidualReached):
        measure(rows(SQUARE + [SQUARE[0]], SQUARE + [SQUARE[0]]))


def test_one_terrain_location_cannot_pair_with_two_imagery_locations():
    with pytest.raises(ValueError, match="inconsistent_control_pairing"):
        align.require_distinct_pairs(SQUARE + [SQUARE[0]], SQUARE + [[5, 5]])


def test_one_imagery_location_cannot_pair_with_two_terrain_locations():
    with pytest.raises(ValueError, match="inconsistent_control_pairing"):
        align.require_distinct_pairs(SQUARE + [[5, 5]], SQUARE + [SQUARE[0]])


def test_integer_and_float_spellings_of_one_pixel_are_one_location():
    with pytest.raises(ValueError, match="four_distinct_control_pairs_required"):
        align.require_distinct_pairs(THREE + [[1.0, 1.0]], THREE + [[1, 1]])
