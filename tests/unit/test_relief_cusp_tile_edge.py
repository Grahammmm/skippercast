"""Synthetic XYZ window controls for the CUSP selector used by relief water."""

from scripts.shoreline import import_cusp as cusp

# The origin of tile (X, Y) is the corner shared by these four tiles.
# Use a negative longitude and the equator, whose latitude maps exactly to Y.
Z, X, Y = 12, 1001, 2048
LON, LAT = cusp.tile_lon(X, Z), cusp.tile_lat(Y, Z)
DX = (cusp.tile_lon(X + 1, Z) - LON) / 8
DY = (LAT - cusp.tile_lat(Y + 1, Z)) / 8
CORNER_TILES = {(Z, X - 1, Y - 1), (Z, X - 1, Y), (Z, X, Y - 1), (Z, X, Y)}


def test_crop_crossing_xyz_corner_includes_all_four_adjacent_tiles():
    # Using only the crop centre, or omitting the terminal row/column, loses shoreline tiles.
    box = [LON - DX, LAT - DY, LON + DX, LAT + DY]
    assert set(cusp.tiles_for(box)) == CORNER_TILES


def test_interior_crop_does_not_include_neighbouring_tiles():
    # Rounding outwards or padding every window can require tiles the crop never reaches.
    box = [LON - 2 * DX, LAT + DY, LON - DX, LAT + 2 * DY]
    assert set(cusp.tiles_for(box)) == {(Z, X - 1, Y - 1)}


def test_crop_ending_on_east_and_south_edges_includes_touch_only_tiles():
    # Treating the east/south bounds as exclusive would omit tiles on the exact edges.
    box = [LON - DX, LAT, LON, LAT + DY]
    assert set(cusp.tiles_for(box)) == CORNER_TILES


def test_crop_starting_on_west_and_north_edges_excludes_touch_only_tiles():
    # Expanding both ends of the window on equality would also include west/north neighbours.
    box = [LON, LAT - DY, LON + DX, LAT]
    assert set(cusp.tiles_for(box)) == {(Z, X, Y)}
