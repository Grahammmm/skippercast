"""Find exact NOAA NBS tile footprints touching displayed original USGS hard context.

This is a bounded acquisition queue. Generalized USGS polygons are incomplete
historical context, and a touching tile is not a depth-qualified fishing site.
"""
import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry import shape
from shapely import wkb

COASTS = ('northern', 'mendocino', 'san-francisco', 'central', 'southern')
RESOLUTIONS = ('2m', '4m')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def gpkg_geometry(raw):
    if not raw or raw[:2] != b'GP' or raw[2] != 0:
        raise ValueError('Expected version-zero GeoPackage binary geometry')
    envelope = (raw[3] >> 1) & 7
    size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope)
    if size is None:
        raise ValueError('Unsupported GeoPackage envelope')
    geom = wkb.loads(raw[8 + size:])
    if geom.is_empty or not geom.is_valid:
        raise ValueError('Invalid NOAA tile geometry')
    return geom


def checked_scheme_layer(db):
    try:
        layers = db.execute("SELECT table_name, srs_id FROM gpkg_contents WHERE data_type='features'").fetchall()
        if (len(layers) != 1 or not isinstance(layers[0][0], str)
                or not re.fullmatch(r'Modeling_Tile_Scheme_[A-Za-z0-9_]+', layers[0][0])):
            raise ValueError('Expected one NOAA NBS Modeling tile scheme feature layer')
        name, srs = layers[0]
        columns = db.execute('SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE table_name=?',
                             (name,)).fetchall()
        if type(srs) is not int or srs in (-1, 0) or columns != [('geom', srs)]:
            raise ValueError('Inconsistent scheme SRS or missing geom declaration')
        rows = db.execute('SELECT organization, organization_coordsys_id, definition '
                          'FROM gpkg_spatial_ref_sys WHERE srs_id=?', (srs,)).fetchall()
    except sqlite3.OperationalError as error:
        raise ValueError('Missing or invalid scheme CRS metadata') from error
    if len(rows) != 1:
        raise ValueError('Missing scheme CRS or ambiguous SRS definition')
    authority, code, definition = rows[0]
    if not isinstance(definition, str) or not definition.strip():
        raise ValueError('Invalid scheme CRS definition')
    try:
        crs = CRS.from_wkt(definition)
    except CRSError as error:
        raise ValueError('Invalid scheme CRS definition') from error
    # Both the R-tree and the geometry join use GeoJSON longitude/latitude.
    if (authority, code) != ('EPSG', 4326) or not crs.equals(CRS.from_epsg(4326), ignore_axis_order=True):
        raise ValueError('NOAA tile scheme has unsupported CRS: expected WGS 84 (EPSG:4326)')

    # Check headers independently of the R-tree: a mismatched tile might be
    # outside every query window precisely because it uses the wrong CRS.
    for header, in db.execute(f'SELECT DISTINCT substr(geom, 1, 8) FROM "{name}"'):
        if not isinstance(header, bytes) or len(header) != 8 or header[:3] != b'GP\x00':
            raise ValueError('Expected version-zero GeoPackage binary geometry')
        order = 'little' if header[3] & 1 else 'big'
        if int.from_bytes(header[4:8], order, signed=True) != srs:
            raise ValueError('Inconsistent tile SRS in GeoPackage geometry header')
    return name


def inventory(scheme, context_files, sectors):
    if len(context_files) != len(COASTS) or set(context_files) != set(COASTS):
        raise ValueError('All five coast contexts required')
    if len(sectors.get('sectors', [])) != 19:
        raise ValueError('Complete 19-sector California browse partition required')
    sector_ids = {s['id'] for s in sectors['sectors']}
    references = []
    selected = defaultdict(lambda: {'coasts': set(), 'source_ids': set(), 'outlines': set(),
                                    'sector_ids': set(), 'url': None, 'rat_url': None,
                                    'resolution': None})
    with closing(sqlite3.connect(scheme.absolute().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')  # Validate and query the same scheme snapshot.
        name = checked_scheme_layer(db)
        for coast in COASTS:
            path = context_files[coast]
            context = json.loads(path.read_text())
            if (context.get('type') != 'FeatureCollection'
                    or context.get('scope') != 'generalized-statewide-usgs-hard-bottom-context'
                    or context.get('coast_id') != coast):
                raise ValueError('Unreviewed USGS hard-bottom display context: ' + coast)
            features = context['features']
            references.append({'coast_id': coast, 'path': str(path),
                               'sha256': digest(path), 'display_outlines': len(features)})
            for feature in features:
                props = feature['properties']
                if props.get('fishing_target') is not False or props.get('exportable') is not False:
                    raise ValueError('A displayed USGS source claims target status')
                source_id = props.get('block_id') or props.get('release_id')
                if not source_id or not props.get('id'):
                    raise ValueError('Hard context lacks original source ID')
                geometry = shape(feature['geometry'])
                if geometry.is_empty or not geometry.is_valid:
                    raise ValueError('Invalid original hard context geometry')
                west, south, east, north = geometry.bounds
                matches = db.execute(
                    f'SELECT a.tile,a.Resolution,a.GeoTIFF_Link,a.RAT_Link,a.geom '
                    f'FROM "{name}" a JOIN "rtree_{name}_geom" r ON a.fid=r.id '
                    'WHERE r.minx<=? AND r.maxx>=? AND r.miny<=? AND r.maxy>=? '
                    "AND a.Resolution IN ('2m','4m') AND a.GeoTIFF_Link IS NOT NULL AND a.RAT_Link IS NOT NULL",
                    (east, west, north, south)).fetchall()
                for tile, resolution, url, rat_url, raw in matches:
                    tile_geom = gpkg_geometry(raw)
                    if not geometry.intersects(tile_geom):
                        continue
                    entry = selected[tile]
                    if entry['url'] and (entry['url'], entry['rat_url'], entry['resolution']) != (url, rat_url, resolution):
                        raise ValueError('NOAA tile identity changed within scheme')
                    entry.update(url=url, rat_url=rat_url, resolution=resolution)
                    entry['coasts'].add(coast)
                    entry['source_ids'].add(source_id)
                    entry['outlines'].add(props['id'])
                    center = geometry.intersection(tile_geom).representative_point()
                    entry['sector_ids'].update(s['id'] for s in sectors['sectors']
                        if s['coast'] == coast and s['latitude'][0] <= center.y <= s['latitude'][1])
    tiles = []
    for tile, entry in sorted(selected.items()):
        if not entry['sector_ids'] <= sector_ids:
            raise ValueError('Unknown planning sector')
        tiles.append({'tile': tile, 'resolution': entry['resolution'],
                      'raster_url': entry['url'], 'contributor_table_url': entry['rat_url'],
                      'coasts': sorted(entry['coasts']), 'planning_sector_ids': sorted(entry['sector_ids']),
                      'source_ids': sorted(entry['source_ids']), 'intersected_display_outlines': len(entry['outlines'])})
    return {'schema_version': 1, 'scope': 'noaa-nbs-tiles-intersecting-displayed-usgs-hard-context',
            'inventoried_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'scheme_sha256': digest(scheme), 'context_sources': references,
            'tile_count': len(tiles), 'resolution_filter': list(RESOLUTIONS),
            'fishing_target': False, 'exportable': False,
            'method': 'Exact polygon intersection of available NOAA 2–4 m NBS tile-scheme footprints with displayed generalized USGS hard-bottom context; deduplicated by tile ID.',
            'limitations': [
                'Only the largest generalized published USGS context outlines are sampled; smaller hard patches and unmapped stretches are omitted.',
                'Tile intersection is an acquisition lead, not evidence that any measured MLLW cell overlaps hard substrate or passes uncertainty, depth and closure gates.',
                'The NBS Modeling product is test-and-evaluation and may reuse original NOAA surveys; contributor reports and present certified charts remain separate.',
                'Planning-sector association uses a representative overlap latitude, not a legal or precise coverage boundary.'
            ], 'tiles': tiles}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scheme', type=Path, default=Path('var/modeling-tile-scheme-20260923.gpkg'))
    parser.add_argument('--hard-dir', type=Path, default=Path('research/receipts'))
    parser.add_argument('--sectors', type=Path, default=Path('catalog/coastal-sectors.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = {coast: args.hard_dir / f'usgs-hard-context-{coast}.geojson' for coast in COASTS}
    report = inventory(args.scheme, paths, json.loads(args.sectors.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(report, indent=2) + '\n')
    temp.replace(args.output)
    print(json.dumps({'tiles': report['tile_count'],
                      'by_coast': {coast: sum(coast in row['coasts'] for row in report['tiles']) for coast in COASTS}}))


if __name__ == '__main__':
    main()
