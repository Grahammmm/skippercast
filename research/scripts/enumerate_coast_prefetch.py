"""Bounded metadata enumeration for the raw mirror; never fetch BAG/raster bodies.

Retain every response and receipt in a per-run directory for offline replay.
This is not the governed discovery lane and never writes its catalogs or ledger.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlencode, urljoin, urlsplit, unquote
import xml.etree.ElementTree as ET

from research.scripts.build_coast_prefetch_plan import BOUNDS, NOAA, build, segments_for
from skippercast.coastal.prefetch import (
    Hold, Prefetch, SEGMENTS, SHA, TransferSession, atomic_json, digest, load_plan,
    read_json, safe_path, stamp,
)
from skippercast.http import USER_AGENT, default_allowlist
from skippercast.paths import repo_root

GIS = 'https://gis.ngdc.noaa.gov/arcgis/rest/services/web_mercator/nos_hydro_dynamic/MapServer/0'
S3 = 'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/'
DIRECTORY = 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/'
CA = [-124.8, 32.5343, -117.05, 42]
SUPPLEMENT_SHA = 'cb2bd023b9ba3e42930ffd7c83f1f888ea44fd4e8d87db33fb1d4c2aa22b3619'
NS = {'s': 'http://s3.amazonaws.com/doc/2006-03-01/'}


class Metadata:
    """Policy transport + durable parking, with hashed local metadata replay."""
    def __init__(self, directory: Path, *, offline=False):
        self.directory = safe_path(directory)
        self.offline = offline
        self.started = time.monotonic()
        self.requests = 0
        self.query_files = {}
        hosts = default_allowlist(root=repo_root())
        session = TransferSession(allowed_hosts=hosts, attempts=1, cache=None,
                                  timeout=60, min_interval={h: 1.0 for h in hosts.exact},
                                  user_agent=USER_AGENT + ' coast-prefetch-metadata')
        self.transport = Prefetch({'files': []}, session, mirror=directory / 'state',
                                  status=directory / 'status.json', lock_dir=directory / 'locks')
        self.transport.state = read_json(directory / 'state/retry-state.json')

    def get(self, url, *, limit=8_000_000, scheme=False):
        # Exact route classes, not just hosts: callers cannot accidentally fetch a raster.
        p = urlsplit(url)
        allowed = (url.startswith(GIS + '/query?') or
                   (p.scheme == 'https' and p.netloc == urlsplit(S3).netloc and p.path == '/') or
                   (url.startswith(DIRECTORY) and p.path.endswith('/BAG/') and not p.query) or
                   (scheme and p.scheme == 'https' and p.netloc == urlsplit(S3).netloc
                    and re.fullmatch(r'/BlueTopo/_BlueTopo_Tile_Scheme/BlueTopo_Tile_Scheme_\d{8}_\d{6}\.gpkg', p.path)
                    and not p.query))
        if not allowed or p.fragment:
            raise Hold('Not an admitted metadata route: ' + url)
        key = hashlib.sha256(url.encode()).hexdigest()
        body_path = safe_path(self.directory / (key + '.body'))
        receipt_path = self.directory / (key + '.json')
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if (receipt['url'] != url or not body_path.exists() or
                    digest(body_path) != receipt['sha256'] or
                    body_path.stat().st_size != receipt['bytes'] or receipt['bytes'] > limit):
                raise Hold('Metadata replay receipt mismatch')
            return body_path.read_bytes()
        if self.offline:
            raise Hold('Missing retained metadata: ' + url)
        if self.requests >= 2000 or time.monotonic() - self.started > 1800:
            raise Hold('Metadata request/time bound reached; retain receipts and resume later')
        # No redirect following here: a metadata route must not become a payload route.
        host, _ = self.transport.session.check_url(url)
        if self.transport.clock() < self.transport.state.get(host, {}).get('retry_at', 0):
            raise Hold('Metadata host parked: ' + host)
        try:
            self.requests += 1
            response = self.transport.session.get(url, max_bytes=limit, attempts=1,
                use_cache=False, follow_redirects='return', raise_for_status=False,
                headers={'Accept-Encoding': 'identity'})
        except OSError as error:
            self.transport.park(host, str(error))
        if response.status == 429 or response.status >= 500:
            self.transport.park(host, f'HTTP {response.status}', response.status, response.headers)
        if response.status != 200:
            raise Hold(f'Metadata HTTP {response.status}: {url}')
        body = response.body
        if not body or len(body) > limit:
            raise Hold('Empty or oversized metadata')
        self.directory.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(body)
        atomic_json(receipt_path, {'url': url, 'bytes': len(body), 'sha256': digest(body_path),
                    'fetched_at': stamp(), 'etag': response.headers.get('ETag'),
                    'last_modified': response.headers.get('Last-Modified'), 'review_required': True})
        return body

    def query(self, parameters):
        url = GIS + '/query?' + urlencode(parameters)
        body = self.get(url)
        value = json.loads(body)
        if 'error' in value:
            raise Hold('ArcGIS returned an error: ' + str(value['error']))
        self.query_files[url] = {'source': 'ncei-footprints', 'url': url,
            'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'licence': NOAA, 'segments': list(SEGMENTS), 'evidence': GIS,
            'association_basis': 'Bounded campaign footprint metadata snapshot, not coverage.'}
        return value

    def head(self, url):
        """BAG sizes only, never a GET fallback; preserve exact header evidence."""
        p = urlsplit(url)
        if not (url.startswith(DIRECTORY) and p.path.endswith('.bag') and not p.query and not p.fragment):
            raise Hold('Not a BAG HEAD route')
        key = hashlib.sha256(('HEAD ' + url).encode()).hexdigest()
        path = self.directory / (key + '.head.json')
        if path.exists():
            receipt = read_json(path)
            if receipt.get('url') != url or receipt.get('method') != 'HEAD':
                raise Hold('HEAD receipt identity mismatch')
        else:
            if self.offline:
                raise Hold('Missing retained HEAD: ' + url)
            if self.requests >= 2000 or time.monotonic() - self.started > 1800:
                raise Hold('Metadata request/time bound reached')
            self.requests += 1
            response = self.transport.request('HEAD', url, max_bytes=0,
                                               headers={'Accept-Encoding': 'identity'})
            receipt = {'method': 'HEAD', 'url': url, 'headers': dict(response.headers),
                       'fetched_at': stamp(), 'final_url': response.final_url}
            atomic_json(path, receipt)
        headers = {k.lower(): v for k, v in receipt['headers'].items()}
        size = headers.get('content-length', '')
        if not size.isdigit() or int(size) <= 0:
            raise Hold('BAG HEAD missing a positive size')
        return {'bytes': int(size), 'size_etag': headers.get('etag'),
                'size_last_modified': headers.get('last-modified')}


def list_s3(get, prefix):
    """Exhaust both scheme and tile prefixes; never mistake ETag for SHA-256."""
    objects, tokens, token = {}, set(), None
    while True:
        parameters = {'list-type': '2', 'prefix': prefix, 'max-keys': 1000}
        if token:
            parameters['continuation-token'] = token
        tree = ET.fromstring(get(S3 + '?' + urlencode(parameters)))
        if tree.tag != '{' + NS['s'] + '}ListBucketResult':
            raise Hold('Unexpected S3 listing document')
        for entry in tree.findall('s:Contents', NS):
            key = entry.findtext('s:Key', namespaces=NS)
            if not key or not key.startswith(prefix):
                raise Hold('S3 key escaped requested prefix')
            row = {'key': key, 'bytes': int(entry.findtext('s:Size', namespaces=NS)),
                   'etag': entry.findtext('s:ETag', namespaces=NS),
                   'last_modified': entry.findtext('s:LastModified', namespaces=NS)}
            if key in objects and objects[key] != row:
                raise Hold('S3 object changed during pagination')
            objects[key] = row
        truncated = tree.findtext('s:IsTruncated', namespaces=NS)
        if truncated == 'false':
            return objects
        token = tree.findtext('s:NextContinuationToken', namespaces=NS)
        if truncated != 'true' or not token or token in tokens:
            raise Hold('Missing/repeated S3 continuation token')
        tokens.add(token)
        if len(tokens) > 1000:
            raise Hold('S3 pagination safety bound exceeded')


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(value for name, value in attrs if name == 'href' and value)


def bag_urls(body, directory):
    parser = Links()
    parser.feed(body.decode('utf-8'))
    urls = set()
    for href in parser.hrefs:
        url = urljoin(directory, href)
        p = urlsplit(url)
        if p.path.lower().endswith('.bag'):
            if not url.startswith(directory) or p.query or p.fragment or '/' in url[len(directory):]:
                raise Hold('BAG listing link escaped its survey directory')
            urls.add(url)
    if not urls:
        raise Hold('Survey-with-BAGs returned no BAG objects')
    return sorted(urls)


def nos_features(query):
    common = {'f': 'json', 'where': '1=1', 'geometry': ','.join(map(str, CA)),
              'geometryType': 'esriGeometryEnvelope', 'inSR': 4326,
              'spatialRel': 'esriSpatialRelIntersects'}
    count = query({**common, 'returnCountOnly': 'true'}).get('count')
    identity = query({**common, 'returnIdsOnly': 'true'})
    ids, field = identity.get('objectIds'), identity.get('objectIdFieldName')
    if (type(count) is not int or count <= 0 or not isinstance(ids, list) or
            len(ids) != count or len(set(ids)) != count or any(type(i) is not int for i in ids)
            or not isinstance(field, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', field)):
        raise Hold('NOS count/unique-ID completeness failed')
    features = []
    for start in range(0, count, 100):
        batch = sorted(ids)[start:start + 100]
        page = query({'f': 'json', 'objectIds': ','.join(map(str, batch)),
                      'outFields': f'{field},SURVEY_ID,DOWNLOAD_URL', 'returnGeometry': 'true', 'outSR': 4326})
        if page.get('exceededTransferLimit') or page.get('spatialReference', {}).get('wkid') != 4326:
            raise Hold('NOS truncated response or unexpected output CRS')
        rows = page.get('features', [])
        if (len(rows) != len(batch) or
                {r['attributes'][field] for r in rows} != set(batch)):
            raise Hold('NOS batch missing/duplicating IDs')
        features.extend(rows)
    if len({f['attributes']['SURVEY_ID'] for f in features}) != count:
        raise Hold('Duplicate NOS survey IDs')
    return features


def enumerate_nos(metadata, *, probe_sizes=False):
    features = nos_features(metadata.query)
    rows, holds, associations = [], [], {}
    for feature in features:
        attrs = feature['attributes']
        survey = attrs['SURVEY_ID']
        page = urlsplit(attrs['DOWNLOAD_URL'])
        match = re.fullmatch(r'/nos/([A-Z]\d{5}-[A-Z]\d{5})/([A-Z]\d{5})\.html', page.path)
        if (page.scheme != 'https' or page.hostname != 'www.ngdc.noaa.gov' or not match or
                match[2] != survey or page.query or page.fragment):
            raise Hold('Unexpected official NOS survey-page identity')
        points = [p for ring in feature['geometry']['rings'] for p in ring]
        if not points or any(len(p) < 2 or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in points):
            raise Hold('Invalid NOS WGS84 footprint')
        bounds = [min(p[0] for p in points), min(p[1] for p in points),
                  max(p[0] for p in points), max(p[1] for p in points)]
        segments = segments_for(bounds)
        associations[survey] = {'segments': segments, 'bounds': bounds, 'survey_page': attrs['DOWNLOAD_URL']}
        if not segments:
            continue  # explicit exclusion in associations, not an unexamined omission
        directory = DIRECTORY + match[1] + '/' + survey + '/BAG/'
        try:
            for url in bag_urls(metadata.get(directory), directory):
                size = {'bytes': None}
                if probe_sizes:
                    try:
                        size = metadata.head(url)
                    except (ValueError, OSError) as error:
                        holds.append({'source': 'noaa-nos', 'url': url, 'reason': str(error)})
                rows.append({'source': 'noaa-nos', 'url': url, 'segments': segments,
                             'licence': NOAA, **size, 'sha256': None, 'evidence': directory,
                             'association_basis': 'Official survey envelope; not per-file valid cells.',
                             'bag_kind_hint': 'variable-resolution' if '_VR_' in url else 'unconfirmed-regular'})
        except (ValueError, OSError) as error:
            holds.append({'source': 'noaa-nos', 'url': directory, 'reason': str(error)})
    rows.extend(metadata.query_files.values())
    return rows, holds, associations


def scheme_rows(path):
    # Only the small geometry/links scheme is read; no raster or RAT is fetched.
    import shapely
    from shapely.geometry import box
    from shapely.ops import transform
    from pyproj import CRS, Transformer
    result, pending = [], []
    with sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        db.row_factory = sqlite3.Row
        tables = list(db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'"))
        if len(tables) != 1 or not re.fullmatch(r'BlueTopo_Tile_Scheme_[0-9_]+', tables[0][0]):
            raise Hold('Expected one BlueTopo feature layer')
        table = tables[0][0]
        geometry = list(db.execute('SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE table_name=?', (table,)))
        if len(geometry) != 1:
            raise Hold('Expected one BlueTopo geometry column')
        column, srs = geometry[0]
        crs = db.execute('SELECT organization, organization_coordsys_id, definition FROM gpkg_spatial_ref_sys WHERE srs_id=?', (srs,)).fetchone()
        if not crs:
            raise Hold('Missing scheme CRS')
        source = CRS.from_epsg(crs[1]) if crs[0] == 'EPSG' else CRS.from_wkt(crs[2])
        project = Transformer.from_crs(source, 4326, always_xy=True).transform
        for row in db.execute(f'SELECT * FROM "{table}"'):
            blob = row[column]
            if blob[:2] != b'GP' or (blob[3] >> 1) & 7 not in (0, 1, 2, 3, 4):
                raise Hold('Invalid GeoPackage geometry header')
            offset = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(blob[3] >> 1) & 7]
            geom = transform(project, shapely.from_wkb(blob[offset:]))
            if geom.is_empty or not geom.is_valid:
                raise Hold('Invalid scheme tile geometry')
            if not geom.intersects(box(*CA)):
                continue
            segments = [s for s, b in BOUNDS.items() if geom.intersection(box(*b)).area > 0]
            if not segments:
                continue
            tile = row['tile']
            if not re.fullmatch(r'[A-Z0-9]{8}', tile):
                raise Hold('Invalid BlueTopo tile ID')
            if not all(row[k] for k in ('Delivered_Date', 'GeoTIFF_Link', 'RAT_Link')):
                pending.append({'tile': tile, 'segments': segments, 'reason': 'Not delivered in current scheme'})
                continue
            result.append({**dict(row), 'segments': segments})
    if len({r['tile'] for r in result}) != len(result) or not result:
        raise Hold('Empty or duplicate selected BlueTopo tiles')
    return result, pending


def enumerate_bluetopo(metadata):
    schemes = list_s3(metadata.get, 'BlueTopo/_BlueTopo_Tile_Scheme/')
    keys = [k for k in schemes if re.fullmatch(r'BlueTopo/_BlueTopo_Tile_Scheme/BlueTopo_Tile_Scheme_\d{8}_\d{6}\.gpkg', k)]
    if not keys:
        raise Hold('No current scheme listed')
    key = max(keys)
    body = metadata.get(S3 + key, limit=20_000_000, scheme=True)
    if len(body) != schemes[key]['bytes']:
        raise Hold('Scheme size differs from S3 listing')
    path = metadata.directory / 'selected-scheme.gpkg'
    safe_path(path).write_bytes(body)
    selected, pending = scheme_rows(path.absolute())
    rows = [{'source': 'noaa-bluetopo-scheme', 'url': S3 + key, 'segments': list(SEGMENTS),
             'licence': NOAA, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
             'evidence': S3 + '?list-type=2&prefix=BlueTopo%2F_BlueTopo_Tile_Scheme%2F'}]
    holds = []
    for tile in selected:
        try:
            objects = list_s3(metadata.get, 'BlueTopo/' + tile['tile'] + '/')
            candidate = []
            for kind, checksum in [('GeoTIFF_Link', 'GeoTIFF_SHA256_Checksum'), ('RAT_Link', 'RAT_SHA256_Checksum')]:
                url, sha = tile[kind], tile[checksum]
                if not url.startswith(S3) or urlsplit(url).query or urlsplit(url).fragment:
                    raise Hold('Unexpected scheme object URL')
                obj = objects.get(unquote(url[len(S3):]))
                if not obj or obj['bytes'] <= 0 or not isinstance(sha, str) or not SHA.fullmatch(sha):
                    raise Hold('Scheme link/checksum and current listing disagree')
                candidate.append({'source': 'noaa-bluetopo', 'url': url, 'segments': tile['segments'],
                    'licence': NOAA + ' Planning context only; retain RAT contributor restrictions before reuse.',
                    'bytes': obj['bytes'], 'sha256': sha, 'etag': obj['etag'],
                    'last_modified': obj['last_modified'], 'evidence': S3 + key, 'tile': tile['tile']})
            rows.extend(candidate)
        except (ValueError, OSError) as error:
            holds.append({'source': 'noaa-bluetopo', 'tile': tile['tile'], 'reason': str(error)})
    return rows, holds, {'scheme_url': S3 + key, 'scheme_sha256': hashlib.sha256(body).hexdigest(),
                         'selected_tiles': len(selected), 'undelivered_tiles': pending}


def supplement(path):
    if digest(path) != SUPPLEMENT_SHA:
        raise Hold('Supplement differs from independently accepted artifact')
    return json.loads(path.read_text())


def reconcile(seed, extra, nos, blue):
    """Keep provenance of replaced generic gaps and retain all scoped holds."""
    files = {r['url']: dict(r) for r in seed['files']}
    resolved = {'crm', 'gmrt', 'usgs-cascadia', 'nccos-channel-islands', 'usgs-dds55',
                'gebco-2026', 'usgs-borderland'}
    holds = list(extra['unresolved'])
    for row in extra['files']:
        if row['url'] in files:
            raise Hold('Supplement unexpectedly duplicates seed')
        files[row['url']] = dict(row)
    audit = []
    for result, ids, replaced in [
        (nos, {'noaa-nos-statewide', 'ncei-footprints'}, {'noaa-gis-footprint-metadata', 'nos-bag-ca-inventory-gaps'}),
        (blue, {'bluetopo-ca'}, {'noaa-bluetopo-inventory-completeness'}),
    ]:
        if result is None:
            continue
        rows, errors, evidence = result
        # A completed catalog scan replaces a vague gap with exact per-object holds.
        resolved.update(ids)
        holds = [g for g in holds if g['source'] not in replaced]
        holds.extend(errors)
        audit.append(evidence)
        for row in rows:
            old = files.get(row['url'])
            if old:
                # Retain reviewed hashes/sizes; replace coarse inspected-window association.
                if old.get('bytes') and row.get('bytes') and old['bytes'] != row['bytes']:
                    holds.append({'source': row['source'], 'url': row['url'],
                                  'reason': 'Current HEAD size differs from committed archive pin'})
                row = {**row, 'bytes': old.get('bytes') or row.get('bytes'), 'sha256': old.get('sha256')}
            files[row['url']] = row
    reconciled, remaining = [], []
    for gap in seed['unresolved']:
        if gap['id'] in resolved or (gap['id'].startswith('association-') and gap.get('url') in files):
            reconciled.append(gap)
        else:
            remaining.append(gap)
    return {**seed, 'scope': 'Campaign raw-mirror candidates; unresolved holds forbid complete status.',
            'supplement_sha256': SUPPLEMENT_SHA, 'enumeration_audit': audit,
            'reconciled_seed_gaps': reconciled, 'unresolved': remaining + holds,
            'files': sorted(files.values(), key=lambda r: (SEGMENTS.index(r['segments'][0]), r['source'], r['url']))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--supplement', required=True, type=Path)
    parser.add_argument('--receipts', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--probe-nos-sizes', action='store_true', help='HEAD every enumerated BAG; no payload body')
    parser.add_argument('--only', choices=['nos', 'bluetopo', 'supplement'], default=None)
    args = parser.parse_args()
    extra = supplement(args.supplement)
    metadata = Metadata(args.receipts, offline=args.offline)
    results = {}
    with metadata.transport.lock():
        for name, function in [('nos', enumerate_nos), ('bluetopo', enumerate_bluetopo)]:
            if args.only and args.only != name:
                continue
            try:
                results[name] = (function(metadata, probe_sizes=args.probe_nos_sizes)
                                 if name == 'nos' else function(metadata))
            except (ValueError, OSError, ET.ParseError, sqlite3.Error) as error:
                extra['unresolved'].append({'source': name, 'reason': str(error)})
    plan = reconcile(build(repo_root()), extra, results.get('nos'), results.get('bluetopo'))
    atomic_json(args.output, plan)
    load_plan(args.output, metadata.transport.session)
    print(json.dumps({'files': len(plan['files']), 'unresolved': len(plan['unresolved']),
                      'enumerated': list(results), 'review_required': True}))
    return 2 if plan['unresolved'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
