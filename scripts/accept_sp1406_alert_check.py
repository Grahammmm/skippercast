#!/usr/bin/env python3
"""Offline, portable SP1406 argv launcher; scoped green remains REVIEW REQUIRED.

Never installs or downloads. Repository/private-path scanning uses only the
staged source manifest's credential_scan_python3. Every invocation gets fresh
candidate-local evidence. Baseline is expected-red evidence, never a fix pass.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
FIXTURES = 'tests/fixtures/sp1406_alert_check'
TEST = 'tests/test_sp1406_alert_check.mjs'
BOOTSTRAP = FIXTURES + '/bootstrap.mjs'
SPEC_PATH = FIXTURES + '/acceptance.json'
SOURCE = 'server/advisor/answers/planning.ts'
BASE = '33734f90073a2150eac5a418564ea314c4a591ac'
BASE_HASH = '569cac7d016d92822a13a24a847341f4003ffe12e8b12b85bce3b6e6c4662647'
REGRESSION = ['tests/test_advisor_tools.mjs']
PAIRS = ['primary regression', 'healthy control']
TAP_RESULT = re.compile(r'^(not ok|ok) \d+ - (.*?)(?: # (SKIP|TODO).*)?$')
TAP_COUNT = re.compile(r'^# (tests|suites|pass|fail|cancelled|skipped|todo) (\d+)$')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def filehash(path):
    return digest(Path(path).read_bytes())


def regular_ancestry(path, *, directory=False):
    """Reject symlink/special-file ancestors before access; absent tails are OK."""
    path = Path(os.path.abspath(path))
    for p in [*reversed(path.parents), path]:
        try:
            mode = p.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or (p == path and not directory and stat.S_ISREG(mode))):
            raise ValueError('unsafe ancestry/type: ' + str(p))
    return path


def git(*args):
    proc = subprocess.run(['git', *args], cwd=REPO, capture_output=True, check=False)
    if proc.returncode:
        raise RuntimeError('git discovery failed: ' + proc.stderr.decode(errors='replace'))
    return proc.stdout


def hashes():
    paths = [SOURCE, TEST, 'scripts/accept_sp1406_alert_check.py', *REGRESSION, 'package.json', 'pnpm-lock.yaml']
    paths += [p.relative_to(REPO).as_posix() for p in sorted((REPO / FIXTURES).rglob('*')) if p.is_file()]
    note = 'docs/engineering/sp1406_alert_check.md'
    if (REPO / note).exists():
        paths.append(note)
    return {p: filehash(regular_ancestry(REPO / p)) for p in sorted(set(paths))}


def expected_tests():
    data = json.loads((REPO / FIXTURES / 'cases.json').read_text())
    js = lambda v: json.dumps(v, separators=(',', ':'))
    return [*PAIRS,
            'A1 one missing required zone and unrelated successful zone', 'A1 missing daily feed',
            *['A1 invalid status ' + js(v) for v in data['invalid_statuses']], 'A1 missing status',
            *['A1 non-array alerts ' + js(v) for v in data['invalid_alerts']],
            'A1 absent data or alerts and non-object source',
            *['A1 invalid checked_at ' + js(v) for v in data['invalid_times']], 'A1 missing checked_at',
            'A2 oldest required check independent of source insertion and unrelated zones',
            'A2 compare timestamp instants not lexicographic strings; no new elapsed-age threshold',
            'A2 no configured required zones is not a complete check',
            'A3 warning survives missing evidence and complete check in en',
            'A3 warning survives missing evidence and complete check in es',
            'A3 known warnings survive a non-ok check status']


def tap(text):
    results, counts = [], {}
    for line in text.splitlines():
        m = TAP_RESULT.match(line)
        if m:
            results.append({'name': m[2].replace('\\#', '#'), 'ok': m[1] == 'ok', 'directive': m[3]})
        m = TAP_COUNT.match(line)
        if m:
            counts[m[1]] = int(m[2])
    return results, counts


def invoke(argv, label, out, *, suite, timed=900):
    env = dict(os.environ)
    # Not a search-path override: selects registration, never name-filtered skips.
    env['SP1406_ALERT_CHECK_SUITE'] = suite
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        proc = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, timeout=timed, check=False)
        code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        code, stdout, stderr = 124, e.stdout or b'', (e.stderr or b'') + b'\nACCEPTANCE TIMEOUT\n'
    except OSError as e:
        code, stdout, stderr = 127, b'', str(e).encode()
    for suffix, data in [('stdout', stdout), ('stderr', stderr)]:
        (out / f'{label}.{suffix}.txt').write_bytes(data)
    results, counts = tap(stdout.decode(errors='replace'))
    return {'label': label, 'argv': argv, 'cwd': str(REPO), 'exit': code,
            'started_at': started, 'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'environment_delta': {'SP1406_ALERT_CHECK_SUITE': suite},
            'counts': counts, 'results': results,
            'stdout': f'{label}.stdout.txt', 'stdout_sha256': digest(stdout),
            'stderr': f'{label}.stderr.txt', 'stderr_sha256': digest(stderr)}


def verify_tests(inv, names, baseline, out):
    problems = []
    results, counts = inv['results'], inv['counts']
    if [r['name'] for r in results] != names:
        problems.append('selected names/order differ from frozen complete list')
    if any(r['directive'] for r in results):
        problems.append('SKIP/TODO directive')
    expected_counts = {'tests': len(names), 'suites': 0, 'pass': len(names) - int(baseline),
                       'fail': int(baseline), 'cancelled': 0, 'skipped': 0, 'todo': 0}
    if counts != expected_counts:
        problems.append(f'counts {counts} != {expected_counts}')
    if inv['exit'] != int(baseline):
        problems.append(f'child exit {inv["exit"]} != {int(baseline)}')
    failed = [r['name'] for r in results if not r['ok']]
    if failed != (['primary regression'] if baseline else []):
        problems.append('unexpected failed test identities: ' + str(failed))
    if baseline:
        text = (out / inv['stdout']).read_text()
        # Isolate the admitted assertion mismatch, not an arbitrary/setup error.
        for token in ['code: \'ERR_ASSERTION\'', 'actual: true', 'expected: false',
                      'missing or invalid required-zone evidence is not a complete check']:
            if token not in text:
                problems.append('missing baseline semantic mismatch marker: ' + token)
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    # Validate all new write ancestry BEFORE creation. Never touch .venv/node_modules links.
    regular_ancestry(CANDIDATE, directory=True)
    regular_ancestry(REPO / FIXTURES, directory=True)
    output = regular_ancestry(args.output, directory=True)
    allowed = CANDIDATE / 'out'
    if output != allowed and allowed not in output.parents:
        parser.error('--output must be below this candidate/out')
    output.mkdir(parents=True, exist_ok=True)
    out = output / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid.uuid4().hex)
    out.mkdir(exist_ok=False)
    receipt = {'schema': 'sp1406.acceptance/v1', 'spec_version': 'SP-14-v1', 'card': 'SP1406-ALERT-CHECK',
               'phase': args.suite, 'argv': [sys.executable, *sys.argv], 'cwd': os.getcwd(),
               'python': {'path': sys.executable, 'resolved': str(Path(sys.executable).resolve()), 'version': platform.python_version()},
               'repo': str(REPO), 'run_dir': str(out), 'invocations': [], 'problems': []}
    try:
        manifest_path = regular_ancestry(CANDIDATE / 'SOURCE-MANIFEST.json')
        manifest = json.loads(manifest_path.read_text())
        if (manifest.get('schema') != 'agentorange.source-manifest/v1' or manifest.get('head') != BASE
                or Path(manifest.get('repo', '')).resolve() != REPO or not manifest.get('runtime', {}).get('credential_scan_python3')):
            raise ValueError('staged source manifest schema/repo/head/runtime mismatch')
        receipt['source_manifest_sha256'] = filehash(manifest_path)
        spec = json.loads((REPO / SPEC_PATH).read_text())
        receipt.update({'staged_base': BASE, 'head': git('rev-parse', 'HEAD').decode().strip(),
                        'worktree_status': git('status', '--porcelain').decode(),
                        'author': spec['author'], 'spec_sha256': filehash(REPO / SPEC_PATH), 'hashes_before': hashes()})
        receipt['material_commits'] = git('log', '--format=%H%n%B', BASE + '..HEAD').decode()
        receipt['staged_runtime'] = manifest['runtime']
        if filehash(REPO / SOURCE) != BASE_HASH and args.suite == 'baseline':
            raise ValueError('baseline product bytes drifted')
        if args.suite == 'baseline' and receipt['head'] != BASE:
            raise ValueError('baseline must run at staged base')
        if not (REPO / '.venv').exists() or not (REPO / 'node_modules').is_dir():
            raise ValueError('missing operator-staged runtime closure; no install/fallback')
        for rel in REGRESSION + ['scripts/check_repository.py', 'package.json', 'pnpm-lock.yaml']:
            if filehash(REPO / rel) != digest(git('show', BASE + ':' + rel)):
                raise ValueError('read-only original drift: ' + rel)
        node, pnpm = shutil.which('node'), manifest['runtime'].get('pnpm')
        if not node or not pnpm or not Path(pnpm).is_file():
            raise ValueError('missing installed node/pnpm; operator staging required')
        receipt['node'] = {'path': node, 'resolved': str(Path(node).resolve())}
        version = invoke([node, '--version'], 'node-version', out, suite=args.suite, timed=30)
        receipt['invocations'].append(version)
        receipt['node']['version'] = (out / version['stdout']).read_text().strip()
        if version['exit'] or not re.fullmatch(r'v(?:22\.(?:1[89]|[2-9]\d)|(?:2[3-9]|[3-9]\d)\.\d+)\.\d+', receipt['node']['version']):
            raise ValueError('installed Node lacks repository-supported type stripping')
        if args.suite in ('baseline', 'focused', 'regression'):
            files = REGRESSION if args.suite == 'regression' else [TEST]
            argv = [node, '--experimental-strip-types', '--import', str(REPO / BOOTSTRAP),
                    '--test', '--test-reporter=tap', '--test-concurrency=1', *files]
            inv = invoke(argv, args.suite, out, suite=args.suite)
            receipt['invocations'].append(inv)
            if args.suite == 'regression':
                # Original tests are literal top-level test/dbTest registrations; zero omissions.
                names = re.findall(r"^(?:test|dbTest)\('((?:\\.|[^'\\])*)'", (REPO / REGRESSION[0]).read_text(), re.M)
                names = [n.replace("\\'", "'").replace('\\\\', '\\') for n in names]
            else:
                names = PAIRS if args.suite == 'baseline' else expected_tests()
            receipt['problems'] += verify_tests(inv, names, args.suite == 'baseline', out)
        else:
            if args.suite == 'repository':
                # Preserve lexical venv interpreter for execution; resolving it would discard venv context.
                scanner = manifest['runtime']['credential_scan_python3']
                if not Path(scanner).is_absolute() or not Path(scanner).is_file():
                    raise ValueError('missing staged credential scanner; no system Python fallback')
                receipt['credential_scan_python3'] = {'literal': scanner, 'resolved': str(Path(scanner).resolve())}
                jobs = [('repository', [scanner, 'scripts/check_repository.py'])]
            elif args.suite == 'typecheck':
                jobs = [(f'typecheck-{i}', [pnpm, 'exec', 'tsc', '--noEmit', '-p', p])
                        for i, p in enumerate(['tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json'], 1)]
            else:
                jobs = [('build', [pnpm, 'build'])]
            for label, argv in jobs:
                inv = invoke(argv, label, out, suite=args.suite)
                receipt['invocations'].append(inv)
                if inv['exit']:
                    receipt['problems'].append(f'{label}: exit {inv["exit"]}')
        receipt['hashes_after'] = hashes()
        if receipt['hashes_before'] != receipt['hashes_after']:
            receipt['problems'].append('authored source/test/fixture bytes changed during run')
        if receipt['head'] != git('rev-parse', 'HEAD').decode().strip():
            receipt['problems'].append('HEAD changed during run')
    except (OSError, ValueError, RuntimeError, KeyError) as e:
        receipt['problems'].append(str(e))
    verdict = 'FAIL' if receipt['problems'] else ('BASELINE_GAP_REPRODUCED' if args.suite == 'baseline' else 'SCOPED_PASS_REVIEW_REQUIRED')
    receipt['verdict'] = verdict
    receipt['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    dest = out / 'receipt.json'
    dest.write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'SP1406-ALERT-CHECK {args.suite}: {verdict}')
    for inv in receipt['invocations']:
        print(f'  {inv["label"]}: exit {inv["exit"]} {inv["counts"]}')
    for problem in receipt['problems']:
        print('  problem: ' + problem)
    print(f'  receipt {dest} sha256 {filehash(dest)}')
    return int(bool(receipt['problems']))


if __name__ == '__main__':
    raise SystemExit(main())
