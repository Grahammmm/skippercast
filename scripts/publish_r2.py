#!/usr/bin/env python3
"""Mirror a published feed directory to Cloudflare R2, uploading only changes.

    python scripts/publish_r2.py <local-dir> <prefix>      # e.g. var/live-published conditions
    python scripts/publish_r2.py var/runs runs             # run manifests (upload only, never delete)

Conditions, data and forecasts use immutable SHA-256 objects plus one atomic
current-release pointer. The Worker resolves ordinary /feeds/<prefix>/<path>
URLs through that snapshot; a request-scoped reader pins forecast manifest and
tiles together. Changed objects and the snapshot are read back before the
conditional pointer update. Failed or competing uploads never expose partial
releases. Previous bytes and legacy stable keys remain available for rollback;
this migration does not garbage-collect historical objects. Tiles retain their
separate screened publication contract and legacy change-indexed mirror.

Without CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID this does nothing, so
pipelines keep working before R2 is set up. With credentials, any upload error
exits non-zero: the Worker serves R2 first, so a failed upload means users see
the last committed release and the publishing job must go red. A lost final
acknowledgment can leave a complete new release; retry detects it as unchanged. S3 credentials are derived from
the API token as Cloudflare documents: access key = token id, secret =
SHA-256 of the token value.

Run manifests (`var/runs/<job>/<run_id>.json`, skippercast.runs) go to
`runs/<job>/<run_id>.json` through upload_run_manifests(): each is checked,
uploaded and read back, and nothing under runs/ is ever deleted here (expiry is
an R2 lifecycle rule), because a runner only holds its own run's manifests.
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
CURRENT = '.r2-current.json'
SNAPSHOT_PREFIXES = {'conditions', 'data', 'forecasts'}
RUN_FILE = re.compile(r'^[a-z][a-z0-9-]{1,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.json$')
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
    parser.add_argument('prefix', choices=['conditions', 'data', 'forecasts', 'tiles', 'runs'])
    parser.add_argument('--bucket', default=os.environ.get('R2_BUCKET', 'skippercast-feeds'))
    args = parser.parse_args()
    token, account = os.environ.get('CLOUDFLARE_API_TOKEN'), os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    if not token or not account:
        print(f'R2 not configured (no CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID); skipped {args.prefix}.')
        return
    s3 = client(token, account)
    if args.prefix == 'runs':
        print(upload_run_manifests(s3, args.bucket, args.source))
    else:
        print(sync(s3, args.bucket, args.source, args.prefix))


def run_manifest_keys(root):
    """{local path: R2 key} for every <job>/<run_id>.json under root; rejects anything else."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from skippercast.platform.contracts import read_json
    from skippercast.runs import validate
    root, keys = Path(root), {}
    if not root.is_dir():
        return keys
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if not RUN_FILE.fullmatch(relative):
            raise ValueError(f'Not a run manifest path (<job>/<run_id>.json): {relative}')
        document = validate(read_json(path))
        if document['job'] != relative.split('/')[0]:
            raise ValueError(f'Run manifest job {document["job"]!r} does not match its folder: {relative}')
        keys[path] = f'runs/{relative}'
    return keys


def upload_run_manifests(s3, bucket, root):
    """Upload each run manifest under root to runs/<job>/<file>, then read back its size. Never deletes."""
    keys = run_manifest_keys(root)
    for path, key in keys.items():
        body = path.read_bytes()
        s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType='application/json',
                      CacheControl='no-store')
        stored = s3.head_object(Bucket=bucket, Key=key).get('ContentLength')
        if stored != len(body):
            raise RuntimeError(f'R2 read-back mismatch for {key}: {stored} != {len(body)} bytes')
    return f'R2 {bucket}/runs: {len(keys)} run manifest(s) uploaded and verified.'


def sync_legacy(s3, bucket, source, prefix):
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


def snapshot_bytes(files):
    """Canonical, content-addressed snapshot. Independent of run order or clocks."""
    body = json.dumps({'schema_version': 1, 'files': files}, sort_keys=True, separators=(',', ':')).encode()
    return body, hashlib.sha256(body).hexdigest()


def sync(s3, bucket, source, prefix):
    """Publish one verified immutable snapshot, then CAS its sole mutable pointer.

    Tiles retain their separate screened publication contract. Old stable keys,
    snapshots and blobs are preserved: migration and rollback never delete data.
    """
    if prefix not in SNAPSHOT_PREFIXES:
        return sync_legacy(s3, bucket, source, prefix)
    pointer_key = f'{prefix}/{CURRENT}'
    try:
        prior = s3.get_object(Bucket=bucket, Key=pointer_key)
        expected = prior['ETag']
        prior_body = prior['Body'].read()
        pointer = json.loads(prior_body)
        if pointer.get('schema_version') != 1 or not re.fullmatch('[a-f0-9]{64}', pointer.get('generation', '')):
            raise ValueError('Invalid current R2 release; refusing to overwrite it')
    except s3.exceptions.NoSuchKey:
        expected, pointer = None, None
    local = scan(source)
    if not local:
        raise ValueError('Refusing to publish an empty snapshot')
    if any(any(part.startswith('.r2-') for part in Path(key).parts) for key in local):
        raise ValueError('Snapshot contains reserved R2 publication paths')
    body, generation = snapshot_bytes(local)
    if pointer and pointer['generation'] == generation:
        return f'R2 {bucket}/{prefix}: snapshot {generation} unchanged.'
    # Each unique byte string has one immutable key, even when several paths share it.
    paths = {sha: Path(source) / key for key, sha in local.items()}

    def put_blob(item):
        sha, path = item
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise RuntimeError('Source changed during publication; current release unchanged')
        key = f'{prefix}/.r2-objects/{sha}'
        try:
            stored = s3.head_object(Bucket=bucket, Key=key)
            if stored.get('Metadata', {}).get('sha256') == sha and stored.get('ContentLength') == len(data):
                return 0
            raise RuntimeError(f'Existing immutable object is inconsistent: {key}')
        except s3.exceptions.NoSuchKey:
            pass
        except Exception as error:
            # boto3 HEAD uses ClientError/404 rather than NoSuchKey.
            if getattr(error, 'response', {}).get('ResponseMetadata', {}).get('HTTPStatusCode') != 404:
                raise
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=TYPES.get(path.suffix, 'application/octet-stream'),
                      CacheControl='public, max-age=31536000, immutable', Metadata={'sha256': sha})
        with s3.get_object(Bucket=bucket, Key=key)['Body'] as stream:
            digest_read = hashlib.sha256()
            for block in iter(lambda: stream.read(1 << 20), b''):
                digest_read.update(block)
        if digest_read.hexdigest() != sha:
            raise RuntimeError(f'R2 read-back hash mismatch: {key}; current release unchanged')
        return 1

    with ThreadPoolExecutor(max_workers=16) as pool:
        uploaded = sum(pool.map(put_blob, paths.items()))
    snapshot_key = f'{prefix}/.r2-releases/{generation}.json'
    s3.put_object(Bucket=bucket, Key=snapshot_key, Body=body, ContentType='application/json', CacheControl='no-store')
    if s3.get_object(Bucket=bucket, Key=snapshot_key)['Body'].read() != body:
        raise RuntimeError('R2 snapshot read-back mismatch; current release unchanged')
    current = json.dumps({'schema_version': 1, 'generation': generation}, separators=(',', ':')).encode()
    # R2 supports conditional PutObject. A concurrent publisher must fail, never
    # silently supersede a release committed since this publisher started.
    condition = {'IfMatch': expected} if expected else {'IfNoneMatch': '*'}
    s3.put_object(Bucket=bucket, Key=pointer_key, Body=current, ContentType='application/json',
                  CacheControl='no-store', **condition)
    if s3.get_object(Bucket=bucket, Key=pointer_key)['Body'].read() != current:
        raise RuntimeError('R2 current release changed after commit; recheck before retrying')
    return (f'R2 {bucket}/{prefix}: snapshot {generation}, {uploaded} immutable objects uploaded and verified, '
            f'{len(local)} paths committed atomically; previous data retained.')


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
