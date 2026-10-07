"""Propose private native bedrock windows from already-qualified local inputs.

This research-only tool never edits a policy, source, cache, reach, screen, or
publication output. The only write is the explicitly requested proposal JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.windows import Window, bounds
from shapely import get_coordinates
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import read_json
from skippercast.seafloor import bedrock_habitat as bh
from skippercast.seafloor import classified_habitat as ch
from skippercast.seafloor.io import sha256
from skippercast.seafloor.fetch import fetch_source
from skippercast.seafloor.normalized import verify_review

MAX_EDGE = 512
MAX_PIXELS = 25_000_000
MIN_DEPTH_M = 25 * 0.3048
MAX_DEPTH_M = 300 * 0.3048


def nominal_depth_count(values, valid):
    """Count finite, valid nominal depths in the inclusive 25–300 ft interval."""
    values = np.asarray(values)
    valid = np.asarray(valid)
    if values.ndim != 2 or values.shape != valid.shape or valid.dtype != np.bool_:
        raise ValueError('Depth values and boolean validity mask must be matching 2-D arrays')
    if not np.issubdtype(values.dtype, np.number):
        raise ValueError('Depth values must be numeric')
    return int((valid & np.isfinite(values) & (values >= MIN_DEPTH_M)
                & (values <= MAX_DEPTH_M)).sum())


def depth_window_eligibility(window_record, valid_pixels):
    """Record the existing nominal-depth result without upgrading its meaning."""
    if type(valid_pixels) is not int or valid_pixels < 0:
        raise ValueError('Valid nominal-depth pixel count must be a nonnegative integer')
    window_record['valid_nominal_depth_pixels'] = valid_pixels
    if valid_pixels == 0:
        window_record['reasons'].append('no_valid_nominal_25_300ft_depth_pixels')
        return False
    return True


def enforce_pixel_bound(pixel_count, max_pixels):
    if (type(pixel_count) is not int or pixel_count < 0 or type(max_pixels) is not int
            or not 1 <= max_pixels <= MAX_PIXELS):
        raise ValueError('Invalid candidate pixel count or resource cap')
    if pixel_count > max_pixels:
        raise ValueError(f'Candidate windows require {pixel_count} pixels, above {max_pixels} cap')


def _window_records(width, height, edge, transform_affine, pure, support,
                    reviewed_scope, foreign_occupied):
    """Create a complete, one-pixel-inset, nonoverlapping native tile inventory."""
    coefficients = tuple(transform_affine)[:6]
    if (type(width) is not int or type(height) is not int or width < 3 or height < 3
            or type(edge) is not int or not 1 <= edge <= MAX_EDGE
            or not all(math.isfinite(float(v)) for v in coefficients)
            or transform_affine.determinant == 0):
        raise ValueError('Invalid raster dimensions, affine, or bounded native tile edge')
    if any(not geom.is_valid for geom in (pure, support, reviewed_scope, foreign_occupied)):
        raise ValueError('Invalid planning geometry; no repair is attempted')
    records = []
    for y in range(1, height - 1, edge):
        for x in range(1, width - 1, edge):
            w = Window(x, y, min(edge, width - 1 - x), min(edge, height - 1 - y))
            native_box = box(*bounds(w, transform_affine))
            if pure.intersection(native_box).area <= 0 or support.intersection(native_box).area <= 0:
                continue
            item = {'window': [int(w.col_off), int(w.row_off), int(w.width), int(w.height)],
                    'pixels': int(w.width * w.height), 'native_bounds': list(native_box.bounds),
                    'source_geometry_intersection_m2': float(pure.intersection(native_box).area),
                    'reasons': []}
            if not reviewed_scope.covers(native_box):
                item['reasons'].append('outside_verified_depth_scope')
            if not foreign_occupied.is_empty and native_box.intersection(foreign_occupied).area > 0:
                item['reasons'].append('whole_window_intersects_existing_occupied_geometry')
            records.append(item)
    # Tiling and insetting are explicit invariants; fail closed if a future edit breaks them.
    seen = set()
    total = 0
    for item in records:
        x, y, w, h = item['window']
        key = (x, y)
        if key in seen or x < 1 or y < 1 or w < 1 or h < 1 or x + w > width - 1 or y + h > height - 1:
            raise ValueError('Proposed native windows overlap or exceed the one-pixel-inset grid')
        seen.add(key)
        total += item['pixels']
    return records, total


def _finite_polygon(geometry, *, label):
    if geometry.geom_type not in {'Polygon', 'MultiPolygon'} or geometry.is_empty:
        raise ValueError(f'{label} must be a nonempty polygon or multipolygon')
    coords = get_coordinates(geometry, include_z=geometry.has_z)
    if coords.size == 0 or not np.isfinite(coords).all():
        raise ValueError(f'{label} coordinates must all be finite')
    return geometry


def _project_occupied(geojson_geometry, source_crs, target_crs, *, label):
    """Project valid polygon occupancy; invalid inputs fail closed without repair."""
    try:
        original = _finite_polygon(shape(geojson_geometry), label=label)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid {label}: {exc}') from exc
    if not original.is_valid:
        raise ValueError(f'Invalid {label}: source polygon is invalid; no repair or envelope is attempted')
    projected = transform(Transformer.from_crs(source_crs, target_crs, always_xy=True).transform,
                          original)
    projected = _finite_polygon(projected, label=f'Projected {label}')
    projected_envelope_used = not projected.is_valid
    if projected_envelope_used:
        projected = _finite_polygon(projected.envelope, label=f'Projected {label} envelope')
    return projected, projected_envelope_used


def _read_feature_collection(path, expected_crs):
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get('features'), list):
        raise ValueError(f'Invalid FeatureCollection schema in foreign occupancy input: {path}')
    if data.get('type') == 'FeatureCollection':
        # Held/candidate GeoJSON uses RFC 7946 coordinates (WGS84).
        if expected_crs != 4326:
            raise ValueError(f'Foreign occupancy CRS mismatch: {path}')
    elif (data.get('version') == 'native-classified-geometry-v1'
          and data.get('crs') == f'EPSG:{expected_crs}' and expected_crs == 3310):
        # The classified native output is a versioned project geometry wrapper.
        pass
    else:
        raise ValueError(f'Invalid FeatureCollection/CRS schema in foreign occupancy input: {path}')
    for feature in data['features']:
        if (not isinstance(feature, dict) or feature.get('type') != 'Feature'
                or not isinstance(feature.get('geometry'), dict)):
            raise ValueError(f'Invalid feature schema in foreign occupancy input: {path}')
    return data['features']


def _native_occupancy(root, target_reach, target_region, ds_crs):
    """Collect authenticated same-region classified occupancy, including held outputs.

    Output files use their established CRS conventions: native=EPSG:3310;
    held/candidate=EPSG:4326. Missing outputs are reported as unprocessed or
    incomplete, never interpreted as proof of empty occupancy. Nonzero private
    bedrock quarantine is flagged rather than imported without its native CRS
    and authentication context.
    """
    root = Path(root)
    pieces, inputs, assessments = [], [], []
    reaches = read_json(root / 'catalog/reaches.json').get('reaches')
    if not isinstance(reaches, list):
        raise ValueError('Invalid reach catalog schema for foreign occupancy')
    if any(not isinstance(r, dict) or not isinstance(r.get('id'), str)
           or not r['id'] or not isinstance(r.get('region'), str) or not r['region'] for r in reaches):
        raise ValueError('Reach catalog contains an invalid reach row')
    all_ids = [r['id'] for r in reaches]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError('Reach catalog contains duplicate IDs')
    foreign_rows = [r for r in reaches if r.get('region') == target_region and r.get('id') != target_reach]
    foreign_ids = [r['id'] for r in foreign_rows]
    expected = ('classified-native.geojson', 'classified-held.geojson',
                'classified-candidates.geojson')
    for reach in foreign_ids:
        folder = root / 'var/seafloor/reaches' / reach
        run_path = folder / 'classified-run.json'
        present = [name for name in expected if (folder / name).is_file()]
        missing = [name for name in expected if name not in present]
        status, reasons, features_total, envelope_count = 'unprocessed', [], 0, 0
        outputs = None
        if not present and not run_path.is_file():
            reasons.append('no classified outputs or receipt; occupancy unknown')
        else:
            status = 'incomplete'
            if missing:
                reasons.append('missing classified outputs: ' + ', '.join(missing))
            if not run_path.is_file():
                reasons.append('missing classified-run.json receipt')
            else:
                run = read_json(run_path)
                outputs = run.get('outputs') if isinstance(run, dict) else None
                if (not isinstance(outputs, dict) or run.get('reach') != reach
                        or any(not isinstance(k, str) or not isinstance(v, str)
                               or len(v) != 64 or any(c not in '0123456789abcdef' for c in v)
                               for k, v in outputs.items())):
                    raise ValueError(f'Invalid classified-run output schema: {run_path}')
                inputs.append({'path': str(run_path.relative_to(root)), 'sha256': sha256(run_path),
                               'kind': 'classified-run-receipt', 'reach_id': reach})
                for name in expected:
                    if outputs.get(name) is not None and not (folder / name).is_file():
                        reasons.append(f'classified-run receipt lists missing output: {name}')
            for name in present:
                path = folder / name
                actual_hash = sha256(path)
                if outputs is not None and outputs.get(name) not in (None, actual_hash):
                    raise ValueError(f'Foreign occupancy receipt hash mismatch: {path}')
                if outputs is None or outputs.get(name) != actual_hash:
                    reasons.append(f'occupancy file not authenticated by classified-run receipt: {name}')
                source_crs = 3310 if name == 'classified-native.geojson' else 4326
                features = _read_feature_collection(path, source_crs)
                inputs.append({'path': str(path.relative_to(root)), 'sha256': actual_hash,
                               'feature_count': len(features), 'crs': f'EPSG:{source_crs}',
                               'receipt_status': 'verified' if outputs and outputs.get(name) == actual_hash else 'unverified',
                               'reach_id': reach})
                features_total += len(features)
                for index, feature in enumerate(features):
                    geom, used_envelope = _project_occupied(
                        feature['geometry'], source_crs, ds_crs,
                        label=f'{reach}/{name} feature {index}')
                    pieces.append(geom)
                    envelope_count += int(used_envelope)
            audit_name = 'classified-bedrock-audit.json'
            audit_path = folder / audit_name
            audit_claimed = outputs is not None and outputs.get(audit_name) is not None
            if audit_claimed:
                if not audit_path.is_file() or outputs[audit_name] != sha256(audit_path):
                    raise ValueError(f'Foreign bedrock quarantine audit receipt mismatch: {audit_path}')
                audit = read_json(audit_path)
                if (not isinstance(audit, dict) or audit.get('version') != 'interpreted-bedrock-private-audit-v1'
                        or not isinstance(audit.get('quarantine'), list)):
                    raise ValueError(f'Invalid private bedrock quarantine audit schema: {audit_path}')
                inputs.append({'path': str(audit_path.relative_to(root)), 'sha256': sha256(audit_path),
                               'quarantine_count': len(audit['quarantine']), 'kind': 'private-bedrock-audit',
                               'reach_id': reach})
                if audit['quarantine']:
                    reasons.append('nonzero private bedrock quarantine not ingested; CRS/authentication required')
            else:
                reasons.append('private bedrock quarantine audit absent; zero quarantine is unverified')
            if not reasons:
                status = 'verified'
        assessments.append({'reach_id': reach, 'status': status, 'complete': status == 'verified',
                            'present_outputs': present, 'missing_outputs': missing,
                            'feature_count': features_total, 'conservative_envelope_count': envelope_count,
                            'reasons': reasons})
    occupancy = unary_union(pieces) if pieces else unary_union([])
    return occupancy, foreign_ids, inputs, assessments


def _read_only_normalized_ingest(row, bounds, *, root, fetch=False, local=None):
    """Return a fully reviewed existing COG receipt; never normalize or write receipts."""
    if fetch or local is not None:
        raise ValueError('The private proposer accepts only already-cached source bytes')
    review = row.get('adapter_review')
    if not isinstance(review, dict) or list(bounds) != review.get('requested_bounds_wgs84'):
        raise ValueError('Missing or mismatched reviewed normalized-depth bounds')
    expected_cog = review.get('cog_sha256')
    if not isinstance(expected_cog, str) or len(expected_cog) != 64:
        raise ValueError('Reviewed normalized COG hash is missing')
    cache = Path(root) / 'var/seafloor/cache'
    source, downloaded = fetch_source(row, cache, fetch=False)
    if downloaded:
        raise ValueError('Unexpected source acquisition during read-only proposal')
    source_receipts = sorted((cache / row['sha256']).glob('*.json'))
    for receipt_path in source_receipts:
        saved = read_json(receipt_path)
        if not isinstance(saved, dict) or saved.get('cog_sha256') != expected_cog:
            continue
        if saved.get('source_id') != row['id'] or saved.get('source_sha256') != row['sha256']:
            continue
        cog = receipt_path.with_suffix('.tif')
        if not cog.is_file():
            raise ValueError('Reviewed normalized COG is missing from the local cache')
        if sha256(cog) != expected_cog:
            raise ValueError('Cached normalized COG hash mismatch')
        verify_review(saved, review, cog)
        return saved, False, True
    raise FileNotFoundError('No complete hash-verified normalized COG receipt is cached; no write attempted')


def _read_only_source_context(root, reach, policy):
    # ArcGrid source_path extracts on a cache miss, even when its caller uses
    # fetch=False. Require the exact extraction and receipt before allowing its
    # existing strict cache-hit checksum validation to run.
    from skippercast.seafloor.adapters import arcgrid

    original_source_path = arcgrid.source_path

    def read_only_arcgrid_source_path(path, row):
        path = Path(path)
        member = arcgrid.safe_name(row['archive_member'])
        identity = hashlib.sha256(member.encode()).hexdigest()[:16]
        destination = path.parent / ('grid-' + identity)
        receipt_path = destination.with_suffix('.json')
        if (destination.is_symlink() or receipt_path.is_symlink()
                or not destination.is_dir() or not receipt_path.is_file()):
            raise FileNotFoundError('Exact ArcGrid extraction and receipt must already be cached; no write attempted')
        receipt = read_json(receipt_path)
        if (not isinstance(receipt, dict) or receipt.get('archive_sha256') != sha256(path)
                or receipt.get('member') != member or not isinstance(receipt.get('files'), dict)):
            raise ValueError('Cached ArcGrid receipt is stale or invalid; no write attempted')
        # The original implementation now takes only its fully verified cache-hit
        # branch. It also checks every extracted member digest and symlink.
        return original_source_path(path, row)

    with (patch.object(ch, 'ingest', _read_only_normalized_ingest),
          patch.object(arcgrid, 'source_path', read_only_arcgrid_source_path)):
        return ch.source_context(root, reach, policy, fetch=False)


def propose(root, reach, policy_id, *, edge=MAX_EDGE, max_pixels=MAX_PIXELS):
    """Read qualified local source evidence and return a private proposal object."""
    root = Path(root).resolve()
    if not root.is_dir() or not 1 <= edge <= MAX_EDGE or not 1 <= max_pixels <= MAX_PIXELS:
        raise ValueError('Invalid local root or resource bound')
    policies = ch.policies(root)
    matches = [p for p in policies if p.get('id') == policy_id]
    if len(matches) != 1:
        raise ValueError('Policy ID must identify exactly one reviewed local policy')
    policy = matches[0]
    if reach not in policy.get('reach_ids', []):
        raise ValueError('Reach is not included in the reviewed policy')
    # fetch=False is essential: the proposer accepts only already-cached originals.
    identity, depth_row, binding, depth_path, support, _existing, rights = _read_only_source_context(
        root, reach, policy)
    region_rows = [r for r in read_json(root/'catalog/reaches.json')['reaches'] if r['id'] == reach]
    if len(region_rows) != 1:
        raise ValueError('Reach must exist exactly once in the local reach catalog')
    region = region_rows[0]['region']

    with rasterio.open(depth_path) as ds:
        if (ds.count != 1 or ds.descriptions[0] != 'depth_m_positive_down'
                or ds.transform.b != 0 or ds.transform.d != 0 or ds.transform.a <= 0 or ds.transform.e >= 0
                or not all(math.isfinite(float(v)) for v in tuple(ds.transform)[:6])):
            raise ValueError('Depth source is not a verified north-up normalized native grid')
        crs = CRS.from_user_input(ds.crs)
        if not crs.is_projected or any(axis.unit_conversion_factor != 1 for axis in crs.axis_info):
            raise ValueError('Depth grid must use projected metre coordinates')
        records, _units, source_holds = bh.original_vectors(binding['archive'], policy, ds.crs)
        to_native = Transformer.from_crs(3310, ds.crs, always_xy=True).transform
        native_support = transform(to_native, support).intersection(box(*ds.bounds))
        pure = unary_union([g.intersection(native_support) for g in records.values()
                            if g.intersects(native_support)])
        reviewed_scope = transform(
            Transformer.from_crs(4326, ds.crs, always_xy=True).transform,
            box(*binding['reviewed_depth_bounds_wgs84']))
        foreign, foreign_ids, foreign_inputs, foreign_assessments = _native_occupancy(
            root, reach, region, ds.crs)
        planned, candidate_pixels = _window_records(
            ds.width, ds.height, edge, ds.transform, pure, native_support, reviewed_scope, foreign)
        enforce_pixel_bound(candidate_pixels, max_pixels)
        eligible, empty_depth = [], []
        for item in planned:
            if item['reasons']:
                continue
            x, y, width, height = item['window']
            window = Window(x, y, width, height)
            values = ds.read(1, window=window, masked=True)
            valid = ~np.ma.getmaskarray(values)
            count = nominal_depth_count(values.filled(float('nan')), valid)
            if depth_window_eligibility(item, count):
                eligible.append(item)
            else:
                empty_depth.append(item)
        eligible_pixels = sum(x['pixels'] for x in eligible)
        enforce_pixel_bound(eligible_pixels, max_pixels)
        header = {'width': ds.width, 'height': ds.height, 'crs': ds.crs.to_string(),
                  'resolution': list(ds.res), 'band': ds.descriptions[0],
                  'normalized_depth_sha256': sha256(depth_path)}

    return {
        'schema_version': 1,
        'artifact_kind': 'research-only-private-native-window-proposal',
        'policy_id': policy_id, 'reach_id': reach,
        'status': ('private_proposal_foreign_assessment_incomplete'
                   if any(not item['complete'] for item in foreign_assessments)
                   else 'private_research_proposal_only'),
        'policy_safeguard': {
            'activation_allowed_by_this_tool': False,
            'source_qualification_claimed': False,
            'measurement_or_rank_claimed': False,
            'publication_or_export_claimed': False,
            'own_policy_occupancy': 'The currently configured target-policy windows are recorded as read-only context and are not treated as foreign occupancy. This avoids self-exclusion; it does not authorize replacing or expanding an existing policy.',
            'configured_windows_read_only': policy.get('vector_review', {}).get('native_windows', []),
            'configured_policy_window_count': len(policy.get('vector_review', {}).get('native_windows', [])),
            'required_before_any_separate_activation': 'Review existing output IDs and geometries against all configured windows. Preserve prior geometry and IDs; no activation or replacement is performed here.'
        },
        'source_context_sha256': ch.digest(identity),
        'depth_source_id': depth_row['id'],
        'depth_source_sha256': depth_row['sha256'],
        'classification_source_id': binding['row']['id'],
        'classification_source_sha256': binding['row']['sha256'],
        'rights_context': rights,
        'native_grid': header,
        'resource_limits': {'edge_max_pixels': edge * edge, 'tile_edge': edge,
                            'candidate_pixel_cap': max_pixels,
                            'candidate_window_count': len(planned),
                            'candidate_pixels': candidate_pixels,
                            'eligible_window_count': len(eligible),
                            'eligible_pixels': eligible_pixels},
        'foreign_region_reaches_considered': foreign_ids,
        'foreign_occupancy_inputs': foreign_inputs,
        'foreign_occupancy_assessments': foreign_assessments,
        'foreign_occupancy_complete': all(item['complete'] for item in foreign_assessments),
        'separate_activation_precondition': 'Resolve each unprocessed/incomplete foreign reach and verify zero or safely ingested native-quarantine geometry before any separate activation. This proposal does not perform that review.',
        'reviewed_bedrock_units': policy.get('vector_review', {}).get('bedrock_units', []),
        'excluded_map_units': policy.get('vector_review', {}).get('excluded_units', []),
        'source_holds': source_holds,
        'invalid_original_records': policy.get('vector_review', {}).get('invalid_original_records', []),
        'proposal_windows': [x['window'] for x in eligible],
        'eligible_windows': eligible,
        'held_windows': [x for x in planned if x['reasons']],
        'empty_depth_windows': empty_depth,
        'exclusions': {
            'outside_verified_depth_scope': sum('outside_verified_depth_scope' in x['reasons'] for x in planned),
            'foreign_occupied_overlap': sum('whole_window_intersects_existing_occupied_geometry' in x['reasons'] for x in planned),
            'empty_nominal_depth': len(empty_depth),
            'invalid_original_records_retained_as_holds': len(policy.get('vector_review', {}).get('invalid_original_records', [])),
        },
        'claim_limits': [
            'Proposal is private research output; it does not qualify a source, modify or activate a policy, or publish or export results.',
            'Native-window bounds and overlap checks do not establish measured habitat edges.',
            'Depth counts use existing normalized nominal depth only; no datum or accuracy upgrade.',
            'No habitat area, grade, fish presence, screening, or publication is claimed.'
        ]
    }


def validate_output_location(root, output):
    root = Path(root).resolve()
    output = Path(output).resolve()
    if output == root or root in output.parents:
        raise ValueError('Proposal output must be outside the inspected checkout/workroot')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='Local checkout/workroot with reviewed catalogs and caches')
    parser.add_argument('--reach', required=True)
    parser.add_argument('--policy-id', required=True)
    parser.add_argument('--output', required=True, help='New private JSON output path; existing files are not overwritten')
    parser.add_argument('--edge', type=int, default=MAX_EDGE)
    parser.add_argument('--max-pixels', type=int, default=MAX_PIXELS)
    args = parser.parse_args(argv)
    try:
        output = validate_output_location(args.root, Path(args.output).expanduser())
    except ValueError as exc:
        parser.error(str(exc))
    if output.exists():
        parser.error('output already exists; choose a new explicit path')
    try:
        result = propose(args.root, args.reach, args.policy_id,
                         edge=args.edge, max_pixels=args.max_pixels)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(result, indent=2, allow_nan=False) + '\n')
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps({'output': str(output), 'candidate_windows': result['resource_limits']['candidate_window_count'],
                      'eligible_windows': result['resource_limits']['eligible_window_count'],
                      'eligible_pixels': result['resource_limits']['eligible_pixels'],
                      'held_windows': len(result['held_windows']),
                      'source_context_sha256': result['source_context_sha256']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
