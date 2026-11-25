#!/usr/bin/env python3
"""Served-build receipt for an assembled Morro stage-preview tree (M20).

Offline and loopback only: no Worker, network, credentials, hosting or visual verdict. Given an asset
tree made by ``morro_preview_assets.py assemble`` it:

1. rechecks the tree against its manifest (``morro_preview_assets.verify``);
2. serves ``client/`` from a 127.0.0.1 server that routes the page paths the way the Worker does
   (``/sources`` and ``/map`` answer with the build's fingerprinted shells; other paths are files);
3. reads back over real HTTP the pointer, both contour files and ``/sources``, and binds each
   response body to the manifest pin. A response that is the app shell (or any HTML page) where a
   data file belongs is refused even with HTTP 200, so a host that falls back to the shell for a
   missing asset cannot pass;
4. rechecks the tree after serving and writes a new receipt file.

On any refusal nothing is written and the exit status is 2. The receipt is not an R8 verdict, a
deployment record or release authority.
"""
from __future__ import annotations

import argparse
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.relief import morro_preview_assets as assets  # noqa: E402

RECEIPT_SCHEMA = 'sc-morro-served-preview-receipt/1'
REGION = assets.REGION
# Served path -> what the manifest pins for it (candidate key, or the /sources shell file).
DATA_PATHS = {
    f'/catalog/relief/{REGION}.json': 'pointer',
    f'/regions/{REGION}/depth-contours.geojson': 'detail',
    f'/regions/{REGION}/depth-contours-overview.geojson': 'overview',
}
PAGE_PATHS = ('/sources', '/map')
MISS_MODES = ('404', 'app-shell')


class Held(ValueError):
    """The served build does not match its manifest; no receipt was written."""


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


class _Handler(SimpleHTTPRequestHandler):
    """Loopback stand-in for the Worker's page routing over the static client tree."""

    pages: dict = {}
    miss: str = '404'
    app_shell: str = ''

    def log_message(self, format, *args):  # noqa: A002 - base-class signature
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def send_head(self):
        path = self.path.split('?', 1)[0]
        if path in self.pages:
            self.path = self.pages[path]
        elif self.miss == 'app-shell' and not Path(self.translate_path(path)).is_file():
            self.path = self.app_shell  # what a single-page-app host does for an unknown path
        return super().send_head()


def serve(client: Path, build_id: str, miss: str = '404'):
    """Start a 127.0.0.1 server for ``client``; returns (server, origin)."""
    if miss not in MISS_MODES:
        raise Held(f'serve: unknown miss mode {miss!r}')
    shells = {'/sources': f'/sources.{build_id}.html', '/map': f'/app.{build_id}.html'}
    handler = type('Handler', (_Handler,), {'pages': shells, 'miss': miss, 'app_shell': shells['/map']})
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(handler, directory=str(client)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}'


def fetch(origin: str, path: str) -> dict:
    if not origin.startswith('http://127.0.0.1:'):
        raise Held('fetch: loopback origins only')
    request = urllib.request.Request(origin + path, headers={'Accept': '*/*', 'Cache-Control': 'no-cache'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body, status, ctype = response.read(), response.status, response.headers.get('Content-Type', '')
    except urllib.error.HTTPError as error:
        body, status, ctype = error.read(), error.code, error.headers.get('Content-Type', '')
    return {'status': status, 'content_type': ctype, 'bytes': len(body), 'sha256': digest(body), '_body': body}


def _html_shells(manifest: dict) -> set:
    return {row['sha256'] for name, row in manifest['files'].items() if name.startswith('client/') and name.endswith('.html')}


def check_responses(manifest: dict, responses: dict) -> list:
    """Return the list of problems (empty when every served response binds to the manifest)."""
    problems = []
    shells = _html_shells(manifest)
    for path, key in DATA_PATHS.items():
        row = responses[path]
        want = manifest['candidate'][key]
        if row['status'] != 200:
            problems.append(f'{path}: HTTP {row["status"]}')
        elif row['sha256'] in shells or 'text/html' in row['content_type'].lower() or row['_body'].lstrip()[:15].lower().startswith(b'<!doctype html'):
            problems.append(f'{path}: HTTP 200 answered with an HTML page (app-shell fallback?), not the pinned {key}')
        elif row['sha256'] != want:
            problems.append(f'{path}: body {row["sha256"][:12]} is not the pinned {key} {want[:12]}')
    sources = responses['/sources']
    shell = manifest['files'][manifest['sources_shell']]['sha256']
    if sources['status'] != 200 or sources['sha256'] != shell:
        problems.append(f'/sources: HTTP {sources["status"]} body {sources["sha256"][:12]} is not the pinned credits shell {shell[:12]}')
    app = responses['/map']
    if app['status'] != 200 or app['sha256'] not in shells:
        problems.append('/map: the app shell was not served')
    return problems


def receipt_for(out: Path, miss: str = '404') -> dict:
    out = out.resolve(strict=True)
    manifest = assets.verify(out)
    manifest_sha = digest((out / 'manifest.json').read_bytes())
    for path, key in DATA_PATHS.items():
        if manifest['served'].get(path) != key:
            raise Held(f'manifest: {path} is not served as {key}')
    server, origin = serve(out / 'client', manifest['build'], miss)
    try:
        responses = {path: fetch(origin, path) for path in (*DATA_PATHS, *PAGE_PATHS)}
        absent = fetch(origin, f'/regions/{REGION}/m20-absent-probe.geojson')
    finally:
        server.shutdown()
        server.server_close()
    problems = check_responses(manifest, responses)
    if problems:
        raise Held('; '.join(problems))
    if assets.verify(out) != manifest or digest((out / 'manifest.json').read_bytes()) != manifest_sha:
        raise Held('manifest: the tree changed while it was served')
    strip = lambda row: {k: v for k, v in row.items() if k != '_body'}  # noqa: E731
    return {
        'schema': RECEIPT_SCHEMA, 'region': REGION,
        'scope': 'LOCAL loopback read-back of an assembled preview tree; not hosted, not an R8 verdict, not release authority',
        'publication_signature': None, 'manifest_sha256': manifest_sha, 'build': manifest['build'],
        **{key: manifest[key] for key in ('identity_sha256', 'envelope_sha256', 'release_sha256', 'generation')},
        'miss_mode': miss,
        'served': {path: {**strip(responses[path]), 'pinned': manifest['candidate'][key], 'binds': key} for path, key in DATA_PATHS.items()},
        'sources': {**strip(responses['/sources']), 'pinned_shell': manifest['sources_shell']},
        'app_shell': strip(responses['/map']),
        'absent_probe': {**strip(absent), 'note': 'an unknown asset path; a 200 here means the host falls back to a page'},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--assets', type=Path, required=True, help='tree made by morro_preview_assets.py assemble')
    parser.add_argument('--receipt', type=Path, required=True, help='new receipt file (must not exist)')
    parser.add_argument('--miss', choices=MISS_MODES, default='404',
                        help='how the loopback host answers an unknown path: 404 (the Worker) or app-shell (a single-page host)')
    args = parser.parse_args(argv)
    try:
        if args.receipt.exists():
            raise Held('receipt: already exists')
        receipt = receipt_for(args.assets, args.miss)
        raw = json.dumps(receipt, indent=2, sort_keys=True).encode() + b'\n'
        with open(args.receipt, 'xb') as handle:
            handle.write(raw)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Morro served preview held: {error}', file=sys.stderr)
        return 2
    print(json.dumps({'build': receipt['build'], 'manifest_sha256': receipt['manifest_sha256'],
                      'receipt_sha256': digest(raw), 'served': {p: r['sha256'][:12] for p, r in receipt['served'].items()},
                      'absent_probe_status': receipt['absent_probe']['status']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
