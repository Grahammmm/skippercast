#!/usr/bin/env python3
"""Triage the six Central release chains using saved public stage receipts only.

Run with --out OUT against a saved receipt tree. This is neither a live snapshot
(no locks) nor the pipeline's done rule (no input or output bytes are checked).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skippercast.relief import receipts

CENTRAL_RELEASES = (
    'big-sur-coast', 'cambria-san-simeon', 'south-big-sur-san-simeon',
    'monterey-point-sur', 'point-arguello-conception', 'santa-cruz-monterey-bay',
)

# Public run_region.py order and the producers' required direct receipt edges.
# The runner binds the shots artifact into QA as a file input, not a required
# receipt edge. census_bind is a different record format, not a stage receipt.
PUBLIC_CHAIN = {
    'select': (),
    'mosaic.public': ('select',),
    'tiles.public': ('select', 'mosaic.public'),
    'zone.public': ('select', 'mosaic.public'),
    'digests': ('tiles.public',),
    'inventory': ('select', 'tiles.public', 'digests', 'zone.public'),
    'contours': ('select', 'mosaic.public'),
    'nearshore_vectors.public': ('select', 'mosaic.public'),
    'package': ('tiles.public', 'digests', 'zone.public', 'inventory', 'contours'),
    'shots': ('package',),
    'qa': ('package', 'mosaic.public', 'nearshore_vectors.public', 'contours'),
    'envelope': ('package', 'qa'),
}


def _is_digest(value):
    return isinstance(value, str) and receipts.HEX64.fullmatch(value) is not None


def _generation_matches(doc):
    inputs, code, params = doc.get('inputs'), doc.get('code'), doc.get('params')
    if not isinstance(inputs, list) or not all(
        isinstance(row, dict) and isinstance(row.get('role'), str) and _is_digest(row.get('sha256'))
        for row in inputs
    ):
        return False
    if not isinstance(code, dict) or not _is_digest(code.get('stage_digest')) or not isinstance(params, dict):
        return False
    return receipts.generation(inputs, doc['upstream'], code['stage_digest'], params) == doc['generation']


def _read(region, key):
    stage, _, scope = key.partition('.')
    scope = scope or None
    path = region.receipt_path(stage, scope)
    try:
        doc = receipts.read_receipt(path)
        if doc is None:
            return None, 'missing', 'no saved receipt'
        if receipts.validate_receipt(doc, region.id, stage, scope):
            return None, 'stale', 'invalid receipt schema or identity'
        if not _generation_matches(doc):
            return None, 'stale', 'receipt generation does not verify'
    except (OSError, ValueError, RecursionError):
        return None, 'stale', 'unreadable or malformed receipt'
    return doc, None, None


def _upstream_problem(region, key, doc, required, verified):
    seen = set()
    for row in doc['upstream']:
        ref = receipts.Ref(row['stage'], row.get('scope'))
        try:
            receipts.check_names(ref.stage, ref.scope)
        except receipts.ReceiptError:
            return 'invalid direct upstream identity'
        if ref.key in seen:
            return 'duplicate direct upstream reference'
        seen.add(ref.key)
        generation = verified.get(ref.key)
        # select may link the optional producer receipt (not the census_bind record).
        if key == 'select' and ref == receipts.Ref('census'):
            census, _, _ = _read(region, 'census')
            if census and census['status'] == 'ok' and not census['upstream']:
                generation = census['generation']
        if generation != row['generation']:
            return 'direct upstream identity or generation does not match'
    if missing := sorted(set(required) - seen):
        return 'required direct upstream omitted: ' + ', '.join(missing)
    return None


def _triage(region):
    verified = {}
    last = None
    for key, required in PUBLIC_CHAIN.items():
        doc, reason, detail = _read(region, key)
        if doc is None:
            return dict(region=region.id, last_verified=last, first_unresolved=key, reason=reason, detail=detail)
        if problem := _upstream_problem(region, key, doc, required, verified):
            reason, detail = 'stale', problem
        elif doc['status'] != 'ok':
            reason, detail = doc['status'], f"saved {doc['status']} receipt (attempt {doc['attempt']})"
        if reason is not None:
            return dict(region=region.id, last_verified=last, first_unresolved=key, reason=reason, detail=detail)
        verified[key] = doc['generation']
        last = dict(step=key, receipt=f'{region.id}/stages/{key}.json', generation=doc['generation'])
    return dict(region=region.id, last_verified=last, first_unresolved=None, reason=None, detail=None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='saved OUT root containing region directories')
    args = parser.parse_args(argv)
    rows = [_triage(receipts.Region(args.out, region)) for region in CENTRAL_RELEASES]
    print(json.dumps({'mode': 'receipt-only, not R8-ready', 'regions': rows}, indent=2))
    return 0  # A successfully generated list is not a readiness verdict.


if __name__ == '__main__':
    raise SystemExit(main())
