"""SP-15-v1 offline acceptance; explicit children, immutable per-invocation receipts.

Run from the clone. SOURCE-MANIFEST.json is an operator staging input outside
this repo, never an imported implementation or a test fixture. Tests also use
the scoped/restorable offline_boundary during ordinary unittest/pytest discovery.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import platform
import re
import runpy
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
PRIMARY = 'src/skippercast/fleet/ais/classify.py'
PRIMARY_SHA = '42d7586f779070adbaf62eb39d0e830499e2f3ef28a78667aeabd1dffec572fa'
TEST = 'tests.unit.test_sp1510_classifier_identity.ClassifierIdentityTest'
PAIR = [TEST + '.test_primary_regression', TEST + '.test_healthy_control']
SPEC = 'SP-15-v1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')


def deny(*args, **kwargs):
    raise RuntimeError('SP1510 offline sentinel: network/model/store/process access forbidden')


class NoLiveImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefixes = ('openai', 'anthropic', 'ollama', 'skippercast.fleet.ais.listener',
                    'skippercast.fleet.ais.process', 'skippercast.fleet.ais.backfill',
                    'skippercast.fleet.ais.ws', 'skippercast.fleet.sink')
        if any(fullname == p or fullname.startswith(p + '.') for p in prefixes):
            deny()
        return None


@contextmanager
def offline_boundary(root):
    """Guards precede product imports; no irreversible audit hooks or peer pollution.

    store's complete module is safe to import (no eager I/O); block its actual
    entrypoints immediately, before the classifier/test can execute. Paths are
    anchored before imports bind defaults/REPO. No planner doubles are used.
    """
    root = Path(root).resolve()
    with ExitStack() as stack:
        for obj, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                          (socket, 'create_connection'), (socket, 'getaddrinfo'),
                          (urllib.request, 'urlopen'), (sqlite3, 'connect'),
                          (subprocess, 'Popen'), (os, 'system')):
            stack.enter_context(patch.object(obj, name, deny))
        finder = NoLiveImports()
        sys.meta_path.insert(0, finder)
        stack.callback(sys.meta_path.remove, finder)
        from skippercast import paths
        stack.enter_context(patch.object(paths, 'repo_root', lambda: root))
        # AIS __init__ imports store, which only defines APIs; no connection is opened.
        from skippercast.fleet.ais import store
        stack.enter_context(patch.object(store, 'fleet_var', lambda environ=None: root / 'var/offline-sp1510'))
        for name in ('connect', 'write', 'days', 'positions', 'statics', 'retain'):
            if hasattr(store.AisStore, name):
                stack.enter_context(patch.object(store.AisStore, name, deny))
        yield


def runtime():
    return {'executable': sys.executable, 'version': sys.version, 'platform': platform.platform()}


def imported_sources():
    sources = {}
    for name, module in list(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if not filename or not name.startswith(('skippercast', 'tests', 'scripts.accept_sp1510')):
            continue
        path = Path(filename).resolve()
        if not path.is_relative_to(ROOT):
            raise RuntimeError(f'Import escaped candidate: {name}')
        if path.is_file():
            sources[path.relative_to(ROOT).as_posix()] = digest(path)
    return sources


class ReceiptResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = []
        self.subtests = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes.append({'id': test.id(), 'outcome': 'passed'})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes.append({'id': test.id(), 'outcome': 'failure',
                              'exception': err[0].__name__, 'message': str(err[1])})

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes.append({'id': test.id(), 'outcome': 'error', 'exception': err[0].__name__})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes.append({'id': test.id(), 'outcome': 'skipped', 'reason': reason})

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.subtests.append({'id': subtest.id(), 'outcome': 'passed' if err is None else 'failed'})


def child(args):
    # These paths override installed editable checkouts before any product import.
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
    report = {'runtime': runtime(), 'cwd': str(Path.cwd()), 'selectors': args.selectors}
    with offline_boundary(ROOT):
        if args.child == 'unittest':
            results = []
            original_runner = unittest.TextTestRunner

            class Runner(original_runner):
                resultclass = ReceiptResult

                def run(self, test):
                    result = super().run(test)
                    results.append(result)
                    return result

            code = 2
            with patch.object(unittest.runner, 'TextTestRunner', Runner):
                sys.argv = ['python3 -m unittest', '-v', *args.selectors]
                try:
                    runpy.run_module('unittest', run_name='__main__', alter_sys=True)
                except SystemExit as error:
                    code = int(error.code or 0)
            if len(results) != 1:
                raise RuntimeError('unittest did not produce exactly one result')
            result = results[0]
            report.update(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                          skips=len(result.skipped), expected_failures=len(result.expectedFailures),
                          unexpected_successes=len(result.unexpectedSuccesses), outcomes=result.outcomes,
                          subtests=result.subtests)
        else:
            import pytest

            class Plugin:
                def __init__(self):
                    self.collected = 0
                    self.reports = []

                def pytest_collection_finish(self, session):
                    self.collected = len(session.items)

                def pytest_runtest_logreport(self, report):
                    self.reports.append({'id': report.nodeid, 'phase': report.when, 'outcome': report.outcome})

            plugin = Plugin()
            code = int(pytest.main(['-v', '-p', 'no:cacheprovider', *args.selectors], plugins=[plugin]))
            report.update(tests=plugin.collected, outcomes=plugin.reports,
                          failures=sum(r['outcome'] == 'failed' for r in plugin.reports),
                          errors=0, skips=sum(r['outcome'] == 'skipped' for r in plugin.reports))
        report['imported_sources'] = imported_sources()
    report['exit'] = code
    write_json(args.report, report)
    return code


def git(*argv):
    proc = subprocess.run(['git', '-C', str(ROOT), *argv], capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def source_identity():
    names = [PRIMARY, 'scripts/accept_sp1510_classifier_identity.py',
             'tests/unit/test_sp1510_classifier_identity.py', 'tests/unit/test_fleet_classify.py',
             'tests/fixtures/sp1510_classifier_identity/synthetic.json']
    note = 'docs/engineering/sp1510_classifier_identity.md'
    if (ROOT / note).exists():
        names.append(note)
    return {'head': git('rev-parse', 'HEAD'), 'status': git('status', '--porcelain'),
            'files': {name: digest(ROOT / name) for name in names}}


def launcher(args):
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError('Acceptance cwd must be this clone')
    manifest_path = ROOT.parent / 'SOURCE-MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get('schema') != 'agentorange.source-manifest/v1' or manifest.get('head') != BASE
            or Path(manifest['repo']).resolve() != ROOT or manifest.get('card') != 'SP1510-CLASSIFIER-IDENTITY'):
        raise RuntimeError('Staging manifest identity mismatch')
    py = Path(manifest['runtime']['pytest_python3'])
    scanner = Path(manifest['runtime']['credential_scan_python3'])
    if not py.is_file() or not scanner.is_file() or not (ROOT / '.venv').is_dir():
        raise RuntimeError('Required staged runtime missing; no fallback/install')
    if git('merge-base', BASE, 'HEAD') != BASE:
        raise RuntimeError('Candidate does not descend from staged base')
    before = source_identity()
    if args.suite == 'baseline' and (before['head'] != BASE or before['files'][PRIMARY] != PRIMARY_SHA):
        raise RuntimeError('Baseline requires unchanged pinned product')
    out = Path(args.output).absolute()
    # Refuse symlink ancestry, including a link pointing back inside the output root.
    for ancestor in (out, *out.parents):
        if ancestor.is_symlink():
            raise RuntimeError('Output ancestry must not contain symlinks')
    if not out.is_relative_to(ROOT.parent / 'out'):
        raise RuntimeError('Output must be below candidate out, outside tracked source')
    out.mkdir(parents=True, exist_ok=True)
    run = out / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex)
    run.mkdir()
    receipt = {'spec': SPEC, 'card': 'SP1510-CLASSIFIER-IDENTITY', 'suite': args.suite,
               'source': before, 'stage_manifest_sha256': digest(manifest_path),
               'launcher_runtime': runtime(), 'launcher_argv': sys.argv, 'cwd': str(ROOT), 'children': []}
    if args.suite == 'repository':
        commands = [[str(scanner), '-B', str(ROOT / 'scripts/check_repository.py')]]
    else:
        selectors = PAIR if args.suite == 'baseline' else ([TEST] if args.suite == 'focused'
                                                         else ['tests.unit.test_fleet_classify'])
        commands = [[str(py), '-B', str(Path(__file__).resolve()), '--child', 'unittest',
                     '--report', str(run / 'unittest.json'), '--selectors', *selectors]]
        if args.suite == 'regression':
            commands.append([str(py), '-B', str(Path(__file__).resolve()), '--child', 'pytest',
                             '--report', str(run / 'pytest.json'), '--selectors', 'tests/unit/test_fleet_classify.py'])
    passed = True
    for index, argv in enumerate(commands):
        stdout, stderr = run / f'{index}.stdout.txt', run / f'{index}.stderr.txt'
        started = time.monotonic()
        with stdout.open('xb') as so, stderr.open('xb') as se:
            proc = subprocess.run(argv, cwd=ROOT, stdout=so, stderr=se, check=False)
        row = {'argv': argv, 'cwd': str(ROOT), 'elapsed_seconds': time.monotonic() - started,
               'exit': proc.returncode, 'stdout': str(stdout), 'stderr': str(stderr),
               'stdout_sha256': digest(stdout), 'stderr_sha256': digest(stderr)}
        if args.suite == 'repository':
            match = re.fullmatch(r'Checked (\d+) text files: .+ passed\.\n', stdout.read_text())
            ok = proc.returncode == 0 and bool(match) and not stderr.read_bytes()
            row['text_files_checked'] = int(match.group(1)) if match else None
            row['interpreter'] = str(scanner)
        else:
            report_path = Path(argv[argv.index('--report') + 1])
            report = json.loads(report_path.read_text()) if report_path.exists() else {}
            row['report'] = str(report_path)
            row['report_sha256'] = digest(report_path) if report_path.exists() else None
            row['summary'] = {k: report.get(k) for k in ('tests', 'failures', 'errors', 'skips', 'runtime')}
            if args.suite == 'baseline':
                outcomes = report.get('outcomes', [])
                ok = (proc.returncode == 1 and report.get('exit') == 1 and report.get('tests') == 2
                      and report.get('failures') == 1 and report.get('errors') == 0 and report.get('skips') == 0
                      and len(outcomes) == 2 and outcomes[0].get('id') == PAIR[0]
                      and outcomes[0].get('outcome') == 'failure'
                      and outcomes[0].get('exception') == 'AssertionError'
                      and 'A1_FINGERPRINT_COLLISION' in outcomes[0].get('message', '')
                      and outcomes[1] == {'id': PAIR[1], 'outcome': 'passed'})
            else:
                ok = (proc.returncode == 0 and report.get('exit') == 0 and report.get('tests', 0) > 0
                      and all(report.get(k) == 0 for k in ('failures', 'errors', 'skips'))
                      and report.get('unexpected_successes', 0) == 0
                      and report.get('expected_failures', 0) == 0)
                if args.suite == 'focused':
                    ok = ok and report.get('tests') == 8
        row['contract_passed'] = bool(ok)
        receipt['children'].append(row)
        passed = passed and bool(ok)
        # Never launch the next child after an unexpected failure.
        if not ok:
            break
    receipt['source_after'] = source_identity()
    passed = passed and receipt['source_after'] == before
    receipt['verdict'] = ('BASELINE_GAP_REPRODUCED' if args.suite == 'baseline' else 'SCOPED_GREEN_REVIEW_REQUIRED') if passed else 'FAILED'
    write_json(run / 'receipt.json', receipt)
    print(json.dumps({'verdict': receipt['verdict'], 'receipt': str(run / 'receipt.json'),
                      'sha256': digest(run / 'receipt.json'), 'children': [r['summary'] if 'summary' in r else r['text_files_checked'] for r in receipt['children']]}))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=['baseline', 'focused', 'regression', 'repository'])
    parser.add_argument('--output')
    parser.add_argument('--child', choices=['unittest', 'pytest'])
    parser.add_argument('--report')
    parser.add_argument('--selectors', nargs='+')
    args = parser.parse_args()
    if args.child:
        if not args.report or not args.selectors:
            parser.error('child requires report and selectors')
        return child(args)
    if not args.suite or not args.output:
        parser.error('launcher requires suite and output')
    return launcher(args)


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
