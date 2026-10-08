"""Plan, record and publish the Chart basemap archive (FE-10, docs/plans/front-end/design.md § 4).

One archive, `tiles/basemap/ca-coast-<build>.pmtiles`, cut by byte ranges
from a Protomaps daily planet build: zooms 0-10 over one overview box around
every active and preview region (padded), zooms 11-14 inside each region's
`bounds` from regions/<id>/region.json. MapLibre overzooms past 14.
scripts/basemap/build_basemap.sh runs the steps:

    python scripts/basemap/regions.py latest                       # newest Protomaps build, YYYYMMDD
    python scripts/basemap/regions.py plan --build 20261008        # var/basemap/{plan.json,detail.geojson}
    python scripts/basemap/regions.py manifest --seconds 812       # var/basemap/manifest.json
    python scripts/basemap/regions.py publish                      # R2: archive, read-back, then manifest

Publishing needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID (scripts/publish_r2.py)
and never deletes: an older archive stays until a lifecycle rule or a person removes it.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ('active', 'preview')
OVERVIEW_MAXZOOM, DETAIL_MAXZOOM, PAD = 10, 14, 0.5
BUILDS = 'https://build-metadata.protomaps.dev/builds.json'
SOURCE = 'https://build.protomaps.com/{build}.pmtiles'
PREFIX = 'tiles/basemap'
ATTRIBUTION = '© OpenStreetMap contributors, © Protomaps'
MAX_LISTING_BYTES = 1 << 20  # 12 KB today
AGENT = {'User-Agent': 'SkipperCast basemap build (https://skippercast.com)'}


def check_bbox(box):
    west, south, east, north = (float(v) for v in box)
    if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
        raise ValueError(f'Invalid bounding box: {box}')
    return [west, south, east, north]


def region_boxes(root=ROOT):
    """[{id, status, bbox}] of every active and preview region; drafts join when previewed."""
    boxes = []
    for path in sorted(Path(root, 'regions').glob('*/region.json')):
        region = json.loads(path.read_text())
        if region.get('status') in PUBLISHED:
            boxes.append({'id': region['id'], 'status': region['status'], 'bbox': check_bbox(region['bounds'])})
    if not boxes:
        raise ValueError('No active or preview region to extract')
    return boxes


def overview_box(boxes, pad=PAD):
    """The union of the region boxes, padded and rounded outward to 0.01°."""
    down = lambda v: math.floor(round(v * 100, 6)) / 100
    up = lambda v: math.ceil(round(v * 100, 6)) / 100
    return check_bbox([max(-180, down(min(b['bbox'][0] for b in boxes) - pad)),
                       max(-85, down(min(b['bbox'][1] for b in boxes) - pad)),
                       min(180, up(max(b['bbox'][2] for b in boxes) + pad)),
                       min(85, up(max(b['bbox'][3] for b in boxes) + pad))])


def detail_region(boxes):
    """A GeoJSON MultiPolygon of the region boxes, for `pmtiles extract --region`."""
    rings = [[[[w, s], [e, s], [e, n], [w, n], [w, s]]] for w, s, e, n in (b['bbox'] for b in boxes)]
    return {'type': 'Feature', 'properties': {'regions': [b['id'] for b in boxes]},
            'geometry': {'type': 'MultiPolygon', 'coordinates': rings}}


def latest(listing):
    """The newest daily build (YYYYMMDD) in the Protomaps builds listing."""
    builds = sorted(b['key'][:8] for b in listing if re.fullmatch(r'\d{8}\.pmtiles', str(b.get('key', ''))))
    if not builds:
        raise ValueError('The Protomaps builds listing has no daily build')
    return builds[-1]


def archive_key(build):
    if not re.fullmatch(r'\d{8}', str(build)):
        raise ValueError(f'A Protomaps build is YYYYMMDD, not {build!r}')
    return f'{PREFIX}/ca-coast-{build}.pmtiles'


def plan(build, listing, root=ROOT):
    """Source URL, overview box, zoom split and archive key for one build."""
    entry = next((b for b in listing if b.get('key') == f'{build}.pmtiles'), None)
    if entry is None:
        raise ValueError(f'Protomaps lists no build {build}')
    boxes = region_boxes(root)
    return {'build': build, 'key': archive_key(build), 'source': {
                'url': SOURCE.format(build=build), 'bytes': entry.get('size'), 'version': entry.get('version'),
                'b3sum': entry.get('b3sum')},
            'overview': {'bbox': overview_box(boxes), 'minzoom': 0, 'maxzoom': OVERVIEW_MAXZOOM},
            'detail': {'minzoom': OVERVIEW_MAXZOOM + 1, 'maxzoom': DETAIL_MAXZOOM}, 'regions': boxes}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def manifest(planned, archive, seconds, now=None):
    """The pointer the Chart style reads: which archive, its size and hash, what it covers."""
    archive = Path(archive)
    if archive.name != planned['key'].rsplit('/', 1)[1] or archive.stat().st_size < 1024:
        raise ValueError(f'{archive} is not the planned archive or is empty')
    return {'schema_version': 1, 'key': planned['key'], 'bytes': archive.stat().st_size, 'sha256': sha256(archive),
            'built_at': (now or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'build_seconds': int(seconds), 'attribution': ATTRIBUTION, 'license': 'ODbL-1.0',
            'source': {'build': planned['build'], **planned['source']},
            'overview': planned['overview'], 'detail': planned['detail'],
            'regions': [{'id': r['id'], 'bbox': r['bbox']} for r in planned['regions']]}


def publish(s3, bucket, archive, document):
    """Upload the archive, check its stored size and hash, then write the manifest. Never deletes."""
    s3.upload_file(str(archive), bucket, document['key'], ExtraArgs={
        'ContentType': 'application/octet-stream', 'CacheControl': 'public, max-age=31536000, immutable',
        'Metadata': {'sha256': document['sha256']}})
    head = s3.head_object(Bucket=bucket, Key=document['key'])
    if head.get('ContentLength') != document['bytes'] or head.get('Metadata', {}).get('sha256') != document['sha256']:
        raise RuntimeError(f"R2 read-back mismatch for {document['key']}; manifest not updated")
    s3.put_object(Bucket=bucket, Key=f'{PREFIX}/manifest.json', Body=json.dumps(document, indent=2).encode(),
                  ContentType='application/json', CacheControl='public, max-age=60')
    return f"Published /feeds/{document['key']} ({document['bytes']:,} bytes) and /feeds/{PREFIX}/manifest.json"


def listing():
    """The Protomaps builds listing, from its exact host and at most 1 MiB."""
    with urlopen(Request(BUILDS, headers=AGENT), timeout=60) as response:
        if urlsplit(response.geturl()).hostname != urlsplit(BUILDS).hostname:
            raise ValueError('The Protomaps builds listing redirected to another host')
        body = response.read(MAX_LISTING_BYTES + 1)
    if len(body) > MAX_LISTING_BYTES:
        raise ValueError('The Protomaps builds listing exceeds 1 MiB')
    return json.loads(body)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['latest', 'plan', 'manifest', 'publish'])
    parser.add_argument('--build')
    parser.add_argument('--dir', type=Path, default=ROOT / 'var/basemap')
    parser.add_argument('--seconds', type=float, default=0)
    args = parser.parse_args(argv)
    if args.command == 'latest':
        print(latest(listing()))
        return
    if args.command == 'plan':
        planned = plan(args.build, listing())
        args.dir.mkdir(parents=True, exist_ok=True)
        (args.dir / 'plan.json').write_text(json.dumps(planned, indent=2))
        (args.dir / 'detail.geojson').write_text(json.dumps(detail_region(planned['regions'])))
        o, d = planned['overview'], planned['detail']
        print(planned['source']['url'], ','.join(map(str, o['bbox'])), o['maxzoom'], d['minzoom'], d['maxzoom'],
              planned['key'].rsplit('/', 1)[1])
        return
    planned = json.loads((args.dir / 'plan.json').read_text())
    archive = args.dir / planned['key'].rsplit('/', 1)[1]
    if args.command == 'manifest':
        m = manifest(planned, archive, args.seconds)
        (args.dir / 'manifest.json').write_text(json.dumps(m, indent=2))
        print(f"{m['key']}: {m['bytes']:,} bytes ({m['bytes'] / 2**20:.1f} MiB) in {m['build_seconds']} s "
              f"from Protomaps {m['source']['build']}")
        return
    document = json.loads((args.dir / 'manifest.json').read_text())
    token, account = os.environ.get('CLOUDFLARE_API_TOKEN'), os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    if not token or not account:
        raise SystemExit('R2 not configured (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID); nothing published.')
    if document['sha256'] != sha256(archive):
        raise SystemExit('The archive changed after its manifest was written; rebuild.')
    sys.path.insert(0, str(ROOT / 'scripts'))
    from publish_r2 import client
    print(publish(client(token, account), os.environ.get('R2_BUCKET', 'skippercast-feeds'), archive, document))


if __name__ == '__main__':
    main()
