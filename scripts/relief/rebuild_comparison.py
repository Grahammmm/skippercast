#!/usr/bin/env python3
"""Compare a saved rebuild plan with rebuilding every declared pair, not elapsed cost."""
import argparse
import json
from pathlib import Path

from skippercast.relief.receipts import check_names

if __package__:
    from . import rebuild_blast_radius
else:
    import rebuild_blast_radius


def compare(plan, inventory):
    """Count only explicit reuse as avoided; absent pairs remain unknown."""
    if not isinstance(inventory, list) or not inventory:
        raise ValueError('inventory must be a nonempty list of [region, stage] pairs')
    declared = set()
    for row in inventory:
        if not isinstance(row, list) or len(row) != 2 or not all(isinstance(v, str) for v in row):
            raise ValueError('inventory entries must be [region, stage] string pairs')
        region, key = row
        stage, dot, scope = key.partition('.')
        check_names(stage, scope if dot else None, region)
        pair = (region, key)
        if pair in declared:
            raise ValueError(f'duplicate inventory pair {pair!r}')
        declared.add(pair)

    blast_radius = rebuild_blast_radius.summarize(plan, {region for region, _ in declared})
    reuse = rebuild = 0
    for region, rows in blast_radius['regions'].items():
        for row in rows:
            pair = (region, row['stage'])
            if pair not in declared:
                raise ValueError(f'plan pair outside inventory: {pair!r}')
            if row['action'] == 'reuse':
                reuse += 1
            else:
                rebuild += 1

    total = len(declared)
    return {
        'rebuild_all_pairs': total,
        'planned_reuse': reuse,
        'planned_rebuild': rebuild,
        'unknown': total - reuse - rebuild,
        'fraction_avoided': reuse / total,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'The fraction avoided is planned reuse divided by the full inventory. '
        'Omitted pairs are unknown; planned reuse does not verify artifacts.'))
    parser.add_argument('--plan', required=True, type=Path, help='saved rebuild_plan.py --json file')
    parser.add_argument('--inventory', required=True, type=Path, help=(
        'JSON list of unique [region, stage] pairs; use stage.scope for scoped stages'))
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text(encoding='utf-8'),
                          object_pairs_hook=rebuild_blast_radius._unique_object)
        inventory = json.loads(args.inventory.read_text(encoding='utf-8'))
        report = compare(plan, inventory)
    except (OSError, ValueError, RecursionError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
