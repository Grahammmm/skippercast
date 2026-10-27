"""Offline, in-process SC54 acceptance with unique, self-identifying receipts."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REGRESSION = 'tests/unit/test_sc54_regression.py'
COMPATIBILITY = 'tests/contract/test_seafloor_source_rights.py'
COMPAT_METHODS = {
    'test_reviewed_ventresca_original_can_qualify_with_same_producer_restrictions': 4,
    'test_exact_macginitie_products_require_unchanged_producer_review': 20,
    'test_unreviewed_or_lookalike_cruise_archives_remain_rejected': 4,
    'test_checked_noncommercial_producer_contract_can_qualify_without_inventing_public_domain': 0,
    'test_missing_conflicting_or_fabricated_permissions_do_not_qualify': 13,
    'test_mixed_source_terms_and_unknown_contributors_cannot_disappear': 0,
}
PINS = {
    COMPATIBILITY: '34426c86d2e868fd0e038a761295535c756cb382f937b6f5d00c79d9189db6c8',
    'scripts/check_repository.py': 'cf39ee4dab44893fae58d4553c8a159942c5674f5ce33f22ca9c441d0a74dec8',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_identity():
    """Hash candidate sources/fixtures without invoking git or a child process."""
    files = {ROOT / REGRESSION, Path(__file__).resolve(), ROOT / COMPATIBILITY,
             ROOT / 'scripts/check_repository.py'}
    for directory in ('src', 'tests/fixtures'):
        files.update(path for path in (ROOT / directory).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts)
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(files)}


def git_head():
    git = ROOT / '.git'
    head = (git / 'HEAD').read_text().strip()
    if head.startswith('ref: '):
        ref = head[5:]
        loose = git / ref
        if loose.is_file():
            head = loose.read_text().strip()
        else:
            matches = [line.split()[0] for line in (git / 'packed-refs').read_text().splitlines()
                       if not line.startswith(('#', '^')) and line.endswith(' ' + ref)]
            if len(matches) != 1:
                raise RuntimeError('Cannot resolve candidate HEAD')
            head = matches[0]
    if len(head) != 40 or any(c not in '0123456789abcdef' for c in head):
        raise RuntimeError('Malformed candidate HEAD')
    return head


class Results:
    def __init__(self):
        self.collected = []
        self.reports = []

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report):
        self.reports.append({'nodeid': report.nodeid, 'when': report.when,
                             'subtest': hasattr(report, 'context'),
                             'outcome': report.outcome, 'detail': str(report.longrepr or '')})


def install_guards(violations):
    """Defense-in-depth seams, not a sandbox; any attempted I/O fails acceptance."""
    def refuse(*args, **kwargs):
        violations.append('network-or-subprocess seam')
        raise RuntimeError('SC54 offline network/subprocess boundary')

    def audit(event, args):
        if (event.startswith(('subprocess.', 'os.exec', 'os.spawn', 'os.posix_spawn'))
                or event in {'socket.connect', 'socket.connect_ex', 'socket.bind',
                             'socket.getaddrinfo', 'socket.gethostbyname',
                             'socket.gethostbyaddr', 'socket.sendto', 'os.system',
                             'os.fork', 'os.forkpty', 'pty.spawn'}):
            violations.append(event)
            raise RuntimeError('SC54 offline network/subprocess audit boundary')

    sys.addaudithook(audit)
    for name in ('connect', 'connect_ex', 'bind', 'listen', 'sendto'):
        setattr(socket.socket, name, refuse)
    for name in ('create_connection', 'getaddrinfo', 'gethostbyname', 'gethostbyname_ex',
                 'gethostbyaddr', 'getnameinfo'):
        setattr(socket, name, refuse)
    subprocess.Popen = refuse
    for name in ('system', 'popen', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp'):
        if hasattr(os, name):
            setattr(os, name, refuse)
    for name in dir(os):
        if name.startswith(('exec', 'spawn')):
            setattr(os, name, refuse)


def module_origins():
    origins = {}
    for name, module in sorted(sys.modules.items()):
        if name.split('.')[0] not in {'skippercast', 'tests', 'research'}:
            continue
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if not path.is_relative_to(ROOT):
                raise RuntimeError(f'Ambient module refused: {name}')
            origins[name] = str(path)
    if 'skippercast.seafloor.rights' not in origins:
        raise RuntimeError('Full candidate rights module was not exercised')
    return origins


def old_two_pass(source_ids, sources, *, use='noncommercial'):
    """Admitted in-memory mutation: exactly the original defective algorithm."""
    from skippercast.seafloor import rights
    if not source_ids or any(ident not in sources for ident in source_ids):
        raise ValueError('Feature source attribution is incomplete')
    return [rights.source_rights(sources[ident], use=use) for ident in sorted(set(source_ids))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True,
                        choices=('regression', 'mutation', 'compatibility', 'portability'))
    parser.add_argument('--output-root', type=Path, required=True)
    options = parser.parse_args()
    options.output_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix=f'sc54-{options.mode}-', dir=options.output_root)).resolve()
    home = run / ('portable-home' if options.mode == 'portability' else 'synthetic-home')
    home.mkdir()
    temporary = run / 'temporary'
    temporary.mkdir()
    os.environ['HOME'] = str(home)
    os.environ['TMPDIR'] = str(temporary)
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    os.environ.pop('SKIPPERCAST_ROOT', None)
    tempfile.tempdir = str(temporary)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
    violations = []
    install_guards(violations)
    receipt = {'argv': sys.argv, 'cwd': str(Path.cwd()), 'mode': options.mode,
               'repository': str(ROOT), 'run_directory': str(run), 'home': str(home),
               'material_author_runtime': 'gpt-6.1-sol/openai-codex; sol-reviewer; run 1486',
               'offline_violations': violations, 'runs': [], 'exit': 1}
    output = io.StringIO()
    error_output = io.StringIO()
    status = 1
    try:
        before = source_identity()
        receipt['head'] = git_head()
        receipt['source_identity'] = before
        for name, expected in PINS.items():
            if before[name] != expected:
                raise RuntimeError(f'Frozen input drift: {name}')
        if Path.home() != home:
            raise RuntimeError('Synthetic HOME was not established before candidate imports')
        import pytest
        # Recheck the admitted read-only runtime, under the offline seams.
        receipt['runtime'] = {name: importlib.import_module(name).__file__
                              for name in ('numpy', 'rasterio', 'pytest', 'jsonschema')}
        from skippercast.seafloor import rights
        receipt['module_origins'] = module_origins()
        subtests = []
        original_subtest = unittest.TestCase.subTest

        @contextmanager
        def counted_subtest(case, *args, **kwargs):
            subtests.append({'method': case._testMethodName, 'parameters': repr(kwargs)})
            with original_subtest(case, *args, **kwargs):
                yield

        def exercise(label, selectors, expected_count, expected_exit=0):
            result = Results()
            arguments = ['-q', '-p', 'no:cacheprovider', '--basetemp',
                         str(run / (('alternate-test-root-' if options.mode == 'portability'
                                     else 'test-root-') + label)), *selectors]
            with redirect_stdout(output), redirect_stderr(error_output):
                code = int(pytest.main(arguments, plugins=[result]))
            calls = [row for row in result.reports if row['when'] == 'call' and not row['subtest']]
            subtest_reports = [row for row in result.reports if row['subtest']]
            skipped = [row for row in result.reports if row['outcome'] == 'skipped']
            failed = [row for row in result.reports if row['outcome'] == 'failed']
            item = {'label': label, 'pytest_argv': arguments, 'exit': code,
                    'collected': result.collected, 'executed_count': len(calls),
                    'subtest_report_count': len(subtest_reports),
                    'subtest_reports': subtest_reports,
                    'skips': skipped, 'failures': failed}
            receipt['runs'].append(item)
            if code != expected_exit or len(result.collected) != expected_count or len(calls) != expected_count or skipped:
                raise RuntimeError(f'{label}: unexpected exit/count/skip: {code}/{len(calls)}/{len(skipped)}')
            if expected_exit == 0 and failed:
                raise RuntimeError(f'{label}: unexpected test failure')
            return item

        with patch.object(unittest.TestCase, 'subTest', counted_subtest):
            if options.mode == 'compatibility':
                selectors = [f'{COMPATIBILITY}::SourceRightsTests::{name}' for name in COMPAT_METHODS]
                exercise('compatibility', selectors, len(COMPAT_METHODS))
                counts = {name: sum(row['method'] == name for row in subtests) for name in COMPAT_METHODS}
                receipt['subtests'] = subtests
                receipt['subtest_counts'] = counts
                if counts != COMPAT_METHODS:
                    raise RuntimeError('Compatibility subtest coverage differs from the frozen cases')
            elif options.mode == 'mutation':
                original = rights.feature_rights
                with patch.object(rights, 'feature_rights', old_two_pass):
                    negative = exercise('old-generator', [f'{REGRESSION}::test_generator_preservation'], 1, 1)
                    if len(negative['failures']) != 1 or 'SC54 contributor terms lost or changed' not in negative['failures'][0]['detail']:
                        raise RuntimeError('Mutation failed for an unintended reason')
                    exercise('old-list-positive', [f'{REGRESSION}::test_list_positive'], 1)
                if rights.feature_rights is not original:
                    raise RuntimeError('In-memory mutation was not restored')
                exercise('restored-regression', [REGRESSION], 33)
                receipt['mutation_restored'] = True
            else:
                exercise(options.mode, [REGRESSION], 33)
        receipt['module_origins'] = module_origins()
        receipt['inputs_unchanged'] = source_identity() == before
        receipt['home_unchanged'] = Path.home() == home
        receipt['unique_output'] = run.parent == options.output_root.resolve()
        receipt['offline_violations'] = violations
        if violations or not all(receipt[key] for key in ('inputs_unchanged', 'home_unchanged', 'unique_output')):
            raise RuntimeError('Offline/portability/preservation invariant failed')
        status = 0
    except Exception as error:
        import traceback
        with redirect_stderr(error_output):
            traceback.print_exc()
        receipt['error'] = f'{type(error).__name__}: {error}'
    finally:
        receipt['exit'] = status
        stdout = run / 'stdout.txt'
        stderr = run / 'stderr.txt'
        stdout.write_text(output.getvalue(), encoding='utf-8')
        stderr.write_text(error_output.getvalue(), encoding='utf-8')
        receipt['raw_output'] = {path.name: digest(path) for path in (stdout, stderr)}
        (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print(output.getvalue(), end='')
        print(error_output.getvalue(), end='', file=sys.stderr)
        print(json.dumps({'receipt': str(run / 'receipt.json'), 'exit': status,
                          'executed_counts': [row['executed_count'] for row in receipt['runs']]}))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
