"""Review several NOAA NBS Modeling tiles per coast sector as source leads.

The first-tile audit is only a sample. This bounded expansion checks more
independently delivered tile files, while retaining correlated camera windows
and reused survey contributors as research evidence, never fishing targets.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
import rasterio
from shapely.geometry import shape
from shapely.ops import unary_union

from scripts.audit_nbs_modeling_tile import audit, contributors, is_measured_survey, item_year
from scripts.audit_nbs_statewide_camera_tiles import screen_camera_positions
from scripts.audit_statewide_regular_camera import rocky_camera_positions
from scripts.audit_usgs_video_observations import sector_for


def ranked_camera_tiles(scheme, manifest, video_cache, sectors, *, coast):
    chosen = {item['id']: item for item in sectors if coast == 'all' or item['coast'] == coast}
    if not chosen:
        raise ValueError(f'Unknown or empty coast group: {coast}')
    counts = Counter()
    positions = defaultdict(list)
    camera_counts = Counter()
    with sqlite3.connect(scheme) as db:
        table = db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()
        if not table or not table[0].startswith('Modeling_Tile_Scheme_'):
            raise ValueError('Expected NOAA NBS Modeling GeoPackage')
        name = table[0]
        for points in rocky_camera_positions(manifest, video_cache).values():
            for longitude, latitude in points:
                sector = sector_for(latitude, sectors)
                if sector not in chosen:
                    continue
                camera_counts[sector] += 1
                rows = db.execute(
                    f'SELECT a.tile FROM "{name}" a JOIN "rtree_{name}_geom" r ON a.fid=r.id '
                    'WHERE r.minx<=? AND r.maxx>=? AND r.miny<=? AND r.maxy>=? '
                    "AND a.Resolution IN ('2m','4m') AND a.GeoTIFF_Link IS NOT NULL AND a.RAT_Link IS NOT NULL",
                    (longitude, longitude, latitude, latitude)).fetchall()
                for (tile,) in rows:
                    counts[(sector, tile)] += 1
                    positions[(sector, tile)].append((longitude, latitude))
    ranked = {}
    for sector in chosen:
        ranked[sector] = sorted(((count, tile) for (sid, tile), count in counts.items()
                                 if sid == sector), key=lambda item: (-item[0], item[1]))
    return ranked, positions, camera_counts


def checked_mpas(snapshot):
    item = snapshot['sources']['mpas']
    features = item['data']['geojson']['features']
    if item['status'] != 'ok' or len(features) != item['data']['feature_count'] or len(features) < 100:
        raise ValueError('Complete current CDFW MPA source required')
    checked = datetime.fromisoformat(item['data_retrieved_at'].replace('Z', '+00:00'))
    if not 0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 36 * 3600:
        raise ValueError('CDFW MPA snapshot is stale')
    return item, unary_union([shape(feature['geometry']) for feature in features])


def uncertainty_diagnostic(cache, tile):
    """Explain screened-out measured depth without changing the target gate."""
    sources = contributors(cache / f'{tile}.tiff.aux.xml')
    recent = {value for value, row in sources.items()
              if is_measured_survey(row) and item_year(row['survey_date_end']) >= 1990}
    with rasterio.open(cache / f'{tile}.tiff') as raster:
        elevation, uncertainty, contributor = raster.read()
    depth = -elevation
    measured = (np.isfinite(depth) & (depth >= 25 * .3048) & (depth <= 200 * .3048)
                & np.isin(contributor, list(recent)))
    finite = measured & np.isfinite(uncertainty) & (uncertainty > 0)
    allowed_depth = finite & (depth + uncertainty + 2 <= 200 * .3048)
    return {'recent_measured_depth_25_to_200_ft': int(measured.sum()),
            'missing_or_invalid_uncertainty': int((measured & ~finite).sum()),
            'within_depth_limit_with_margin_by_supplied_uncertainty_m': {
                'at_most_1': int((allowed_depth & (uncertainty <= 1)).sum()),
                'over_1_to_2': int((allowed_depth & (uncertainty > 1) & (uncertainty <= 2)).sum()),
                'over_2': int((allowed_depth & (uncertainty > 2)).sum())}}


def build(scheme, manifest, video_cache, sectors, cache, mpa_snapshot, *, coast,
          max_tiles=3, fetch=False, workers=4):
    if not 1 <= max_tiles <= 12 or not 1 <= workers <= 8:
        raise ValueError('max_tiles must be 1–12 and workers 1–8')
    item, protected = checked_mpas(mpa_snapshot)
    ranked, positions, camera_counts = ranked_camera_tiles(
        scheme, manifest, video_cache, sectors, coast=coast)
    requested = sorted({tile for choices in ranked.values() for _, tile in choices[:max_tiles]})
    audited, failed = {}, {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(audit, scheme, tile, cache, fetch=fetch): tile for tile in requested}
        for future in as_completed(futures):
            tile = futures[future]
            try:
                audited[tile] = future.result()
            except (OSError, ValueError, KeyError) as exc:
                failed[tile] = f'{type(exc).__name__}: {exc}'
    diagnostics = {tile: uncertainty_diagnostic(cache, tile) for tile in audited}
    rows = []
    for sector in sectors:
        sid = sector['id']
        if sid not in ranked:
            continue
        tile_rows = []
        for count, tile in ranked[sid][:max_tiles]:
            tile_rows.append({'tile': tile, 'historical_camera_windows_in_envelope': count,
                              'source_audit': audited.get(tile), 'source_failure': failed.get(tile),
                              'uncertainty_diagnostic': diagnostics.get(tile),
                              'historical_camera_native_cell_screen': screen_camera_positions(
                                  cache, tile, positions[(sid, tile)], protected) if tile in audited else None,
                              'historical_camera_2m_uncertainty_sensitivity': screen_camera_positions(
                                  cache, tile, positions[(sid, tile)], protected,
                                  max_uncertainty_m=2.0) if tile in audited else None})
        rows.append({'sector_id': sid, 'name': sector['name'],
                     'historical_rocky_camera_windows': camera_counts[sid],
                     'candidate_tiles': len(ranked[sid]), 'reviewed_tiles': tile_rows})
    return {'schema_version': 1, 'scope': 'coast-nbs-multiple-rocky-camera-tile-source-review',
            'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'coast': coast, 'max_tiles_per_sector': max_tiles,
            'scheme_sha256': hashlib.sha256(scheme.read_bytes()).hexdigest(),
            'cdfw_mpa_source_url': item['data']['source_url'],
            'cdfw_mpa_retrieved_at': item['data_retrieved_at'],
            'cdfw_mpa_geojson_sha256': hashlib.sha256(json.dumps(
                item['data']['geojson'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'camera_manifest_sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            'requested_unique_tiles': len(requested), 'audited_unique_tiles': len(audited),
            'failed_tiles': failed, 'sectors': rows, 'fishing_target': False, 'exportable': False,
            'limitations': ['Top tiles are selected by historical camera-window count, not fish presence or unique reef area.',
                            'Camera windows along the same transect and overlapping tiles are correlated; counts are not additive.',
                            'NBS Modeling is test-and-evaluation bathymetry and may reuse the same original NOAA surveys.',
                            'A zero in these selected tiles does not establish absent habitat in the sector.',
                            'The 2 m uncertainty sensitivity is a research comparison, not a change to the 1 m target gate or a fishing waypoint.',
                            'Original survey, substrate, hazards, current chart, rights, closures and local rules remain separate target gates.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scheme', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=Path('catalog/usgs-video-cruises.json'))
    parser.add_argument('--video-cache', type=Path, default=Path('var/usgs-video-cache'))
    parser.add_argument('--sectors', type=Path, default=Path('catalog/coastal-sectors.json'))
    parser.add_argument('--cache', type=Path, default=Path('var/nbs-cache'))
    parser.add_argument('--mpas', type=Path, default=Path('var/qualification-current/coastal/latest.json'))
    parser.add_argument('--coast', required=True, choices=('all', 'northern', 'mendocino', 'san-francisco', 'central', 'southern'))
    parser.add_argument('--max-tiles', type=int, default=3)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.scheme, json.loads(args.manifest.read_text()), args.video_cache,
                   json.loads(args.sectors.read_text())['sectors'], args.cache,
                   json.loads(args.mpas.read_text()), coast=args.coast,
                   max_tiles=args.max_tiles, fetch=args.fetch, workers=args.workers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(result['coast'], result['audited_unique_tiles'], '/', result['requested_unique_tiles'],
          'tiles;', len(result['failed_tiles']), 'failures')
    if result['failed_tiles'] or any(not row['reviewed_tiles'] for row in result['sectors']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
