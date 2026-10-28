#!/usr/bin/env python3
"""Offline, fail-closed SP-18-v1 acceptance; never a release/semantic gate."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
PRODUCT = 'src/skippercast/platform/sectors.py'
BASE_HASH = '4ec857aa65fff57b52735cce51867512f15661b27d7533ac30f451d5f70ee915'
TEST = 'tests/unit/test_sp1807_sector_endpoint.py'
FIXTURES = 'tests/fixtures/sp1807_sector_endpoint'
PRIMARY = 'tests.unit.test_sp1807_sector_endpoint.BaselineTests.test_primary_regression'
HEALTHY = 'tests.unit.test_sp1807_sector_endpoint.BaselineTests.test_healthy_control'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def identity():
    files = [PRODUCT, TEST, 'scripts/accept_sp1807_sector_endpoint.py',
             'tests/contract/test_coastal_sectors.py', 'tests/_support.py',
             'scripts/check_repository.py', 'catalog/coasts.json',
             'catalog/coastal-sectors.json', 'package.json', 'pnpm-lock.yaml']
    files += [str(p.relative_to(ROOT)) for p in sorted((ROOT / FIXTURES).rglob('*')) if p.is_file()]
    note = 'docs/engineering/sp1807_sector_endpoint.md'
    if (ROOT / note).exists():
        files.append(note)
    return {'head': git('rev-parse', 'HEAD'), 'base': BASE,
            'status': git('status', '--porcelain'),
            'sha256': {name: digest(ROOT / name) for name in files}}


def deny(*args, **kwargs):
    raise RuntimeError('SP1807 offline sentinel: network/model/child execution forbidden')


def copy_static(work):
    """Only the static catalog/config/atlas closure of the unchanged old suite."""
    def copy(relative):
        source = ROOT / relative
        if not source.resolve().is_relative_to(ROOT) or source.is_symlink():
            raise RuntimeError('Static compatibility input escapes staged repository')
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for name in ('catalog/coastal-sectors.json', 'catalog/coasts.json', 'dist/regions/index.json'):
        copy(name)
    packages = json.loads((work / 'dist/regions/index.json').read_text())['regions']
    for package in packages:
        config = f"regions/{package['id']}/region.json"
        copy(config)
        atlas = json.loads((work / config).read_text())['assets']['atlas']
        copy('dist/' + atlas)


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []

    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)


def child(args):
    # This bootstrap is an explicit script argv, never inline interpreter source.
    # No environment-based import path; restore patches at process teardown.
    sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
    report_path = Path(args.report).resolve()
    work = report_path.parent / 'work'
    work.mkdir()
    temporary = work / 'temporary'
    temporary.mkdir()
    with ExitStack() as stack:
        for name in ('connect', 'connect_ex'):
            stack.enter_context(patch.object(socket.socket, name, deny))
        for name in ('getaddrinfo', 'create_connection'):
            stack.enter_context(patch.object(socket, name, deny))
        stack.enter_context(patch.object(subprocess, 'Popen', deny))
        stack.enter_context(patch.object(tempfile, 'tempdir', str(temporary)))
        if args.child == 'regression':
            copy_static(work)
            from skippercast import paths
            stack.enter_context(patch.object(paths, 'repo_root', lambda: work))
            from skippercast.platform import contracts
            stack.enter_context(patch.object(contracts, 'REPO', work))
            # Bound default is formed only after the constant has been redirected.
            from skippercast.platform import sectors
            stack.enter_context(patch.object(sectors, 'REPO', work))
            stack.enter_context(patch.object(sectors.compile_sectors, '__defaults__', (work,)))
            real_read, real_write = contracts.read_json, contracts.atomic_json

            def confined(path):
                path = Path(path).resolve()
                if not path.is_relative_to(work):
                    raise RuntimeError('SP1807 live-store sentinel: compatibility path escape')
                return path

            stack.enter_context(patch.object(sectors, 'read_json', lambda p: real_read(confined(p))))
            stack.enter_context(patch.object(sectors, 'atomic_json', lambda p, v: real_write(confined(p), v)))
            from tests import _support
            stack.enter_context(patch.object(_support, 'ROOT', work))
        suite = unittest.defaultTestLoader.loadTestsFromNames(args.selectors)
        result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
        report = {'tests_run': result.testsRun, 'ids': getattr(result, 'ids'),
                  'failures': [{'id': t.id(), 'traceback': text} for t, text in result.failures],
                  'errors': [{'id': t.id(), 'traceback': text} for t, text in result.errors],
                  'skips': [{'id': t.id(), 'reason': reason} for t, reason in result.skipped],
                  'expected_failures': len(result.expectedFailures),
                  'unexpected_successes': len(result.unexpectedSuccesses),
                  'python': sys.version, 'executable': sys.executable}
        save(report_path, report)
        return 0 if result.wasSuccessful() and not result.skipped and result.testsRun > 0 else 1


def run_row(run, label, argv, *, expected=0, test_count=None):
    directory = run / label
    directory.mkdir()
    started = time.monotonic()
    completed = subprocess.run(argv, cwd=ROOT, capture_output=True, check=False)
    elapsed = time.monotonic() - started
    stdout, stderr = directory / 'stdout.txt', directory / 'stderr.txt'
    stdout.write_bytes(completed.stdout)
    stderr.write_bytes(completed.stderr)
    report_path = directory / 'tests.json'
    tests = json.loads(report_path.read_text()) if report_path.exists() else None
    record = {'label': label, 'argv': argv, 'cwd': str(ROOT), 'exit': completed.returncode,
              'expected_exit': expected, 'elapsed_seconds': elapsed,
              'stdout': {'path': str(stdout), 'sha256': digest(stdout)},
              'stderr': {'path': str(stderr), 'sha256': digest(stderr)}, 'tests': tests}
    if tests is not None:
        record['tests_report_sha256'] = digest(report_path)
    record['passed'] = completed.returncode == expected
    if test_count is not None:
        record['passed'] = record['passed'] and tests is not None
        if tests is not None:
            record['passed'] = record['passed'] and tests['tests_run'] == test_count and not tests['errors'] and not tests['skips'] and not tests['expected_failures'] and not tests['unexpected_successes']
    save(directory / 'receipt.json', record)
    print(f"{label}: exit={completed.returncode}, tests={tests['tests_run'] if tests else 'n/a'}, passed={record['passed']}", flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['baseline', 'focused', 'regression', 'repository'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child', choices=['unit', 'regression'])
    parser.add_argument('--report')
    parser.add_argument('--runtime-info', action='store_true')
    parser.add_argument('selectors', nargs='*')
    args = parser.parse_args()
    if args.runtime_info:
        print(json.dumps({'executable': sys.executable, 'version': sys.version}))
        return 0
    if args.child:
        if not args.report or not args.selectors:
            parser.error('child requires report and selectors')
        return child(args)
    if not args.phase or not args.output:
        parser.error('phase and output are required')
    output = args.output.resolve()
    # Only a new unique evidence directory in this candidate, never fixture input.
    allowed = ROOT.parent / 'out'
    if not output.is_relative_to(allowed) or output == allowed:
        parser.error('output must be a child of the candidate out directory')
    output.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=output))
    manifest_path = ROOT.parent / 'SOURCE-MANIFEST.json'
    receipt = {'schema': 'skippercast.sp1807-acceptance/v1', 'spec': 'SP-18-v1',
               'scope': 'SP1807-SECTOR-ENDPOINT', 'phase': args.phase,
               'started_at': datetime.now(timezone.utc).isoformat(), 'rows': [],
               'status': 'ERROR', 'meaning': 'REVIEW REQUIRED, not release or semantic acceptance'}
    code = 1
    try:
        manifest = json.loads(manifest_path.read_text())
        if (manifest['schema'] != 'agentorange.source-manifest/v1' or manifest['head'] != BASE
                or Path(manifest['repo']).resolve() != ROOT or manifest['card'] != 'SP1807-SECTOR-ENDPOINT'):
            raise RuntimeError('Invalid standard source manifest identity')
        git('merge-base', '--is-ancestor', BASE, 'HEAD')
        receipt['source_manifest_sha256'] = digest(manifest_path)
        receipt['before'] = identity()
        receipt['launcher_runtime'] = {'executable': sys.executable, 'version': sys.version}
        python = ROOT / '.venv/bin/python3'
        if not python.exists():
            raise RuntimeError('Missing standard staged Python runtime; no substitution')
        receipt['test_runtime'] = str(python.resolve())

        def unit(label, selectors, count, expected=0, mode='unit'):
            argv = [str(python), str(Path(__file__).resolve()), '--child', mode,
                    '--report', str(run / label / 'tests.json'), *selectors]
            row = run_row(run, label, argv, expected=expected, test_count=count)
            receipt['rows'].append(row)
            return row

        if args.phase == 'baseline':
            if receipt['before']['sha256'][PRODUCT] != BASE_HASH:
                raise RuntimeError('Baseline requires unchanged pinned product bytes')
            primary = unit('primary-red', [PRIMARY], 1, expected=1)
            healthy = unit('healthy-green', [HEALTHY], 1)
            tests = primary['tests']
            exact = (tests is not None and len(tests['failures']) == 1
                     and tests['failures'][0]['id'] == PRIMARY
                     and 'A1 terminal northern target must not disappear' in tests['failures'][0]['traceback']
                     and '[1, 1] != [1, 2]' in tests['failures'][0]['traceback'])
            if not primary['passed'] or not healthy['passed'] or not exact:
                raise RuntimeError('Unexpected baseline: internal operator disposition required')
            receipt['status'] = 'BASELINE_GAP_REPRODUCED'
        elif args.phase == 'focused':
            row = unit('focused', ['tests.unit.test_sp1807_sector_endpoint'], 13)
            if not row['passed']:
                raise RuntimeError('Focused suite failed')
            receipt['status'] = 'SCOPED_PASS_REVIEW_REQUIRED'
        elif args.phase == 'regression':
            row = unit('coastal-sectors', ['tests.contract.test_coastal_sectors'], 2, mode='regression')
            if not row['passed']:
                raise RuntimeError('Unchanged compatibility suite failed')
            receipt['status'] = 'SCOPED_PASS_REVIEW_REQUIRED'
        else:
            runtime = manifest['runtime']
            scanner = Path(runtime['credential_scan_python3'])
            pnpm = Path(runtime['pnpm'])
            if not scanner.is_file() or not pnpm.is_file():
                raise RuntimeError('Missing admitted scanner/pnpm runtime; no substitution')
            commands = [
                ('scanner-runtime', [str(scanner), str(Path(__file__).resolve()), '--runtime-info']),
                ('node-runtime', ['node', '--version']),
                ('pnpm-runtime', [str(pnpm), '--version']),
                ('repository', [str(scanner), str(ROOT / 'scripts/check_repository.py')])]
            commands += [(f'typecheck-{i}', [str(pnpm), 'exec', 'tsc', '--noEmit', '--project', project])
                         for i, project in enumerate(('tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json'), 1)]
            commands.append(('build', [str(pnpm), 'build']))
            for label, argv in commands:
                row = run_row(run, label, argv)
                if label == 'repository':
                    match = re.search(rb'Checked (\d+) text files:', (run / label / 'stdout.txt').read_bytes())
                    row['checked_files'] = int(match.group(1)) if match else 0
                    row['passed'] = row['passed'] and row['checked_files'] > 0
                    save(run / label / 'receipt.json', row)
                receipt['rows'].append(row)
                if not row['passed']:
                    raise RuntimeError(f'{label} failed; remaining production-like rows not run')
            receipt['status'] = 'SCOPED_PASS_REVIEW_REQUIRED'
        receipt['after'] = identity()
        if receipt['before'] != receipt['after']:
            raise RuntimeError('Source identity changed during acceptance')
        code = 0
    except Exception as error:
        receipt['status'] = 'ERROR'
        receipt['error'] = f'{type(error).__name__}: {error}'
        print(receipt['error'], file=sys.stderr)
    receipt['exit'] = code
    receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
    save(run / 'receipt.json', receipt)
    print(f"{receipt['status']}: {run / 'receipt.json'}", flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
