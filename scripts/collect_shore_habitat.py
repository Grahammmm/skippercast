"""Import ESI 2006 sandy-shore runs and Coastal Commission beach approaches (FE-43).

A reviewed, manual import (ported from fish's ``scripts/import-shore-habitat.mjs``),
not an hourly collector. It reads two public ArcGIS layers and writes
``catalog/shore-habitat/<region>.geojson``; ``skippercast.platform.build`` copies
that to ``dist/regions/<region>/shore-habitat.geojson``.

- Runs keep only original NOAA ESI 3A (sand beach) vertices inside each named
  beach's latitude window: no interpolation, buffering or joins across gaps.
- Access points keep factual inventory fields only (id, name, coordinates,
  public flag); never the inventory's photos, descriptions, phones or links.
- Review dates come from ``REVIEWS`` below, a dated human review. The importer
  copies them verbatim; it never derives an expiry from its own clock, so a
  fresh download cannot renew a source, access or legal review.

    python scripts/collect_shore_habitat.py                       # download, write the asset
    python scripts/collect_shore_habitat.py --save-sources DIR    # also keep the raw responses
    python scripts/collect_shore_habitat.py --sources DIR         # offline rebuild from saved responses

An offline rebuild verifies each saved response against its recorded sha256 and
keeps the recorded fetch times, so it reproduces the committed asset byte for byte.
Saved responses hold the full inventory (photos, phones), so keep them under var/.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from skippercast import validate  # noqa: E402

NOAA = 'https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/Central_California_ESI_2006_test/FeatureServer'
ACCESS = 'https://services9.arcgis.com/wwVnNW92ZHUIr0V0/arcgis/rest/services/AccessPoints/FeatureServer'
TERMS = 'https://www.arcgis.com/sharing/rest/content/items/e45f130ce101423ea1de943a69445ece?f=json'
TERMS_PAGE = 'https://www.arcgis.com/home/item.html?id=e45f130ce101423ea1de943a69445ece'
RULES = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central'
MAX_BYTES = 8_000_000
ACCESS_FIELDS = 'OBJECTID,Name,O_PUBLIC,AccessType,Archived,Date_Closd,ClosureCom'
SOURCE_FILES = {'noaa': 'noaa-esi-shoreline.json', 'access': 'ccc-access-points.json', 'terms': 'ccc-access-item.json'}

# Dated human reviews, carried from fish's shore source review of 2026-10-03
# (shore-source-review-2026-10-03.json in the fish repository), pending owner
# confirmation. Renew only after re-reading the sources by hand.
# source: NOAA run geometry and sand class (30 days); access: CCC approaches and the
# owner pages (7 days); legal: the CDFW Central Coast rules page (24 hours).
REVIEWS = {
    'morro-bay': {
        'source': {'reviewedAt': '2026-10-03T02:48:10.509Z', 'expiresAt': '2026-11-02T02:48:10.509Z'},
        'access': {'reviewedAt': '2026-10-03T02:48:10.183Z', 'expiresAt': '2026-10-10T02:48:10.183Z'},
        'legal': {'reviewedAt': '2026-10-03T02:43:19.000Z', 'expiresAt': '2026-10-04T02:43:19.000Z'},
    },
}

SITES = {
    'morro-bay': {
        'countyId': 'slo',
        'bbox': (-121.35, 34.92, -120.51, 35.82),
        'sites': [
            {'id': 'hearst-memorial-beach', 'name': 'Hearst Memorial Beach · San Simeon', 'areaId': 'north', 'objects': [2094, 2100],
             'lat': (35.6405, 35.6433), 'access': [770], 'accessUrl': 'https://www.parks.ca.gov/?page_id=589',
             'note': 'Public beach approach at the day-use area; State Parks lists dawn-to-dusk hours. Keep clear of resting seals, respect signed closures, and recheck access on arrival. The adjacent pier license exemption does not extend onto the beach.'},
            {'id': 'morro-strand', 'name': 'Morro Strand', 'areaId': 'central', 'objects': [2294],
             'lat': (35.375, 35.4036), 'access': [804, 805], 'accessUrl': 'https://www.parks.ca.gov/?page_id=593',
             'note': 'Use signed public approaches; respect fenced restoration and snowy plover areas.'},
            {'id': 'cayucos-beach', 'name': 'Cayucos sandy shore', 'areaId': 'central', 'objects': [2283, 2287, 2289],
             'lat': (35.436, 35.449), 'access': [797, 798], 'accessUrl': 'https://slocountyparks.com/day-use-parks/cayucos-beach/',
             'note': 'Use public stairs and beach entrances during day use. Avoid private property and check wave run-up, posted closures and wildlife areas.'},
            {'id': 'pismo-beach', 'name': 'Pismo Beach', 'areaId': 'south', 'objects': [2632, 2636, 2637],
             'lat': (35.125, 35.1482), 'access': [868, 870], 'accessUrl': 'https://www.parks.ca.gov/?page_id=595',
             'note': 'Use city beach approaches. Adjacent creek mouths, breakers and rip currents require local checks.'},
            {'id': 'oceano-beach', 'name': 'Oceano · Pier Avenue shore', 'areaId': 'south', 'objects': [2638],
             'lat': (35.089, 35.114), 'access': [875], 'accessUrl': 'https://ohv.parks.ca.gov/?page_id=1207',
             'note': 'Pier Avenue approach. Respect posted vehicle, creek-crossing, dune and wildlife restrictions; do not infer access from a habitat line.'},
        ],
    },
}

LIMITATIONS = [
    'Historical shoreline classification; not today’s shoreline or surf channels.',
    'Accuracy and current beach width unknown.',
    'Access points are official inventory references, not real-time opening status or directions.',
    'Each beach’s fishing line retains only source vertices. Display stroke width is a visual emphasis, not a mapped fish-bearing zone.',
]


def query_url(base, bbox):
    return base + '?' + urlencode({'where': '1=1', 'geometry': ','.join(map(str, bbox)), 'geometryType': 'esriGeometryEnvelope',
                                   'inSR': '4326', 'outSR': '4326', 'outFields': '*', 'f': 'geojson'})


def source_urls(region):
    bbox = SITES[region]['bbox']
    return {'noaa': query_url(NOAA + '/3/query', bbox), 'access': query_url(ACCESS + '/0/query', bbox), 'terms': TERMS}


def parse(body):
    if len(body) > MAX_BYTES:
        raise ValueError('Oversized source response')
    data = json.loads(body)
    if not isinstance(data, dict) or data.get('error') or data.get('exceededTransferLimit'):
        raise ValueError('Source error or incomplete response')
    return data


def receipt(url, body, fetched_at):
    return {'url': url, 'fetchedAt': fetched_at, 'responseSha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}


def download(region):
    bodies, receipts = {}, {}
    for key, url in source_urls(region).items():
        with urlopen(Request(url, headers={'User-Agent': 'SkipperCast shore import'}), timeout=60) as response:
            if urlsplit(response.geturl()).netloc != urlsplit(url).netloc:
                raise ValueError('Source redirected to another host: ' + key)
            body = response.read(MAX_BYTES + 1)
        at = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        bodies[key], receipts[key] = body, receipt(url, body, at)
    return bodies, receipts


def load_saved(directory, now):
    """Saved responses and their receipts; the receipt clock is kept, never advanced."""
    directory = Path(directory)
    receipts = json.loads((directory / 'receipts.json').read_text())
    bodies = {}
    for key, name in SOURCE_FILES.items():
        r, body = receipts.get(key), (directory / name).read_bytes()
        at = parse_time(r.get('fetchedAt') if isinstance(r, dict) else None)
        if at is None or at > now.timestamp() + 3600 or r.get('responseSha256') != hashlib.sha256(body).hexdigest():
            raise ValueError('Missing or invalid saved source receipt: ' + key)
        bodies[key] = body
    return bodies, receipts


def parse_time(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() if isinstance(value, str) else None
    except ValueError:
        return None


def finite_pair(p):
    return isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float('inf') for v in p)


def blank(value):
    return not str(value if value is not None else '').strip()


def access_point(feature, ident, reviewed_at, note):
    p, g = feature.get('properties') or {}, feature.get('geometry') or {}
    if (g.get('type') != 'Point' or not finite_pair(g.get('coordinates')) or p.get('O_PUBLIC') != 'Yes'
            or p.get('AccessType') != 'Beach Access' or str(p.get('Archived') or '').strip().lower() == 'yes'
            or not blank(p.get('Date_Closd')) or not blank(p.get('ClosureCom')) or blank(p.get('Name'))):
        raise ValueError(f'Unverified public beach approach {ident}')
    return {'id': f'ccc-{ident}', 'name': str(p['Name']).strip(), 'coordinates': g['coordinates'],
            'sourceUrl': ACCESS + '/0/query?' + urlencode({'objectIds': str(ident), 'outFields': ACCESS_FIELDS, 'outSR': '4326', 'f': 'geojson'}),
            'publicAccess': True, 'checkedAt': reviewed_at, 'note': note}


def run_paths(feature, lat_min, lat_max):
    g = feature.get('geometry') or {}
    lines = [g.get('coordinates')] if g.get('type') == 'LineString' else g.get('coordinates') if g.get('type') == 'MultiLineString' else None
    if not isinstance(lines, list):
        raise ValueError('Reviewed sandy source feature has no line geometry')
    paths = []
    for line in lines:
        run = []
        for point in line:
            if not finite_pair(point):
                raise ValueError('Invalid coordinate')
            if lat_min <= point[1] <= lat_max:
                run.append(point)
                continue
            if len(run) >= 2:
                paths.append(run)
            run = []
        if len(run) >= 2:
            paths.append(run)
    return paths


def extract(region, shore, access):
    """Runs and approaches for ``region``; review dates come only from ``REVIEWS``."""
    if shore.get('type') != 'FeatureCollection' or access.get('type') != 'FeatureCollection':
        raise ValueError('Invalid GeoJSON')
    review = REVIEWS[region]
    by_shore = {f.get('properties', {}).get('OBJECTID'): f for f in shore['features']}
    by_access = {f.get('properties', {}).get('OBJECTID'): f for f in access['features']}
    features = []
    for site in SITES[region]['sites']:
        paths, ids = [], []
        for ident in site['objects']:
            f = by_shore.get(ident)
            if not f or (f.get('properties') or {}).get('ESI') != '3A':
                raise ValueError(f'Reviewed sandy source feature changed: {ident}')
            kept = run_paths(f, *site['lat'])
            if kept:
                paths += kept
                ids.append(ident)
        if not paths:
            raise ValueError('Missing site geometry: ' + site['id'])
        points = []
        for ident in site['access']:
            if ident not in by_access:
                raise ValueError(f'Unverified public beach approach {ident}')
            points.append(access_point(by_access[ident], ident, review['access']['reviewedAt'], site['note']))
        features.append({'type': 'Feature', 'id': site['id'], 'geometry': {'type': 'MultiLineString', 'coordinates': paths}, 'properties': {
            'id': site['id'], 'name': site['name'], 'areaId': site['areaId'], 'region': region, 'substrate': 'sand',
            'shoreClass': 'NOAA ESI 3A · fine to medium-grained sandy beach', 'sourceYear': 2006, 'sourceUrl': NOAA + '/3',
            'sourceObjectIds': ids,
            'geometryMethod': 'Contiguous original NOAA vertices selected within named beach latitude limits; no interpolation, buffers, coordinate simplification, or connections across gaps.',
            'horizontalAccuracyM': None, 'access': points, 'accessUrl': site['accessUrl'],
            'checkedAt': review['source']['reviewedAt'], 'reviewExpiresAt': review['source']['expiresAt'],
            'accessReviewedAt': review['access']['reviewedAt'], 'accessReviewExpiresAt': review['access']['expiresAt'],
            'legalReviewedAt': review['legal']['reviewedAt'], 'legalReviewExpiresAt': review['legal']['expiresAt'], 'legalSourceUrl': RULES,
            'license': 'NOAA ESI: no use constraints beyond stated mapping limitations; CCC access: factual coordinates/names only, source terms retained in provenance.',
            'attribution': 'NOAA NOS Office of Response and Restoration, Central California ESI (2006); California Coastal Commission access inventory.'}})
    return features


def build_asset(region, bodies, receipts):
    data = {key: parse(body) for key, body in bodies.items()}
    terms = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(data['terms'].get('licenseInfo') or ''))).strip()
    if not terms:
        raise ValueError('Coastal Commission source terms are missing')
    features = extract(region, data['noaa'], data['access'])
    return {'type': 'FeatureCollection', 'schemaVersion': 1, 'countyId': SITES[region]['countyId'], 'regionId': region,
            'builtAt': max(r['fetchedAt'] for r in receipts.values()), 'sourceYear': 2006,
            'sourceChecks': {'noaaUrl': NOAA, 'accessUrl': ACCESS, 'acquisitions': receipts, 'accessTermsUrl': TERMS_PAGE, 'accessTerms': terms},
            'reviews': REVIEWS[region], 'limitations': LIMITATIONS, 'features': features}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--region', default='morro-bay', choices=sorted(SITES))
    p.add_argument('--sources', type=Path, help='rebuild offline from responses saved by --save-sources')
    p.add_argument('--save-sources', type=Path, help='keep the raw responses and receipts here (use var/)')
    p.add_argument('--output', type=Path)
    args = p.parse_args(argv)
    if args.sources:
        bodies, receipts = load_saved(args.sources, datetime.now(timezone.utc))
    else:
        bodies, receipts = download(args.region)
    asset = build_asset(args.region, bodies, receipts)
    validate.check('shore-habitat', asset)
    if args.save_sources:
        args.save_sources.mkdir(parents=True, exist_ok=True)
        for key, name in SOURCE_FILES.items():
            (args.save_sources / name).write_bytes(bodies[key])
        (args.save_sources / 'receipts.json').write_text(json.dumps(receipts, indent=1) + '\n')
    output = args.output or ROOT / 'catalog/shore-habitat' / f'{args.region}.geojson'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asset, ensure_ascii=False, separators=(',', ':')) + '\n')
    vertices = sum(len(line) for f in asset['features'] for line in f['geometry']['coordinates'])
    print(json.dumps({'region': args.region, 'runs': len(asset['features']), 'vertices': vertices, 'bytes': output.stat().st_size}))


if __name__ == '__main__':
    sys.exit(main())
