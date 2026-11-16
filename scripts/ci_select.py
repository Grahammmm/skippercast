"""Conservative affected-area selection and evidence gate for Offline checks.

No network or third-party imports. The map is deliberately coarse: shared Python
producers and data select all consumers, not a guessed per-module dependency graph.
Path fixtures exercise selection, not the contents or behavior of other tests.
"""
import argparse
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

MAP = Path(__file__).with_name('ci_affected.json')
AREAS = ('core', 'survey', 'web')


def load_map():
    data = json.loads(MAP.read_text())
    for rule in data['rules']:
        if not rule['patterns'] or not rule['areas'] or set(rule['areas']) - set(AREAS):
            raise ValueError('invalid affected-area map')
    return data


def select(paths, rules=None):
    """Union areas for every old/new path; no paths or unknowns run everything."""
    rules = load_map()['rules'] if rules is None else rules
    selected = set()
    for path in paths:
        parts = PurePosixPath(path).parts
        if not path or path.startswith('/') or '..' in parts or '\\' in path:
            return dict.fromkeys(AREAS, True)
        for rule in rules:
            if any(fnmatchcase(path, pattern) for pattern in rule['patterns']):
                selected.update(rule['areas'])
                break
        else:
            return dict.fromkeys(AREAS, True)
    if not selected:
        selected.update(AREAS)
    return {area: area in selected for area in AREAS}


def changed_paths(base, head):
    """Disable rename collapsing so both sides participate; -z preserves names."""
    result = subprocess.run(
        ['git', 'diff', '--no-renames', '--name-only', '-z', base, head, '--'],
        check=True, stdout=subprocess.PIPE,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b'\0') if path]


def evidence(event, gate, core, survey, web, check, tests):
    """Required context succeeds only on complete classification + job evidence.

    Even a passing GIS job cannot hide a cancelled/failed selector. Skipped science
    is evidence only for an explicitly selected PR with no science dependencies.
    A cancelled prerequisite is non-success, never permission for defect auto-fix.
    DCO remains a separate required context using its base-branch checker.
    """
    if gate != 'success' or check != 'success':
        return False
    if any(value not in {'true', 'false'} for value in (core, survey, web)):
        return False
    if event != 'pull_request' and (core, survey, web) != ('true', 'true', 'true'):
        return False
    if not any(value == 'true' for value in (core, survey, web)):
        return False
    return tests == ('success' if survey == 'true' else 'skipped')


def fixtures():
    data = load_map()
    count = 0
    for fixture in data['fixtures']:
        actual = select(fixture['paths'], data['rules'])
        expected = {area: area in fixture['areas'] for area in AREAS}
        if actual != expected:
            raise AssertionError(f"{fixture['name']}: {actual} != {expected}")
        count += 1
    # Exercise the required-context decision on real GitHub result vocabulary.
    # Only explicit success can provide evidence; no truthy substring matching.
    results = ('success', 'failure', 'cancelled', 'skipped', '', 'pending')
    for event in ('pull_request', 'push', 'schedule', 'merge_group', 'workflow_dispatch'):
        for gate in results:
            for check in results:
                for tests in results:
                    for survey in ('true', 'false', ''):
                        wanted = (gate == check == 'success' and (
                            survey == 'true' and tests == 'success'
                            or event == 'pull_request' and survey == 'false' and tests == 'skipped'
                        ))
                        actual = evidence(event, gate, 'true', survey, 'true', check, tests)
                        if actual != wanted:
                            raise AssertionError((event, gate, check, tests, survey))
                        count += 1
    if evidence('pull_request', 'success', 'false', 'false', 'false', 'success', 'skipped'):
        raise AssertionError('an empty selection cannot authorize a pass')
    print(f'{count + 1} selector/evidence fixtures passed')


GATE_NAMES = ('GATE', 'CORE', 'SURVEY', 'WEB', 'CHECK', 'TESTS')
# Result variable -> the upstream job it reports (for the readable summary).
UPSTREAM_JOBS = (('GATE', 'changes'), ('CHECK', 'check'), ('TESTS', 'survey-tests'))
DECISIVE = ('failure', 'cancelled')


def clean(value):
    """Untrusted workflow value -> short inert token (never a command, heading or markup)."""
    value = str(value)
    return value if re.fullmatch(r'[A-Za-z0-9_.-]{0,32}', value) else '<invalid>'


def gate(event, environ=None, stdout=None, stderr=None):
    """Diagnostic CLI around evidence(), which alone decides pass/fail.

    An exact upstream failed/cancelled job already carries the decisive failure, so name
    it readably instead of a second unparseable ::error annotation. Anything else that
    evidence() refuses (skipped/missing/malformed) stays an explicit contract error.
    Always nonzero when evidence() refuses; never a skip.
    """
    environ = os.environ if environ is None else environ
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    got = {name: environ.get(name, '') for name in GATE_NAMES}
    if evidence(event, *got.values()):
        print('Required selected-area evidence passed; DCO is checked independently.', file=stdout)
        return 0
    decisive = [(job, clean(got[var])) for var, job in UPSTREAM_JOBS if got[var] in DECISIVE]
    if decisive:
        print('survey-science is not green because an upstream job did not succeed: '
              + ', '.join(f'{job} = {result}' for job, result in decisive) + '.\n'
              'The failing job reports the cause; this roll-up only restates it.', file=stdout)
        title = 'Upstream job did not succeed'
    else:
        print('::error::Required evidence incomplete (selector/contract): '
              + ', '.join(f'{name}={clean(value)}' for name, value in got.items()), file=stderr)
        title = 'Required evidence incomplete'
    if summary := environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a') as stream:
            stream.write(f'**survey-science: {title}**\n\n- `EVENT` = `{clean(event)}`\n')
            stream.write(''.join(f'- `{name}` = `{clean(value)}`\n' for name, value in got.items()))
    return 1


def main():
    parser = argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0])
    parser.add_argument('--event', default=os.environ.get('EVENT', 'pull_request'))
    parser.add_argument('--base', default='HEAD^1')
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--fixtures', action='store_true')
    parser.add_argument('--gate', action='store_true')
    args = parser.parse_args()
    if args.fixtures:
        fixtures()
        return 0
    if args.gate:
        return gate(args.event)
    # Git lookup failure cannot narrow the tier. A map/parse error fails the job,
    # so the required evidence gate cannot manufacture a successful classification.
    if args.event == 'pull_request':
        try:
            paths = changed_paths(args.base, args.head)
        except subprocess.CalledProcessError:
            print('::warning::Changed paths unavailable; selecting every area', file=sys.stderr)
            paths = []
        selected = select(paths)
    else:
        paths = []
        selected = dict.fromkeys(AREAS, True)
    lines = [f'{area}={str(value).lower()}' for area, value in selected.items()]
    print('\n'.join(lines))
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            stream.write('\n'.join(lines) + '\n')
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a') as stream:
            stream.write(f'### Affected areas ({len(paths)} changed paths)\n\n')
            stream.write('\n'.join(f'- {line}' for line in lines) + '\n')
            stream.write('Unknown/shared paths select all consumers. DCO always runs.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
