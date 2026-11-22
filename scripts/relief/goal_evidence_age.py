#!/usr/bin/env python3
"""Report freshness of explicitly supplied saved relief live-check receipts.

Times are caller attestations, not inferred from receipt contents or filesystem
metadata. Freshness does not authenticate an attestation or change the saved
check verdict. This command reads only the named files and reports to stdout.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _instant(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    if value.utcoffset() is None:
        raise ValueError('timestamps require an explicit UTC offset (or Z)')
    return value.astimezone(UTC)


def _report(path: Path, observed: datetime | None, as_of: datetime, max_age: timedelta) -> dict:
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(receipt, dict) or not isinstance(receipt.get('region'), str)
            or not receipt['region'] or receipt.get('verdict') not in ('PASS', 'FAIL')):
        raise ValueError(f'{path}: expected a live-check receipt with region and PASS/FAIL verdict')

    if observed is None or observed > as_of:
        freshness = 'unknown'
    elif as_of - observed > max_age:
        freshness = 'stale'
    else:
        freshness = 'current'
    return {
        'receipt': str(path),
        'region': receipt['region'],
        'verdict': receipt['verdict'],
        'observed_at': observed.isoformat() if observed is not None else None,
        'freshness': freshness,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--as-of', required=True, help='fixed ISO 8601 evaluation time with offset')
    parser.add_argument('--max-age-seconds', required=True, type=int,
                        help='inclusive freshness threshold in seconds')
    parser.add_argument('--receipt', required=True, action='append', nargs='+', metavar='ARG',
                        help='local PATH optionally followed by attested ISO 8601 time with offset; repeatable')
    args = parser.parse_args(argv)
    if args.max_age_seconds < 0:
        parser.error('--max-age-seconds must be nonnegative')
    try:
        as_of = _instant(args.as_of)
        max_age = timedelta(seconds=args.max_age_seconds)
        rows = []
        for path, *times in args.receipt:
            if len(times) > 1:
                parser.error('--receipt takes PATH and at most one observation time')
            observed = _instant(times[0]) if times else None
            rows.append(_report(Path(path), observed, as_of, max_age))
    except (OSError, ValueError, OverflowError) as exc:
        parser.error(str(exc))
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
