"""Offline controls for the CRS boundary of the NOAA hard-context inventory."""
import json
import sqlite3
import struct
from contextlib import closing

import pytest

pytestmark = pytest.mark.gis
LAYER = 'Modeling_Tile_Scheme_fixture'


@pytest.fixture
def run_inventory(tmp_path):
    from pyproj import CRS, Transformer
    from shapely.geometry import box, mapping

    from research.scripts.inventory_nbs_hard_footprint_tiles import COASTS, inventory

    contexts = {}
    for coast in COASTS:
        path = tmp_path / f'{coast}.geojson'
        feature = {
            'type': 'Feature', 'geometry': mapping(box(11, 21, 12, 22)),
            'properties': {'id': 'outline', 'block_id': 'block', 'fishing_target': False,
                           'exportable': False},
        }
        path.write_text(json.dumps({
            'type': 'FeatureCollection', 'scope': 'generalized-statewide-usgs-hard-bottom-context',
            'coast_id': coast, 'features': [feature] if coast == COASTS[0] else [],
        }))
        contexts[coast] = path
    sectors = {'sectors': [{'id': str(i), 'coast': COASTS[i % len(COASTS)],
                            'latitude': [21, 22] if i == 0 else [0, 1]} for i in range(19)]}

    def run(*, epsg=4326, definition_epsg=None, byte_order='<', edit=None, overlap=True):
        scheme = tmp_path / 'tiles.gpkg'
        geom = box(10, 20, 13, 23) if overlap else box(30, 40, 33, 43)
        if epsg != 4326:
            geom = box(*Transformer.from_crs(4326, epsg, always_xy=True).transform_bounds(*geom.bounds))
        x0, y0, x1, y1 = geom.bounds
        header = struct.pack(f'{byte_order}2sBBi', b'GP', 0, int(byte_order == '<'), epsg)
        with closing(sqlite3.connect(scheme)) as db, db:
            db.execute('CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INTEGER)')
            db.execute('INSERT INTO gpkg_contents VALUES (?, ?, ?)', (LAYER, 'features', epsg))
            db.execute('CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, srs_id INTEGER)')
            db.execute('INSERT INTO gpkg_geometry_columns VALUES (?, ?, ?)', (LAYER, 'geom', epsg))
            db.execute('CREATE TABLE gpkg_spatial_ref_sys (srs_id INTEGER, organization TEXT, '
                       'organization_coordsys_id INTEGER, definition TEXT)')
            db.execute('INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?)',
                       (epsg, 'EPSG', epsg, CRS.from_epsg(definition_epsg or epsg).to_wkt('WKT1_GDAL')))
            db.execute(f'CREATE TABLE {LAYER} (fid INTEGER PRIMARY KEY, tile TEXT, Resolution TEXT, '
                       'GeoTIFF_Link TEXT, RAT_Link TEXT, geom BLOB)')
            db.execute(f'INSERT INTO {LAYER} VALUES (1, ?, ?, ?, ?, ?)',
                       ('FIXTURE', '2m', 'https://example.invalid/tif', 'https://example.invalid/rat',
                        header + geom.wkb))
            db.execute(f'CREATE VIRTUAL TABLE rtree_{LAYER}_geom USING rtree(id, minx, maxx, miny, maxy)')
            db.execute(f'INSERT INTO rtree_{LAYER}_geom VALUES (1, ?, ?, ?, ?)', (x0, x1, y0, y1))
            if edit:
                db.execute(edit)
        return inventory(scheme, contexts, sectors)

    return run


def test_geographic_scheme_selects_tile_and_sector(run_inventory):
    # A valid big-endian GP header is not a different CRS; sector latitude stays in degrees.
    report = run_inventory(byte_order='>')
    assert report['tile_count'] == 1
    assert [(row['tile'], row['planning_sector_ids']) for row in report['tiles']] == [('FIXTURE', ['0'])]


def test_inventory_discovers_clipped_neighboring_coast(run_inventory, tmp_path):
    from shapely.geometry import box, mapping
    from research.scripts.inventory_nbs_hard_footprint_tiles import COASTS
    from research.scripts.split_usgs_context import split

    feature = {'type': 'Feature', 'geometry': mapping(box(11, 21, 12, 24)),
               'properties': {'id': 'cross', 'block_id': 'block',
                              'fishing_target': False, 'exportable': False}}
    data = {'type': 'FeatureCollection', 'scope': 'generalized-statewide-usgs-hard-bottom-context',
            'features': [feature]}
    bands = [(20, 22), (22, 25), (25, 26), (26, 27), (27, 28)]
    shards = split(data, {'regions': [{'id': coast, 'latitude': band}
                                      for coast, band in zip(COASTS, bands)]})
    assert shards['northern']['features'] == []
    for coast, shard in shards.items():
        (tmp_path / f'{coast}.geojson').write_text(json.dumps(shard))
    tile = run_inventory()['tiles'][0]
    assert tile['coasts'] == ['mendocino', 'northern']
    assert tile['planning_sector_ids'] == ['0']
    assert tile['source_ids'] == ['block']


def test_projected_scheme_holds_instead_of_returning_an_empty_queue(run_inventory):
    # Identical footprint in metres would silently miss an untransformed lon/lat R-tree query.
    with pytest.raises(ValueError, match='unsupported CRS'):
        run_inventory(epsg=3857)


def test_projected_wkt_cannot_pass_as_geographic(run_inventory):
    # Trusting the authority ID alone would ignore a contradictory CRS definition.
    with pytest.raises(ValueError, match='unsupported CRS'):
        run_inventory(definition_epsg=3857, overlap=False)


@pytest.mark.parametrize('edit,reason', [
    ('DELETE FROM gpkg_spatial_ref_sys', 'Missing scheme CRS'),
    ('UPDATE gpkg_geometry_columns SET srs_id = 3857', 'Inconsistent scheme SRS'),
    ("UPDATE gpkg_spatial_ref_sys SET definition = 'undefined'", 'Invalid scheme CRS'),
    ('UPDATE gpkg_spatial_ref_sys SET organization_coordsys_id = 3857', 'unsupported CRS'),
    (f'UPDATE {LAYER} SET geom = CAST(x\'47500001110F0000\' || substr(geom, 9) AS BLOB)',
     'Inconsistent tile SRS'),  # 3857 in a tile header, even outside the query window.
    ("INSERT INTO gpkg_contents VALUES ('other_layer', 'features', 4326)", 'Expected one NOAA NBS'),
], ids=['missing-crs', 'conflicting-layer-ids', 'invalid-wkt', 'conflicting-authority',
        'out-of-window-header-mismatch', 'ambiguous-layer'])
def test_bad_declarations_hold_even_without_spatial_matches(run_inventory, edit, reason):
    with pytest.raises(ValueError, match=reason):
        run_inventory(edit=edit, overlap=False)


def test_valid_disjoint_scheme_can_return_an_empty_queue(run_inventory):
    # A CRS hold is not a blanket ban on genuine no-overlap results.
    assert run_inventory(overlap=False)['tiles'] == []
