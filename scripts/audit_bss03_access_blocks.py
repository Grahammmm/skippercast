"""Screen private Block 03 camera/sonar research blocks against fresh official GIS."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

import numpy as np
import rasterio
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

from scripts.audit_csumb_bss_native import ROOT, acquire
from scripts.audit_monterey_300_closures import fresh, official_query_envelope, safe_union
from scripts.audit_usgs_video_observations import load_archive, open_original_zip
from scripts.refresh_enc_hazards import LAYERS, SERVICES


SURVEY = 'BSS_Block03'
CRUISE = 'c0212sc'
BLOCK_M = 100
MARGIN_M = 100
MPA_NAMES = {'Piedras Blancas SMCA', 'Piedras Blancas SMR'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(features):
    rows = [json.dumps({'geometry': item['geometry'], 'properties': item['properties']},
                       sort_keys=True, separators=(',', ':')) for item in features]
    return hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()


def source_blocks(spec, video_manifest, grid_cache, video_cache):
    if spec['survey_id'] != SURVEY:
        raise ValueError('Wrong original Big Sur survey')
    archive = acquire(spec, grid_cache, False)
    raw = load_archive(video_cache, CRUISE, video_manifest['archives'][CRUISE],
                       video_manifest['base_url'], False)
    reader = open_original_zip(raw)
    blocks = defaultdict(lambda: Counter())
    grid_path = spec['bathymetry_grid']
    with tarfile.open(archive, 'r:gz') as bundle, tempfile.TemporaryDirectory() as directory:
        members = [m for m in bundle.getmembers() if m.isfile() and m.name.startswith(grid_path + '/')]
        if not members or sum(m.size for m in members) > 100_000_000:
            raise ValueError('Unexpected original depth grid members')
        for member in members:
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe original source member')
            target = Path(directory) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.extractfile(member).read())
        with rasterio.open(Path(directory) / grid_path) as grid:
            if str(grid.crs) != 'EPSG:26910' or tuple(grid.res) != (2.0, 2.0):
                raise ValueError('Original grid reference changed')
            valid = grid.read_masks(1) > 0
            depth = grid.read(1)
            project = Transformer.from_crs('EPSG:4326', grid.crs, always_xy=True)
            for item in reader.iterShapeRecords():
                if not item.shape.points:
                    continue
                row = item.record.as_dict()
                if str(row.get('MAJOR_GEO') or '').lower() not in ('rock', 'boulder', 'cobble'):
                    continue
                x, y = project.transform(*item.shape.points[0])
                if not (grid.bounds.left <= x < grid.bounds.right
                        and grid.bounds.bottom < y <= grid.bounds.top):
                    continue
                r, c = grid.index(x, y)
                if not valid[r, c] or not -91.44 <= float(depth[r, c]) < -60.96:
                    continue
                key = (int(x // BLOCK_M), int(y // BLOCK_M))
                blocks[key]['rock_boulder_cobble_windows'] += 1
                blocks[key]['rockfish_positive_windows'] += int(row.get('rockfish', 0) > 0)
                blocks[key]['lingcod_positive_windows'] += int(row.get('lingcod', 0) > 0)
    if len(blocks) != 3 or sum(v['rock_boulder_cobble_windows'] for v in blocks.values()) != 11:
        raise ValueError('Original camera/depth research block set changed')
    return blocks


def screen(blocks, mpas, federal, enc, *, now=None):
    now = now or datetime.now(timezone.utc)
    if (mpas.get('status') != 'research-closure-screen-only'
            or {x['properties']['NAME'] for x in mpas.get('features', [])} != MPA_NAMES
            or mpas.get('exceededTransferLimit')
            or federal.get('status') != 'ok'
            or federal.get('scope') != 'noaa-west-coast-groundfish-conservation-areas'
            or len(federal.get('source_layers', [])) < 25
            or federal.get('feature_count') != len(federal.get('features', []))
            or enc.get('scope_id') != 'bss03-original-camera-depth-context'
            or enc.get('bounds') != [-121.46, 35.74, -121.33, 35.84]
            or enc.get('status') != 'charted-danger-screen-only'
            or {(q['service'], q['layer']) for q in enc.get('query_receipts', [])}
            != {(service, layer) for service in SERVICES for layer in LAYERS}
            or sum(q['count'] for q in enc['query_receipts']) != len(enc.get('features', []))):
        raise ValueError('Big Sur source set incomplete or changed')
    for value in (mpas['checked_at'], federal['retrieved_at'], enc['checked_at']):
        fresh(value, now)
    project = Transformer.from_crs('EPSG:4326', 'EPSG:26910', always_xy=True).transform
    mpa_coverage = transform(project, official_query_envelope(mpas['source_url']))
    enc_coverage = transform(project, box(*enc['bounds']))
    mpa = safe_union(mpas['features'], project)
    geas = [row for row in federal['features'] if row['properties']['area_type'] == 'GEA']
    if len(geas) < 10:
        raise ValueError('NOAA groundfish exclusion source incomplete')
    gea = safe_union(geas, project)
    dangers = [transform(project, shape(item['geometry'])) for item in enc['features']]
    if any(item.is_empty or not item.is_valid for item in dangers):
        raise ValueError('NOAA ENC danger geometry invalid')
    danger = unary_union(dangers)
    totals = Counter()
    private = []
    for (east, north), evidence in sorted(blocks.items()):
        footprint = box(east * BLOCK_M, north * BLOCK_M,
                        (east + 1) * BLOCK_M, (north + 1) * BLOCK_M)
        review = footprint.buffer(MARGIN_M)
        if not mpa_coverage.covers(review) or not enc_coverage.covers(review):
            raise ValueError('Official query does not cover the full research margin')
        holds = {'mpa': review.intersects(mpa), 'gea': review.intersects(gea),
                 'charted_danger': not danger.is_empty and review.intersects(danger)}
        totals['blocks'] += 1
        totals['rock_boulder_cobble_windows'] += evidence['rock_boulder_cobble_windows']
        for label, held in holds.items():
            totals[label + '_margin_blocks'] += int(held)
        totals['all_three_clear_margin_blocks'] += int(not any(holds.values()))
        private.append({'type': 'Feature', 'geometry': mapping(footprint),
                        'properties': {**dict(evidence), 'review_holds': holds,
                                       'fishing_target': False, 'exportable': False}})
    return ({'schema_version': 1, 'scope': 'bss03-original-camera-100m-access-triage',
             'survey_id': SURVEY, 'camera_cruise': CRUISE,
             'block_m': BLOCK_M, 'review_margin_m': MARGIN_M,
             'source_checked_at': {'cdfw_mpa': mpas['checked_at'],
                                   'noaa_federal': federal['retrieved_at'],
                                   'noaa_enc': enc['checked_at']},
             'source_urls': {'cdfw_mpa': mpas['source_url'],
                             'noaa_federal': federal['service_url'],
                             'noaa_enc': enc['source_url']},
             'official_geometry_sha256': {'cdfw_mpas': fingerprint(mpas['features']),
                                          'noaa_federal_geas': fingerprint(geas),
                                          'noaa_enc_dangers': fingerprint(enc['features'])},
             'private_block_fingerprint': fingerprint(private),
             'cdfw_mpa_feature_count': len(mpas['features']),
             'noaa_gea_feature_count': len(geas),
             'noaa_enc_danger_feature_count': len(enc['features']),
             'noaa_enc_query_layers': len(enc['query_receipts']),
             'totals': dict(sorted(totals.items())),
             'qualified_waypoints': 0, 'fishing_target': False, 'exportable': False,
             'limitations': [
                 'Three private 100 m blocks are a triage footprint around correlated 2012 camera windows, not a mapped reef edge or a safe drift.',
                 'The 100 m GIS margin is not a position-derived navigation or approach buffer. CDFW MPAs, NOAA GEAs and three ENC danger families are partial screens only.',
                 'Original depths are NAVD88 source elevations in a nominal 200–300 ft band, not upper-uncertainty-bounded MLLW depths.',
                 'Current species rules, other closures, security notices, charter access, approach and return routes, producer rights and catch probability remain unresolved.'
             ]},
            {'type': 'FeatureCollection', 'crs': 'EPSG:26910',
             'scope': 'private-bss03-camera-100m-research-blocks', 'features': private})


def stable(report):
    return {key: value for key, value in report.items()
            if key not in ('source_checked_at', 'raw_snapshot_sha256')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bss-cache', type=Path, default=ROOT / 'var/noaa-native-cache')
    parser.add_argument('--video-cache', type=Path, default=ROOT / 'var/usgs-video-cache')
    parser.add_argument('--mpas', required=True, type=Path)
    parser.add_argument('--federal', required=True, type=Path)
    parser.add_argument('--enc', required=True, type=Path)
    parser.add_argument('--private-blocks', type=Path, default=ROOT / 'var/review/bss03-camera-100m-blocks.geojson')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/data/bss03-camera-access-triage.json')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    bss = next(source for source in json.loads((ROOT / 'catalog/csumb-bss-native-sources.json').read_text())['sources']
               if source['survey_id'] == SURVEY)
    video = json.loads((ROOT / 'catalog/usgs-video-cruises.json').read_text())
    blocks = source_blocks(bss, video, args.bss_cache, args.video_cache)
    source_data = [json.loads(path.read_text()) for path in (args.mpas, args.federal, args.enc)]
    report, private = screen(blocks, *source_data)
    report['original_source_sha256'] = {'bss03': bss['archive_sha256'], 'video': video['archives'][CRUISE]}
    report['raw_snapshot_sha256'] = {name: sha(path) for name, path in
                                     zip(('cdfw_mpa', 'noaa_federal', 'noaa_enc'), (args.mpas, args.federal, args.enc))}
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise ValueError('Big Sur access evidence changed; review before publication')
    for path in (args.private_blocks, args.output):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.private_blocks.write_text(json.dumps(private, separators=(',', ':')) + '\n')
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'blocks': report['totals']['blocks'],
                      'margin_holds': {key: value for key, value in report['totals'].items()
                                       if key.endswith('_margin_blocks')}}))


if __name__ == '__main__':
    main()
