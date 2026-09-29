#!/usr/bin/env python3
"""Mirror a published feed directory to Cloudflare R2, uploading only changes.

    python scripts/publish_r2.py <local-dir> <prefix>      # e.g. var/live-published conditions

Keys mirror the GitHub branch layout (`<prefix>/<path>`), so the site's
/feeds/<prefix>/<path> route serves R2 and GitHub interchangeably. A hash
index stored at `<prefix>/.r2-sync.json` limits each run to changed files
(the conditions feed has ~1,500 files; most don't change each cycle). Data
files upload before pointer files (latest/index/manifest), so readers never
see a pointer to a file that is not there yet; removed files go last.

Without CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID this does nothing, so
pipelines keep working before R2 is set up. With credentials, any upload error
exits non-zero: the Worker serves R2 first, so a failed upload means users see
stale data and the publishing job must go red. S3 credentials are derived from
the API token as Cloudflare documents: access key = token id, secret =
SHA-256 of the token value.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

INDEX = '.r2-sync.json'
POINTER = re.compile(r'(^|/)(latest|index|manifest|status|health|intelligence-health|habitat-health)[^/]*\.json$')
TYPES = {'.json': 'application/json', '.geojson': 'application/json', '.md': 'text/markdown; charset=utf-8',
         '.pmtiles': 'application/octet-stream', '.gpx': 'application/gpx+xml', '.html': 'text/html; charset=utf-8'}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def scan(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '.git' not in p.relative_to(root).parts and p.name != INDEX}


def plan(local, remote):
    """(uploads data-first then pointers, deletions) between two {path: sha} maps."""
    changed = [k for k, v in local.items() if remote.get(k) != v]
    uploads = sorted(k for k in changed if not POINTER.search(k)) + sorted(k for k in changed if POINTER.search(k))
    return uploads, sorted(set(remote) - set(local))


def cache_control(key):
    return 'public, max-age=60' if POINTER.search(key) else 'public, max-age=300'


def token_id(token, account):
    for url in ('https://api.cloudflare.com/client/v4/user/tokens/verify',
                f'https://api.cloudflare.com/client/v4/accounts/{account}/tokens/verify'):
        try:
            with urlopen(Request(url, headers={'Authorization': f'Bearer {token}'}), timeout=20) as response:
                body = json.load(response)
            if body.get('success') and body.get('result', {}).get('id'):
                return body['result']['id']
        except Exception:
            continue
    raise RuntimeError('could not verify CLOUDFLARE_API_TOKEN; check it is active and has R2 edit permission')


def client(token, account):
    import boto3
    from botocore.config import Config
    return boto3.client('s3', endpoint_url=f'https://{account}.r2.cloudflarestorage.com', region_name='auto',
                        aws_access_key_id=token_id(token, account),
                        aws_secret_access_key=hashlib.sha256(token.encode()).hexdigest(),
                        config=Config(retries={'max_attempts': 6, 'mode': 'adaptive'},
                                      request_checksum_calculation='when_required',
                                      response_checksum_validation='when_required'))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('source')
    parser.add_argument('prefix', choices=['conditions', 'data', 'forecasts', 'tiles'])
    parser.add_argument('--bucket', default=os.environ.get('R2_BUCKET', 'skippercast-feeds'))
    args = parser.parse_args()
    token, account = os.environ.get('CLOUDFLARE_API_TOKEN'), os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    if not token or not account:
        print(f'R2 not configured (no CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID); skipped {args.prefix}.')
        return
    print(sync(client(token, account), args.bucket, args.source, args.prefix))


def sync(s3, bucket, source, prefix):
    """Upload changed files (data first, pointers last), delete removed ones, store the index."""
    index_key = f'{prefix}/{INDEX}'
    try:
        remote = json.loads(s3.get_object(Bucket=bucket, Key=index_key)['Body'].read())
    except s3.exceptions.NoSuchKey:
        remote = {}
    local = scan(source)
    uploads, deletions = plan(local, remote)
    data_files = [k for k in uploads if not POINTER.search(k)]
    pointers = [k for k in uploads if POINTER.search(k)]

    def put(key):
        path = Path(source) / key
        s3.put_object(Bucket=bucket, Key=f'{prefix}/{key}', Body=path.read_bytes(),
                      ContentType=TYPES.get(path.suffix, 'application/octet-stream'), CacheControl=cache_control(key))

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(put, data_files))
        list(pool.map(put, pointers))
    for start in range(0, len(deletions), 1000):
        chunk = deletions[start:start + 1000]
        s3.delete_objects(Bucket=bucket, Delete={'Objects': [{'Key': f'{prefix}/{k}'} for k in chunk], 'Quiet': True})
    s3.put_object(Bucket=bucket, Key=index_key, Body=json.dumps(local).encode(), ContentType='application/json')
    return (f'R2 {bucket}/{prefix}: {len(uploads)} uploaded ({len(pointers)} pointers last), '
            f'{len(deletions)} removed, {len(local) - len(uploads)} unchanged.')


def run():
    """Exit status for the command line: 0 when synced or not configured, 1 on any upload error."""
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:  # R2 is what the site serves: a failed upload must fail the job
        print(f'::error title=R2 publish failed::{type(error).__name__}: {str(error)[:300]}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(run())
