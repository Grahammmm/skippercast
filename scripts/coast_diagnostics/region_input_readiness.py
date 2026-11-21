#!/usr/bin/env python3
"""Report relief input declarations for an explicit cohort, without running relief.

Example: region_input_readiness.py --repo-root . --region coast-a --region coast-b
         --through zone --bindings operator-inputs.json

The optional binding file is a JSON object keyed by region ID. Each row is an
object with the runner's flag names (without '--'), for example
{"coast-a": {"coarse": "grid.tif", "water": "ocean.geojson", "coarse-source": "grid-id"}}.
Only declarations required through the target stage are checked; coarse-date is optional.
"""

import argparse
import json
from pathlib import Path
import re

# Mirror scripts/relief/run_region.py without importing the guarded runner.
STAGES = ('select', 'mosaic', 'tiles', 'zone', 'digests', 'inventory', 'contours',
          'package', 'shots', 'qa', 'envelope')
STAGE_INPUTS = {'zone': ('coarse', 'water', 'coarse-source'), 'shots': ('basemap',)}
REGION_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')


def read_object(path):
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None, 'missing'
    except OSError:
        return None, 'unreadable'
    except (ValueError, RecursionError):  # Includes malformed JSON and invalid UTF-8.
        return None, 'malformed'
    return (doc, 'read') if isinstance(doc, dict) else (None, 'malformed')


def valid_bounds(box):
    # Range comparisons also reject NaN and infinities without coercing huge ints.
    return (isinstance(box, list) and len(box) == 4
            and all(type(v) in (int, float) for v in box)
            and -180 <= box[0] < box[2] <= 180
            and -90 <= box[1] < box[3] <= 90)


def config_issues(repo_root, region):
    if not REGION_ID.fullmatch(region):
        return ['invalid_region_id']
    doc, status = read_object(repo_root / 'regions' / region / 'region.json')
    if doc is None:
        return [f'config_{status}']
    issues = []
    identity = doc.get('id')
    if not isinstance(identity, str) or not REGION_ID.fullmatch(identity):
        issues.append('invalid_config_id')
    elif identity != region:
        issues.append('config_id_mismatch')
    if not valid_bounds(doc.get('bounds')):
        issues.append('invalid_wgs84_bounds')
    return issues


def binding_row(bindings, file_status, region):
    if bindings is None:
        return {}, 'not_supplied' if file_status == 'not_supplied' else 'unavailable'
    if region not in bindings:
        return {}, 'missing'
    row = bindings[region]
    return (row, 'read') if isinstance(row, dict) else ({}, 'malformed')


def declaration_status(row, name):
    if name not in row:
        return 'missing'
    value = row[name]
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        return 'malformed'
    return 'declared' if name == 'coarse-source' else 'declared_unverified'


def build_report(repo_root, regions, through, bindings_path=None):
    if bindings_path is None:
        bindings, file_status = None, 'not_supplied'
    else:
        bindings, file_status = read_object(bindings_path)
    required = [name for stage in STAGES[:STAGES.index(through) + 1]
                for name in STAGE_INPUTS.get(stage, ())]
    rows = []
    for region in regions:
        issues = config_issues(repo_root, region)
        binding, row_status = binding_row(bindings, file_status, region)
        if row_status not in ('read', 'not_supplied'):
            issues.append(f'binding_row_{row_status}')
        declarations = {name: declaration_status(binding, name) for name in required}
        issues.extend(f'{status}_declaration:{name}' for name, status in declarations.items()
                      if status in ('missing', 'malformed'))
        rows.append({'region': region, 'binding_row': row_status, 'declarations': declarations,
                     'issues': issues, 'structurally_complete': not issues})
    return {
        'through': through,
        'binding_file': file_status,
        'qualification': 'Structural declarations only. Payload paths were not verified. '
                         'This is not run or release approval.',
        'regions': rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repo-root', required=True, type=Path)
    parser.add_argument('--region', required=True, action='append', help='region ID; repeat for each region')
    parser.add_argument('--through', required=True, choices=STAGES)
    parser.add_argument('--bindings', type=Path, help='explicit binding JSON path (relative to cwd if not absolute)')
    args = parser.parse_args(argv)
    report = build_report(args.repo_root, args.region, args.through, args.bindings)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if any(row['issues'] for row in report['regions']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
