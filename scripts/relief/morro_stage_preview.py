#!/usr/bin/env python3
"""Plan an isolated, stage-only Morro preview and check what it serves. Offline: never calls Cloudflare.

`plan` derives a Wrangler config for a separate preview Worker from the reviewed
production config and an exact candidate commit. The preview keeps the map and
feeds but has nothing that can reach production: no custom domains or routes, no
cron trigger, no queues, no D1 database, no production bucket, and private routes
closed. It also binds the candidate commit and the Morro relief pointer it
carries, so a later deploy of a different commit or pointer cannot be passed off
as this preview.

`verify` compares what a preview origin served (its /deploy.json receipt and the
pointer bytes) with that plan. Unlike the production check, an ancestor commit
is not enough: the preview must serve exactly the planned commit and pointer.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True

REGION = 'morro-bay'
# The four contour-bearing Central Coast regions share ONE separate preview Worker and bucket of their
# own (.github/workflows/central-stage-preview.yml), one region per run; Morro keeps its own. This
# preview pins and serves a detail + overview contour pair, so the two terrain-only Central regions
# (monterey-point-sur, santa-cruz-monterey-bay: no contours to pin) are not stage regions here and are
# refused everywhere a region is checked, until a terrain-only stage path is built for them.
CENTRAL_REGIONS = ('big-sur-coast', 'cambria-san-simeon', 'south-big-sur-san-simeon', 'point-arguello-conception')
REGIONS = (REGION, *CENTRAL_REGIONS)
# Each region may be previewed only on its own group's Worker and bucket, so a Central run can never
# overwrite the Morro preview (or the other way round).
STAGE_TARGETS = {REGION: ('skippercast-morro-stage', 'skippercast-feeds-stage'),
                 **{region: ('skippercast-central-stage', 'skippercast-feeds-central-stage')
                    for region in CENTRAL_REGIONS}}


def pointer_path(region: str) -> str:
    return f'catalog/relief/{region}.json'


def contours_path(region: str) -> str:
    return f'catalog/depth-contours/{region}.geojson'


def label(region: str) -> str:
    """How errors name the region (Morro keeps its historical wording)."""
    return 'Morro Bay' if region == REGION else region


def check_region(region: object) -> str:
    if not isinstance(region, str) or region not in REGIONS:
        raise PreviewError('region is not one the stage preview may carry')
    return region


POINTER = pointer_path(REGION)
CONTOURS = contours_path(REGION)
PRODUCTION_WORKER = 'skippercast'
# Every bucket the production config or the deploy can bind or write.
PRODUCTION_BUCKETS = frozenset({'skippercast-feeds', 'skippercast-backups', 'skippercast-advisor-media'})
# Vars the preview may keep. Anything else (feature switches, limits on spend) is dropped.
PREVIEW_VARS = ('COST_CEILING_R2_READS_PER_DAY',)
# server/auth.ts: any IDENTITY_PROVIDER other than `skippercast` closes every private route.
CLOSED_IDENTITY = 'none'
# The only top-level keys a preview config may carry. Everything else is dropped by
# `stage_config` and refused by `refuse_production`, so a resource binding the review
# never considered (KV, Hyperdrive, Vectorize, AI, ratelimits, ...) cannot ride along.
# `r2_buckets` and `vars` are rebuilt from scratch and are checked further below.
SAFE_KEYS = frozenset({'$schema', 'name', 'main', 'compatibility_date', 'compatibility_flags',
                       'workers_dev', 'assets', 'r2_buckets', 'vars', 'observability'})
# Git-ignored paths a candidate checkout may still hold: dependencies and build output only.
# Any other ignored file (a `.git/info/exclude` or global-ignore entry, a stray ignored
# source file) could be built in while the receipt names only the commit, so it is refused.
GENERATED_PREFIXES = ('dist/client/', 'dist/server/', '.wrangler/', '.venv/', '.pytest_cache/', '.ruff_cache/',
                      'test-results/', 'playwright-report/')
GENERATED_DIRS = frozenset({'node_modules', '__pycache__'})
_SHA = re.compile(r'[0-9a-f]{40}')
_SHA256 = re.compile(r'[0-9a-f]{64}')
_NAME = re.compile(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]')


class PreviewError(ValueError):
    """A preview that could reach production or does not match its plan."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_wrangler(text: str) -> dict:
    """Parse wrangler.jsonc. Only whole-line comments are allowed; anything else fails closed."""
    body = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('//'))
    try:
        config = json.loads(body)
    except (ValueError, RecursionError):
        raise PreviewError('wrangler config is not JSON with whole-line comments') from None
    if not isinstance(config, dict):
        raise PreviewError('wrangler config must be a JSON object')
    return config


def stage_config(base: dict, *, worker: str, bucket: str) -> dict:
    """A copy of `base` for an isolated preview Worker serving feeds from `bucket`."""
    if not _NAME.fullmatch(worker) or not worker.endswith('-stage'):
        raise PreviewError('preview Worker name must be a Worker name ending in -stage')
    if not _NAME.fullmatch(bucket) or not bucket.endswith('-stage'):
        raise PreviewError('preview bucket must be an R2 bucket name ending in -stage')
    config = {key: copy.deepcopy(value) for key, value in base.items() if key in SAFE_KEYS}
    config['name'] = worker
    config['workers_dev'] = True
    feeds = [entry for entry in base.get('r2_buckets', []) if isinstance(entry, dict) and entry.get('binding') == 'FEEDS']
    if len(feeds) != 1:
        raise PreviewError('base config must bind exactly one FEEDS bucket')
    config['r2_buckets'] = [{'binding': 'FEEDS', 'bucket_name': bucket}]
    vars_ = base.get('vars', {})
    config['vars'] = {name: vars_[name] for name in PREVIEW_VARS if name in vars_}
    config['vars']['IDENTITY_PROVIDER'] = CLOSED_IDENTITY
    refuse_production(config)
    return config


def refuse_production(config: dict) -> None:
    """Raise unless `config` is isolated from every production name, route, schedule and store."""
    name = config.get('name')
    if not isinstance(name, str) or name == PRODUCTION_WORKER or not name.endswith('-stage'):
        raise PreviewError('preview would deploy the production Worker')
    extra = sorted(str(key) for key in config if key not in SAFE_KEYS)
    if extra:
        raise PreviewError('preview config keeps bindings or settings outside the safe set: ' + ', '.join(extra))
    if config.get('workers_dev') is not True:
        raise PreviewError('preview must be served only on its own workers.dev address')
    buckets = config.get('r2_buckets')
    if not isinstance(buckets, list) or not buckets:
        raise PreviewError('preview must bind its own feeds bucket')
    for entry in buckets:
        if not isinstance(entry, dict):
            raise PreviewError('malformed R2 binding')
        for field in ('bucket_name', 'preview_bucket_name'):
            value = entry.get(field)
            if value is not None and (value in PRODUCTION_BUCKETS or not str(value).endswith('-stage')):
                raise PreviewError('preview binds a production bucket')
    vars_ = config.get('vars', {})
    if not isinstance(vars_, dict) or vars_.get('IDENTITY_PROVIDER') != CLOSED_IDENTITY:
        raise PreviewError('preview must close private routes')


def _git(tree: Path, *args: str) -> bytes:
    return subprocess.run(['git', '-C', str(tree), *args], check=True, capture_output=True, timeout=30).stdout


def _is_generated(path: str) -> bool:
    """True for a git-ignored path that is only a dependency or build output."""
    if path.startswith(GENERATED_PREFIXES):
        return True
    return any(part in GENERATED_DIRS for part in path.rstrip('/').split('/')[:-1]) or \
        (path.endswith('/') and path.rstrip('/').split('/')[-1] in GENERATED_DIRS)


def _unexpected_files(tree: Path) -> list[str]:
    """Ignored-but-not-generated or index-hidden files in the checkout."""
    out = []
    # `status` lists ignored paths only on request; `matching` reports each at the ignore rule's own
    # directory (dist/client/, node_modules/), not collapsed to an enclosing all-ignored parent.
    for raw in _git(tree, 'status', '--porcelain', '-z', '--ignored=matching', '--untracked-files=all').split(b'\0'):
        if raw[:3] == b'!! ':
            path = raw[3:].decode(errors='replace')
            if not _is_generated(path):
                out.append(path)
    # A tracked file marked assume-unchanged or skip-worktree hides edits from `status`.
    for raw in _git(tree, 'ls-files', '-z', '-v').split(b'\0'):
        if raw and raw[:1] != b'H':
            out.append(raw[2:].decode(errors='replace'))
    return out


def candidate(tree: Path, sha: str, region: str = REGION) -> dict:
    """The exact clean candidate commit and the region data it carries."""
    check_region(region)
    if not _SHA.fullmatch(sha):
        raise PreviewError('candidate must be a full lowercase commit SHA')
    try:
        head = _git(tree, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
        # Untracked files that are not git-ignored, ignored non-generated files, and index-hidden edits
        # could be built in while the receipt names only the commit; see `_unexpected_files`.
        dirty = _git(tree, 'status', '--porcelain', '--untracked-files=all')
        hidden = _unexpected_files(tree)
    except (OSError, subprocess.SubprocessError):
        raise PreviewError('candidate checkout could not be read') from None
    if head != sha:
        raise PreviewError('checkout is not the candidate commit')
    if dirty:
        raise PreviewError('candidate checkout has uncommitted or untracked files')
    if hidden:
        raise PreviewError('candidate checkout has ignored or hidden files outside build output: ' + ', '.join(sorted(hidden)[:5]))
    pointer_name, contours_name = pointer_path(region), contours_path(region)
    found = {}
    for path in (pointer_name, contours_name):
        try:
            found[path] = _git(tree, 'cat-file', 'blob', f'{sha}:{path}')
        except subprocess.SubprocessError:
            found[path] = None
    pointer = found[pointer_name]
    if pointer is None:
        raise PreviewError(f'candidate has no {pointer_name}')
    try:
        doc = json.loads(pointer)
    except (ValueError, RecursionError):
        raise PreviewError('candidate relief pointer is not JSON') from None
    if not isinstance(doc, dict) or doc.get('region') != region:
        raise PreviewError(f'candidate relief pointer is not for {label(region)}')
    return {'commit': sha, 'pointer_sha256': _sha256(pointer),
            'contours_sha256': _sha256(found[contours_name]) if found[contours_name] is not None else None}


def plan(tree: Path, sha: str, base_text: str, *, worker: str, bucket: str, pointer_sha256: str,
         region: str = REGION) -> tuple[dict, dict]:
    """(stage config, plan receipt) for the candidate; the pointer must be the reviewed one."""
    check_region(region)
    if (worker, bucket) != STAGE_TARGETS[region]:
        raise PreviewError(f'{label(region)} may be previewed only on its own stage Worker and bucket')
    if not _SHA256.fullmatch(pointer_sha256):
        raise PreviewError('reviewed pointer digest must be 64 lowercase hex digits')
    found = candidate(tree, sha, region)
    if found['pointer_sha256'] != pointer_sha256:
        raise PreviewError('candidate relief pointer is not the reviewed pointer')
    config = stage_config(read_wrangler(base_text), worker=worker, bucket=bucket)
    encoded = (json.dumps(config, indent=2, sort_keys=True) + '\n').encode()
    receipt = {'schema': 'sc-morro-stage-preview/1', 'region': region, **found,
               'worker': worker, 'bucket': bucket, 'config_sha256': _sha256(encoded),
               'scope': 'stage-only plan; not deployed, not hosted evidence'}
    return config, receipt


def read_plan(data: bytes) -> dict:
    """A saved plan receipt; anything damaged or not written by `plan` is held, never trusted."""
    try:
        receipt = json.loads(data)
    except (ValueError, RecursionError):  # RecursionError: nesting deeper than the decoder allows
        raise PreviewError('plan is not JSON') from None
    if not isinstance(receipt, dict) or receipt.get('schema') != 'sc-morro-stage-preview/1' \
            or receipt.get('region') not in REGIONS:
        raise PreviewError('plan is not a Morro stage preview plan')
    if STAGE_TARGETS[receipt['region']] != (receipt.get('worker'), receipt.get('bucket')):
        raise PreviewError('plan does not name its region\'s own stage Worker and bucket')
    if not isinstance(receipt.get('commit'), str) or not _SHA.fullmatch(receipt['commit']):
        raise PreviewError('plan commit must be a full lowercase commit SHA')
    if not isinstance(receipt.get('pointer_sha256'), str) or not _SHA256.fullmatch(receipt['pointer_sha256']):
        raise PreviewError('plan pointer digest must be 64 lowercase hex digits')
    return receipt


def verify(receipt: dict, deploy_doc: object, served_pointer: bytes | None) -> list[dict]:
    """Checks for one preview origin's served commit and pointer; exact matches only."""
    commit = deploy_doc.get('commit') if isinstance(deploy_doc, dict) else None
    if not isinstance(commit, str) or not _SHA.fullmatch(commit):
        deploy = {'check': 'deploy', 'status': 'FAIL', 'reason': 'unreadable'}
    elif commit != receipt['commit']:
        deploy = {'check': 'deploy', 'status': 'FAIL', 'reason': 'other-commit'}
    else:
        deploy = {'check': 'deploy', 'status': 'PASS', 'reason': 'exact'}
    if served_pointer is None:
        pointer = {'check': 'pointer', 'status': 'FAIL', 'reason': 'missing'}
    elif _sha256(served_pointer) != receipt['pointer_sha256']:
        pointer = {'check': 'pointer', 'status': 'FAIL', 'reason': 'differs'}
    else:
        pointer = {'check': 'pointer', 'status': 'PASS', 'reason': 'exact'}
    return [deploy, pointer]


def _write(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + '.tmp')
    temp.write_bytes(data)
    temp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Plan or verify an isolated, stage-only Morro preview.')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan', help='write the stage-only Wrangler config and its plan receipt')
    p.add_argument('--tree', type=Path, required=True, help='clean checkout of the candidate commit')
    p.add_argument('--sha', required=True, help='exact candidate commit')
    p.add_argument('--pointer-sha256', required=True, help='SHA-256 of the reviewed region pointer bytes')
    p.add_argument('--wrangler', type=Path, required=True, help='reviewed production wrangler.jsonc')
    p.add_argument('--region', default=REGION, choices=REGIONS)
    p.add_argument('--worker', default='skippercast-morro-stage')
    p.add_argument('--bucket', default='skippercast-feeds-stage')
    p.add_argument('--out', type=Path, required=True, help='directory for wrangler.stage.json and plan.json')
    v = sub.add_parser('verify', help='check a preview origin\'s served receipt and pointer against a plan')
    v.add_argument('--plan', type=Path, required=True)
    v.add_argument('--deploy-json', type=Path, required=True, help='saved /deploy.json from the preview origin')
    v.add_argument('--pointer', type=Path, help='saved pointer bytes from the preview origin (omit if missing)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            config, receipt = plan(args.tree, args.sha, args.wrangler.read_text(encoding='utf-8'),
                                   worker=args.worker, bucket=args.bucket, pointer_sha256=args.pointer_sha256,
                                   region=args.region)
            args.out.mkdir(parents=True, exist_ok=True)
            _write(args.out / 'wrangler.stage.json', (json.dumps(config, indent=2, sort_keys=True) + '\n').encode())
            _write(args.out / 'plan.json', (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode())
            print(f"PLAN {receipt['worker']} commit={receipt['commit']} pointer={receipt['pointer_sha256']}")
            return 0
        receipt = read_plan(args.plan.read_bytes())
        try:
            deploy_doc = json.loads(args.deploy_json.read_bytes())
        except (ValueError, RecursionError):
            deploy_doc = None
        served = args.pointer.read_bytes() if args.pointer and args.pointer.exists() else None
        checks = verify(receipt, deploy_doc, served)
        verdict = 'PASS' if all(check['status'] == 'PASS' for check in checks) else 'FAIL'
        print(json.dumps({'verdict': verdict, 'commit': receipt['commit'], 'checks': checks}, sort_keys=True))
        return 0 if verdict == 'PASS' else 1
    except (PreviewError, OSError, KeyError) as error:
        print(f'Morro stage preview held: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
