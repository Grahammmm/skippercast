#!/usr/bin/env python3
"""Set the R2 feed bucket's lifecycle rules (idempotent; replaces the whole rule set).

    python scripts/r2_lifecycle.py --print           # show the rules, change nothing
    python scripts/r2_lifecycle.py [--bucket NAME]   # apply with wrangler (needs Cloudflare credentials)

The pipelines already prune what they publish: daily history keeps 90 days,
the verification archive 30 days, and publish_r2.py deletes from R2 whatever
left the branch snapshot. These rules are the backstop for objects a sync can
no longer see (a lost `.r2-sync.json` index, a renamed prefix, a region that
stopped publishing) and for run manifests, which nothing else deletes.

Each backstop expires objects some days AFTER the pipeline stops referencing
them, never before: R2 counts age from upload, and a file still listed in the
feed must not disappear from under a reader. `wrangler r2 bucket lifecycle set`
PUTs the complete configuration, so re-running with the same regions is a
no-op and adding a region adds its rules. It also replaces R2's default
multipart-abort rule, which is therefore kept here under its default name.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
WRANGLER = ['npx', '--yes', 'wrangler@4.142.0']
DAY = 86400

RUN_MANIFEST_DAYS = 7          # runs/<job>/<run_id>.json (skippercast.runs)
DAILY_HISTORY_DAYS = 90 + 10   # refresh_regions.py and pipeline/__main__.py keep 90 days
VERIFICATION_DAYS = 30 + 15    # verification_archive.py keeps 30 days of rows
MULTIPART_ABORT_DAYS = 7       # R2's default for every new bucket


def expire(rule_id, prefix, days):
    return {'id': rule_id, 'enabled': True, 'conditions': {'prefix': prefix},
            'deleteObjectsTransition': {'condition': {'type': 'Age', 'maxAge': days * DAY}}}


def region_ids(root=ROOT):
    return sorted(path.parent.name for path in (root / 'regions').glob('*/region.json'))


def rules(regions):
    """The complete lifecycle configuration for the feed bucket."""
    result = [
        {'id': 'Default Multipart Abort Rule', 'enabled': True, 'conditions': {},
         'abortMultipartUploadsTransition': {'condition': {'type': 'Age', 'maxAge': MULTIPART_ABORT_DAYS * DAY}}},
        expire('run-manifests', 'runs/', RUN_MANIFEST_DAYS),
        expire('data-history', 'data/history/', DAILY_HISTORY_DAYS),
    ]
    for region in regions:
        result.append(expire(f'data-history-{region}', f'data/regions/{region}/history/', DAILY_HISTORY_DAYS))
        result.append(expire(f'verification-archive-{region}',
                             f'conditions/regions/{region}/verification-archive/', VERIFICATION_DAYS))
    return {'rules': result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bucket', default=os.environ.get('R2_BUCKET', 'skippercast-feeds'))
    parser.add_argument('--print', action='store_true', help='print the configuration and exit')
    args = parser.parse_args(argv)
    config = rules(region_ids())
    if args.print:
        print(json.dumps(config, indent=2))
        return 0
    if not os.environ.get('CLOUDFLARE_API_TOKEN') or not os.environ.get('CLOUDFLARE_ACCOUNT_ID'):
        print('R2 not configured (no CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID); lifecycle rules not applied.')
        return 0
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
        json.dump(config, handle)
    try:
        # --force skips the interactive "overwrite all rules?" confirmation.
        result = subprocess.run(WRANGLER + ['r2', 'bucket', 'lifecycle', 'set', args.bucket,
                                            '--file', handle.name, '--force'])
    finally:
        os.unlink(handle.name)
    if result.returncode:
        print(f'::error title=R2 lifecycle::could not set lifecycle rules on {args.bucket}')
        return 1
    print(f'R2 {args.bucket}: {len(config["rules"])} lifecycle rules set.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
