"""Publish coarse CDFW-predicted hard substrate as non-target atlas context.

Only patches of at least 100 observed 40 m cells survive this context view.
This source uses rugosity as a proxy, includes interpolated shallow gaps, and
must not be presented as native survey geology, a fishing point, or depth proof.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import lerc
import numpy as np
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.transform import from_origin
from shapely.geometry import mapping, shape
from shapely.ops import transform

from build_usgs_statewide_context import mpa_union
from audit_cdfw_substrate_tiles import BASE, LEVEL, ORIGIN, RESOLUTION_M

MIN_CELLS = 100
PIXEL_AREA = RESOLUTION_M * RESOLUTION_M


def build(audit, mpas, coasts, cache):
    if audit.get('scope') != 'cdfw-ds3091-40m-tile-audit' or audit.get('failures') or audit.get('requested_tiles') != audit.get('audited_tiles'):
        raise ValueError('Complete audited CDFW ds3091 tile set is required')
    age = datetime.now(timezone.utc) - datetime.fromisoformat(audit['checked_at'])
    if not 0 <= age.total_seconds() < 30 * 86400:
        raise ValueError('CDFW substrate tile audit is stale')
    mpa_wgs = mpa_union(mpas)
    to_projected = Transformer.from_crs(4326, 3310, always_xy=True).transform
    to_wgs = Transformer.from_crs(3310, 4326, always_xy=True).transform
    # Keep a conservative 100 m display buffer because transformed long MPA
    # edges and later WGS84 serialization can otherwise leave tiny slivers.
    excluded = transform(to_projected, mpa_wgs).buffer(100)
    rows = {coast['id']: [] for coast in coasts['regions']}
    for item in audit['tiles']:
        if item['hard_cells'] < MIN_CELLS:
            continue
        row, col = item['row'], item['col']
        blob = (cache / str(LEVEL) / str(row) / f'{col}.lerc').read_bytes()
        import hashlib
        if hashlib.sha256(blob).hexdigest() != item['sha256']:
            raise ValueError(f'CDFW tile hash changed: {row}/{col}')
        status, values, mask = lerc.decode(blob)
        if status != 0 or values.shape != (256, 256):
            raise ValueError(f'CDFW tile decode changed: {row}/{col}')
        hard = ((values == 1) & (mask if mask is not None else True)).astype('uint8')
        affine = from_origin(ORIGIN[0] + col*256*RESOLUTION_M,
                             ORIGIN[1] - row*256*RESOLUTION_M,
                             RESOLUTION_M, RESOLUTION_M)
        rank = 0
        for geometry, value in shapes(hard, mask=hard.astype(bool), transform=affine):
            if value != 1:
                continue
            projected = shape(geometry)
            if projected.area < MIN_CELLS * PIXEL_AREA:
                continue
            projected = projected.simplify(RESOLUTION_M / 2, preserve_topology=True)
            legal = projected.difference(excluded) if projected.intersects(excluded) else projected
            if legal.is_empty:
                continue
            for part in (list(legal.geoms) if hasattr(legal, 'geoms') else [legal]):
                if part.geom_type != 'Polygon' or part.area < MIN_CELLS * PIXEL_AREA:
                    continue
                wgs = transform(to_wgs, part)
                latitude = wgs.centroid.y
                matches = [coast['id'] for coast in coasts['regions'] if coast['latitude'][0] <= latitude < coast['latitude'][1]]
                if len(matches) != 1:
                    continue
                rank += 1
                rows[matches[0]].append({'type': 'Feature', 'geometry': mapping(wgs), 'properties': {
                    'id': f'cdfw-ds3091-{LEVEL}-{row}-{col}-{rank}', 'source': 'CDFW ds3091 predicted substrate',
                    'source_url': BASE, 'metadata_url': audit['metadata_url'],
                    'source_tile_sha256': item['sha256'], 'source_class': 'Predicted hard (rugosity proxy)',
                    'display_resolution_m': RESOLUTION_M, 'approx_area_m2': round(part.area),
                    'fishing_target': False, 'exportable': False, 'depth_qualified': False,
                    'fish_confirmed': False, 'mpa_screened_at': mpas['sources']['mpas']['data_retrieved_at']}})
    return {coast: {'type': 'FeatureCollection', 'schema_version': 1,
                    'scope': 'cdfw-predicted-hard-substrate-context', 'coast_id': coast,
                    'compiled_at': datetime.now(timezone.utc).isoformat(),
                    'source_catalog_url': audit['metadata_url'], 'source_service_url': BASE,
                    'method': 'CDFW ds3091 level-7 40 m LERC overview; hard-class components >=100 cells, simplified to 20 m, cut by current complete CDFW MPA polygons plus 100 m display buffer.',
                    'limitations': ['Predicted rugosity proxy, not verified rock or native survey bathymetry.',
                                    'Source includes interpolated shallow gaps and varying original resolutions.',
                                    'Patches smaller than 0.16 km² are omitted; displayed borders are coarse.',
                                    'No fish presence, legal depth, catch success, or navigational accuracy is inferred.'],
                    'features': features} for coast, features in rows.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, default=Path('var/cdfw-ds3091-tile-audit.json'))
    parser.add_argument('--mpas', type=Path, default=Path('var/live-coastal-latest.json'))
    parser.add_argument('--coasts', type=Path, default=Path('dist/data/coasts.json'))
    parser.add_argument('--cache', type=Path, default=Path('var/cdfw-ds3091-tiles'))
    parser.add_argument('--output-dir', type=Path, default=Path('dist/data'))
    args = parser.parse_args()
    outputs = build(json.loads(args.audit.read_text()), json.loads(args.mpas.read_text()),
                    json.loads(args.coasts.read_text()), args.cache)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for coast, data in outputs.items():
        path = args.output_dir / f'cdfw-predicted-hard-{coast}.geojson'
        path.write_text(json.dumps(data, separators=(',', ':')) + '\n')
        print(coast, len(data['features']))


if __name__ == '__main__':
    main()
