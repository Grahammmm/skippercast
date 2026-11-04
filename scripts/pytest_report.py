"""Summarise pytest JUnit XML for the CI step summary, and fail on unexpected skips.

  python scripts/pytest_report.py pytest-survey.xml --title "Survey science" --strict-skips

prints a Markdown table (tests per layer, outcomes, time, slowest tests) to stdout;
CI appends it to $GITHUB_STEP_SUMMARY. With --strict-skips it exits 1 when any test
was skipped for a reason not in ALLOWED_SKIPS. The survey-science job installs every
package the suite uses, so the only legitimate skips left are tests that re-derive a
receipt from private, gitignored caches (var/, original survey archives) that exist
only on the maintainer's machine; each has a committed-output twin that does run.

An expected failure (pytest writes <skipped type="pytest.xfail">) is not a skip: it is its
own counted outcome, "xfailed", and --strict-skips ignores it. Only that exact type counts;
a skip whose reason merely mentions xfail is still a skip. A strict XPASS is a <failure>, so
it stays failed here and in pytest's own exit status; this script does not re-decide it.
"""
from collections import Counter
from datetime import datetime
from pathlib import Path
import argparse
import json
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
    # TA-M1: CI's survey-science job does not install the advisor extra; the stdlib half of
    # tests/unit/test_advisor_media_job.py (SigV4, R2 client, job loop) runs everywhere.
    'Pillow and pillow-heif are not installed (pip install -e ".[advisor]")',
    # Video privacy: the strip itself runs ffmpeg; the atom walk and the tag check on crafted MP4 bytes
    # in the same file run everywhere. GitHub's Ubuntu images ship ffmpeg, so CI normally runs it too.
    'ffmpeg and ffprobe are not installed (the advisor media runner needs them; docs/operations/runners.md)',
    'Pinned NOAA PDFs are cached in var/review (gitignored); run the audit with --fetch locally',
    'Pinned NOAA scheme not cached',
    'Pinned original NOAA research assets are not cached',
    'Pinned original archive not cached locally',
    'Private coordinate fixture absent in CI',
    'Private reference grid absent; committed ledger tested separately',
    'Private review blocks (var/review, gitignored) are only on the maintainer machine',
    # SC-4's retained source checkout is not distributed in CI; committed inventory
    # identities, counts and handoff paths are checked without it in the same file.
    'Retained coastal source snapshot unavailable; committed inventory checked separately',
    'run after fetching the pinned original ROV release',
})

LAYERS = (('research.tests.gis.', 'claims (gis)'), ('research.tests.', 'claims'),
          ('tests.unit.', 'unit'), ('tests.contract.', 'contract'),
          ('tests.integration.', 'integration'), ('tests.gis.', 'gis'))


def layer(classname):
    return next((name for prefix, name in LAYERS if classname.startswith(prefix)), 'other')


def _time(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number < float('inf') else None


def cases(paths):
    for path in paths:
        for case in ET.parse(path).getroot().iter('testcase'):
            outcome = 'passed'
            reason = None
            for child in case:
                if child.tag in {'failure', 'error'}:
                    # a failure or error wins over a skipped child, whatever the child order
                    outcome, reason = ('failed' if child.tag == 'failure' else 'error'), None
                elif child.tag == 'skipped' and outcome not in {'failed', 'error'}:
                    # only the exact type pytest writes for an expected failure; never the reason text
                    outcome = 'xfailed' if child.get('type') == 'pytest.xfail' else 'skipped'
                    reason = (child.get('message') or '').strip()
            time = _time(case.get('time') or 0)
            yield {'id': f"{case.get('classname')}::{case.get('name')}", 'layer': layer(case.get('classname', '')),
                   'outcome': outcome, 'reason': reason, 'time': time or 0.0, 'time_unreadable': time is None}


def report(rows, title, slowest=10):
    by_layer = Counter(row['layer'] for row in rows)
    outcomes = Counter(row['outcome'] for row in rows)
    lines = [f'### {title}', '',
             f"{len(rows)} tests: {outcomes['passed']} passed, {outcomes['failed']} failed, "
             f"{outcomes['error']} errors, {outcomes['skipped']} skipped, {outcomes['xfailed']} xfailed; "
             f"{sum(row['time'] for row in rows):.1f} s in tests", '',
             '| Layer | Tests | Skipped | Xfailed | Time (s) |', '| --- | ---: | ---: | ---: | ---: |']
    for name in [*(name for _, name in LAYERS), 'other']:
        if by_layer[name]:
            layer_rows = [row for row in rows if row['layer'] == name]
            lines.append(f"| {name} | {len(layer_rows)} | {sum(r['outcome'] == 'skipped' for r in layer_rows)} "
                         f"| {sum(r['outcome'] == 'xfailed' for r in layer_rows)} "
                         f"| {sum(r['time'] for r in layer_rows):.1f} |")
    unreadable = sum(bool(row.get('time_unreadable')) for row in rows)
    lines += ['', f'{unreadable} test time(s) unreadable; counted as 0 s'] if unreadable else []
    lines += ['', f'Slowest {slowest}:', '']
    lines += [f"- {row['time']:.2f} s `{row['id']}`" for row in sorted(rows, key=lambda r: -r['time'])[:slowest]]
    return '\n'.join(lines) + '\n'


def unexpected_skips(rows, allowed=ALLOWED_SKIPS):
    return [row for row in rows if row['outcome'] == 'skipped' and row['reason'] not in allowed]


def _receipt_ok(run):
    """A run ci_budget can read: every key it uses and timezone-aware ISO dates; otherwise it is a HOLD row."""
    try:
        hash(run['databaseId']), run['status'], run['conclusion'], [job['name'] for job in run['jobs']]
        [job['status'] for job in run['jobs'] if job.get('conclusion') != 'skipped']
        dates = [run['createdAt'], run['updatedAt'], *(j[k] for j in run['jobs'] for k in ('startedAt', 'completedAt') if j.get(k))]
        return all(datetime.fromisoformat(d.replace('Z', '+00:00')).tzinfo is not None for d in dates)
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def ci_budget(runs):
    """Report measured Actions wall/runner time, including independent DCO runs.

    Input is a JSON list of `gh run view --json databaseId,createdAt,updatedAt,
    status,conclusion,jobs` objects for the same head. Runner minutes are elapsed
    job time, not billing-rounded minutes; wall time includes queue waits.
    Incomplete/cancelled evidence never authorizes further feature admission.
    """
    lines = ['### Measured CI budget (R12)', '',
             '| Run/job | Wall min | Runner min | Result |',
             '| --- | ---: | ---: | --- |']
    starts, ends, total = [], [], 0.0
    complete = bool(runs)
    seen = set()
    for run in runs:
        if not _receipt_ok(run):
            complete = False
            lines.append(f"| {run.get('databaseId', '?')} | — | unknown | incomplete receipt |")
            continue
        if run['databaseId'] in seen:
            raise ValueError('duplicate run receipt')
        seen.add(run['databaseId'])
        start = datetime.fromisoformat(run['createdAt'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(run['updatedAt'].replace('Z', '+00:00'))
        starts.append(start)
        ends.append(end)
        complete &= run['status'] == 'completed' and run['conclusion'] == 'success'
        complete &= bool(run['jobs']) and end >= start
        for job in run['jobs']:
            result = job.get('conclusion')
            if result == 'skipped':
                lines.append(f"| {run['databaseId']}/{job['name']} | — | 0.00 | skipped |")
                continue
            complete &= job['status'] == 'completed' and result == 'success'
            first, last = job.get('startedAt'), job.get('completedAt')
            if not first or not last:
                complete = False
                lines.append(f"| {run['databaseId']}/{job['name']} | — | unknown | {result} |")
                continue
            seconds = (datetime.fromisoformat(last.replace('Z', '+00:00'))
                       - datetime.fromisoformat(first.replace('Z', '+00:00'))).total_seconds()
            complete &= seconds >= 0
            minutes = max(seconds, 0) / 60
            total += minutes
            lines.append(f"| {run['databaseId']}/{job['name']} | — | {minutes:.2f} | {result} |")
    wall = (max(ends) - min(starts)).total_seconds() / 60 if starts else 0
    ok = complete and wall < 10 and total <= 30
    lines.append(f'| **Total** | **{wall:.2f}** | **{total:.2f}** | {"PASS" if ok else "HOLD"} |')
    lines += ['', 'Elapsed job time (not billing-rounded); wall time includes queue waits.',
              'R12: <10 wall minutes and <=30 runner-minutes per commit.',
              'Feature admission may continue.' if ok else
              'BLOCK further feature admission: incomplete evidence or CI trimming required.']
    return '\n'.join(lines) + '\n', ok


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('junit', nargs='*', type=Path)
    parser.add_argument('--ci-runs', type=Path,
                        help='JSON Actions run receipts; report R12 budget instead of JUnit')
    parser.add_argument('--title', default='Python tests')
    parser.add_argument('--strict-skips', action='store_true',
                        help='exit 1 if a test was skipped for a reason not in ALLOWED_SKIPS '
                             '(expected failures, counted as xfailed, are not skips)')
    args = parser.parse_args(argv)
    if args.ci_runs:
        if args.junit:
            parser.error('--ci-runs cannot be combined with JUnit paths')
        try:
            runs = json.loads(args.ci_runs.read_text())
        except (OSError, UnicodeDecodeError, ValueError, RecursionError):
            print(f'pytest_report: {args.ci_runs}: unreadable JSON', file=sys.stderr)
            return 2
        if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
            print(f'pytest_report: {args.ci_runs}: expected a JSON list of run objects', file=sys.stderr)
            return 2
        text, ok = ci_budget(runs)
        sys.stdout.write(text)
        return 0 if ok else 1
    if not args.junit:
        parser.error('provide JUnit paths or --ci-runs')
    rows = []
    for path in args.junit:
        try:
            rows += cases([path])
        except (OSError, ET.ParseError):
            print(f'pytest_report: {path}: unreadable JUnit XML', file=sys.stderr)
            return 2
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
