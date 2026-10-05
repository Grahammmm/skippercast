"""Original publisher rugose-rock areas, separate from graded terrain physics.

A narrow reviewed opt-in pairs an original categorical grid with valid native
nominal depth and current Tier 1 reference support. The versioned paired mode
is opt-in; absent mode keeps selected-source support. Unknown masks remain
unknown. This stage adds interpreted outlines, never measurement, ranks or exports.
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
from .classified_geometry import (VERSION as GEOMETRY_VERSION, geographic,
                                  runtime as geometry_runtime, verify_inventory)
from .manifest import load_manifest
from .normalized import verify_review
from .resolution_profile import fine_detail_valid
from .source_ingest import ingest
from .substrate import resolve_bindings, verify_sources, class_reader
from .rights import feature_rights, deployment_use, source_rights
from .source_scope import scoped_manifest

PROFILE = 'original-rugose-classified-area-v1'
POLICY_FILE = 'catalog/classified-habitat-policy.json'
TO_LOCAL = Transformer.from_crs(4326, 3310, always_xy=True).transform
SELECTED_SOURCE_SUPPORT = 'selected-source-v1'
PAIRED_REFERENCE_SUPPORT = 'paired-reference-footprint-v1'
REFERENCE_NOTICE = ('Current measured coverage footprint only; no reference '
                    'terrain, substrate or species metrics borrowed.')
NEIGHBOR_VERSION = 'planning-neighbor-suppression-v1'
NEIGHBOR_BUFFER_M = 5  # Deliberately conservative exclusion, not accuracy.
NATIVE_PAIR_DEDUP_VERSION = 'reviewed-policy-order-native-union-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def support_mode(policy):
    """Resolve the opt-in support contract without changing legacy policy bytes."""
    mode = policy.get('support_mode', SELECTED_SOURCE_SUPPORT)
    if (not isinstance(mode, str)
            or mode not in {SELECTED_SOURCE_SUPPORT, PAIRED_REFERENCE_SUPPORT}):
        raise ValueError('Unknown classified habitat support mode')
    return mode


def policy_applies_to_reach(policy, reach):
    reach_ids = policy.get('reach_ids')
    return reach_ids is None or reach in reach_ids


def _known_reaches(root):
    path = Path(root)/'catalog/reaches.json'
    if not path.exists():
        return None
    rows = read_json(path).get('reaches')
    if not isinstance(rows, list):
        raise ValueError('Invalid classified habitat reach inventory')
    ids = [row.get('id') for row in rows if isinstance(row, dict)]
    if (len(ids) != len(rows) or any(not isinstance(ident, str) for ident in ids)
            or len(ids) != len(set(ids))):
        raise ValueError('Invalid classified habitat reach inventory')
    return set(ids)


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
    known_reaches = (_known_reaches(root) if any(
        isinstance(p, dict) and (p.get('reach_ids') is not None or 'neighbor_reaches' in p)
        for p in rows) else None)
    for p in rows:
        mode = support_mode(p)
        reach_ids = p.get('reach_ids')
        if mode == PAIRED_REFERENCE_SUPPORT and reach_ids is None:
            raise ValueError('Paired-reference support requires reviewed reach_ids')
        if reach_ids is not None:
            if (not isinstance(reach_ids, list) or not reach_ids
                    or any(not isinstance(r, str) for r in reach_ids)
                    or len(reach_ids) != len(set(reach_ids)) or known_reaches is None
                    or any(r not in known_reaches for r in reach_ids)):
                raise ValueError('Invalid classified habitat reach scope')
        if 'neighbor_reaches' in p:
            neighbors = p['neighbor_reaches']
            if (reach_ids is None or not isinstance(neighbors, list) or not neighbors
                    or any(not isinstance(r, str) for r in neighbors)
                    or len(neighbors) != len(set(neighbors))
                    or any(r not in known_reaches for r in neighbors)
                    or set(neighbors).intersection(reach_ids)):
                raise ValueError('Invalid classified neighbor reach scope')
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


def _physical_inputs(contexts):
    """Bind multi-pair native priority semantics into stage and publish identity."""
    physical = {'sources': [c[0] for c in contexts],
        'geometry_representation': geometry_runtime(),
        'geometry_implementation_sha256': sha256(Path(__file__).with_name('classified_geometry.py'))}
    if len(contexts) > 1:
        physical['native_pair_dedup'] = {
            'version': NATIVE_PAIR_DEDUP_VERSION,
            'policy_order': [c[0]['policy']['id'] for c in contexts],
            'existing_geometry': 'graded-baseline-plus-earlier-original-native-patches'}
    return physical


def verify_pair_disjointness(candidates, native, contexts):
    """Reject duplicate native area, including held patches and cache hits."""
    if len(contexts) <= 1:
        return  # Preserve the existing single-pair contract.
    groups = {c[0]['policy']['id']: [] for c in contexts}
    policy_by_id = {f['properties']['id']:
        f['properties'].get('classified_area', {}).get('policy_id')
        for f in candidates['features']}
    for feature in native['features']:
        policy_id = policy_by_id.get(feature['properties']['id'])
        if policy_id not in groups:
            raise ValueError('Unreviewed classified native source-pair group')
        groups[policy_id].append(shape(feature['geometry']))
    prior = None
    for patches in groups.values():
        current = unary_union(patches)
        if prior is not None and current.intersection(prior).area > 0:
            raise ValueError('Classified native habitat overlap across source pairs')
        prior = current if prior is None else unary_union([prior, current])


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
            or p.get('geometry_representation') != {'version': GEOMETRY_VERSION, 'native_crs': 'EPSG:3310'}
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


def normalized_depth(row, root, *, fetch=False):
    """Recheck existing native bytes and their reviewed normalized dependency."""
    receipt, _, _ = ingest(row, row['adapter_review']['requested_bounds_wgs84'],
                           root=root, fetch=fetch)
    cache = Path(root)/'var/seafloor/cache'/row['sha256']
    paths = sorted(p.with_suffix('.tif') for p in cache.glob('*.json')
        if read_json(p).get('cog_sha256') == receipt['cog_sha256'] and p.with_suffix('.tif').exists())
    if not paths or sha256(paths[0]) != receipt['cog_sha256']:
        raise ValueError('Classified depth normalized bytes changed')
    verify_review(receipt, row['adapter_review'], paths[0])
    return receipt, paths[0]


def neighbor_planning(root, reach, policy, *, baseline=None):
    """Conservative whole-patch exclusion; planning is never measurement."""
    if 'neighbor_reaches' not in policy:
        return None, None
    root = Path(root)
    neighbors = policy['neighbor_reaches']
    known = _known_reaches(root)
    if (not isinstance(neighbors, list) or not neighbors or known is None
            or any(not isinstance(r, str) or r not in known for r in neighbors)
            or len(neighbors) != len(set(neighbors)) or reach in neighbors):
        raise ValueError('Invalid classified neighbor reach scope')
    baseline = baseline or read_json(root/'var/seafloor/reaches'/reach/'run.json')
    physics = {k: v for k, v in baseline['inputs'].items()
               if k not in {'screen', 'screen_implementation_sha256'}}
    if digest(physics) != baseline['physical_input_hash']:
        raise ValueError('Neighbor planning baseline physical identity changed')
    folder = root/'var/seafloor/reference'
    grid = read_json(folder/'cells.json')
    receipt = read_json(folder/'run.json')
    catalog = read_json(root/'catalog/reaches.json')
    grid_sha, catalog_sha = sha256(folder/'cells.json'), sha256(root/'catalog/reaches.json')
    if (grid['input_hash'] != catalog['input_hash'] or receipt['input_hash'] != catalog['input_hash']
            or receipt['output_hashes']['cells.json'] != grid_sha
            or baseline['inputs']['reference_cells_sha256'] != grid_sha
            or baseline['inputs']['reaches_sha256'] != catalog_sha):
        raise ValueError('Neighbor planning reference identity changed')
    cells = [c for c in grid['cells'] if c.get('reach') in neighbors]
    keys = [(c['reach'], c['id']) for c in cells]
    if (len(keys) != len(set(keys)) or {c['reach'] for c in cells} != set(neighbors)):
        raise ValueError('Neighbor planning cells missing or duplicated')
    mask = unary_union([cell_geometry(c) for c in cells]).buffer(NEIGHBOR_BUFFER_M)
    metadata = {'version': NEIGHBOR_VERSION, 'neighbor_reaches': sorted(neighbors),
        'reference_input_hash': grid['input_hash'], 'reference_cells_sha256': grid_sha,
        'reference_run_sha256': sha256(folder/'run.json'), 'reaches_sha256': catalog_sha,
        'planning_cell_count': len(cells), 'buffer_m': NEIGHBOR_BUFFER_M,
        'basis': 'Conservative neighboring planning footprint; no measured coverage or accuracy inferred.'}
    return metadata, mask


def classified_screen(candidates, state, native_geometries, contexts, root, reach):
    """Reconstruct per-policy native holds at stage and independent admission."""
    from .screen import screen_candidates
    exclusions = {}
    for context in contexts:
        identity = context[0]
        policy = identity['policy']
        metadata, mask = neighbor_planning(root, reach, policy)
        if metadata != identity.get('neighbor_planning'):
            raise ValueError('Classified neighbor planning context changed')
        if metadata is not None:
            for f in candidates['features']:
                if f['properties'].get('classified_area', {}).get('policy_id') == policy['id']:
                    exclusions[f['properties']['id']] = [('neighbor-planning', mask)]
    return screen_candidates(candidates, state, native_geometries=native_geometries,
                             native_exclusions=exclusions or None)


def source_context(root, reach, policy, *, fetch=False):
    """Bind current baseline physics, reviewed source pair and normalized bytes."""
    root = Path(root)
    scope_name(reach)
    support_mode(policy)
    if not policy_applies_to_reach(policy, reach):
        raise ValueError('Classified policy does not include requested reach')
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
    receipt, path = normalized_depth(row, root, fetch=fetch)
    cells = read_json(folder/'cells.json')['cells']
    mode = support_mode(policy)
    reference_support = None
    if mode == SELECTED_SOURCE_SUPPORT:
        support_cells = [c for c in cells
                         if c['tier'] == 1 and c['source_id'] == row['id']]
    else:
        # Reference geometry comes only from current hash-verified Tier 1
        # baseline cells. extract() still applies the paired source's own
        # depth, class, nodata and resolution masks inside that footprint.
        support_cells = [c for c in cells if type(c.get('tier')) is int and c['tier'] == 1]
        input_sources = run['inputs'].get('sources')
        if not isinstance(input_sources, list):
            raise ValueError('Missing classified baseline source inventory')
        saved_sources = {s.get('id'): s for s in input_sources if isinstance(s, dict)}
        if len(saved_sources) != len(input_sources):
            raise ValueError('Invalid classified baseline source inventory')
        # Paired support is valid only while every winning Tier 1 contributor
        # remains the same usable, rights-cleared bathymetry input in the
        # current scoped manifest. Recheck this at stage and publication, since
        # both rebuild source_context from current catalog state.
        reference_ids = {c.get('source_id') for c in support_cells}
        if any(not isinstance(ident, str) or ident not in rows
               or ident not in saved_sources for ident in reference_ids):
            raise ValueError('Unknown or out-of-scope current Tier 1 reference source')
        reference_dependencies, reference_rights = [], []
        from . import terrain_support
        for ident in sorted(reference_ids):
            reference = rows[ident]
            if (reference != saved_sources[ident] or reference.get('kind') != 'bathymetry'
                    or reference.get('status') != 'usable'
                    or reference.get('habitat_quality_hold')
                    or reference.get('habitat_quality_dependencies')):
                raise ValueError('Current Tier 1 reference source changed or is unusable')
            reference_rights.append(source_rights(reference, use=deployment_use(root)))
            terrain_support.validate_binding(reference)
            ref_receipt, ref_path = ((receipt, path) if ident == row['id']
                                    else normalized_depth(reference, root, fetch=fetch))
            terrain_support.verify_sources(
                [{'row': reference, 'path': ref_path, 'receipt': ref_receipt}], root=root)
            reference_dependencies.append({'source_id': ident, 'source_sha256': reference['sha256'],
                'normalized_sha256': ref_receipt['cog_sha256'],
                'terrain_binding_sha256': (terrain_support.binding_digest(reference)
                                          if reference.get('terrain_support') else None)})
        reference_support = {'version': PAIRED_REFERENCE_SUPPORT,
            'source_ids': sorted(reference_ids), 'sources': reference_dependencies,
            'meaning': REFERENCE_NOTICE}
        # The original scientific pair stays distinct. Footprint derivatives
        # nevertheless retain every reference producer's terms and credits.
        rights_by_id = {r['source_id']: r for r in reference_rights}
        rights_by_id.update({r['source_id']: r for r in rights})
        rights = [rights_by_id[ident] for ident in sorted(rights_by_id)]
    support = unary_union([cell_geometry(c) for c in support_cells])
    from .screen import polygon
    existing = unary_union([transform(TO_LOCAL, polygon(f['geometry']))
                for f in read_json(folder/'candidates.geojson')['features']])
    identity = {'profile': PROFILE, 'reach': reach, 'policy': policy,
        'support_mode': mode,
        'reference_support': reference_support,
        'depth_source': row, 'classification_binding': binding, 'normalized_receipt': receipt,
        'normalized_sha256': receipt['cog_sha256'], 'source_scope': source_scope,
        'baseline_physical_input_hash': physical['input_hash'],
        'baseline_physical_sha256': sha256(folder/'physical.json'),
        'baseline_cells_sha256': sha256(folder/'cells.json'),
        'baseline_candidates_sha256': sha256(folder/'candidates.geojson'),
        'implementation': {n: sha256(Path(__file__).with_name(n)) for n in
            ('classified_habitat.py', 'classified_geometry.py', 'substrate.py', 'resolution_profile.py', 'normalized.py')},
        'geometry_representation': geometry_runtime()}
    neighbor, _ = neighbor_planning(root, reach, policy, baseline=run)
    if neighbor is not None:
        identity['neighbor_planning'] = neighbor
    return identity, row, binding, path, support, existing, rights


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


def features_for(patches, reach, policy, row, binding, *, reference_support=None, neighbor_planning=None):
    from .screen import polygon
    features = []
    for index, patch in enumerate(patches):
        geo = geographic(patch)
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
            'geometry_representation': {'version': GEOMETRY_VERSION, 'native_crs': 'EPSG:3310'},
            'classified_area': {'profile': PROFILE, 'policy_id': policy['id'],
                'metadata_sha256': policy['metadata_sha256'], 'independent_confirmation': False,
                'new_measured_area_km2': 0, 'interpolation_mask': 'unknown',
                'basis': 'Original publisher interpreted rugose rock and boulders; no fish presence inferred.'}}})
    if reference_support is not None:
        for feature in features:
            feature['properties']['reference_support'] = deepcopy(reference_support)
    if neighbor_planning is not None:
        for feature in features:
            feature['properties']['neighbor_planning'] = deepcopy(neighbor_planning)
    return {'type': 'FeatureCollection', 'features': features}


def stage(reach, *, root=REPO, fetch=False, edge=512, max_pixels=25_000_000):
    """Refresh only opt-in classified physics/screens; never edit the graded run."""
    from .screen import load_snapshot, input_identity
    root = Path(root)
    scope_name(reach)
    folder = root/'var/seafloor/reaches'/reach
    baseline = read_json(folder/'run.json')
    selected = [p for p in policies(root) if p['depth_source_id'] in
                {s['id'] for s in baseline['inputs']['sources']}
                and policy_applies_to_reach(p, reach)]
    receipt_path = folder/'classified-run.json'
    if not selected and not receipt_path.exists():
        return None  # An absent opt-in adds no artifacts to an untouched reach.
    # An explicit rerun reconciles a withdrawn policy to empty current outputs.
    # No-rerun publication still rejects the stale previously admitted receipt.
    # Policy changes add/remove explicit pairs without invalidating graded physics.
    contexts = [source_context(root, reach, p, fetch=fetch) for p in selected]
    physical_inputs = _physical_inputs(contexts)
    physical_hash = digest(physical_inputs)
    candidates_path = folder/'classified-candidates.geojson'
    native_path = folder/'classified-native.geojson'
    previous = read_json(receipt_path) if receipt_path.exists() else None
    reuse = bool(previous and previous['physical_input_hash'] == physical_hash)
    if reuse:
        if (sha256(candidates_path) != previous['outputs']['classified-candidates.geojson']
                or sha256(native_path) != previous['outputs']['classified-native.geojson']):
            raise ValueError('Classified candidates failed hash verification')
        candidates = read_json(candidates_path)
        native = read_json(native_path)
        physical_summary = previous['physical_summary']
    else:
        candidates = {'type': 'FeatureCollection', 'features': []}
        native = {'version': GEOMETRY_VERSION, 'crs': 'EPSG:3310', 'features': []}
        physical_summary = {'candidate_count': 0, 'class3_valid_depth_pixels': 0,
                            'classified_selected_area_km2': 0, 'new_measured_area_km2': 0}
        prior_native_patches = []
        for p, (identity, row, binding, path, support, existing, _) in zip(selected, contexts):
            pair_existing = (unary_union([existing, *prior_native_patches])
                             if prior_native_patches else existing)
            patches, summary = extract(row, binding, path, support, pair_existing,
                                       root=root, edge=edge, max_pixels=max_pixels)
            represented = features_for(patches, reach, p, row, binding,
                reference_support=identity.get('reference_support'),
                neighbor_planning=identity.get('neighbor_planning'))['features']
            candidates['features'].extend(represented)
            native['features'].extend({'type': 'Feature', 'geometry': mapping(patch),
                'properties': {'id': f['properties']['id']}} for patch, f in zip(patches, represented))
            prior_native_patches.extend(patches)
            for key, value in summary.items():
                physical_summary[key] += value
        physical_summary['candidate_count'] = len(candidates['features'])
        atomic_json(candidates_path, candidates)
        atomic_json(native_path, native)
    state = load_snapshot(root, reach)
    representation = verify_inventory(candidates, native)
    verify_pair_disjointness(candidates, native, contexts)
    native_geometries = {f['properties']['id']: f['geometry'] for f in native['features']}
    habitat, held, summary = classified_screen(candidates, state, native_geometries, contexts, root, reach)
    inputs = {'physical': physical_inputs, 'screen': input_identity(state),
              'screen_implementation_sha256': sha256(Path(__file__).with_name('screen.py'))}
    atomic_json(folder/'classified-habitat.geojson', habitat)
    atomic_json(folder/'classified-held.geojson', held)
    receipt = {'version': 1, 'reach': reach, 'input_hash': digest(inputs), 'inputs': inputs,
        'physical_input_hash': physical_hash, 'physical_reused': reuse,
        'physical_summary': physical_summary, 'summary': summary, 'representation': representation,
        'outputs': {name: sha256(folder/name) for name in
            ('classified-candidates.geojson', 'classified-native.geojson', 'classified-habitat.geojson', 'classified-held.geojson')}}
    atomic_json(receipt_path, receipt, indent=2)
    return receipt


def publication_features(reach, *, root=REPO):
    """Rehash current pair/physics, rights, artifacts and whole-polygon screen."""
    from .screen import load_snapshot, input_identity
    root = Path(root)
    scope_name(reach)
    folder = root/'var/seafloor/reaches'/reach
    path = folder/'classified-run.json'
    if not path.exists():
        return [], None
    receipt = read_json(path)
    if receipt.get('version') != 1 or receipt.get('reach') != reach:
        raise ValueError('Classified receipt identity mismatch')
    current_policies = policies(root)
    current = {p['id']: p for p in current_policies}
    contexts = []
    for saved in receipt['inputs']['physical']['sources']:
        p = saved['policy']
        if p != current.get(p['id']):
            raise ValueError('Classified opt-in changed or withdrawn')
        contexts.append(source_context(root, reach, p))
    baseline = read_json(folder/'run.json')
    baseline_ids = {s['id'] for s in baseline['inputs']['sources']}
    current_order = [p['id'] for p in current_policies
        if p['depth_source_id'] in baseline_ids and policy_applies_to_reach(p, reach)]
    if len(contexts) > 1 or len(current_order) > 1:
        saved_order = [c[0]['policy']['id'] for c in contexts]
        if saved_order != current_order:
            raise ValueError('Classified source-pair order changed; restage required')
    physical = _physical_inputs(contexts)
    state = load_snapshot(root, reach)
    inputs = {'physical': physical, 'screen': input_identity(state),
              'screen_implementation_sha256': sha256(Path(__file__).with_name('screen.py'))}
    if (receipt['inputs'] != inputs or receipt['input_hash'] != digest(inputs)
            or receipt['physical_input_hash'] != digest(physical)):
        raise ValueError('Classified inputs changed; restage required')
    expected_names = {'classified-candidates.geojson', 'classified-native.geojson', 'classified-habitat.geojson', 'classified-held.geojson'}
    if set(receipt['outputs']) != expected_names or any(
            sha256(folder/name) != expected for name, expected in receipt['outputs'].items()):
        raise ValueError('Classified output hash mismatch')
    candidates = read_json(folder/'classified-candidates.geojson')
    native = read_json(folder/'classified-native.geojson')
    representation = verify_inventory(candidates, native)
    verify_pair_disjointness(candidates, native, contexts)
    native_geometries = {f['properties']['id']: f['geometry'] for f in native['features']}
    habitat, held, summary = classified_screen(candidates, state, native_geometries, contexts, root, reach)
    if (representation != receipt.get('representation')
            or habitat != read_json(folder/'classified-habitat.geojson')
            or held != read_json(folder/'classified-held.geojson') or summary != receipt['summary']):
        raise ValueError('Classified whole-polygon screen changed')
    rights = {c[0]['policy']['id']: c[-1] for c in contexts}
    for f in habitat['features']:
        p = f['properties']
        saved = next((c[0] for c in contexts if c[0]['policy']['id'] ==
                      p.get('classified_area', {}).get('policy_id')), None)
        if (not published_contract(p) or saved is None
                or p.get('reference_support') != saved.get('reference_support')
                or p.get('neighbor_planning') != saved.get('neighbor_planning')
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
