"""Original publisher rugose-rock areas, separate from graded terrain physics.

A narrow reviewed opt-in pairs an original categorical grid with valid native
nominal depth and selected-source support. Unknown masks remain unknown. This
stage adds interpreted habitat outlines, never measurement, ranks or exports.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes, geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform
from rasterio.windows import Window, from_bounds
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import unary_union, transform

from skippercast.platform.contracts import REPO, atomic_json, read_json, public_url
from .coverage import cell_geometry
from .io import sha256
from .state_cache import scope_name
from .manifest import load_manifest
from .normalized import verify_review
from .resolution_profile import fine_detail_valid
from .source_ingest import ingest
from .substrate import resolve_bindings, verify_sources, class_reader
from .rights import feature_rights, deployment_use
from .source_scope import scoped_manifest

PROFILE = 'original-rugose-classified-area-v1'
POLICY_FILE = 'catalog/classified-habitat-policy.json'
TO_LOCAL = Transformer.from_crs(4326, 3310, always_xy=True).transform
TO_GEO = Transformer.from_crs(3310, 4326, always_xy=True).transform


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def policies(root):
    path = Path(root)/POLICY_FILE
    if not path.exists():
        return []  # No opt-in is never implicit admission.
    data = read_json(path)
    if data.get('schema_version') != 1 or data.get('profile') != PROFILE:
        raise ValueError('Unreviewed classified habitat policy')
    rows = data['sources']
    if (not isinstance(rows, list) or len({p['depth_source_id'] for p in rows}) != len(rows)
            or len({p['id'] for p in rows}) != len(rows)):
        raise ValueError('Ambiguous classified habitat opt-in')
    for p in rows:
        public_url(p['metadata_url'])
        if (not re.fullmatch('[a-z0-9-]+', p['id'])
                or date.fromisoformat(p['reviewed_on']) > date.today()
                or any(not re.fullmatch('[a-f0-9]{64}', p[k]) for k in
                       ('depth_source_sha256', 'classification_source_sha256', 'metadata_sha256'))
                or p['release_license'] != 'public-domain-us-gov'
                or not p['credit'] or not p['notice'] or not p['review_basis']
                or not p['rugose_raw_codes']
                or any(type(c) is not int for c in p['rugose_raw_codes'])
                or len(set(p['rugose_raw_codes'])) != len(p['rugose_raw_codes'])):
            raise ValueError('Incomplete classified habitat source review')
    return rows


def candidate_mask(depth, valid, classes, inside):
    return (valid & inside & np.isfinite(depth) & (depth >= 7.62)
            & (depth <= 91.44) & (classes == 3))


def polygons(mask, affine):
    return [shape(g) for g, value in shapes(mask.astype('uint8'), mask=mask,
            transform=affine, connectivity=4) if value]


def components(geometry):
    if geometry.geom_type == 'Polygon':
        return [geometry]
    return [p for part in getattr(geometry, 'geoms', [])
            if part.geom_type in {'Polygon', 'MultiPolygon', 'GeometryCollection'}
            for p in components(part)]


def additional_patches(pieces, support, existing):
    # Dissolve before area filtering, preserving native missing-data holes.
    classified = unary_union(pieces).intersection(support)
    additional = classified.difference(existing)
    return [p for p in components(additional) if p.area >= 1000], classified


def assessment(p):
    """Distinct unranked interpreted-area contract; never a terrain shortcut."""
    area = p.get('classified_area')
    if (not isinstance(area, dict) or area.get('profile') != PROFILE
            or not isinstance(area.get('policy_id'), str) or not area['policy_id']
            or area.get('independent_confirmation') is not False
            or area.get('new_measured_area_km2') != 0
            or p.get('terrain') != 'unknown' or p.get('fit') != {
                'lingcod': 'unknown', 'rockfish-reef': 'unknown'}
            or p.get('detail_level') != 'classified-area'
            or p.get('depth_basis') != 'nominal-band'
            or p.get('depth_min_ft') != 25 or p.get('depth_max_ft') != 300
            or not isinstance(p.get('source_ids'), list) or len(p['source_ids']) != 2
            or len(set(p['source_ids'])) != 2
            or p.get('terrain_grade', 'unknown') != 'unknown'
            or p.get('terrain_score', 'unknown') != 'unknown'
            or not isinstance(p.get('substrate'), dict)
            or p['substrate'].get('normalized_code') != 3
            or not p['substrate'].get('source_id')
            or p['substrate'].get('independent_confirmation') is not False
            or p.get('metric_support_fraction') is not None
            or p.get('habitat_quality_hold') or p.get('habitat_quality_dependencies')):
        return None
    return area


def published_contract(p):
    return bool(assessment(p) and p.get('tier') == 1
        and p.get('status') == 'classified-area' and p.get('exportable') is False
        and p.get('screen', {}).get('status') == 'pass' and not p.get('hold_reasons'))


def source_context(root, reach, policy, *, fetch=False):
    """Bind current baseline physics, reviewed source pair and normalized bytes."""
    root = Path(root)
    scope_name(reach)
    folder = root/'var/seafloor/reaches'/reach
    run = read_json(folder/'run.json')
    physical = read_json(folder/'physical.json')
    if (run.get('publication_prohibited') or run['physical_input_hash'] != physical['input_hash']
            or run['inputs']['reach_id'] != reach):
        raise ValueError('Unqualified classified baseline identity')
    for name in ('cells.json', 'candidates.geojson', 'physical.json'):
        if run['outputs'][name] != sha256(folder/name):
            raise ValueError('Classified baseline output hash mismatch')
    for name, expected in physical['outputs'].items():
        if Path(name).name != name or sha256(folder/name) != expected:
            raise ValueError('Classified baseline physical hash mismatch')
    manifest, source_scope = scoped_manifest(root, load_manifest(root))
    rows = {s['id']: s for s in manifest['surveys']}
    row = rows[policy['depth_source_id']]
    binding = resolve_bindings(read_json(root/'catalog/habitat-rules.json'), manifest,
                               scoped=source_scope is not None).get(row['id'])
    if (row['status'] != 'usable' or row['sha256'] != policy['depth_source_sha256']
            or row.get('habitat_quality_hold') or row.get('habitat_quality_dependencies') or row.get('terrain_support')
            or row not in run['inputs']['sources'] or binding is None
            or binding != run['inputs']['substrate_bindings'].get(row['id'])
            or run['inputs'].get('source_scope') != source_scope):
        raise ValueError('Classified source or baseline binding changed')
    b, cls = binding['binding'], binding['row']
    if (cls['id'] != policy['classification_source_id']
            or cls['sha256'] != policy['classification_source_sha256']
            or cls['status'] in {'hold', 'withdrawn', 'physical-only'}
            or cls.get('habitat_quality_hold') or cls.get('habitat_quality_dependencies')
            or b['metadata_sha256'] != policy['metadata_sha256']
            or b['metadata_url'] != policy['metadata_url']
            or not b['same_survey_as_depth']
            or set(policy['rugose_raw_codes']) != {
                int(code) for code, cat in b['classes'].items() if cat['normalized_code'] == 3}):
        raise ValueError('Classified original interpretation review changed')
    rights = feature_rights([row['id'], cls['id']], rows, use=deployment_use(root))
    if any(r['license'] != policy['release_license'] for r in rights):
        raise ValueError('Classified original publication rights changed')
    rights = [dict(r, attribution=policy['credit'], notice=policy['notice'],
                   policy_url=policy['metadata_url']) for r in rights]
    verify_sources({row['id']: binding}, root=root, fetch=fetch)
    receipt, _, _ = ingest(row, row['adapter_review']['requested_bounds_wgs84'], root=root, fetch=fetch)
    cache = root/'var/seafloor/cache'/row['sha256']
    paths = sorted(p.with_suffix('.tif') for p in cache.glob('*.json')
        if read_json(p).get('cog_sha256') == receipt['cog_sha256'] and p.with_suffix('.tif').exists())
    if not paths or sha256(paths[0]) != receipt['cog_sha256']:
        raise ValueError('Classified depth normalized bytes changed')
    verify_review(receipt, row['adapter_review'], paths[0])
    cells = read_json(folder/'cells.json')['cells']
    support = unary_union([cell_geometry(c) for c in cells
                          if c['tier'] == 1 and c['source_id'] == row['id']])
    from .screen import polygon
    existing = unary_union([transform(TO_LOCAL, polygon(f['geometry']))
                for f in read_json(folder/'candidates.geojson')['features']])
    identity = {'profile': PROFILE, 'reach': reach, 'policy': policy,
        'depth_source': row, 'classification_binding': binding, 'normalized_receipt': receipt,
        'normalized_sha256': receipt['cog_sha256'], 'source_scope': source_scope,
        'baseline_physical_input_hash': physical['input_hash'],
        'baseline_physical_sha256': sha256(folder/'physical.json'),
        'baseline_cells_sha256': sha256(folder/'cells.json'),
        'baseline_candidates_sha256': sha256(folder/'candidates.geojson'),
        'implementation': {n: sha256(Path(__file__).with_name(n)) for n in
            ('classified_habitat.py', 'substrate.py', 'resolution_profile.py', 'normalized.py')}}
    return identity, row, binding, paths[0], support, existing, rights


def extract(row, binding, path, support, existing, *, root, edge=512, max_pixels=25_000_000):
    if not 16 <= edge <= 1024 or not 1 <= max_pixels <= 25_000_000:
        raise ValueError('Invalid bounded classified processing limit')
    if support.is_empty:
        return [], {'class3_valid_depth_pixels': 0, 'classified_selected_area_km2': 0}
    pieces, pixels = [], 0
    with rasterio.open(path) as original:
        affine, width, height = calculate_default_transform(original.crs, 3310,
            original.width, original.height, *original.bounds, resolution=row['resolution_m'])
        with WarpedVRT(original, crs='EPSG:3310', transform=affine, width=width, height=height,
                       resampling=Resampling.nearest, nodata=np.nan) as vrt:
            window = from_bounds(*support.bounds, transform=affine).round_offsets().round_lengths()
            window = window.intersection(Window(0, 0, width, height))
            if window.width*window.height > max_pixels:
                raise ValueError('Classified window exceeds bounded pixel budget')
            with class_reader(binding, (height, width), affine, root=root) as read:
                for y in range(int(window.row_off), int(window.row_off+window.height), edge):
                    for x in range(int(window.col_off), int(window.col_off+window.width), edge):
                        tile = Window(x, y, min(edge, window.col_off+window.width-x),
                                      min(edge, window.row_off+window.height-y))
                        data = vrt.read(1, window=tile, masked=True).astype('float32')
                        depth = data.filled(np.nan)
                        valid = fine_detail_valid(depth, ~np.ma.getmaskarray(data) & np.isfinite(depth), row)
                        tr = vrt.window_transform(tile)
                        inside = geometry_mask([mapping(support)], depth.shape, tr, invert=True)
                        mask = candidate_mask(depth, valid, read(tile), inside)
                        pixels += int(mask.sum())
                        pieces.extend(polygons(mask, tr))
                        if len(pieces) > 100_000:
                            raise ValueError('Classified polygon fragment budget exceeded')
    patches, classified = additional_patches(pieces, support, existing)
    return patches, {'class3_valid_depth_pixels': pixels,
                     'classified_selected_area_km2': classified.area/1e6}


def features_for(patches, reach, policy, row, binding):
    from .screen import polygon
    features = []
    for index, patch in enumerate(patches):
        geo = transform(TO_GEO, patch)
        polygon(mapping(geo))  # No repair, buffer, simplified shells or lost holes.
        features.append({'type': 'Feature', 'geometry': mapping(geo), 'properties': {
            'id': f'classified-{reach}-{policy["id"]}-{index}', 'reach': reach,
            'source_ids': [row['id'], binding['row']['id']], 'source_year': row.get('survey_year', 'unknown'),
            'resolution_m': row['resolution_m'], 'vertical_datum': row['vertical_datum'],
            'terrain': 'unknown', 'fit': {'lingcod': 'unknown', 'rockfish-reef': 'unknown'},
            'depth_min_ft': 25, 'depth_max_ft': 300, 'depth_basis': 'nominal-band',
            'detail_level': 'classified-area', 'exportable': False, 'tier': 1,
            'status': 'held', 'hold_reasons': ['legal-screen-pending'], 'area_ha': patch.area/10000,
            'substrate': {'source_id': binding['row']['id'], 'normalized_code': 3,
                'same_survey_as_depth': True, 'independent_confirmation': False},
            'classified_area': {'profile': PROFILE, 'policy_id': policy['id'],
                'metadata_sha256': policy['metadata_sha256'], 'independent_confirmation': False,
                'new_measured_area_km2': 0, 'interpolation_mask': 'unknown',
                'basis': 'Original publisher interpreted rugose rock and boulders; no fish presence inferred.'}}})
    return {'type': 'FeatureCollection', 'features': features}


def stage(reach, *, root=REPO, fetch=False, edge=512, max_pixels=25_000_000):
    """Refresh only opt-in classified physics/screens; never edit the graded run."""
    from .screen import load_snapshot, input_identity, screen_candidates
    root = Path(root)
    scope_name(reach)
    folder = root/'var/seafloor/reaches'/reach
    baseline = read_json(folder/'run.json')
    selected = [p for p in policies(root) if p['depth_source_id'] in
                {s['id'] for s in baseline['inputs']['sources']}]
    if not selected:
        return None
    # Policy changes add/remove explicit pairs without invalidating graded physics.
    contexts = [source_context(root, reach, p, fetch=fetch) for p in selected]
    physical_inputs = {'sources': [c[0] for c in contexts]}
    physical_hash = digest(physical_inputs)
    receipt_path = folder/'classified-run.json'
    candidates_path = folder/'classified-candidates.geojson'
    previous = read_json(receipt_path) if receipt_path.exists() else None
    reuse = bool(previous and previous['physical_input_hash'] == physical_hash)
    if reuse:
        if sha256(candidates_path) != previous['outputs']['classified-candidates.geojson']:
            raise ValueError('Classified candidates failed hash verification')
        candidates = read_json(candidates_path)
        physical_summary = previous['physical_summary']
    else:
        candidates = {'type': 'FeatureCollection', 'features': []}
        physical_summary = {'candidate_count': 0, 'class3_valid_depth_pixels': 0,
                            'classified_selected_area_km2': 0, 'new_measured_area_km2': 0}
        for p, (_, row, binding, path, support, existing, _) in zip(selected, contexts):
            patches, summary = extract(row, binding, path, support, existing,
                                       root=root, edge=edge, max_pixels=max_pixels)
            candidates['features'].extend(features_for(patches, reach, p, row, binding)['features'])
            for key, value in summary.items():
                physical_summary[key] += value
        physical_summary['candidate_count'] = len(candidates['features'])
        atomic_json(candidates_path, candidates)
    state = load_snapshot(root, reach)
    habitat, held, summary = screen_candidates(candidates, state)
    inputs = {'physical': physical_inputs, 'screen': input_identity(state),
              'screen_implementation_sha256': sha256(Path(__file__).with_name('screen.py'))}
    atomic_json(folder/'classified-habitat.geojson', habitat)
    atomic_json(folder/'classified-held.geojson', held)
    receipt = {'version': 1, 'reach': reach, 'input_hash': digest(inputs), 'inputs': inputs,
        'physical_input_hash': physical_hash, 'physical_reused': reuse,
        'physical_summary': physical_summary, 'summary': summary,
        'outputs': {name: sha256(folder/name) for name in
            ('classified-candidates.geojson', 'classified-habitat.geojson', 'classified-held.geojson')}}
    atomic_json(receipt_path, receipt, indent=2)
    return receipt


def publication_features(reach, *, root=REPO):
    """Rehash current pair/physics, rights, artifacts and whole-polygon screen."""
    from .screen import load_snapshot, input_identity, screen_candidates
    root = Path(root)
    scope_name(reach)
    folder = root/'var/seafloor/reaches'/reach
    path = folder/'classified-run.json'
    if not path.exists():
        return [], None
    receipt = read_json(path)
    if receipt.get('version') != 1 or receipt.get('reach') != reach:
        raise ValueError('Classified receipt identity mismatch')
    current = {p['id']: p for p in policies(root)}
    contexts = []
    for saved in receipt['inputs']['physical']['sources']:
        p = saved['policy']
        if p != current.get(p['id']):
            raise ValueError('Classified opt-in changed or withdrawn')
        contexts.append(source_context(root, reach, p))
    physical = {'sources': [c[0] for c in contexts]}
    state = load_snapshot(root, reach)
    inputs = {'physical': physical, 'screen': input_identity(state),
              'screen_implementation_sha256': sha256(Path(__file__).with_name('screen.py'))}
    if (receipt['inputs'] != inputs or receipt['input_hash'] != digest(inputs)
            or receipt['physical_input_hash'] != digest(physical)):
        raise ValueError('Classified inputs changed; restage required')
    expected_names = {'classified-candidates.geojson', 'classified-habitat.geojson', 'classified-held.geojson'}
    if set(receipt['outputs']) != expected_names or any(
            sha256(folder/name) != expected for name, expected in receipt['outputs'].items()):
        raise ValueError('Classified output hash mismatch')
    candidates = read_json(folder/'classified-candidates.geojson')
    habitat, held, summary = screen_candidates(candidates, state)
    if (habitat != read_json(folder/'classified-habitat.geojson')
            or held != read_json(folder/'classified-held.geojson') or summary != receipt['summary']):
        raise ValueError('Classified whole-polygon screen changed')
    rights = {c[0]['policy']['id']: c[-1] for c in contexts}
    for f in habitat['features']:
        p = f['properties']
        saved = next((c[0] for c in contexts if c[0]['policy']['id'] ==
                      p.get('classified_area', {}).get('policy_id')), None)
        if (not published_contract(p) or saved is None
                or p['source_ids'] != [saved['depth_source']['id'], saved['classification_binding']['row']['id']]
                or p['substrate']['source_id'] != saved['classification_binding']['row']['id']
                or p['classified_area']['metadata_sha256'] != saved['policy']['metadata_sha256']):
            raise ValueError('Unqualified classified feature in publication input')
        p['source_rights'] = deepcopy(rights[p['classified_area']['policy_id']])
    return habitat['features'], {'input_hash': receipt['input_hash'],
        'run_sha256': sha256(path), 'summary': summary, 'screen': input_identity(state)}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=REPO)
    parser.add_argument('--reach', required=True)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    print(json.dumps(stage(args.reach, root=args.root, fetch=args.fetch), indent=2))
