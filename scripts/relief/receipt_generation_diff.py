#!/usr/bin/env python3
"""Explain generation changes between two saved stage receipts, offline.

This checks identity evidence only, not whether outputs still exist or the
upstream receipts are current. Recorded paths are never followed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from skippercast.relief import receipts


def _digest(value):
    return isinstance(value, str) and receipts.HEX64.fullmatch(value) is not None


def _target(doc):
    return {key: doc.get(key) for key in ('region', 'stage', 'scope')}


def _read_identity(path):
    try:
        doc = receipts.read_receipt(path)
    except (OSError, ValueError, RecursionError):
        return None, {'error': 'cannot read a JSON receipt object'}
    if doc is None:
        return None, {'error': 'receipt not found'}

    evidence = {}
    try:
        region, stage, scope = (doc.get(key) for key in ('region', 'stage', 'scope'))
        if not isinstance(region, str) or not isinstance(stage, str):
            raise receipts.ReceiptError('region or stage malformed')
        receipts.check_names(stage, scope, region)
        if problem := receipts.validate_receipt(doc, region, stage, scope):
            raise receipts.ReceiptError(problem)
        inputs, code, params = (doc.get(key) for key in ('inputs', 'code', 'params'))
        if not isinstance(inputs, list) or not all(
            isinstance(row, dict) and isinstance(row.get('role'), str) and _digest(row.get('sha256'))
            for row in inputs
        ):
            raise receipts.ReceiptError('input roles or hashes malformed')
        if not isinstance(code, dict) or not _digest(code.get('stage_digest')):
            raise receipts.ReceiptError('stage digest malformed')
        if not isinstance(params, dict):
            raise receipts.ReceiptError('params must be a JSON object')
        for row in doc['upstream']:
            receipts.check_names(row['stage'], row.get('scope'))
        recomputed = receipts.generation(inputs, doc['upstream'], code['stage_digest'], params)
        evidence.update(recorded=doc['generation'], recomputed=recomputed)
        if doc['generation'] != recomputed:
            raise receipts.ReceiptError('recorded generation does not match recomputed generation')
    except (receipts.ReceiptError, RecursionError) as exc:
        evidence['error'] = str(exc)
        return None, evidence
    return doc, evidence


def _input_counts(doc):
    return Counter((row['role'], row['sha256']) for row in doc['inputs'])


def _upstream_by_scope(doc):
    # Keep multiplicity: the landed hash covers every upstream row.
    grouped = defaultdict(list)
    for row in doc['upstream']:
        key = receipts.Ref(row['stage'], row.get('scope')).key
        grouped[key].append(row['generation'])
    return {key: sorted(values) for key, values in grouped.items()}


def _changes(before, after):
    changes = {}
    old, new = _input_counts(before), _input_counts(after)
    if old != new:
        changes['inputs'] = [
            {'role': role, 'sha256': digest, 'before': old[role, digest], 'after': new[role, digest]}
            for role, digest in sorted(old.keys() | new.keys()) if old[role, digest] != new[role, digest]
        ]
    old, new = _upstream_by_scope(before), _upstream_by_scope(after)
    if old != new:
        changes['upstream'] = {
            key: {'before': old.get(key, []), 'after': new.get(key, [])}
            for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)
        }
    old, new = before['code']['stage_digest'], after['code']['stage_digest']
    if old != new:
        changes['stage_digest'] = {'before': old, 'after': new}
    old, new = before['params'], after['params']
    # Python equality conflates True, 1 and 1.0; the generation hash does not.
    if receipts.canonical(old) != receipts.canonical(new):
        changes['params'] = {
            key: {side: params[key] for side, params in (('before', old), ('after', new)) if key in params}
            for key in sorted(old.keys() | new.keys())
            if key not in old or key not in new or receipts.canonical(old[key]) != receipts.canonical(new[key])
        }
    return changes


def compare(before_path: Path, after_path: Path) -> dict:
    """Return a comparison, or separate evidence errors for either receipt."""
    before, old = _read_identity(before_path)
    after, new = _read_identity(after_path)
    report = {'evidence': {'before': old, 'after': new}}
    if before is None or after is None:
        return dict(report, status='invalid_evidence')
    if _target(before) != _target(after):
        return dict(report, status='different_target', before=_target(before), after=_target(after))
    changes = _changes(before, after)
    return dict(report, status='changed' if changes else 'same', target=_target(before), changes=changes)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Prints JSON. Exit 0 for a valid comparison (same or changed), '
        '1 for invalid evidence or different region/stage/scope.'))
    parser.add_argument('before', type=Path, help='earlier saved receipt JSON')
    parser.add_argument('after', type=Path, help='later saved receipt JSON')
    args = parser.parse_args(argv)
    report = compare(args.before, args.after)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['status'] in ('same', 'changed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
