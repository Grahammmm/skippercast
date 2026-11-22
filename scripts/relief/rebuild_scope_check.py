#!/usr/bin/env python3
"""Compare a saved rebuild_plan.py --json report with a synthetic review ceiling."""
import argparse
import json
from pathlib import Path

from skippercast.relief.receipts import REGION_ID, SCOPE_NAME, STAGE_NAME

if __package__:
    from .rebuild_blast_radius import _unique_object, summarize
    from .rebuild_plan import HEAVY
    from .run_region import SCOPED_STAGES, STAGES
else:
    from rebuild_blast_radius import _unique_object, summarize
    from rebuild_plan import HEAVY
    from run_region import SCOPED_STAGES, STAGES

# The planner always emits the runner's current keys, even without receipts.
# Historical receipt keys can add rows, but cannot replace these required rows.
REQUIRED_STAGES = {f'{stage}.public' if stage in SCOPED_STAGES else stage for stage in STAGES}


def _allowed_pairs(ceiling):
    if not isinstance(ceiling, dict):
        raise ValueError('expected an allowed region-to-stage object')
    pairs = set()
    for region, keys in ceiling.items():
        if not REGION_ID.fullmatch(region) or not isinstance(keys, list):
            raise ValueError(f'invalid allowed region or stage list: {region!r}')
        for key in keys:
            stage, dot, scope = key.partition('.') if isinstance(key, str) else ('', '', '')
            if not STAGE_NAME.fullmatch(stage) or (dot and not SCOPE_NAME.fullmatch(scope)):
                raise ValueError(f'{region}: invalid allowed stage key {key!r}')
            pairs.add((region, key))
    return pairs


def _check(plan, ceiling, expected):
    allowed = _allowed_pairs(ceiling)
    expected_set = set(expected)
    if len(expected_set) != len(expected):
        raise ValueError('duplicate expected region')
    blocks = plan.get('regions') if isinstance(plan, dict) else None
    if not isinstance(blocks, list):
        raise ValueError('expected a rebuild plan object with a regions list')
    observed = {block['region'] for block in blocks
                if isinstance(block, dict) and isinstance(block.get('region'), str)}
    # Validate observed extras too, so their proposed rebuilds are not hidden by a roster mismatch.
    regions = summarize(plan, sorted(expected_set | observed))['regions']
    rebuilds = [(region, row) for region, rows in regions.items() for row in rows
                if row['action'] == 'rebuild']
    counts = {'regions': len(regions),
              'rebuild_heavy': sum(row['stage'].partition('.')[0] in HEAVY for _, row in rebuilds)}
    summary = plan.get('summary')
    summary_matches = isinstance(summary, dict) and all(
        type(summary.get(key)) is int and summary[key] == count for key, count in counts.items())
    missing_stages = {}
    for region, rows in regions.items():
        missing = REQUIRED_STAGES - {row['stage'] for row in rows}
        if missing:
            missing_stages[region] = sorted(missing)
    outside = [{'region': region, **row} for region, row in rebuilds
               if (region, row['stage']) not in allowed]
    missing_regions = sorted(set(expected) - regions.keys())
    unexpected_regions = sorted(observed - set(expected))
    return {
        'within_ceiling': not (outside or missing_regions or unexpected_regions or missing_stages
                               or not summary_matches),
        'outside_ceiling': outside,
        'missing_regions': missing_regions,
        'unexpected_regions': unexpected_regions,
        'missing_stages': missing_stages,
        'summary_matches': summary_matches,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Exit 0: complete and within ceiling; 1: outside ceiling or roster/count mismatch; '
        '2: malformed input. This report does not authorize or run any rebuild.'))
    parser.add_argument('--plan', required=True, type=Path, help='saved rebuild_plan.py --json output')
    parser.add_argument('--allow', required=True, type=Path,
                        help='ceiling JSON, e.g. {"sample-bay": ["tiles.public"]}; {} allows no rebuilds')
    parser.add_argument('regions', metavar='REGION', nargs='+',
                        help='independent roster of regions requested from the planner')
    args = parser.parse_args(argv)
    try:
        plan, ceiling = (json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
                         for path in (args.plan, args.allow))
        report = _check(plan, ceiling, args.regions)
    except (OSError, ValueError, RecursionError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return 0 if report['within_ceiling'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
