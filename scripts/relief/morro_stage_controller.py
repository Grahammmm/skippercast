#!/usr/bin/env python3
"""Controller steps for the manual Morro stage preview (.github/workflows/stage-preview.yml).

Runs from the workflow's own reviewed revision, never from the candidate checkout, and
never touches production: no production Worker, bucket, route, schedule or secret.

  scope         the candidate differs from the reviewed controller commit only in
                Morro's data files (DATA_PATHS), so the code built is exactly reviewed code
  place-config  put the planned stage Wrangler config into the built candidate tree,
                after re-checking its digest, its isolation and the preview origin
  copy          copy the candidate pointer's published release objects into the
                separate stage bucket (create-only, full read-back), never production

The candidate's data is inert here: nothing in this file writes the repository,
the production bucket or the production Worker. A hosted run needs G's explicit
preview approval and the stage-only credentials; see the workflow header.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

CONTROLLER = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(CONTROLLER / 'src'), str(CONTROLLER)]

from scripts.relief import morro_stage_preview as preview  # noqa: E402

PLAN_SCHEMA = 'sc-morro-stage-preview/1'
# The Morro data a candidate may change: the relief pointer, the contour import and the
# two published contour files the browser loads (scripts/build_depth_contours.py output).
DATA_PATHS = frozenset({preview.POINTER, preview.CONTOURS,
                        f'dist/regions/{preview.REGION}/depth-contours.geojson',
                        f'dist/regions/{preview.REGION}/depth-contours-overview.geojson'})
CONFIG_NAME = 'wrangler.stage.json'
_SHA = re.compile(r'[0-9a-f]{40}')
_SHA256 = re.compile(r'[0-9a-f]{64}')
_SUBDOMAIN = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')


class HoldError(ValueError):
    """The preview is held; the message is safe to log (no URL bodies, tokens or paths)."""


def _git(tree: Path, *args: str) -> bytes:
    try:
        return subprocess.run(['git', '-C', str(tree), *args], check=True, capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        raise HoldError('git could not read the candidate checkout') from None


def scope(tree: Path, base: str, sha: str) -> list[str]:
    """Paths the candidate changes against the reviewed base; only Morro's data files may differ."""
    if not _SHA.fullmatch(base) or not _SHA.fullmatch(sha):
        raise HoldError('base and candidate must be full lowercase commit SHAs')
    raw = _git(tree, 'diff', '--name-only', '-z', '--no-renames', '--no-ext-diff', base, sha, '--')
    changed = sorted(path.decode(errors='replace') for path in raw.split(b'\0') if path)
    outside = [path for path in changed if path not in DATA_PATHS]
    if outside:
        raise HoldError('candidate changes files outside the Morro data: ' + ', '.join(outside[:5]))
    for path in changed:
        listing = _git(tree, 'ls-tree', '-z', sha, '--', path)
        if listing and not listing.startswith(b'100644 blob '):
            raise HoldError(f'candidate {path} is not a regular file')
    return changed


def check_origin(origin: str, worker: str) -> str:
    """The preview Worker's own workers.dev origin; anything else (a custom domain, production) is held."""
    match = re.fullmatch(r'https://([a-z0-9-]+)\.([a-z0-9-]+)\.workers\.dev', origin or '')
    if not match or match.group(1) != worker or not _SUBDOMAIN.fullmatch(match.group(2)):
        raise HoldError('preview origin must be https://<stage worker>.<account>.workers.dev')
    return origin


def load_plan(plan_dir: Path) -> tuple[dict, bytes]:
    """(plan receipt, stage config bytes) as written by morro_stage_preview.py plan; digest re-checked."""
    try:
        receipt = json.loads((plan_dir / 'plan.json').read_bytes())
        config = (plan_dir / CONFIG_NAME).read_bytes()
    except (OSError, ValueError):
        raise HoldError('stage plan is missing or not JSON') from None
    if (not isinstance(receipt, dict) or receipt.get('schema') != PLAN_SCHEMA or receipt.get('region') != preview.REGION
            or not isinstance(receipt.get('commit'), str) or not _SHA.fullmatch(receipt['commit'])
            or not isinstance(receipt.get('pointer_sha256'), str) or not _SHA256.fullmatch(receipt['pointer_sha256'])):
        raise HoldError('stage plan is not a Morro stage preview plan')
    if hashlib.sha256(config).hexdigest() != receipt.get('config_sha256'):
        raise HoldError('stage config differs from the plan')
    try:
        doc = json.loads(config)
        preview.refuse_production(doc)
    except (ValueError, preview.PreviewError) as error:
        raise HoldError(f'stage config is not isolated: {error}') from None
    if doc.get('name') != receipt.get('worker') or doc['r2_buckets'] != [{'binding': 'FEEDS', 'bucket_name': receipt.get('bucket')}]:
        raise HoldError('stage config does not name the planned Worker and bucket')
    return receipt, config


def place_config(plan_dir: Path, tree: Path, origin: str) -> Path:
    """Write the checked stage config into the candidate tree for Wrangler; refuse to overwrite anything."""
    receipt, config = load_plan(plan_dir)
    check_origin(origin, receipt['worker'])
    head = _git(tree, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    if head != receipt['commit']:
        raise HoldError('candidate checkout is not the planned commit')
    dest = tree / CONFIG_NAME
    try:
        with dest.open('xb') as out:
            out.write(config)
    except FileExistsError:
        raise HoldError(f'{CONFIG_NAME} already exists in the candidate tree') from None
    return dest


class StageR2:
    """Create-only R2 access bound to one *-stage bucket; the production feeds bucket is unreachable.

    Same contract as stage_transport.R2 (full GET, PutObject If-None-Match: *, never HEAD), with
    the bucket fixed at construction instead of the production constant.
    """

    def __init__(self, client, bucket: str):
        if bucket in preview.PRODUCTION_BUCKETS or not bucket.endswith('-stage') or not preview._NAME.fullmatch(bucket):
            raise HoldError('stage copy may only write a *-stage bucket')
        self.client = client
        self.bucket = bucket

    @classmethod
    def connect(cls, token: str, account: str, *, bucket: str):
        from skippercast.relief import stage_transport as stage

        # Reuse the reviewed token check and client settings, then bind the stage bucket.
        return cls(stage.R2.connect(token, account).client, bucket)

    @contextmanager
    def get(self, key):
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if (error.response.get('Error', {}).get('Code') != 'NoSuchKey'
                    or error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 404):
                raise
            yield None
            return
        with closing(response['Body']) as stream:
            if response['ResponseMetadata']['HTTPStatusCode'] != 200 or response.get('ContentRange') is not None:
                raise HoldError('stage R2 did not return a full GET')
            yield stream

    def create(self, key, body, size):
        from botocore.exceptions import ClientError

        brotli = key.endswith('.geojson.br')
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentLength=size, IfNoneMatch='*',
                                   **({'ContentEncoding': 'br'} if brotli else {}),
                                   ContentType='application/geo+json' if brotli else
                                   'application/json' if key.endswith('.json') else 'application/octet-stream',
                                   CacheControl='public, max-age=31536000, immutable')
        except ClientError as error:
            if (error.response.get('Error', {}).get('Code') != 'PreconditionFailed'
                    or error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 412):
                raise
            # A racing writer won; copy_release still reads the object back in full.


def candidate_pointer(tree: Path, receipt: dict) -> dict:
    """The planned commit's Morro pointer, checked against the plan digest and the controller's policy."""
    from skippercast.relief import package

    data = _git(tree, 'cat-file', 'blob', f"{receipt['commit']}:{preview.POINTER}")
    if hashlib.sha256(data).hexdigest() != receipt['pointer_sha256']:
        raise HoldError('candidate pointer differs from the planned pointer')
    pointer = package.decode_document(data)
    if pointer.get('region') != preview.REGION:
        raise HoldError('candidate pointer is not for Morro Bay')
    # The controller's reviewed schema and source policy, never the candidate's copies.
    schema = package.pointer_schema()
    registry = package.decode_document((CONTROLLER / 'catalog/sources.json').read_bytes())
    package.validate_schema(pointer, schema)
    package.validate_metadata(pointer, schema, registry)
    return pointer


def copy(plan_dir: Path, tree: Path, env, *, github=None, r2=None) -> int:
    """Copy the pointer's release objects into the planned stage bucket; returns the object count."""
    from skippercast.relief import stage_transport as stage

    receipt, _ = load_plan(plan_dir)
    pointer = candidate_pointer(tree, receipt)
    if 'survey_detail' in pointer:
        from skippercast.relief import survey_delivery
        try:
            survey_delivery.decoder()
        except ValueError as error:
            raise HoldError(str(error)) from None
    if github is None:
        github = stage.GitHubRelease(env.get('STAGE_GITHUB_READ_TOKEN', ''))
    if r2 is None:
        r2 = StageR2.connect(env.get('STAGE_R2_PUBLISH_TOKEN', ''), env.get('STAGE_CLOUDFLARE_ACCOUNT_ID', ''),
                             bucket=receipt['bucket'])
    if getattr(r2, 'bucket', None) != receipt['bucket']:
        raise HoldError('stage copy is not bound to the planned bucket')
    return stage.copy_release(pointer, github, r2, allow_create=True, recheck=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Controller steps for the manual Morro stage preview.')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scope', help='require the candidate to differ from the reviewed base only in Morro data')
    s.add_argument('--tree', type=Path, required=True)
    s.add_argument('--base', required=True, help='the reviewed controller commit (github.workflow_sha)')
    s.add_argument('--sha', required=True, help='the candidate commit')
    for name, text in (('place-config', 'write the checked stage config into the candidate tree'),
                       ('copy', 'copy the release objects into the stage bucket')):
        p = sub.add_parser(name, help=text)
        p.add_argument('--plan-dir', type=Path, required=True)
        p.add_argument('--tree', type=Path, required=True)
        if name == 'place-config':
            p.add_argument('--origin', required=True, help='the preview Worker workers.dev origin')
    args = parser.parse_args(argv)
    try:
        if args.command == 'scope':
            changed = scope(args.tree, args.base, args.sha)
            print('SCOPE data-only: ' + (', '.join(changed) or 'no change from the reviewed base'))
        elif args.command == 'place-config':
            print(f'CONFIG {place_config(args.plan_dir, args.tree, args.origin).name}')
        else:
            print(f'COPIED {copy(args.plan_dir, args.tree, os.environ)} objects to the stage bucket')
        return 0
    except (HoldError, preview.PreviewError) as error:
        print(f'::error::Morro stage preview held: {error}', file=sys.stderr)
        return 2
    except Exception as error:
        # SDK and transport errors may carry headers or signed URLs; never log their bodies.
        print(f'::error::Morro stage preview held ({type(error).__name__}); nothing promoted.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
