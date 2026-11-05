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
the selected region's source URL, and keeps the recorded fetch times, so it
reproduces the committed asset byte for byte.
Saved responses hold the full inventory (photos, phones), so keep them under var/.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
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
            # Rocky run (SC1952-08): only the named objects at their exact ESI code, only vertices inside 'lon' x 'lat'
            # (the State Parks "Estero Bluffs SP" bounding box), and no review dates until the owner's gate ('reviewed': False).
            {'id': 'estero-bluffs', 'name': 'Estero Bluffs', 'areaId': 'central', 'substrate': 'rocky', 'reviewed': False,
             'classes': {2234: '2A', 2237: '2A', 2242: '2A', 2244: '2A', 2246: '2A', 2250: '2A', 2251: '2A', 2253: '2A',
                         2255: '1A', 2259: '2A', 2274: '2A', 2276: '2A', 2277: '2A'},
             'objects': [2234, 2237, 2242, 2244, 2246, 2250, 2251, 2253, 2255, 2259, 2274, 2276, 2277],
             'lon': (-120.97380, -120.91612), 'lat': (35.44610, 35.46514), 'access': [792, 793, 794, 795],
             'accessUrl': 'https://www.parks.ca.gov/?page_id=22263',
             'note': 'Estero Bluffs State Park, California State Parks; the Cayucos Land Conservancy holds a conservation easement. Use signed public approaches, keep off the bluff edges and recheck access on arrival.'},
        ],
    },
}

# ESI codes the rocky shoreClass text names; a site's 'classes' may use only these.
ROCKY_LEGEND = {'1A': 'exposed rocky shores', '2A': 'exposed wave-cut platforms in bedrock'}
# Extra NOAA window for sites added without refetching the region (offline additive rebuild).
WINDOWS = {'estero-bluffs': (-121.02, 35.43, -120.89, 35.50)}
# sha256 of each legacy sand feature as serialized in the committed package before SC1952-08; the additive
# rebuild keeps these bytes and refuses a baseline in which any of them differs.
LEGACY_FEATURE_SHA256 = {
    'hearst-memorial-beach': '48603c7b01fdc4dbd2183363305ab442b88e919aa2608007a513097d7a1e4ae2',
    'morro-strand': '49dc5d8595816e286ba1db891b7009de12f81c0567671ab483faedca23d9a7c9',
    'cayucos-beach': 'd33c25f6e8ba9f64a018028e697e72b3a83f75b80284f4e6f0fa3670dd46b20a',
    'pismo-beach': 'faa67135a343eae09d143f19b3153dd611366c2f50aaa7b3f79d060995060827',
    'oceano-beach': '93db830f657f9a23a295196e4ec72e99783d66f7de737faee0faa87dd0d06623',
}
ADDED_SITE = 'estero-bluffs'
ADD_FILES = {'noaa': 'noaa-esi-shoreline.json', 'access': 'ccc-access-estero.json'}

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


def load_saved(directory, region, now):
    """Saved responses and their receipts; the receipt clock is kept, never advanced."""
    directory = Path(directory)
    urls = source_urls(region)
    try:
        receipts = json.loads((directory / 'receipts.json').read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise ValueError('Unreadable saved receipts: receipts.json') from None
    if not isinstance(receipts, dict):
        raise ValueError('Saved receipts must be a JSON object')
    bodies = {}
    for key, name in SOURCE_FILES.items():
        try:
            r, body = receipts.get(key), (directory / name).read_bytes()
        except OSError:
            raise ValueError('Missing or invalid saved source receipt: ' + key) from None
        at = parse_time(r.get('fetchedAt') if isinstance(r, dict) else None)
        if (at is None or at > now.timestamp() + 3600 or r.get('url') != urls[key]
                or r.get('responseSha256') != hashlib.sha256(body).hexdigest()):
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
    """One approach; ``reviewed_at`` is the access review date, or None while the run has never been reviewed."""
    p, g = feature.get('properties') or {}, feature.get('geometry') or {}
    if (g.get('type') != 'Point' or not finite_pair(g.get('coordinates')) or p.get('O_PUBLIC') != 'Yes'
            or p.get('AccessType') != 'Beach Access' or str(p.get('Archived') or '').strip().lower() == 'yes'
            or not blank(p.get('Date_Closd')) or not blank(p.get('ClosureCom')) or blank(p.get('Name'))):
        raise ValueError(f'Unverified public beach approach {ident}')
    return {'id': f'ccc-{ident}', 'name': str(p['Name']).strip(), 'coordinates': g['coordinates'],
            'sourceUrl': ACCESS + '/0/query?' + urlencode({'objectIds': str(ident), 'outFields': ACCESS_FIELDS, 'outSR': '4326', 'f': 'geojson'}),
            'publicAccess': True, 'checkedAt': reviewed_at, 'note': note}


def run_paths(feature, lat_min, lat_max, lon_min=-180, lon_max=180):
    g = feature.get('geometry') or {}
    lines = [g.get('coordinates')] if g.get('type') == 'LineString' else g.get('coordinates') if g.get('type') == 'MultiLineString' else None
    if not isinstance(lines, list):
        raise ValueError('Reviewed source feature has no line geometry')
    paths = []
    for line in lines:
        run = []
        for point in line:
            if not finite_pair(point):
                raise ValueError('Invalid coordinate')
            if lat_min <= point[1] <= lat_max and lon_min <= point[0] <= lon_max:
                run.append(point)
                continue
            if len(run) >= 2:
                paths.append(run)
            run = []
        if len(run) >= 2:
            paths.append(run)
    return paths


def site_feature(region, site, by_shore, by_access, receipts=None):
    """One run. A site with ``reviewed: False`` carries null review clocks: no download, import or regional date renews it."""
    reviewed = site.get('reviewed', True)
    review = REVIEWS[region] if reviewed else None
    classes, rocky = site.get('classes'), site.get('substrate') == 'rocky'
    if rocky and (not classes or set(classes) != set(site['objects']) or not set(classes.values()) <= set(ROCKY_LEGEND)):
        raise ValueError('Rocky site needs one named ESI code per object: ' + site['id'])
    paths, ids = [], []
    for ident in site['objects']:
        f = by_shore.get(ident)
        if not f or (f.get('properties') or {}).get('ESI') != (classes[ident] if classes else '3A'):
            raise ValueError(f'Reviewed {"rocky" if rocky else "sandy"} source feature changed: {ident}')
        kept = run_paths(f, *site['lat'], *site.get('lon', (-180, 180)))
        if kept:
            paths += kept
            ids.append(ident)
    if not paths:
        raise ValueError('Missing site geometry: ' + site['id'])
    points = []
    for ident in site['access']:
        if ident not in by_access:
            raise ValueError(f'Unverified public beach approach {ident}')
        points.append(access_point(by_access[ident], ident, review['access']['reviewedAt'] if review else None, site['note']))
    codes = sorted(set(classes.values())) if classes else ['3A']
    shore_class = ('NOAA ESI ' + ', '.join(codes) + ' · ' + ' and '.join(ROCKY_LEGEND[c] for c in codes)) if rocky \
        else 'NOAA ESI 3A · fine to medium-grained sandy beach'
    method = ('Original NOAA vertices of the named rocky shore objects inside the State Parks unit bounding box, in source order; no interpolation, buffers, '
              'coordinate simplification, or connections across gaps.') if rocky else \
        'Contiguous original NOAA vertices selected within named beach latitude limits; no interpolation, buffers, coordinate simplification, or connections across gaps.'
    clocks = {'checkedAt': None, 'reviewExpiresAt': None, 'accessReviewedAt': None, 'accessReviewExpiresAt': None,
              'legalReviewedAt': None, 'legalReviewExpiresAt': None} if not review else {
        'checkedAt': review['source']['reviewedAt'], 'reviewExpiresAt': review['source']['expiresAt'],
        'accessReviewedAt': review['access']['reviewedAt'], 'accessReviewExpiresAt': review['access']['expiresAt'],
        'legalReviewedAt': review['legal']['reviewedAt'], 'legalReviewExpiresAt': review['legal']['expiresAt']}
    props = {'id': site['id'], 'name': site['name'], 'areaId': site['areaId'], 'region': region, 'substrate': 'rocky' if rocky else 'sand',
             'shoreClass': shore_class, 'sourceYear': 2006, 'sourceUrl': NOAA + '/3', 'sourceObjectIds': ids, 'geometryMethod': method,
             'horizontalAccuracyM': None, 'access': points, 'accessUrl': site['accessUrl'], **clocks, 'legalSourceUrl': RULES,
             'license': 'NOAA ESI: no use constraints beyond stated mapping limitations; CCC access: factual coordinates/names only, source terms retained in provenance.',
             'attribution': 'NOAA NOS Office of Response and Restoration, Central California ESI (2006); California Coastal Commission access inventory.'}
    if not reviewed and receipts:
        props['sourceAcquisitions'] = {k: receipts[k] for k in ('noaa', 'access', 'terms')}
    return {'type': 'Feature', 'id': site['id'], 'geometry': {'type': 'MultiLineString', 'coordinates': paths}, 'properties': props}


def extract(region, shore, access, receipts=None):
    """Runs and approaches for ``region``; review dates come only from ``REVIEWS`` and never for an unreviewed site."""
    if shore.get('type') != 'FeatureCollection' or access.get('type') != 'FeatureCollection':
        raise ValueError('Invalid GeoJSON')
    by_shore = {f.get('properties', {}).get('OBJECTID'): f for f in shore['features']}
    by_access = {f.get('properties', {}).get('OBJECTID'): f for f in access['features']}
    return [site_feature(region, site, by_shore, by_access, receipts) for site in SITES[region]['sites']]


def build_asset(region, bodies, receipts):
    data = {key: parse(body) for key, body in bodies.items()}
    terms = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(data['terms'].get('licenseInfo') or ''))).strip()
    if not terms:
        raise ValueError('Coastal Commission source terms are missing')
    features = extract(region, data['noaa'], data['access'], receipts)
    return {'type': 'FeatureCollection', 'schemaVersion': 1, 'countyId': SITES[region]['countyId'], 'regionId': region,
            'builtAt': max(r['fetchedAt'] for r in receipts.values()), 'sourceYear': 2006,
            'sourceChecks': {'noaaUrl': NOAA, 'accessUrl': ACCESS, 'acquisitions': receipts, 'accessTermsUrl': TERMS_PAGE, 'accessTerms': terms},
            'reviews': REVIEWS[region], 'limitations': LIMITATIONS, 'features': features}


def feature_bytes(feature):
    return json.dumps(feature, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def add_site(region, site_id, baseline, bodies, receipts):
    """The committed package plus one more run, offline: the five legacy sand features keep their exact bytes.

    ``baseline`` is the committed package (parsed); a legacy feature that is missing, changed or out of order is
    refused. An existing ``site_id`` feature is replaced, never duplicated. Root reviews and acquisitions stay as they are.
    """
    if site_id != ADDED_SITE or region != 'morro-bay':
        raise ValueError('Unknown site to add: ' + str(site_id))
    site = next(s for s in SITES[region]['sites'] if s['id'] == site_id)
    legacy = [f for f in baseline.get('features', []) if f.get('id') != site_id]
    if [f.get('id') for f in legacy] != list(LEGACY_FEATURE_SHA256):
        raise ValueError('Baseline legacy runs changed or reordered')
    for f in legacy:
        if hashlib.sha256(feature_bytes(f)).hexdigest() != LEGACY_FEATURE_SHA256[f['id']]:
            raise ValueError('Baseline legacy run changed: ' + f['id'])
    shore, access = parse(bodies['noaa']), parse(bodies['access'])
    if shore.get('type') != 'FeatureCollection' or access.get('type') != 'FeatureCollection':
        raise ValueError('Invalid GeoJSON')
    by_shore = {f.get('properties', {}).get('OBJECTID'): f for f in shore['features']}
    by_access = {f.get('properties', {}).get('OBJECTID'): f for f in access['features']}
    return {**baseline, 'features': legacy + [site_feature(region, site, by_shore, by_access, receipts)]}


def load_added(directory, region, now):
    """Saved responses for the additive rebuild: the NOAA window response is hash-checked; access points come from the
    SC1952-07 receipt (a subset, not the full response), and the access and terms receipts are that dossier's."""
    directory = Path(directory)
    try:
        receipts = json.loads((directory / 'receipts.json').read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise ValueError('Unreadable saved receipts: receipts.json') from None
    if not isinstance(receipts, dict):
        raise ValueError('Saved receipts must be a JSON object')
    urls = {**source_urls(region), 'noaa': query_url(NOAA + '/3/query', WINDOWS[ADDED_SITE])}
    bodies = {}
    for key, name in ADD_FILES.items():
        try:
            bodies[key] = (directory / name).read_bytes()
        except OSError:
            raise ValueError('Missing or invalid saved source receipt: ' + key) from None
    for key in ('noaa', 'access', 'terms'):
        r = receipts.get(key)
        at = parse_time(r.get('fetchedAt') if isinstance(r, dict) else None)
        if (at is None or at > now.timestamp() + 3600 or r.get('url') != urls[key] or set(r) != {'url', 'fetchedAt', 'responseSha256', 'bytes'}
                or not isinstance(r.get('bytes'), int) or r['bytes'] < 1 or not re.fullmatch(r'[0-9a-f]{64}', str(r.get('responseSha256')))):
            raise ValueError('Missing or invalid saved source receipt: ' + key)
    if receipts['noaa']['responseSha256'] != hashlib.sha256(bodies['noaa']).hexdigest() or receipts['noaa']['bytes'] != len(bodies['noaa']):
        raise ValueError('Missing or invalid saved source receipt: noaa')
    return bodies, {k: receipts[k] for k in ('noaa', 'access', 'terms')}


def _write_atomic(path, data):
    tmp = path.with_name('.' + path.name + f'.{os.getpid()}.tmp')
    try:
        with open(tmp, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--region', default='morro-bay', choices=sorted(SITES))
    p.add_argument('--sources', type=Path, help='rebuild offline from responses saved by --save-sources')
    p.add_argument('--save-sources', type=Path, help='keep the raw responses and receipts here (use var/)')
    p.add_argument('--output', type=Path)
    p.add_argument('--add-site', choices=[ADDED_SITE], help='offline: add one run to the committed package from --sources, keeping the legacy runs byte for byte')
    args = p.parse_args(argv)
    try:
        return run(args)
    except (validate.MissingDependency, ValueError, OSError, validate.ContractError) as error:
        print('collect_shore_habitat: ' + str(error).replace('\n', ' '), file=sys.stderr)
        return 2 if isinstance(error, validate.MissingDependency) else 1


def run(args):
    output = args.output or ROOT / 'catalog/shore-habitat' / f'{args.region}.geojson'
    if args.add_site:
        if not args.sources or args.save_sources:
            raise ValueError('--add-site needs --sources and no --save-sources')
        bodies, receipts = load_added(args.sources, args.region, datetime.now(timezone.utc))
        asset = add_site(args.region, args.add_site, json.loads(output.read_bytes()), bodies, receipts)
    else:
        if args.sources:
            bodies, receipts = load_saved(args.sources, args.region, datetime.now(timezone.utc))
        else:
            bodies, receipts = download(args.region)
        asset = build_asset(args.region, bodies, receipts)
    validate.check('shore-habitat', asset)
    if args.save_sources:
        args.save_sources.mkdir(parents=True, exist_ok=True)
        for key, name in SOURCE_FILES.items():
            _write_atomic(args.save_sources / name, bodies[key])
        _write_atomic(args.save_sources / 'receipts.json', (json.dumps(receipts, indent=1) + '\n').encode())
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(output, (json.dumps(asset, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8'))
    vertices = sum(len(line) for f in asset['features'] for line in f['geometry']['coordinates'])
    print(json.dumps({'region': args.region, 'runs': len(asset['features']), 'vertices': vertices, 'bytes': output.stat().st_size}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
