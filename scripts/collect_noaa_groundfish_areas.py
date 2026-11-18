"""Collect NOAA's original West Coast federal groundfish-area geometries.

These approximate GIS polygons are source evidence, not the controlling legal
boundary. GEA geometry is a conservative groundfish-candidate exclusion; other
area types require method- and date-specific regulatory review.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from itertools import combinations, groupby, pairwise
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


SERVICE = ('https://maps.fisheries.noaa.gov/server/rest/services/WCR_SFD_GCA/'
           'NOAA_Fisheries_West_Coast_Region_Groundfish_Conservation_Area_service/MapServer')
LAW = 'https://www.ecfr.gov/current/title-50/section-660.70'
MAX_BYTES = 5_000_000


def fetch_json(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'maps.fisheries.noaa.gov'
            or not parsed.path.startswith('/server/rest/services/WCR_SFD_GCA/')
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('Unreviewed NOAA GIS host or path')
    with urlopen(Request(url, headers={'User-Agent': 'SkipperCast federal groundfish area review/1.0'}), timeout=30) as response:
        if response.url != url:
            raise ValueError('NOAA GIS redirected')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('NOAA GIS response exceeds bound')
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _side(a, b, p):
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _contacts(a, b, c, d):
    ab_c, ab_d = _side(a, b, c), _side(a, b, d)
    cd_a, cd_b = _side(c, d, a), _side(c, d, b)
    if ab_c * ab_d < 0 and cd_a * cd_b < 0:
        raise ValueError('Crossing polygon edges')
    touches = {p for p, u, v, side in ((c, a, b, ab_c), (d, a, b, ab_d),
                                      (a, c, d, cd_a), (b, c, d, cd_b))
               if side == 0 and all(min(x, y) <= z <= max(x, y) for z, x, y in zip(p, u, v))}
    if len(touches) > 1:
        raise ValueError('Overlapping polygon edges')
    return touches


def _boundary_contacts(rings):
    edges = sorted((min(a[0], b[0]), max(a[0], b[0]), i, j, a, b)
                   for i, ring in enumerate(rings) for j, (a, b) in enumerate(pairwise(ring)))
    cuts = [{} for _ in rings]
    contacts = {}
    # Sweep in longitude so only edges with intersecting bounding boxes are compared.
    for k, (_, right, i, j, a, b) in enumerate(edges):
        for l in range(k + 1, len(edges)):
            left, _, m, n, c, d = edges[l]
            if left > right:
                break
            if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
                continue
            touches = _contacts(a, b, c, d)
            if not touches:
                continue
            if i == m:
                if abs(j - n) not in (1, len(rings[i]) - 2):
                    raise ValueError('Self-touching polygon ring')
            else:
                cuts[i].setdefault(j, set()).update(touches)
                cuts[m].setdefault(n, set()).update(touches)
                contacts.setdefault(next(iter(touches)), set()).update((i, m))
    return cuts, contacts


def _arc_samples(ring, cuts):
    # One midpoint per open arc after splitting at boundary contacts. Use
    # doubled coordinates so even the midpoints are exact integers.
    if not cuts:
        a, b = ring[:2]
        return [(a[0] + b[0], a[1] + b[1])]
    return [(u[0] + v[0], u[1] + v[1]) for j, (a, b) in enumerate(pairwise(ring))
            for u, v in pairwise(sorted({a, b} | cuts.get(j, set())))]


def _inside(ring, point2):
    x2, y2 = point2
    inside = False
    for (ax, ay), (bx, by) in pairwise(ring):
        if (2 * ay > y2) != (2 * by > y2):
            side = (bx - ax) * (y2 - 2 * ay) - (by - ay) * (x2 - 2 * ax)
            if (side > 0) == (by > ay):
                inside = not inside
    return inside


def _connected_interior(component, contacts):
    # A cycle between rings via distinct contact points disconnects the interior.
    # A single contact shared by multiple rings is one node, not a cycle.
    parent = {i: i for i in component}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for touching in contacts.values():
        group = iter(touching.intersection(parent))
        first = next(group, None)
        for i in group:
            a, b = root(first), root(i)
            if a == b:
                return False
            parent[b] = a
    return True


def _polygon_topology(polygons):
    rings, areas, components = [], [], []
    # In the bounded NOAA domain every binary64 ordinate is an exact multiple
    # of 2**-48. Scale the XY plane once to avoid floating-point cancellation.
    for polygon in polygons:
        start = len(rings)
        for ring in polygon:
            points = ((int(x * 2**48), int(y * 2**48)) for x, y, *_ in ring)
            points = [point for point, _ in groupby(points)]  # adjacent duplicates add no edge
            area = abs(sum(ax * by - bx * ay for (ax, ay), (bx, by) in pairwise(points)))
            if not area:
                return False
            rings.append(points)
            areas.append(area)
        components.append(range(start, len(rings)))

    try:
        cuts, contacts = _boundary_contacts(rings)
    except ValueError:
        return False
    samples = [_arc_samples(ring, cut) for ring, cut in zip(rings, cuts)]
    for component in components:
        shell, *holes = component
        if areas[shell] <= sum(areas[hole] for hole in holes):
            return False
        if any(not _inside(rings[shell], p) for hole in holes for p in samples[hole]):
            return False
        if any(_inside(rings[target], p) for a, b in combinations(holes, 2)
               for source, target in ((a, b), (b, a)) for p in samples[source]):
            return False
        if not _connected_interior(component, contacts):
            return False

    for a, b in combinations(components, 2):
        for source, target in ((a, b), (b, a)):
            shell, *holes = target
            if any(_inside(rings[shell], p) and not any(_inside(rings[hole], p) for hole in holes)
                   for i in source for p in samples[i]):
                return False
    return True


def polygon_valid(geometry, *, require_topology=True):
    if geometry.get('type') not in ('Polygon', 'MultiPolygon'):
        return False
    polygons = [geometry.get('coordinates')] if geometry['type'] == 'Polygon' else geometry.get('coordinates')
    if not isinstance(polygons, list) or not polygons:
        return False
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            return False
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                return False
            if any(not isinstance(point, list) or len(point) < 2 or
                   not all(isinstance(n, (int, float)) for n in point[:2]) or
                   not (-130 <= point[0] <= -115 and 30 <= point[1] <= 50) for point in ring):
                return False
    return not require_topology or _polygon_topology(polygons)


def selected_layers(layers):
    wanted = []
    for n, row in enumerate(layers):
        name = row.get('name') if isinstance(row, dict) else None
        if not isinstance(name, str):
            raise ValueError(f'NOAA federal area layer row {n} misshaped')
        category = ('GEA' if name.startswith('GEA_') and not name.startswith('GEA_ALL_') else
                    'CCA' if name.startswith('CCA_') and 'Transit_Corridor' not in name else
                    'YRCA' if name.startswith('YRCA_') and name != 'YRCA_All_20231201' else None)
        if category and (type(row.get('id')) is not int or not 0 <= row['id'] <= 10000):
            raise ValueError(f'NOAA federal area layer row {n} misshaped')
        if category:
            wanted.append((row['id'], name, category))
    if (len({name for _, name, _ in wanted}) != len(wanted)
            or len({ident for ident, _, _ in wanted}) != len(wanted)
            or sum(category == 'GEA' for _, _, category in wanted) < 10
            or not any(name.startswith('GEA_Cordell_Bank_20260623') for _, name, _ in wanted)
            or sum(category == 'CCA' for _, _, category in wanted) < 2
            or sum(category == 'YRCA' for _, _, category in wanted) < 10):
        raise ValueError('NOAA federal area layer inventory incomplete or revised')
    return wanted


def collect(getter=fetch_json, now=None):
    now = now or datetime.now(timezone.utc)
    service_url = SERVICE + '?f=pjson'
    service, service_hash = getter(service_url)
    if not isinstance(service, dict) or service.get('error') or not isinstance(service.get('layers'), list):
        raise ValueError('Invalid NOAA federal groundfish service')
    chosen = selected_layers(service['layers'])
    sources = []
    features = []
    for ident, name, category in chosen:
        base = f'{SERVICE}/{ident}/query?'
        count_url = base + urlencode({'where': '1=1', 'returnCountOnly': 'true', 'f': 'json'})
        count_data, count_hash = getter(count_url)
        count = count_data.get('count') if isinstance(count_data, dict) else None
        if not isinstance(count, int) or not 1 <= count <= 100:
            raise ValueError(f'Unexpected NOAA feature count for {name}')
        geo_url = base + urlencode({'where': '1=1', 'outFields': '*', 'outSR': 4326,
                                   'returnGeometry': 'true', 'f': 'geojson', 'resultRecordCount': 100})
        geo, geo_hash = getter(geo_url)
        if (not isinstance(geo, dict) or not isinstance(geo.get('features'), list) or geo.get('type') != 'FeatureCollection'
                or geo.get('exceededTransferLimit') or len(geo['features']) != count):
            raise ValueError(f'Incomplete NOAA geometry for {name}')
        seen = set()
        for feature in geo['features']:
            props = (feature.get('properties') or {}) if isinstance(feature, dict) else None
            oid = props.get('OBJECTID') if isinstance(props, dict) else None
            if (type(oid) is not int or oid < 0 or oid in seen or
                    not polygon_valid(feature['geometry'] if isinstance(feature.get('geometry'), dict) else {},
                                      require_topology=category == 'GEA') or
                    props.get('AREA_GROUP') not in ({'GEA', 'Groundfish Exclusion Area'} if category == 'GEA' else {category})):
                raise ValueError(f'Invalid NOAA polygon or classification for {name}')
            seen.add(oid)
            citation = props.get('CFR_BOUNDARY_URL') or props.get('CFR_AREA_URL')
            if not isinstance(citation, str) or not citation.startswith('https://www.ecfr.gov/current/title-50/'):
                raise ValueError(f'Missing NOAA legal boundary citation for {name}')
            features.append({'type': 'Feature', 'geometry': feature['geometry'], 'properties': {
                'id': f'noaa-gca-{ident}-{oid}', 'name': props.get('SITE_NAME') or name,
                'area_type': category, 'source_layer': name, 'source_layer_id': ident,
                'cfr_boundary_url': citation, 'fr_citation': props.get('FR_CITATION'),
                'groundfish_candidate_exclusion': category == 'GEA',
                'fishing_permission': None, 'exportable_as_fishing_spot': False}})
        sources.append({'layer_id': ident, 'layer_name': name, 'area_type': category,
                        'feature_count': count, 'count_url': count_url, 'count_sha256': count_hash,
                        'geometry_url': geo_url, 'geometry_sha256': geo_hash})
    return {'type': 'FeatureCollection', 'schema_version': 1,
            'scope': 'noaa-west-coast-groundfish-conservation-areas',
            'retrieved_at': now.isoformat(), 'status': 'ok', 'service_url': SERVICE,
            'service_response_sha256': service_hash, 'legal_text_url': LAW,
            'source_layers': sources, 'feature_count': len(features),
            'method': 'Complete per-layer NOAA ArcGIS GeoJSON and count check; excludes aggregate and transit-corridor layers. GEA polygons conservatively exclude groundfish candidate publication.',
            'limitations': ['GIS boundaries are approximate; 50 CFR 660.70 and current notices govern exact limits.',
                            'CCA and YRCA applicability depends on fishery, gear, date and location; no automatic fishing permission or prohibition is inferred.',
                            'Retrieval time is not the regulation effective date. All source geometries are West Coast, not California only.'],
            'features': features}


def _usable_previous(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None, 'unreadable JSON'
    if not isinstance(data, dict):
        return None, 'not an object'
    count, features = data.get('feature_count'), data.get('features')
    for bad, reason in ((data.get('scope') != 'noaa-west-coast-groundfish-conservation-areas', 'wrong scope'),
                        (data.get('type') != 'FeatureCollection', 'not a FeatureCollection'),
                        (not isinstance(features, list), 'features is not a list'),
                        (type(count) is not int, 'feature_count is not an int'),
                        (isinstance(features, list) and count != len(features), 'feature_count does not match features'),
                        (not isinstance(data.get('source_layers'), list), 'source_layers is not a list')):
        if bad:
            return None, reason
    return data, ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    try:
        data = collect()
    except (OSError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        if not args.previous or not args.previous.is_file():
            raise
        data, reason = _usable_previous(args.previous)
        if data is None:
            raise SystemExit(f'NOAA refresh failed ({type(error).__name__}) and '
                             f'previous snapshot unusable: {reason}') from error
        data['status'] = 'retained'
        data['refresh_attempted_at'] = datetime.now(timezone.utc).isoformat()
        data['refresh_issue'] = str(error)[:250]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(data, separators=(',', ':')) + '\n')
    temp.replace(args.output)
    print(f"{data['status']}: {data['feature_count']} federal areas from {len(data['source_layers'])} layers")
    if data['status'] != 'ok':
        raise SystemExit('NOAA federal area refresh retained prior geometry; review source health')


if __name__ == '__main__':
    main()
