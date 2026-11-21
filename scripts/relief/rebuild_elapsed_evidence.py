#!/usr/bin/env python3
"""Summarize observed elapsed seconds from explicitly listed saved stage receipts.

Each file contributes only its top-level receipt, not embedded history. This
report neither checks current artifacts nor estimates future rebuild costs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
import json
from pathlib import Path

from skippercast.relief import receipts


def _clock(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError('missing or non-text timestamp')
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError('timestamp needs an explicit UTC offset')
    return moment


def summarize(paths: Iterable[Path]) -> dict:
    """Read saved receipts and count each exclusion once per listed file."""
    ignored: Counter[str] = Counter()
    groups: dict[tuple[str, str, str | None], list[float]] = defaultdict(list)
    seen = set()
    for path in paths:
        try:
            doc = receipts.read_receipt(path)
        except (OSError, ValueError, RecursionError):
            ignored['unreadable_receipt'] += 1
            continue
        if doc is None:
            ignored['missing_receipt'] += 1
            continue
        status = doc.get('status')
        if doc.get('schema') == receipts.SCHEMA and status in ('busy', 'held', 'failed'):
            ignored[status] += 1
            continue
        region, stage, scope = doc.get('region'), doc.get('stage'), doc.get('scope')
        if not isinstance(region, str) or not isinstance(stage, str):
            ignored['invalid_receipt'] += 1
            continue
        try:
            receipts.check_names(stage, scope, region)
        except receipts.ReceiptError:
            ignored['invalid_receipt'] += 1
            continue
        if (status != 'ok' or type(doc.get('rc')) is not int or doc['rc'] != 0
                or type(doc.get('attempt')) is not int
                or receipts.validate_receipt(doc, region, stage, scope) is not None):
            ignored['invalid_receipt'] += 1
            continue
        try:
            started, ended = _clock(doc.get('started')), _clock(doc.get('ended'))
        except ValueError:
            ignored['invalid_clock'] += 1
            continue
        elapsed = (ended - started).total_seconds()
        if elapsed < 0:
            ignored['negative_elapsed'] += 1
            continue
        group = region, stage, scope
        # Generation hashes need not differ across groups. A rerun within a group
        # is distinct if the generation, attempt, or recorded time window differs.
        identity = group, doc['generation'], doc['attempt'], started, ended
        if identity in seen:
            ignored['duplicate'] += 1
            continue
        seen.add(identity)
        groups[group].append(elapsed)

    return {
        'groups': [
            {'region': region, 'stage': stage, 'scope': scope, 'count': len(samples),
             'min_seconds': min(samples), 'max_seconds': max(samples)}
            for (region, stage, scope), samples in sorted(
                groups.items(), key=lambda item: (*item[0][:2], item[0][2] or ''))
        ],
        'ignored': dict(sorted(ignored.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipts', type=Path, nargs='+', metavar='RECEIPT',
                        help='saved sc-stage-receipt/1 JSON file (list each sample explicitly)')
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.receipts), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
