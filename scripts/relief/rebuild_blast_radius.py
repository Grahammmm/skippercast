#!/usr/bin/env python3
"""Summarize saved rebuild_plan.py --json output; reuse is not artifact verification."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from skippercast.relief.receipts import REGION_ID, SCOPE_NAME, STAGE_NAME


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'duplicate JSON field: {key!r}')
        obj[key] = value
    return obj


def _stage_rows(block, region):
    rows = block.get('stages')
    if not isinstance(rows, list) or not rows:
        raise ValueError(f'{region}: expected a nonempty stages list')
    seen = set()
    for index, row in enumerate(rows):
        key = row.get('stage') if isinstance(row, dict) else None
        if not isinstance(key, str):
            raise ValueError(f'{region}: stages[{index}] needs a stage key')
        stage, dot, scope = key.partition('.')
        if not STAGE_NAME.fullmatch(stage) or (dot and not SCOPE_NAME.fullmatch(scope)):
            raise ValueError(f'{region}: invalid stage key {key!r}')
        if key in seen:
            raise ValueError(f'{region}: duplicate stage {key!r}')
        seen.add(key)
        action, reasons = row.get('action'), row.get('reasons')
        if (action not in ('rebuild', 'reuse') or not isinstance(reasons, list)
                or not all(isinstance(reason, str) and reason.strip() for reason in reasons)
                or (action == 'rebuild') != bool(reasons)):
            raise ValueError(f'{region}: {key}: invalid action or reasons')
        yield {'stage': key, 'action': action, 'reasons': reasons}


def summarize(plan, expected):
    """Project plan decisions, marking absent expected regions without inventing rows."""
    roster = set()
    for region in expected:
        if not REGION_ID.fullmatch(region):
            raise ValueError(f'invalid expected region {region!r}')
        if region in roster:
            raise ValueError(f'duplicate expected region {region!r}')
        roster.add(region)

    blocks = plan.get('regions') if isinstance(plan, dict) else None
    if not isinstance(blocks, list):
        raise ValueError('expected a rebuild plan object with a regions list')
    regions = {}
    affected = defaultdict(list)
    for block in blocks:
        region = block.get('region') if isinstance(block, dict) else None
        if not isinstance(region, str) or region not in roster:
            raise ValueError(f'unexpected or invalid plan region {region!r}')
        if region in regions:
            raise ValueError(f'duplicate plan region {region!r}')
        rows = regions[region] = list(_stage_rows(block, region))
        for row in rows:
            if row['action'] == 'rebuild':
                affected[row['stage']].append(region)
    return {
        'regions': regions,
        'affected_regions_by_stage': {key: sorted(names) for key, names in affected.items()},
        'incomplete_regions': sorted(roster - regions.keys()),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Missing expected regions are listed in incomplete_regions. Malformed plans, '
        'duplicates, and unexpected regions are rejected without a partial report.'))
    parser.add_argument('--plan', required=True, type=Path, help='saved planner JSON file')
    parser.add_argument('regions', nargs='+', metavar='REGION', help='explicit expected region roster')
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        report = summarize(plan, args.regions)
    except (OSError, ValueError, RecursionError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
