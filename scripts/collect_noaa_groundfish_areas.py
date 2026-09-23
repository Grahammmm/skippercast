"""Collect NOAA's original West Coast federal groundfish-area geometries.

These approximate GIS polygons are source evidence, not the controlling legal
boundary. GEA geometry is a conservative groundfish-candidate exclusion; other
area types require method- and date-specific regulatory review.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
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


def polygon_valid(geometry):
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
                   not all(isinstance(n, (int, float)) and math.isfinite(n) for n in point[:2]) or
                   not (-130 <= point[0] <= -115 and 30 <= point[1] <= 50) for point in ring):
                return False
    return True


def selected_layers(layers):
    wanted = []
    for row in layers:
        name = row.get('name', '')
        category = ('GEA' if name.startswith('GEA_') and not name.startswith('GEA_ALL_') else
                    'CCA' if name.startswith('CCA_') and 'Transit_Corridor' not in name else
                    'YRCA' if name.startswith('YRCA_') and name != 'YRCA_All_20231201' else None)
        if category:
            wanted.append((row['id'], name, category))
    if (len({name for _, name, _ in wanted}) != len(wanted)
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
    if service.get('error') or not isinstance(service.get('layers'), list):
        raise ValueError('Invalid NOAA federal groundfish service')
    chosen = selected_layers(service['layers'])
    sources = []
    features = []
    for ident, name, category in chosen:
        base = f'{SERVICE}/{ident}/query?'
        count_url = base + urlencode({'where': '1=1', 'returnCountOnly': 'true', 'f': 'json'})
        count_data, count_hash = getter(count_url)
        count = count_data.get('count')
        if not isinstance(count, int) or not 1 <= count <= 100:
            raise ValueError(f'Unexpected NOAA feature count for {name}')
        geo_url = base + urlencode({'where': '1=1', 'outFields': '*', 'outSR': 4326,
                                   'returnGeometry': 'true', 'f': 'geojson', 'resultRecordCount': 100})
        geo, geo_hash = getter(geo_url)
        if geo.get('type') != 'FeatureCollection' or geo.get('exceededTransferLimit') or len(geo.get('features', [])) != count:
            raise ValueError(f'Incomplete NOAA geometry for {name}')
        for feature in geo['features']:
            props = feature.get('properties') or {}
            group = props.get('AREA_GROUP')
            if (not polygon_valid(feature.get('geometry') or {}) or
                    group not in ({'GEA', 'Groundfish Exclusion Area'} if category == 'GEA' else {category})):
                raise ValueError(f'Invalid NOAA polygon or classification for {name}')
            citation = props.get('CFR_BOUNDARY_URL') or props.get('CFR_AREA_URL')
            if not isinstance(citation, str) or not citation.startswith('https://www.ecfr.gov/current/title-50/'):
                raise ValueError(f'Missing NOAA legal boundary citation for {name}')
            features.append({'type': 'Feature', 'geometry': feature['geometry'], 'properties': {
                'id': f'noaa-gca-{ident}-{props.get("OBJECTID")}', 'name': props.get('SITE_NAME') or name,
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
        data = json.loads(args.previous.read_text())
        if data.get('scope') != 'noaa-west-coast-groundfish-conservation-areas':
            raise ValueError('Previous NOAA federal area snapshot has wrong scope') from error
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
