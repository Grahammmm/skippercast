"""Check every legacy Central atlas geometry against fresh state/federal polygons.

The atlas depth evidence is recorded at 200 ft, which is within a 300 ft boat
ceiling. This audit only updates closure proximity; it cannot resurvey depth,
clear other access limits, certify a route, or add deeper fishing targets.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh(when):
    checked = datetime.fromisoformat(when.replace('Z', '+00:00'))
    age = (datetime.now(timezone.utc) - checked).total_seconds()
    if not 0 <= age <= 36 * 3600:
        raise ValueError('Protected-area geometry is stale or future-dated')


EXPECTED_COUNTS = {'targets': 132, 'areas': 107, 'drifts': 31}
EXPECTED_TYPES = {'areas': {'Polygon', 'MultiPolygon'},
                  'drifts': {'LineString', 'MultiLineString'}}


def _valid_shape(name, item):
    if not isinstance(item, dict):
        return False
    if name == 'targets':
        return 'longitude' in item and 'latitude' in item
    geom = item.get('geometry')
    return isinstance(geom, dict) and geom.get('type') in EXPECTED_TYPES[name]


def completeness(name, items, expected_ids=None):
    """Report which atlas features were screened; any problem withholds all-clear."""
    ids = [i.get('id') if isinstance(i, dict) else None for i in items]
    seen, dupes = set(), set()
    for i in ids:
        if isinstance(i, str) and i:
            (dupes if i in seen else seen).add(i)
    bad_ids = sum(1 for i in ids if not isinstance(i, str) or not i)
    wrong = [str(i) for item, i in zip(items, ids) if not _valid_shape(name, item)]
    want_n = EXPECTED_COUNTS[name]
    out = {'screened_count': len(items), 'expected_count': want_n,
           'unique_id_count': len(seen), 'duplicate_ids': sorted(map(str, dupes)),
           'invalid_id_count': bad_ids, 'wrong_geometry_type_ids': wrong}
    problems = bool(dupes or bad_ids or wrong or len(items) != want_n or len(seen) != want_n)
    if expected_ids is not None:
        want = set(expected_ids.get(name, ()))
        out['missing_ids'] = sorted(want - seen)
        out['unexpected_ids'] = sorted(map(str, seen - want))
        problems = problems or bool(out['missing_ids'] or out['unexpected_ids'])
    out['complete'] = not problems
    return out


def audit(atlas, mpa, federal, expected_ids=None, expected_atlas_sha256=None, atlas_sha256=None):
    """The all-clear is true only when the atlas is bound to a reviewed revision (digest)
    or expected ID sets, every section is complete and nothing is held."""
    if atlas.get('fishing_depth_limit_ft') != 200:
        raise ValueError('Unexpected legacy Central atlas scope')
    bound = expected_ids is not None or (expected_atlas_sha256 is not None
                                         and atlas_sha256 == expected_atlas_sha256)
    state = mpa['sources']['mpas']
    fresh(state['data_retrieved_at'])
    features = state['data']['geojson']['features']
    if state['status'] != 'ok' or len(features) < 100:
        raise ValueError('Incomplete CDFW MPA source')
    fresh(federal['retrieved_at'])
    if federal.get('status') != 'ok' or len(federal.get('features', [])) < 25:
        raise ValueError('Incomplete NOAA federal-area source')
    geas = [f for f in federal['features'] if f['properties']['area_type'] == 'GEA']
    if len(geas) < 10:
        raise ValueError('Incomplete NOAA GEA source')
    project = Transformer.from_crs(4326, 32610, always_xy=True).transform
    closed = unary_union([transform(project, shape(f['geometry'])) for f in features + geas])
    sections = {}
    for name, clearance in (('targets', 200), ('areas', 100), ('drifts', 100)):
        items = atlas.get(name) or []
        report = completeness(name, items, expected_ids)
        rows = []
        for item in items:
            if (not _valid_shape(name, item) or not isinstance(item.get('id'), str)
                    or not item['id']):
                continue  # reported in completeness; nothing to screen
            geom = (Point(item['longitude'], item['latitude']) if name == 'targets'
                    else shape(item['geometry']))
            if geom.is_empty or not geom.is_valid:
                raise ValueError('Invalid atlas geometry: ' + str(item.get('id')))
            projected = transform(project, geom)
            if (projected.is_empty or not projected.is_valid
                    or not all(math.isfinite(v) for v in projected.bounds)):
                raise ValueError('Invalid projected atlas geometry: ' + str(item['id']))
            distance = float(projected.distance(closed))
            if not math.isfinite(distance):
                raise ValueError('Invalid geometry clearance: ' + str(item['id']))
            rows.append({'id': item['id'], 'clearance_m': round(distance, 1),
                         'held': distance < clearance})
        sections[name] = {'count': len(rows), 'screen_buffer_m': clearance,
                          'minimum_clearance_m': min((r['clearance_m'] for r in rows), default=None),
                          'held_ids': [r['id'] for r in rows if r['held']],
                          'completeness': report}
    return {'schema_version': 1, 'scope': 'central-legacy-atlas-current-closure-screen',
            'audited_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'atlas_source_depth_ceiling_ft': 200, 'boat_planning_depth_ceiling_ft': 300,
            'cdfw_mpa_retrieved_at': state['data_retrieved_at'],
            'noaa_federal_retrieved_at': federal['retrieved_at'],
            'sections': sections,
            'atlas_bound_to_reviewed_revision': bound,
            'all_sections_complete': all(s['completeness']['complete'] for s in sections.values()),
            'all_geometry_clear_of_screen_buffers': bool(
                bound and all(s['completeness']['complete'] and not s['held_ids']
                              for s in sections.values())),
            'limitations': ['The 132 targets retain historical recorded 200-ft survey evidence; this is not a new native-depth survey.',
                            'Approximate GIS polygon clearance is not an official legal-boundary or navigation determination.',
                            'Current ENC hazards, Diablo security limits, Vandenberg access, drift route and season/method rules need separate checks.',
                            'No new 200–300-ft targets were qualified by this audit.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--atlas', type=Path, default=Path('dist/data/atlas.json'))
    p.add_argument('--mpas', type=Path, required=True)
    p.add_argument('--federal', type=Path, required=True)
    p.add_argument('--expected-ids', type=Path,
                   help='JSON {targets|areas|drifts: [ids]} from the reviewed atlas edition')
    p.add_argument('--expected-atlas-sha256', help='reviewed atlas file digest')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = audit(json.loads(a.atlas.read_text()), json.loads(a.mpas.read_text()),
                   json.loads(a.federal.read_text()),
                   expected_ids=json.loads(a.expected_ids.read_text()) if a.expected_ids else None,
                   expected_atlas_sha256=a.expected_atlas_sha256, atlas_sha256=digest(a.atlas))
    result['input_sha256'] = {'atlas': digest(a.atlas), 'mpas': digest(a.mpas),
                              'federal': digest(a.federal)}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.output.with_suffix(a.output.suffix + '.tmp')
    tmp.write_text(json.dumps(result, indent=2) + '\n')
    tmp.replace(a.output)
    print(result['sections'])


if __name__ == '__main__':
    main()
