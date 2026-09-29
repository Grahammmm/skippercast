"""Small public-route probe: a private R2 receipt alone is not deployment proof."""
import json
from urllib.request import Request, urlopen


def verify_public(region, manifest, *, base='https://skippercast.com', opener=urlopen):
    if not base.startswith('https://') or manifest['region'] != region:
        raise ValueError('Invalid public verification target')
    prefix = base.rstrip('/')+'/feeds/tiles/seafloor/'
    with opener(Request(prefix+f'manifest-{region}.json', headers={'Cache-Control': 'no-cache', 'User-Agent': 'SkipperCast-Seafloor/1.0'}), timeout=30) as response:
        current = json.load(response)
    if current.get('status') != 'ready' or current.get('archive_sha256') != manifest['archive_sha256']:
        raise ValueError('Public manifest does not match R2 publication')
    request = Request(prefix+manifest['archive'], headers={'Range': 'bytes=0-126', 'Cache-Control': 'no-cache', 'User-Agent': 'SkipperCast-Seafloor/1.0'})
    with opener(request, timeout=30) as response:
        raw = response.read(128)
        if (response.status != 206 or len(raw) != 127 or raw[:8] != b'PMTiles\x03'
                or response.headers.get('Content-Range') != f"bytes 0-126/{manifest['archive_bytes']}"
                or response.headers.get('X-Feed-Source') != 'r2'
                or response.headers.get('Cache-Control') != 'no-store'):
            raise ValueError('Public PMTiles range/expiry gate is not deployed correctly')
    return {'region': region, 'url': prefix+manifest['archive'],
            'archive_sha256': manifest['archive_sha256'], 'range_status': 206}


def main():
    import argparse
    import os
    from pathlib import Path
    from skippercast.platform.contracts import atomic_json
    from .publish import credentials
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', type=Path, required=True)
    args = parser.parse_args()
    s3, bucket = credentials()
    receipts = []
    for region in sorted({r['region'] for r in json.loads(args.matrix.read_text())['include']}):
        manifest = json.loads((Path('var/seafloor/public')/region/'manifest.json').read_text())
        receipt = verify_public(region, manifest, base=os.environ.get('SEAFLOOR_PUBLIC_BASE', 'https://skippercast.com'))
        receipts.append(receipt)
        s3.put_object(Bucket=bucket, Key=f'seafloor-review/publication/{region}/{manifest["archive_sha256"]}.json',
                      Body=json.dumps(receipt).encode(), ContentType='application/json', CacheControl='private, no-store')
    atomic_json(Path('var/seafloor/publication/http-verification.json'), receipts)
    print(json.dumps(receipts))


if __name__ == '__main__':
    main()
