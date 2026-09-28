"""Whole-polygon planning screen. Missing, stale or out-of-scope evidence holds.

This is a spatial restriction screen, not a season/gear permission decision.
All MPA and federal features are conservatively held, including areas whose
applicability would need a fishery-specific review. Never clip away the conflict.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import read_json
from .io import sha256

VERSION = 'whole-polygon-screen-v1'
LAYERS = {'cdfw-mpa', 'noaa-federal', 'security'}
PROJECT = Transformer.from_crs(4326, 3310, always_xy=True).transform


def polygon(geometry):
    result = shape(geometry)
    if (result.geom_type not in ('Polygon', 'MultiPolygon') or result.is_empty
            or not result.is_valid or not all(math.isfinite(x) for x in result.bounds)):
        raise ValueError('Invalid screen polygon')
    w, s, e, n = result.bounds
    if not (-180 <= w <= e <= 180 and -90 <= s <= n <= 90):
        raise ValueError('Screen geometry must be WGS84')
    return result


def exclusion_polygon(geometry):
    """Union overlapping/nested *valid* components without subtracting any area.

    Some original CDFW MultiPolygons contain nested shells. Repair is limited
    to unioning individually valid polygons, never generic buffer/make-valid
    operations that might shrink a restriction or invent its intended boundary.
    """
    raw = shape(geometry)
    if raw.geom_type == 'MultiPolygon' and not raw.is_valid:
        parts = [polygon(part.__geo_interface__) for part in raw.geoms]
        return polygon(unary_union(parts).__geo_interface__)
    return polygon(geometry)


def current(stamp, now):
    try:
        checked = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        return checked.tzinfo is not None and 0 <= (now-checked).total_seconds() <= 35*86400
    except (ValueError, TypeError, AttributeError):
        return False


def load_snapshot(root, reach_id, now=None):
    """Hash every input; an unavailable layer cannot silently become an empty layer."""
    now = now or datetime.now(timezone.utc)
    path = Path(root)/'var/seafloor/screen/snapshot.json'
    state = {'version': VERSION, 'status': 'held', 'reasons': [], 'layers': []}
    if not path.exists():
        state['reasons'] = ['screen-missing']
        return state
    state['snapshot_sha256'] = sha256(path)
    try:
        data = read_json(path)
        if (path.parent/'refresh-failure.json').exists():
            state['reasons'].append('screen-refresh-failed')
        if data['policy_sha256'] != sha256(Path(root)/'catalog/seafloor-screen.json'):
            state['reasons'].append('screen-policy-changed')
        if data['version'] != VERSION or set(data['layers']) != LAYERS:
            raise ValueError('Incomplete screen layer inventory')
        if reach_id not in data['reviewed_reaches']:
            state['reasons'].append('screen-scope-unreviewed')
        state['scope'] = data['scope']
        polygon(state['scope'])
        state['snapshot'] = data['checked_at']
        if not current(data['checked_at'], now):
            state['reasons'].append('screen-stale')
        for ident, row in sorted(data['layers'].items()):
            if not current(row['checked_at'], now):
                state['reasons'].append('screen-stale')
            if ident == 'security' and not current(row['evidence']['up_to_date_as_of']+'T00:00:00+00:00', now):
                state['reasons'].append('screen-stale')
            if (row['status'] != 'ok' or row['feature_count'] < 1
                    or not row['source_url'].startswith('https://')):
                raise ValueError('Missing reviewed source')
            source = path.parent/row['file']
            if source.resolve().parent != path.parent.resolve() or sha256(source) != row['sha256']:
                raise ValueError('Screen source failed hash verification')
            layer = read_json(source)
            features = layer['features']
            if layer['type'] != 'FeatureCollection' or len(features) != row['feature_count']:
                raise ValueError('Truncated screen inventory')
            normalized = 0
            for feature in features:
                exclusion_polygon(feature['geometry'])
                normalized += not shape(feature['geometry']).is_valid
            state['layers'].append({**row, 'id': ident, 'features': features,
                'nested_or_overlapping_components_unioned': normalized})
        state['reasons'] = sorted(set(state['reasons']))
        state['status'] = 'held' if state['reasons'] else 'ready'
    except (ValueError, KeyError, TypeError, OSError) as error:
        state['reasons'] = sorted(set(state['reasons'] + ['screen-invalid']))
        state['error'] = str(error)
    return state


def input_identity(state):
    """Include freshness state as well as bytes: unchanged snapshots still expire."""
    value = {k: v for k, v in state.items() if k != 'layers'}
    value['layers'] = [{k: v for k, v in row.items() if k != 'features'} for row in state['layers']]
    return value


def screen_candidates(candidates, state):
    passed, held, counts, grades = [], [], Counter(), Counter()
    scope = polygon(state['scope']) if state['status'] == 'ready' else None
    exclusions = [(row['id'], unary_union([transform(PROJECT, exclusion_polygon(f['geometry']))
                    for f in row['features']])) for row in state['layers']] if scope else []
    for original in candidates['features']:
        feature = deepcopy(original)
        p = feature['properties']
        # Start fresh; a prior pass never exempts a feature from a changed screen.
        reasons = [r for r in p.get('hold_reasons', []) if r not in ('legal-screen-pending',)
                   and not r.startswith(('screen-', 'overlap-'))]
        reasons += state['reasons']
        try:
            geo = polygon(feature['geometry'])
            local = transform(PROJECT, geo)
            if scope is not None:
                if not scope.covers(geo):
                    reasons.append('screen-outside-coverage')
                for ident, exclusion in exclusions:
                    # Boundary touch, small overlap and polygon holes are all tested.
                    if local.intersects(exclusion):
                        reasons.append('overlap-'+ident)
            terrain = p.get('terrain')
            if not isinstance(terrain, dict) or terrain.get('grade') not in ('A', 'B', 'C'):
                reasons.append('metric-support-incomplete')
            if (not p.get('fit') or any(v not in (1, 2, 3) for v in p['fit'].values())
                    or not 0 < p['resolution_m'] <= 16
                    or not 25-1e-6 <= p['depth_min_ft'] <= p['depth_max_ft'] <= 300+1e-6
                    or local.area < 1000-0.01):
                reasons.append('habitat-contract-incomplete')
        except (KeyError, ValueError, TypeError):
            reasons.append('habitat-geometry-invalid')
        reasons = sorted(set(reasons))
        p.update(tier=1 if reasons else 2, status='held' if reasons else 'habitat',
                 exportable=not reasons, hold_reasons=reasons)
        p['screen'] = {'status': 'held' if reasons else 'pass',
                       'snapshot': state.get('snapshot', 'unknown'),
                       'snapshot_sha256': state.get('snapshot_sha256', 'unknown'),
                       'version': VERSION, 'layers': [r['id'] for r in state['layers']],
                       'scope': 'Spatial planning screen; season, gear and current notices still apply.'}
        label = f"Habitat candidate, unverified. Nominal depth ({p.get('vertical_datum', 'unknown')}); verify on your sounder."
        if p.get('resolution_m', 0) > 4:
            label += ' Broad area, not an individual pile.'
        p['label'] = ('Held: '+', '.join(reasons)+'. ' if reasons else '') + label
        p['planning_notice'] = 'Planning only. Not a navigation chart. Check current CDFW regulations.'
        if reasons:
            held.append(feature); counts.update(reasons)
        else:
            passed.append(feature); grades.update([p['terrain']['grade']])
    area = unary_union([transform(PROJECT, shape(f['geometry'])) for f in passed]).area/1e6
    return ({'type': 'FeatureCollection', 'features': passed},
            {'type': 'FeatureCollection', 'features': held},
            {'tier2_km2': round(area, 9), 'habitat_count': len(passed),
             'held_candidate_count': len(held), 'held_by_reason': dict(sorted(counts.items())),
             'habitat_by_grade': dict(sorted(grades.items())),
             'screen': input_identity(state)})
