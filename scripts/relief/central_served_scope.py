#!/usr/bin/env python3
"""Read back an independently pinned Central rehearsal tree over IPv4 loopback.

Point --port at a local server for --tree/client that serves the fingerprinted
credits shell on /sources. C33 pins the overlay; C35 pins how its static client
was built and its exact fingerprinted shell. Neither evidence covers /feeds,
Worker behavior, hosted stage, or release approval.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
import json
from pathlib import Path
import re
import sys

CONTOUR = {'big-sur-coast', 'cambria-san-simeon', 'point-arguello-conception', 'south-big-sur-san-simeon'}
TERRAIN = {'monterey-point-sur', 'santa-cruz-monterey-bay'}
REGIONS = CONTOUR | TERRAIN
SUFFIXES = ('', '-overview')
BASELINE = {f'/regions/morro-bay/depth-contours{s}.geojson' for s in SUFFIXES}
PROBES = ({f'/regions/{r}/depth-contours{s}.geojson' for r in TERRAIN for s in SUFFIXES}
          | {'/catalog/relief/morro-bay.json', '/catalog/relief/not-a-region.json'})
MAX_RESPONSE = 8 * 1024 * 1024


def digest(raw):
    return sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, val in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = val
    return result


def load(path, pin):
    raw = path.read_bytes()
    if digest(raw) != pin:
        raise ValueError(f'{path.name}: differs from the separately supplied pin')
    return json.loads(raw, object_pairs_hook=unique)


def expectations(scope, manifest):
    if (scope['schema'] != 'sc-central-local-scope/1' or sorted(scope['regions']) != sorted(REGIONS)
            or manifest['schema'] != 'sc-central-stage-tree/1' or sorted(manifest['regions']) != sorted(REGIONS)):
        raise ValueError('scope and built tree must name exactly the six Central regions')
    routes = scope['routes']
    if any(not isinstance(pin, str) or not re.fullmatch('[a-f0-9]{64}', pin) for pin in routes.values()):
        raise ValueError('invalid independent route digest')
    static = {f'/catalog/relief/{r}.json' for r in REGIONS}
    static |= {f'/regions/{r}/depth-contours{s}.geojson' for r in CONTOUR for s in SUFFIXES}
    feeds = {url for url in routes if url.startswith(tuple(f'/feeds/tiles/relief/{r}/' for r in REGIONS))}
    if set(routes) - feeds != static | {'/sources'}:
        raise ValueError('unexpected or missing scoped static route')
    if manifest['pinned'] != {url: routes[url] for url in static}:
        raise ValueError('built overlay differs from independent pointer/contour pins')
    if manifest['sources_overlay_html_sha256'] != routes['/sources']:
        raise ValueError('stale sources overlay pin')
    build = manifest['build']
    if not isinstance(build, str) or not re.fullmatch('[a-f0-9]{10}', build):
        raise ValueError('invalid fingerprinted build ID')
    shell = f'client/sources.{build}.html'
    if manifest['sources_shell'] != shell or manifest['served'] != {
        **{url: f'client{url}' for url in static}, '/sources': shell,
    }:
        raise ValueError('built tree specifies a noncanonical route or sources shell')
    files = manifest['files']
    for url in static:
        if files[f'client{url}']['sha256'] != routes[url]:
            raise ValueError(f'{url}: built bytes disagree with independent pin')
    # Only pre-existing, independently pinned Morro v1 contours are outside the overlay.
    baseline = {url: files[f'client{url}']['sha256'] for url in BASELINE if f'client{url}' in files}
    return ({**{url: routes[url] for url in static}, '/sources': files[shell]['sha256']}, baseline, len(feeds))


def inventory(client):
    if client.is_symlink() or not client.is_dir():
        raise ValueError('missing or linked client directory')
    found = set()
    for file in client.rglob('*'):
        url = '/' + file.relative_to(client).as_posix()
        if file.is_symlink():
            raise ValueError(f'linked client path: {url}')
        if not file.is_file():
            continue
        if (url.startswith('/catalog/relief/') or url.startswith('/feeds/tiles/relief/')
                or url.startswith('/regions/') and file.name.startswith('depth-contours')):
            found.add(url)
    return found


def fetch(port, url):
    # Numeric loopback only. http.client never uses proxies or follows a Location header.
    connection = HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request('GET', url, headers={'Accept-Encoding': 'identity'})
        with connection.getresponse() as response:
            if response.status != 200:
                return response.status, None
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError(f'{url}: expected identity response')
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError(f'{url}: response exceeds local check limit')
            if url != '/sources' and ('html' in response.getheader('Content-Type', '').lower()
                                      or raw.lstrip().startswith(b'<')):
                raise ValueError(f'{url}: HTTP 200 HTML fallback')
            return response.status, digest(raw)
    finally:
        connection.close()


def check(tree, scope, manifest, port):
    if not 1 <= port <= 65535:
        raise ValueError('invalid loopback port')
    expected, baseline, feed_count = expectations(scope, manifest)
    found = inventory(tree / 'client')
    wanted = (expected.keys() - {'/sources'}) | baseline.keys()
    if found != wanted:
        raise ValueError(f'client inventory scope differs; missing={sorted(wanted - found)} extra={sorted(found - wanted)}')
    observed = []
    for url, pin in sorted((expected | baseline).items()):
        status, received = fetch(port, url)
        if status != 200 or received != pin:
            raise ValueError(f'{url}: expected exact pinned bytes, received HTTP {status} sha256={received}')
        observed.append({'route': url, 'status': status, 'sha256': received, 'base_asset': url in baseline})
    for url in sorted(PROBES):
        status, _ = fetch(port, url)
        if status != 404:
            raise ValueError(f'{url}: must be absent (HTTP 404), got {status}')
        observed.append({'route': url, 'status': status})
    return {'schema': 'sc-central-loopback-receipt/1', 'hosted': False, 'rows': observed,
            'excluded_feed_routes': feed_count, 'build': manifest['build']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--scope', type=Path, required=True)
    parser.add_argument('--scope-sha256', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    try:
        scope = load(args.scope, args.scope_sha256)
        manifest = load(args.tree / 'manifest.json', args.manifest_sha256)
        receipt = check(args.tree, scope, manifest, args.port)
    except (OSError, ValueError, KeyError, TypeError, HTTPException) as exc:
        print(f'Central loopback scope held: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
