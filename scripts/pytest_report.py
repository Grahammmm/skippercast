"""Summarise pytest JUnit XML for the CI step summary, and fail on unexpected skips.

  python scripts/pytest_report.py pytest-survey.xml --title "Survey science" --strict-skips

prints a Markdown table (tests per layer, outcomes, time, slowest tests) to stdout;
CI appends it to $GITHUB_STEP_SUMMARY. With --strict-skips it exits 1 when any test
was skipped for a reason not in ALLOWED_SKIPS. The survey-science job installs every
package the suite uses, so the only legitimate skips left are tests that re-derive a
receipt from private, gitignored caches (var/, original survey archives) that exist
only on the maintainer's machine; each has a committed-output twin that does run.
"""
from collections import Counter
from pathlib import Path
import argparse
import sys
import xml.etree.ElementTree as ET

# Exact skip reasons allowed in the full (survey-science) run. Adding one needs review:
# say in the PR why CI cannot provide the input and which test covers the committed output.
ALLOWED_SKIPS = frozenset({
    'Monthly job downloads original NOAA archive before full source audit',
    'Monthly source job downloads original archives before full audit',
    'Original archives not cached locally',
    'Original archives or fresh official snapshots unavailable locally',
    'Original bathymetry metadata not fetched in this environment',
    'Original character metadata not fetched in this environment',
    'Pinned NOAA PDFs are cached in var/review (gitignored); run the audit with --fetch locally',
    'Pinned NOAA scheme not cached',
    'Pinned original NOAA research assets are not cached',
    'Pinned original archive not cached locally',
    'Private coordinate fixture absent in CI',
    'Private reference grid absent; committed ledger tested separately',
    'Private review blocks (var/review, gitignored) are only on the maintainer machine',
    'run after fetching the pinned original ROV release',
})

LAYERS = (('research.tests.gis.', 'claims (gis)'), ('research.tests.', 'claims'),
          ('tests.unit.', 'unit'), ('tests.contract.', 'contract'),
          ('tests.integration.', 'integration'), ('tests.gis.', 'gis'))


def layer(classname):
    return next((name for prefix, name in LAYERS if classname.startswith(prefix)), 'other')




def cases(paths):
    for path in paths:
        for case in ET.parse(path).getroot().iter('testcase'):
            outcome = 'passed'
            reason = None
            for child in case:
                if child.tag in {'failure', 'error'}:
                    outcome = 'failed' if child.tag == 'failure' else 'error'
                elif child.tag == 'skipped':
                    outcome, reason = 'skipped', (child.get('message') or '').strip()
            yield {'id': f"{case.get('classname')}::{case.get('name')}", 'layer': layer(case.get('classname', '')),
                   'outcome': outcome, 'reason': reason, 'time': float(case.get('time') or 0)}


def report(rows, title, slowest=10):
    by_layer = Counter(row['layer'] for row in rows)
    outcomes = Counter(row['outcome'] for row in rows)
    lines = [f'### {title}', '',
             f"{len(rows)} tests: {outcomes['passed']} passed, {outcomes['failed']} failed, "
             f"{outcomes['error']} errors, {outcomes['skipped']} skipped; "
             f"{sum(row['time'] for row in rows):.1f} s in tests", '',
             '| Layer | Tests | Skipped | Time (s) |', '| --- | ---: | ---: | ---: |']
    for name in [*(name for _, name in LAYERS), 'other']:
        if by_layer[name]:
            layer_rows = [row for row in rows if row['layer'] == name]
            lines.append(f"| {name} | {len(layer_rows)} | {sum(r['outcome'] == 'skipped' for r in layer_rows)} "
                         f"| {sum(r['time'] for r in layer_rows):.1f} |")
    lines += ['', f'Slowest {slowest}:', '']
    lines += [f"- {row['time']:.2f} s `{row['id']}`" for row in sorted(rows, key=lambda r: -r['time'])[:slowest]]
    return '\n'.join(lines) + '\n'


def unexpected_skips(rows, allowed=ALLOWED_SKIPS):
    return [row for row in rows if row['outcome'] == 'skipped' and row['reason'] not in allowed]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('junit', nargs='+', type=Path)
    parser.add_argument('--title', default='Python tests')
    parser.add_argument('--strict-skips', action='store_true',
                        help='exit 1 if a test was skipped for a reason not in ALLOWED_SKIPS')
    args = parser.parse_args(argv)
    rows = list(cases(args.junit))
    sys.stdout.write(report(rows, args.title))
    if args.strict_skips:
        bad = unexpected_skips(rows)
        for row in bad:
            print(f"::error::Unexpected skip in the full run: {row['id']}: {row['reason']}", file=sys.stderr)
        if bad:
            print(f'\n**{len(bad)} unexpected skip(s)**; install what the test needs or, for a private '
                  'cache, add its exact reason to ALLOWED_SKIPS in scripts/pytest_report.py with a reason.')
            return 1
        print(f"\nNo unexpected skips ({sum(r['outcome'] == 'skipped' for r in rows)} allow-listed private-cache skips).")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
