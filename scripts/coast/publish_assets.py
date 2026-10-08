#!/usr/bin/env python3
"""Copy reviewed coastal terrain, imagery and habitat assets into SkipperCast's R2 store.

    python scripts/coast/publish_assets.py --plan                      # rights check only, no asset downloads
    python scripts/coast/publish_assets.py --out var/coast-assets      # download, verify and write the manifest
    python scripts/coast/publish_assets.py --out var/coast-assets --upload --groups habitat

Assets are read from the owner's Fish Worker at their public paths, checked
against the SHA-256 and byte counts its own manifests declare, and written to
R2 content-addressed (`coast/objects/<sha256>`). The manifest maps each public
path to `{sha256, bytes, contentType}`; its own SHA-256 is the release id
(`coast/releases/<id>.json`). `coast/current.json` is written last, after every
object and the manifest read back with matching digests, so the Worker
(`server/coast-data.ts`) never sees a partial release.

Every source behind a group must be an approved `catalog/sources.json` row with
`commercial_use: allowed`. An unknown source (no catalog row) or a held one
(candidate, restricted, permission-required, unknown) refuses the whole run
before any asset is downloaded. See docs/coastal-service.md.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = 'https://fish-report.g4651.workers.dev'
RANGE = 2 * 1024 * 1024  # the Fish habitat proxy serves archives only in ranges of at most 2 MiB
TYPES = {'.json': 'application/json', '.geojson': 'application/json', '.bin': 'application/octet-stream',
         '.png': 'image/png', '.jpg': 'image/jpeg'}
# Documents whose `sources` the terrain group's rights check reads; their exact bytes are copied.
TERRAIN_INDEX = ['/data/coast-wide/manifest.json', '/data/coast3d/chart-model.json', '/data/coast3d/chart-provenance.json']
TERRAIN_SOURCES = ['/data/coast-wide/manifest.json', '/data/coast3d/chart-provenance.json']
REEF_CONTEXT = '/data/coast-wide/reef-context.json'
# Sources a group carries that its upstream manifest does not list by URL (design § 11 register rows).
DECLARED = {'terrain': ['usgs-naip'], 'habitat': []}
PUBLIC_PATH = re.compile(r'^/data/(?:coast-wide|coast3d)/[A-Za-z0-9_.-]+\.(?:json|bin|png|jpg)$')
SHA = re.compile(r'^[a-f0-9]{64}$')


def group_of(path):
    """The asset group the Worker uses to choose R2 or the bridge (server/coast-data.ts assetGroup).

    The reef context is derived from the habitat release and pinned to its archives, so it
    travels with habitat and its sources' rights, not with terrain. Other paths (the shore
    files, FE-10 and FE-43) belong to no group and stay on the bridge."""
    if path.startswith(('/api/habitat/', '/data/skippercast-', '/data/coast-wide/reef-context.')):
        return 'habitat'
    return 'terrain' if PUBLIC_PATH.match(path) else None


def get(path, origin=ORIGIN, headers=None):
    request = Request(origin + path, headers={'Accept-Encoding': 'identity', 'User-Agent': 'SkipperCast-coast-assets/1', **(headers or {})})
    with urlopen(request, timeout=60) as response:
        return response.status, dict(response.headers), response.read()


def catalog_ids(urls, catalog):
    """{url: catalog id or None}: matched by DOI, else by the row's documentation or terms URL prefix."""
    found = {}
    for url in urls:
        doi = re.search(r'10\.5066[/-](P9[A-Z0-9]+)', url)
        hits = [s['id'] for s in catalog if (doi and doi.group(1) in (s.get('documentation_url') or '')) or any(
            prefix and url.startswith(prefix) for prefix in (s.get('documentation_url'), s.get('rights', {}).get('terms_url')))]
        found[url] = hits[0] if len(hits) == 1 else None
    return found


def refusals(group, urls, catalog):
    """Reasons this group may not be published; empty when every source is approved for commercial use."""
    rows, problems = {s['id']: s for s in catalog}, []
    if not urls:  # a manifest that names no source is never treated as cleared
        problems.append(f'{group}: upstream manifest lists no sources')
    ids = set(DECLARED[group])
    for url, source in catalog_ids(urls, catalog).items():
        if source is None:
            problems.append(f'{group}: unknown source {url}')
        ids.add(source)
    for source in sorted(i for i in ids if i):
        row = rows.get(source)
        if row is None:
            problems.append(f'{group}: unknown source {source} (no catalog/sources.json row)')
        elif row.get('review_status') != 'approved' or row.get('rights', {}).get('commercial_use') != 'allowed':
            problems.append(f"{group}: rights held for {source} ({row.get('review_status')}, "
                            f"commercial_use {row.get('rights', {}).get('commercial_use')})")
    return problems


def assets(value, out):
    """Every {url, sha256, bytes} asset and every bare public path referenced inside a manifest."""
    if isinstance(value, dict):
        if isinstance(value.get('url'), str) and SHA.match(str(value.get('sha256', ''))):
            out[value['url']] = {'sha256': value['sha256'], 'bytes': value.get('bytes')}
        for item in value.values():
            assets(item, out)
    elif isinstance(value, list):
        for item in value:
            assets(item, out)
    elif isinstance(value, str) and PUBLIC_PATH.match(value):
        out.setdefault(value, {})
    return out


def pinned(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def habitat_plan(origin, catalog, now):
    """Problems and wanted entries for the live habitat release, its public copy and the reef context."""
    release, public_bytes, reef_bytes = (get(path, origin)[2] for path in
                                         ('/api/habitat/release', '/data/skippercast-manifest.json', REEF_CONTEXT))
    control, public, reef = json.loads(release), json.loads(public_bytes), json.loads(reef_bytes)
    problems = refusals('habitat', sorted({s['url'] for s in public.get('sources') or []}), catalog)
    if control.get('status') != 'ready' or control.get('ready') is not True or public.get('releaseId') != control.get('releaseId'):
        problems.append('habitat: public manifest does not name the live ready release')
    if not datetime.fromisoformat(control['expiresAt']) > now:
        problems.append('habitat: release expired')
    tag = {'habitatRelease': control['releaseId'], 'expiresAt': control['expiresAt']}
    wanted = {'/api/habitat/release': {**tag, **pinned(release)},
              '/data/skippercast-manifest.json': {**tag, **pinned(public_bytes)},
              '/data/skippercast-habitat.geojson': {**tag, 'sha256': public['geojsonSha256'], 'bytes': public['geojsonBytes']},
              '/data/skippercast-species.json': dict(tag),
              REEF_CONTEXT: {'expiresAt': reef['expiresAt'], **pinned(reef_bytes)},
              reef['asset']['url']: {'expiresAt': reef['expiresAt'], 'sha256': reef['asset']['sha256'], 'bytes': reef['asset']['bytes']}}
    archives = {r['regionId']: r for r in control['regions']}
    # The renderer HEADs every region the public manifest lists and compares ETag and length
    # (packages/coast habitat-lifecycle.ts); the Worker answers with "sha256-<digest>".
    for region in public['regions']:
        live = archives.get(region['regionId'])
        if not re.fullmatch(r'[a-z0-9-]+', region['regionId']) or live is None or any(
                live[k] != region[k] for k in ('archiveSha256', 'archiveBytes', 'archiveETag')):
            problems.append(f"habitat: region {region['regionId']} differs from the live release")
        elif region['archiveETag'] != f'"sha256-{region["archiveSha256"]}"':
            problems.append(f"habitat: region {region['regionId']} ETag is not its SHA-256")
        else:
            wanted[f"/api/habitat/tiles?region={region['regionId']}"] = {
                'habitatRelease': control['releaseId'], 'expiresAt': region['expiresAt'],
                'sha256': region['archiveSha256'], 'bytes': region['archiveBytes']}
    if group_of(str(reef['asset']['url'])) != 'habitat' or not PUBLIC_PATH.match(str(reef['asset']['url'])):
        problems.append('habitat: reef context asset outside its group')
    return problems, wanted


def plan(groups, origin=ORIGIN, catalog=None, now=None):
    """(problems, {public path: expected entry}) for the selected groups, downloading only manifests."""
    catalog = catalog if catalog is not None else json.loads((ROOT / 'catalog/sources.json').read_text())['sources']
    now, problems, wanted = now or datetime.now(timezone.utc), [], {}
    if 'terrain' in groups:
        raw = {path: get(path, origin)[2] for path in TERRAIN_INDEX}
        indexes = {path: json.loads(data) for path, data in raw.items()}
        for path in TERRAIN_SOURCES:  # each document must name its own sources
            problems += refusals('terrain', sorted({s['url'] for s in indexes[path].get('sources') or []}), catalog)
        for index in indexes.values():
            wanted.update({k: v for k, v in assets(index, {}).items() if group_of(k) == 'terrain'})
        # The copied indexes are the exact bytes whose references were enumerated and rights-checked.
        for path, data in raw.items():
            if wanted.get(path, {}).get('sha256') not in (None, pinned(data)['sha256']):
                problems.append(f'terrain: {path} differs from the digest the chart model declares')
            wanted[path] = pinned(data)
    if 'habitat' in groups:
        found, entries = habitat_plan(origin, catalog, now)
        problems += found
        wanted.update(entries)
    return list(dict.fromkeys(problems)), wanted


def fetch(path, entry, origin=ORIGIN):
    """Bytes of one public asset, checked against the digest and size its upstream manifest declares."""
    release = entry.get('habitatRelease')
    if path.startswith('/api/habitat/tiles'):
        # The proxy refuses a single range covering the whole archive, so a small one takes two.
        url, parts, step = f'{path}&release={release}', [], max(1, min(RANGE, entry['bytes'] - 1))
        for start in range(0, entry['bytes'], step):
            end = min(start + step, entry['bytes']) - 1
            status, _, body = get(url, origin, {'Range': f'bytes={start}-{end}'})
            if status != 206 or len(body) != end - start + 1:
                raise ValueError(f'{path}: range {start}-{end} not returned exactly')
            parts.append(body)
        data = b''.join(parts)
    else:
        suffix = f'?release={release}' if release and path in ('/data/skippercast-habitat.geojson', '/data/skippercast-species.json') else ''
        data = get(path + suffix, origin)[2]
    digest = hashlib.sha256(data).hexdigest()
    if entry.get('sha256') not in (None, digest) or entry.get('bytes') not in (None, len(data)):
        raise ValueError(f'{path}: bytes differ from the upstream manifest')
    content_type = 'application/json' if path == '/api/habitat/release' else TYPES.get(Path(path).suffix, 'application/octet-stream')
    return data, {**{k: v for k, v in entry.items() if k in ('habitatRelease', 'expiresAt')},
                  'sha256': digest, 'bytes': len(data), 'contentType': content_type}


def build(groups, wanted, out, origin=ORIGIN, now=None):
    """Download into out/objects/<sha256> and write the canonical manifest; returns (release id, manifest bytes)."""
    objects = Path(out) / 'objects'
    objects.mkdir(parents=True, exist_ok=True)

    def one(path):
        data, entry = fetch(path, wanted[path], origin)
        (objects / entry['sha256']).write_bytes(data)
        return path, entry
    with ThreadPoolExecutor(8) as pool:
        entries = dict(pool.map(one, sorted(wanted)))
    manifest = json.dumps({'schemaVersion': 1, 'kind': 'skippercast-coast-assets', 'origin': origin,
                           'createdAt': (now or datetime.now(timezone.utc)).isoformat(timespec='seconds'),
                           'groups': sorted(groups), 'objects': entries}, sort_keys=True, separators=(',', ':')).encode()
    release = hashlib.sha256(manifest).hexdigest()
    (Path(out) / f'{release}.json').write_bytes(manifest)
    return release, manifest


def upload(s3, bucket, out, release, manifest):
    """Objects, then the manifest, each read back by digest; the current pointer last."""
    def put(key, data, content_type):
        try:  # content-addressed objects already uploaded and read back by an earlier run are kept
            head = s3.head_object(Bucket=bucket, Key=key)
            if key.startswith('coast/objects/') and head.get('Metadata', {}).get('sha256') == key.rsplit('/', 1)[1] \
                    and head.get('ContentLength') == len(data):
                return
        except Exception:
            pass
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type, CacheControl='no-store',
                      Metadata={'sha256': hashlib.sha256(data).hexdigest()})
        with s3.get_object(Bucket=bucket, Key=key)['Body'] as stream:
            if hashlib.sha256(stream.read()).hexdigest() != hashlib.sha256(data).hexdigest():
                raise RuntimeError(f'R2 read-back differs for {key}')
    for entry in {e['sha256']: e for e in json.loads(manifest)['objects'].values()}.values():
        data = (Path(out) / 'objects' / entry['sha256']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise RuntimeError(f"local object {entry['sha256']} changed since the manifest was built")
        put('coast/objects/' + entry['sha256'], data, entry['contentType'])
    put(f'coast/releases/{release}.json', manifest, 'application/json')
    put('coast/current.json', json.dumps({'schemaVersion': 1, 'status': 'ready', 'releaseId': release}).encode(), 'application/json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--groups', default='terrain,habitat')
    parser.add_argument('--origin', default=ORIGIN)
    parser.add_argument('--out', default='var/coast-assets')
    parser.add_argument('--plan', action='store_true', help='check rights and list assets; download nothing else')
    parser.add_argument('--upload', action='store_true')
    parser.add_argument('--bucket', default=os.environ.get('R2_BUCKET', 'skippercast-feeds'))
    args = parser.parse_args(argv)
    groups = sorted(set(args.groups.split(',')))
    if not groups or not set(groups) <= set(DECLARED):
        parser.error(f'--groups must be drawn from {sorted(DECLARED)}')
    problems, wanted = plan(groups, args.origin)
    for problem in problems:
        print('REFUSED', problem)
    if problems:
        return 1
    print(f'{len(wanted)} assets in {", ".join(groups)}')
    if args.plan:
        return 0
    release, manifest = build(groups, wanted, args.out, args.origin)
    print(f'release {release}')
    if args.upload:
        token, account = os.environ.get('CLOUDFLARE_API_TOKEN'), os.environ.get('CLOUDFLARE_ACCOUNT_ID')
        if not token or not account:
            raise SystemExit('R2 credentials required; nothing was uploaded')
        sys.path.insert(0, str(ROOT))
        from scripts.publish_r2 import client
        upload(client(token, account), args.bucket, args.out, release, manifest)
        print(f'promoted coast/current.json -> {release}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
