#!/usr/bin/env python3
"""Report retained artifact IDs inside and outside an explicit dry-plan write scope."""
import argparse
import json
from pathlib import Path

from skippercast.relief.receipts import check_names


def _owner_key(region, stage_key):
    if not isinstance(region, str) or not isinstance(stage_key, str):
        raise ValueError('expected a region and a stage key')
    stage, dot, scope = stage_key.partition('.')
    check_names(stage, scope if dot else None, region)
    return region, stage_key


def report(plan, owners):
    """Join planner JSON to a list of {artifact_id, region, stage} owner records.

    Use the planner's full stage key (e.g. tiles.public) in both inputs. IDs
    are opaque, unique strings. Unaffected means no matching `rebuild` row in
    this plan, not that the artifact was verified or is safe to remove.
    """
    blocks = plan.get('regions') if isinstance(plan, dict) else None
    if not isinstance(blocks, list):
        raise ValueError('expected a rebuild plan object with a regions list')
    writes = set()
    for block in blocks:
        rows = block['stages']
        if not isinstance(rows, list):
            raise ValueError('expected a stages list')
        for row in rows:
            key = _owner_key(block['region'], row['stage'])
            action = row['action']
            if action not in ('rebuild', 'reuse'):
                raise ValueError(f'{key}: unknown plan action {action!r}')
            if action == 'rebuild':
                writes.add(key)

    result = {'affected': [], 'unaffected': []}
    seen = set()
    if not isinstance(owners, list):
        raise ValueError('expected a list of retained artifact owners')
    for owner in owners:
        artifact_id = owner['artifact_id']
        if not isinstance(artifact_id, str) or not artifact_id.strip() or artifact_id in seen:
            raise ValueError('each retained artifact needs a unique nonempty artifact_id')
        seen.add(artifact_id)
        key = _owner_key(owner['region'], owner['stage'])
        result['affected' if key in writes else 'unaffected'].append(artifact_id)
    return {bucket: sorted(ids) for bucket, ids in result.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Unaffected means outside the supplied plan only; this does not inspect artifact files.'))
    parser.add_argument('--plan', type=Path, required=True, help='saved rebuild_plan.py --json output')
    parser.add_argument('--owners', type=Path, required=True,
                        help='JSON list of {artifact_id, region, stage} owner records')
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        owners = json.loads(args.owners.read_text(encoding='utf-8'))
        result = report(plan, owners)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        parser.error(str(exc))
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
