"""Offline runtime contracts for the coarse planning grid."""

import hashlib
from contextlib import ExitStack

import pytest


_BOUNDS = (-123.0, 37.998, -122.994, 38.003)
_X, _Y = 500_000, 4_206_400
_METHOD = (
    "Four-connected nodata components in the region-bounds window. A strict in-band hole has every valid "
    "cardinal rim cell in [-91.44, 0] m. Nodata itself has no depth. Mixed rims and edge-connected gaps "
    "are not verified shallow holes. No water mask or fill applied."
)


@pytest.fixture
def tiles(tmp_path):
    import numpy as np
    import rasterio as rio

    def write(name, values, *, spacing=16, x=_X, y=_Y, crs="EPSG:26910", nodata=np.nan):
        path = tmp_path / name
        height, width = values.shape
        with rio.open(path, "w", driver="GTiff", crs=crs, count=1, width=width, height=height,
                      dtype="float32", nodata=nodata, transform=rio.Affine(spacing, 0, x, 0, -spacing, y)) as ds:
            ds.write(values.astype("float32"), 1)
        return path, hashlib.sha256(path.read_bytes()).hexdigest(), "NAVD88-up"

    # Two real UTM GeoTIFFs. The finer patch crosses coarse cell boundaries
    # on a 2 m offset; its nodata leaves the underlying valid coarse cells intact.
    coarse = np.full((56, 56), -25, dtype="float32")
    coarse[:, 42:] = 12
    coarse[24:29, 8:13] = np.nan  # enclosed offshore absence
    coarse[37:42, :9] = np.nan  # gap open to the west
    fine = np.full((48, 48), -55, dtype="float32")
    fine[:, 24:] = -45
    fine[16:32, 16:32] = np.nan  # must not erase the valid coarse coverage below
    return write("coarse_20260102.tif", coarse), write(
        "fine_20260101.tif", fine, spacing=4, x=_X + 322, y=_Y - 66, crs="EPSG:26910+5703",
    ), coarse, fine, write


def test_C1_exact_native_mosaic_one_warp_and_halo(tiles, tmp_path):
    """C1: Wrong overlap, intermediate smoothing, or a cropped halo changes the whole grid."""
    import numpy as np
    import rasterio as rio
    from rasterio.warp import reproject

    from skippercast.relief.coarse import build_coarse

    coarse_path, fine_path, coarse, fine, write = tiles
    # Independent, materialized 2 m image of the expected native mosaic;
    # only valid fine values overwrite the known 4 m footprints.
    native = coarse.repeat(8, axis=0).repeat(8, axis=1)
    valid_fine = fine.repeat(2, axis=0).repeat(2, axis=1)
    np.copyto(native[33:129, 161:257], valid_fine, where=~np.isnan(valid_fine))
    oracle, _, _ = write("reference.tif", native, spacing=2)

    result, transform, report = build_coarse([fine_path, coarse_path], _BOUNDS, cell_m=16)
    # Projected bounds, 1 km halo, then outward snap (not the tile extent).
    assert transform == rio.Affine(16, 0, -264064, 0, -16, 3680)
    assert result.shape == (161, 160)
    assert result.dtype == np.float32
    expected = np.full(result.shape, np.nan, dtype="float32")
    with rio.open(oracle) as source:
        reproject(rio.band(source, 1), expected, dst_transform=transform, dst_crs="EPSG:3310",
                  src_nodata=np.nan, dst_nodata=np.nan, resampling=rio.enums.Resampling.bilinear,
                  num_threads=1, warp_mem_limit=128)
    np.testing.assert_array_equal(result, expected)
    assert np.isfinite(result).any()
    assert np.isnan(result).any()

    before = sorted(p.name for p in tmp_path.iterdir())
    repeat, repeat_transform, repeat_report = build_coarse([coarse_path, fine_path], _BOUNDS, cell_m=16)
    assert repeat.tobytes() == result.tobytes()
    assert (repeat_transform, repeat_report) == (transform, report)
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_C1_equal_spacing_priority_and_numeric_nodata(tiles):
    """C1: Equal-spacing precedence uses date before path; a nodata value cannot win."""
    import numpy as np

    from skippercast.relief.coarse import build_coarse

    *_, write = tiles
    old = write("Z_20260101.tif", np.full((24, 24), -70))
    new = write("B_20260102.tif", np.full((24, 24), -40))
    shadow = write("A_20260102.tif", np.full((24, 24), -20))
    missing = write("C_20260102.tif", np.full((24, 24), -9999), nodata=-9999)
    expected, transform, report = build_coarse([new], _BOUNDS, cell_m=20)
    actual, other_transform, other_report = build_coarse([missing, shadow, old, new], _BOUNDS, cell_m=20)
    np.testing.assert_array_equal(actual, expected)
    assert (other_transform, other_report) == (transform, report)
    assert np.nanmin(actual) == np.nanmax(actual) == -40
    assert other_transform.a == -other_transform.e == 20


def test_C1_pins_checked_before_any_raster_opens(tiles, monkeypatch):
    """C1: Even a wrong pin on the second tile must fail before a raster opens."""
    from skippercast.relief import coarse

    first, (path, _, vertical), *_ = tiles

    def unexpected_open(*args, **kwargs):
        pytest.fail("opened a raster before all pins passed")

    monkeypatch.setattr(coarse.rio, "open", unexpected_open)
    with pytest.raises(ValueError, match="SHA-256 mismatch") as err:
        coarse.build_coarse([first, (path, "0" * 64, vertical)], _BOUNDS, cell_m=16)
    assert type(err.value) is ValueError


@pytest.mark.parametrize("case,reason", [
    pytest.param("vertical", "Expected NAVD88-up", id="C1: refuse positive-down input"),
    pytest.param("compound", "Expected NAVD88-up", id="C1: refuse conflicting compound datum"),
    pytest.param("projection", "share one horizontal UTM CRS", id="C1: refuse mixed UTM projections"),
    pytest.param("lattice", "Unsupported native elevation grid", id="C1: refuse shifted footprint"),
    pytest.param("empty", "Expected at least one planning tile", id="C1: refuse empty tile set"),
    pytest.param("bounds", "Expected ordered WGS84 bounds", id="C1: refuse backwards bounds"),
    pytest.param("cell", "Expected a positive finite cell size", id="C1: refuse zero-sized pixels"),
])
def test_C1_refusals(tiles, case, reason):
    """C1: Unsupported inputs cannot be silently reinterpreted as valid elevations."""
    import numpy as np

    from skippercast.relief.coarse import build_coarse

    first, _, _, _, write = tiles
    inputs, bounds, cell = [first], _BOUNDS, 16
    if case == "vertical":
        inputs = [(*first[:2], "NAVD88-down")]
    elif case == "compound":
        inputs.append(write("other.tif", np.zeros((2, 2)), crs="EPSG:26910+5714"))
    elif case == "projection":
        inputs.append(write("other.tif", np.zeros((2, 2)), crs="EPSG:26911"))
    elif case == "lattice":
        inputs.append(write("other.tif", np.zeros((2, 2)), x=_X + 1))
    elif case == "empty":
        inputs = []
    elif case == "bounds":
        bounds = (0, 1, -1, -1)
    elif case == "cell":
        cell = 0
    with pytest.raises(ValueError, match=reason) as err:
        build_coarse(inputs, bounds, cell_m=cell)
    assert type(err.value) is ValueError


def test_C1_refuses_tile_modified_during_warp(tiles, monkeypatch):
    """C1: An input changed after hashing must not be accepted as the pinned tile."""
    from skippercast.relief import coarse

    first, *_ = tiles
    warp = coarse.reproject

    def mutate(*args, **kwargs):
        warp(*args, **kwargs)
        with first[0].open("ab") as out:
            out.write(b"changed after read")

    monkeypatch.setattr(coarse, "reproject", mutate)
    with pytest.raises(ValueError, match="Input changed during build") as err:
        coarse.build_coarse([first], _BOUNDS, cell_m=16)
    assert type(err.value) is ValueError


def test_C2_receipt_topology_and_order():
    """C2: Diagonal connectivity, a clipped edge, or a wrong rim threshold alters the full report."""
    import numpy as np
    from pyproj import Transformer
    from rasterio import Affine

    from skippercast.relief.coarse import _hole_report

    array = np.full((10, 12), -25, dtype="float32")
    array[2, 2] = array[3, 3] = np.nan  # diagonal: two strict holes
    array[1, 2] = -91.44
    array[2, 1] = 0
    array[6, 2:4] = np.nan  # largest strict hole, first in report
    array[2, 6] = np.nan
    array[3, 6] = 10  # land is valid but not in-band
    array[:3, 9] = np.nan
    array[6:9, 7:10] = -92
    array[7, 8] = np.nan  # enclosed and entirely deep: counted, not classified
    transform = Affine(16, 0, 0, 0, -16, 0)
    to_wgs = Transformer.from_crs(3310, 4326, always_xy=True)

    def lonlat(x, y):
        return list(map(lambda value: round(value, 7), to_wgs.transform(x, y)))

    assert _hole_report(array, transform) == {
        "method": _METHOD,
        "enclosed_total": 5,
        "strict": [
            dict(cells=2, sample_lonlat=lonlat(40, -104), window_bbox_colrow=[2, 6, 4, 7],
                 rim_cells=6, rim_in_band_cells=6),
            dict(cells=1, sample_lonlat=lonlat(40, -40), window_bbox_colrow=[2, 2, 3, 3],
                 rim_cells=4, rim_in_band_cells=4),
            dict(cells=1, sample_lonlat=lonlat(56, -56), window_bbox_colrow=[3, 3, 4, 4],
                 rim_cells=4, rim_in_band_cells=4),
        ],
        "mixed_rim": [dict(cells=1, sample_lonlat=lonlat(104, -40), window_bbox_colrow=[6, 2, 7, 3],
                           rim_cells=4, rim_in_band_cells=3)],
        "edge_connected_components_touching_band": 1,
        "edge_connected_cells_adjacent_to_band": 3,
        "edge_connected_adjacent_first_last_lonlat": [lonlat(152, -8), lonlat(152, -40)],
    }


def test_C2_no_survey_is_not_an_in_band_hole(tiles):
    """C2: A known tile outside the region cannot invent a shallow rim or edge sample."""
    import numpy as np

    from skippercast.relief.coarse import build_coarse

    first, *_ = tiles
    grid, _, report = build_coarse([first], (-122.1, 37.9, -122.09, 37.91), cell_m=16)
    np.testing.assert_array_equal(grid, np.full(grid.shape, np.nan, dtype="float32"))
    assert report == {
        "method": _METHOD, "enclosed_total": 0, "strict": [], "mixed_rim": [],
        "edge_connected_components_touching_band": 0,
        "edge_connected_cells_adjacent_to_band": 0,
        "edge_connected_adjacent_first_last_lonlat": [],
    }


def test_C2_build_reports_in_the_unbuffered_region_window(tiles):
    """C2: Using the full halo instead would shift the hole bbox and count extra edge cells."""
    from skippercast.relief.coarse import build_coarse

    first, second, *_ = tiles
    _, _, report = build_coarse([first, second], _BOUNDS, cell_m=16)
    assert report == {
        "method": _METHOD,
        "enclosed_total": 1,
        "strict": [dict(cells=25, sample_lonlat=[-122.9984047, 38.0017781],
                        window_bbox_colrow=[10, 9, 15, 14], rim_cells=20, rim_in_band_cells=20)],
        "mixed_rim": [],
        "edge_connected_components_touching_band": 1,
        "edge_connected_cells_adjacent_to_band": 53,
        "edge_connected_adjacent_first_last_lonlat": [[-123.0000979, 38.0030318], [-123.0000724, 37.9978484]],
    }


def test_C2_nonfinite_elevation_refused():
    """C2: Infinite values are not allowed to act as observed rims."""
    import numpy as np
    from rasterio import Affine

    from skippercast.relief.coarse import _hole_report

    with pytest.raises(ValueError, match="Non-finite valid elevation") as err:
        _hole_report(np.array([[np.inf]], dtype="float32"), Affine(16, 0, 0, 0, -16, 0))
    assert type(err.value) is ValueError


def test_C3_byte_repeat_and_zone_reader(tiles, tmp_path):
    """C3: A nonconforming TIFF, lost mask, changed elevation, or unstable bytes breaks the handoff."""
    import numpy as np

    from scripts.build_survey_zone import _open_grid
    from skippercast.relief.coarse import build_coarse, write_coarse

    first, second, *_ = tiles
    array, transform, _ = build_coarse([first, second], _BOUNDS, cell_m=16)
    path, twin = tmp_path / "zone.tif", tmp_path / "repeat.tif"
    assert write_coarse(path, array, transform) is None
    assert write_coarse(twin, array, transform) is None
    assert path.read_bytes() == twin.read_bytes()
    with ExitStack() as stack:
        raster = _open_grid(stack, path)
        assert (raster.driver, raster.count, raster.crs.to_epsg(), raster.dtypes, raster.transform) == (
            "GTiff", 1, 3310, ("float32",), transform,
        )
        assert (raster.units, raster.descriptions) == (("m",), ("Elevation",))
        assert raster.tags(1) == {"POSITIVE": "up", "VERTICAL_DATUM": "NAVD88 (EPSG:5703)"}
        assert np.isnan(raster.nodata)
        restored = raster.read(1, masked=True)
        np.testing.assert_array_equal(restored.mask, np.isnan(array))
        np.testing.assert_array_equal(restored.filled(np.nan), array)
