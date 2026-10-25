#!/usr/bin/env python3
"""Bounded SC168 acceptance: complete offline APIs, retained unique evidence."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
SELECTORS = [
    'tests/gis/test_coast_sign_off_graph.py::test_normal_sample_and_chain_idempotency',
    'tests/gis/test_coast_sign_off_graph.py::test_cross_ledger_crash_reconciliation',
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


class Recorded(unittest.TextTestResult):
    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []


class Originals:
    def __init__(self):
        self.ids, self.reports = [], []

    def pytest_collection_modifyitems(self, items):
        self.ids = [i.nodeid for i in items]

    def pytest_runtest_logreport(self, report):
        self.reports.append({'id': report.nodeid, 'phase': report.when, 'outcome': report.outcome})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.source_manifest.read_text())
    if (manifest.get('schema') != 'agentorange.source-manifest/v1'
            or manifest.get('repo') != str(ROOT) or manifest.get('write_root') != str(ROOT.parent)
            or manifest.get('head') != BASE
            or manifest.get('runtime', {}).get('credential_scan_python3') !=
            str(ROOT.parent.parent.parent / 'tools/venv-fullsuite/bin/python3')):
        raise ValueError('staging manifest mismatch')
    if not args.out.resolve().is_relative_to(ROOT.parent / 'out'):
        raise ValueError('output must be under candidate sibling out')
    if not git('merge-base', BASE, 'HEAD') == BASE:
        raise ValueError('candidate not based on admitted pin')
    args.out.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=args.out))
    metadata = {'schema': 'sc168.acceptance/v1', 'argv': sys.argv, 'cwd': str(Path.cwd()),
                'interpreter': sys.executable, 'base': BASE, 'head': git('rev-parse', 'HEAD'),
                'baseline': False, 'source_manifest_sha256': sha(args.source_manifest),
                'spec_sha256': sha(ROOT.parent / 'SPEC.json'),
                'product_sha256': sha(ROOT / 'skills/coast-campaign-shared/scripts/coast_ledger.py')}
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
    from tests.unit import test_sc168_ledger_distinct as tests
    tests.LedgerDistinctTests.output_parent = out
    names = list(tests.EXPECTED)
    plugin = Originals()
    with (out / 'stdout.log').open('w') as stdout, (out / 'stderr.log').open('w') as stderr:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            suite = unittest.TestSuite(tests.LedgerDistinctTests(name) for name in names)
            result = unittest.TextTestRunner(stream=stderr, verbosity=2, resultclass=Recorded).run(suite)
            original_root = out / 'originals'
            original_root.mkdir()
            with tests.offline(original_root) as (_, origins):
                import pytest
                pytest_exit = int(pytest.main([*SELECTORS, '-v', '-p', 'no:cacheprovider',
                                              '--basetemp', str(original_root / 'basetemp')], plugins=[plugin]))
    expected = [{'method': method, 'case': case} for method in names for case in tests.EXPECTED[method]]
    calls = [r['id'] for r in plugin.reports if r['phase'] == 'call' and r['outcome'] == 'passed']
    original_ok = (pytest_exit == 0 and sorted(plugin.ids) == sorted(SELECTORS)
                   and sorted(calls) == sorted(SELECTORS)
                   and all(r['outcome'] == 'passed' for r in plugin.reports))
    ok = (result.wasSuccessful() and not result.skipped and result.testsRun == len(names)
          and tests.LedgerDistinctTests.events == expected and original_ok)
    metadata.update(status='PASS_REVIEW_REQUIRED' if ok else 'FAIL', exit=0 if ok else 1,
                    tests_run=result.testsRun, ids=result.ids,
                    subcases=tests.LedgerDistinctTests.events,
                    expected_subcase_count=len(expected), actual_subcase_count=len(tests.LedgerDistinctTests.events),
                    failures=[{'id': str(t), 'trace': trace} for t, trace in result.failures],
                    errors=[{'id': str(t), 'trace': trace} for t, trace in result.errors],
                    skips=[str(t) for t, _ in result.skipped],
                    origins=tests.LedgerDistinctTests.origins, original_origins=origins,
                    original_selectors=plugin.ids, original_reports=plugin.reports, pytest_exit=pytest_exit,
                    negative_control=tests.LedgerDistinctTests.control,
                    fixture_hashes=tests.snapshot(tests.LedgerDistinctTests.run_root),
                    logs={name: sha(out / name) for name in ('stdout.log', 'stderr.log')})
    (out / 'result.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print((out / 'stdout.log').read_text(), end='')
    print((out / 'stderr.log').read_text(), file=sys.stderr, end='')
    print(json.dumps({'result': str(out / 'result.json'), 'status': metadata['status'],
                      'tests': result.testsRun, 'subcases': len(tests.LedgerDistinctTests.events),
                      'originals': len(calls), 'exit': metadata['exit']}))
    return metadata['exit']


if __name__ == '__main__':
    raise SystemExit(main())
