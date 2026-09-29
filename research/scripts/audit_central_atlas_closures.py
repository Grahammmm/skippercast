"""Check every legacy Central atlas geometry against fresh state/federal polygons.

The atlas depth evidence is recorded at 200 ft, which is within a 300 ft boat
ceiling. This audit only updates closure proximity; it cannot resurvey depth,
clear other access limits, certify a route, or add deeper fishing targets.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
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


def audit(atlas, mpa, federal):
    if atlas.get('fishing_depth_limit_ft') != 200 or len(atlas.get('targets', [])) != 132:
        raise ValueError('Unexpected legacy Central atlas scope')
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
        rows = []
        for item in atlas[name]:
            geom = (Point(item['longitude'], item['latitude']) if name == 'targets'
                    else shape(item['geometry']))
            if geom.is_empty or not geom.is_valid:
                raise ValueError('Invalid atlas geometry: ' + item['id'])
            distance = float(transform(project, geom).distance(closed))
            rows.append({'id': item['id'], 'clearance_m': round(distance, 1),
                         'held': distance < clearance})
        sections[name] = {'count': len(rows), 'screen_buffer_m': clearance,
                          'minimum_clearance_m': min(r['clearance_m'] for r in rows),
                          'held_ids': [r['id'] for r in rows if r['held']]}
    return {'schema_version': 1, 'scope': 'central-legacy-atlas-current-closure-screen',
            'audited_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'atlas_source_depth_ceiling_ft': 200, 'boat_planning_depth_ceiling_ft': 300,
            'cdfw_mpa_retrieved_at': state['data_retrieved_at'],
            'noaa_federal_retrieved_at': federal['retrieved_at'],
            'sections': sections,
            'all_geometry_clear_of_screen_buffers': all(not s['held_ids'] for s in sections.values()),
            'limitations': ['The 132 targets retain historical recorded 200-ft survey evidence; this is not a new native-depth survey.',
                            'Approximate GIS polygon clearance is not an official legal-boundary or navigation determination.',
                            'Current ENC hazards, Diablo security limits, Vandenberg access, drift route and season/method rules need separate checks.',
                            'No new 200–300-ft targets were qualified by this audit.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--atlas', type=Path, default=Path('dist/data/atlas.json'))
    p.add_argument('--mpas', type=Path, required=True)
    p.add_argument('--federal', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = audit(json.loads(a.atlas.read_text()), json.loads(a.mpas.read_text()),
                   json.loads(a.federal.read_text()))
    result['input_sha256'] = {'atlas': digest(a.atlas), 'mpas': digest(a.mpas),
                              'federal': digest(a.federal)}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.output.with_suffix(a.output.suffix + '.tmp')
    tmp.write_text(json.dumps(result, indent=2) + '\n')
    tmp.replace(a.output)
    print(result['sections'])


if __name__ == '__main__':
    main()
