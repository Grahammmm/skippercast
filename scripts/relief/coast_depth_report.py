#!/usr/bin/env python3
"""Summarize existing regional depth coverage. Unknown-band water is not assigned
to either band. Totals are sums across the reports read, not a spatial union.
"""

import argparse
import json
from pathlib import Path
import sys

BANDS = ('0-66ft', '66-300ft')
CLASSES = ('measured', 'estimated', 'unsurveyed')
REPORT = Path('coverage/depth-coverage.json')
RELEASE_INDEX = Path(__file__).resolve().parents[2] / 'dist/regions/index.json'


def _band(areas):
    total = sum(areas[key + '_m2'] for key in CLASSES)
    return {
        **areas,
        **{key + '_pct': round(100 * areas[key + '_m2'] / total, 1) if total else None
           for key in CLASSES},
    }


def summarize(out, regions=()):
    if not regions:
        regions = sorted(row['id'] for row in json.loads(RELEASE_INDEX.read_text(encoding='utf-8'))['regions'])
        if not regions:
            raise ValueError(f'{RELEASE_INDEX}: no release regions')
    paths = [out / region / REPORT for region in dict.fromkeys(regions)]
    totals = {band: {key + '_m2': 0 for key in CLASSES} for band in BANDS}
    reaches = None
    rows = []
    for path in paths:
        region = path.parent.parent.name
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            rows.append({'region': region, 'status': 'no report'})
            continue
        claimed_region = doc['region']
        if claimed_region != region:
            raise ValueError(f'{path}: region {claimed_region!r} does not match directory {region!r}')
        bands = {}
        for band, total in totals.items():
            areas = {key: doc['bands'][band][key] for key in total}
            for key, value in areas.items():
                total[key] += value
            bands[band] = _band(areas)
        reached = doc['reaches_300ft']
        reaches = bool(reaches or reached)
        rows.append({'region': region, 'bands': bands, 'reaches_300ft': reached})
    return {'regions': rows,
            'total': {'bands': {band: _band(areas) for band, areas in totals.items()},
                      'reaches_300ft': reaches}}


def _print_table(report):
    print(' | '.join(['Region', 'Reaches 300 ft',
                      *(f'{band} {key} m² (%)' for band in BANDS for key in CLASSES)]))
    for row in [*report['regions'], {'region': 'TOTAL', **report['total']}]:
        if row.get('status') == 'no report':
            print(f'{row["region"]} | no report')
            continue
        reached = row['reaches_300ft']
        cells = [row['region'], 'n/a' if reached is None else 'yes' if reached else 'no']
        for band in BANDS:
            for key in CLASSES:
                area = row['bands'][band][key + '_m2']
                pct = row['bands'][band][key + '_pct']
                cells.append(f'{area} (n/a)' if pct is None else f'{area} ({pct:.1f}%)')
        print(' | '.join(cells))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='pipeline output root')
    parser.add_argument('--json', action='store_true', help='print machine-readable JSON')
    parser.add_argument('regions', metavar='REGION', nargs='*', help='defaults to all release regions')
    args = parser.parse_args(argv)
    for region in args.regions:
        if not region or Path(region).name != region or region in {'.', '..'}:
            parser.error(f'expected a region directory name, got {region!r}')
    try:
        report = summarize(args.out, args.regions)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'coast_depth_report: {exc}', file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_table(report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
