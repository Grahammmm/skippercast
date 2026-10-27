"""Synthetic geometry-only BlueTopo scheme selection, no raster or network."""
import sqlite3
import struct

import pytest
from shapely.geometry import box
from shapely.ops import transform
from pyproj import Transformer

from research.scripts.enumerate_coast_prefetch import Hold, scheme_rows


def make_scheme(path, *, crs=4326, pending=False):
    geometry = box(-121.2, 35.5, -121.1, 35.6)
    if crs != 4326:
        geometry = transform(Transformer.from_crs(4326, crs, always_xy=True).transform, geometry)
    blob = b'GP\x00\x01' + struct.pack('<i', crs) + geometry.wkb
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)')
        db.execute("INSERT INTO gpkg_contents VALUES ('BlueTopo_Tile_Scheme_20261020_000000','features')")
        db.execute('CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER)')
        db.execute("INSERT INTO gpkg_geometry_columns VALUES ('BlueTopo_Tile_Scheme_20261020_000000','geom',?)", (crs,))
        db.execute('CREATE TABLE gpkg_spatial_ref_sys (srs_id INTEGER, organization TEXT, organization_coordsys_id INTEGER, definition TEXT)')
        db.execute("INSERT INTO gpkg_spatial_ref_sys VALUES (?, 'EPSG', ?, '')", (crs, crs))
        db.execute('CREATE TABLE BlueTopo_Tile_Scheme_20261020_000000 (geom BLOB, tile TEXT, Delivered_Date TEXT, GeoTIFF_Link TEXT, RAT_Link TEXT)')
        db.execute('INSERT INTO BlueTopo_Tile_Scheme_20261020_000000 VALUES (?, ?, ?, ?, ?)',
                   (blob, 'BH4545C2', None if pending else '2026-10-20', 'https://example.com/a.tiff', 'https://example.com/a.xml'))


@pytest.mark.parametrize('crs', [4326, 3857])
def test_scheme_transforms_geometry_and_assigns_all_segments(tmp_path, crs):
    path = tmp_path / 'scheme.gpkg'
    make_scheme(path, crs=crs)
    rows, pending = scheme_rows(path)
    assert len(rows) == 1 and rows[0]['segments'] == ['C1', 'C2']
    assert not pending


def test_undelivered_not_misreported_as_downloadable(tmp_path):
    path = tmp_path / 'scheme.gpkg'
    make_scheme(path, pending=True)
    with pytest.raises(Hold, match='Empty'):
        scheme_rows(path)
