"""Offline, in-process N3 acceptance; separate invocations and unique receipts."""
import argparse
import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
# Current PR base; keep the protected byte checks explicit and fail closed.
PIN = '32f24af48837826c155b8733f239f45b25f37832'
PROTECTED = {
    'src/skippercast/seafloor/rights.py': '35253bfa59aea113bfa74252d61471065fc0e386716120e02cf2b183917c01fb',
    'tests/contract/test_seafloor_source_rights.py': '34426c86d2e868fd0e038a761295535c756cb382f937b6f5d00c79d9189db6c8',
    'scripts/check_repository.py': 'cf39ee4dab44893fae58d4553c8a159942c5674f5ce33f22ca9c441d0a74dec8',
}
EXCLUDED = 'test_paid_deployment_cannot_enable_noncommercial_sources_or_weaken_policy'
AUTHORED = (
    'scripts/coast_diagnostics/rights_coverage.py',
    'scripts/run_n3_rights_coverage_acceptance.py',
    'tests/unit/test_n3_rights_coverage.py',
    'tests/fixtures/n3_rights_coverage/federal.json',
    'docs/coast-rights-coverage.md',
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def head(root):
    git = root / '.git'
    if git.is_file():
        git = (root / git.read_text().strip().split('gitdir: ', 1)[1]).resolve()
    value = (git / 'HEAD').read_text().strip()
    if value.startswith('ref: '):
        ref = value[5:]
        if (git / ref).exists():
            return (git / ref).read_text().strip()
        for line in (git / 'packed-refs').read_text().splitlines():
            if line.endswith(' ' + ref):
                return line.split()[0]
        raise ValueError('HEAD ref unavailable')
    return value


class CountResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subtests = 0

    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        super().addSubTest(test, subtest, err)


def run_suite(suite):
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=CountResult).run(suite)
    text = stream.getvalue()
    print(text, end='')
    return {
        'tests': result.testsRun, 'subtests': result.subtests, 'skips': len(result.skipped),
        'failures': len(result.failures), 'errors': len(result.errors),
        'success': result.wasSuccessful() and result.testsRun > 0 and not result.skipped,
        'failure_text': '\n'.join(t for _, t in result.failures),
    }


def portable_copy(destination):
    destination.mkdir()
    for name in ('src', 'catalog', 'regions'):
        shutil.copytree(ROOT / name, destination / name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in (*AUTHORED, 'tests/_support.py'):
        source = ROOT / name
        if source.exists():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for name in ('tests/__init__.py', 'tests/unit/__init__.py'):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('')


def execute(mode, run):
    selected = ROOT
    if mode == 'portability':
        selected = run / 'differently-named-tree'
        portable_copy(selected)
        home = run / 'synthetic-home'
        home.mkdir()
        os.environ['HOME'] = str(home)
    fixture_root = run / 'tests/fixtures/n3_rights_coverage'
    fixture_root.mkdir(parents=True)
    os.environ['N3_FIXTURE_ROOT'] = str(fixture_root)
    # Explicit candidate roots before imports; no environment import overrides.
    sys.path[:0] = [str(selected), str(selected / 'src')]
    sys.dont_write_bytecode = True
    importlib.invalidate_caches()
    results = []
    if mode == 'compatibility':
        for name, expected in PROTECTED.items():
            if digest(ROOT / name) != expected:
                raise ValueError('Pinned byte identity changed: ' + name)
        module = importlib.import_module('tests.contract.test_seafloor_source_rights')
        names = unittest.defaultTestLoader.getTestCaseNames(module.SourceRightsTests)
        admitted = [name for name in names if name != EXCLUDED]
        expected = {
            'test_reviewed_ventresca_original_can_qualify_with_same_producer_restrictions',
            'test_exact_macginitie_products_require_unchanged_producer_review',
            'test_unreviewed_or_lookalike_cruise_archives_remain_rejected',
            'test_checked_noncommercial_producer_contract_can_qualify_without_inventing_public_domain',
            'test_missing_conflicting_or_fabricated_permissions_do_not_qualify',
            'test_mixed_source_terms_and_unknown_contributors_cannot_disappear',
        }
        if set(admitted) != expected or set(names) != expected | {EXCLUDED}:
            raise ValueError('Compatibility selector inventory changed')
        print('COMPATIBILITY_SELECTORS ' + json.dumps(admitted))
        results.append(run_suite(unittest.TestSuite(module.SourceRightsTests(n) for n in admitted)))
    else:
        module = importlib.import_module('tests.unit.test_n3_rights_coverage')
        if mode == 'negative':
            coverage = importlib.import_module('scripts.coast_diagnostics.rights_coverage')
            real = coverage._verdict
            def mutant(rows):
                return 'COMPLETE' if any(not row['catalog_found'] for row in rows) else real(rows)
            with patch.object(coverage, '_verdict', mutant):
                bad = run_suite(unittest.TestSuite([module.RightsCoverageTests('test_missing_catalog_incomplete')]))
            good = run_suite(unittest.TestSuite([module.RightsCoverageTests('test_missing_catalog_incomplete')]))
            exact = (bad['tests'] == 1 and bad['failures'] == 1 and bad['errors'] == 0
                     and bad['skips'] == 0 and 'missing catalog slug must prevent COMPLETE' in bad['failure_text'])
            if not exact or not good['success']:
                raise ValueError('Negative control did not isolate missing-catalog verdict gate')
            results.extend([bad, good])
            print('NEGATIVE_CONTROL expected mutant failure; restored positive passed')
        else:
            results.append(run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(module.RightsCoverageTests)))
            if results[0]['tests'] < 9:
                raise ValueError('Focused suite must execute at least nine tests')
    origins = {}
    for name, module in sorted(sys.modules.items()):
        if name == 'skippercast' or name.startswith(('skippercast.', 'scripts.coast_diagnostics', 'tests.')):
            filename = getattr(module, '__file__', None)
            if filename:
                location = Path(filename).resolve()
                if not location.is_relative_to(selected.resolve()):
                    raise ValueError('Ambient candidate module origin: ' + name)
                origins[name] = str(location)
    if not any(name == 'skippercast.seafloor.rights' for name in origins):
        raise ValueError('Actual rights module was not imported')
    if mode == 'portability':
        if Path(os.environ['HOME']).parent != run:
            raise ValueError('Synthetic HOME not retained')
        for name in AUTHORED:
            if (selected / name).exists():
                text = (selected / name).read_text()
                if str(ROOT) in text or re.search(r'/(?:home|Users)/[A-Za-z0-9_.-]+/', text):
                    raise ValueError('Box-only path in candidate source')
        print('PORTABILITY alternate root, pre-import HOME, candidate origins and unique allocation checked')
    success = all(r['success'] for r in results) if mode != 'negative' else results[-1]['success']
    return {'results': results, 'module_origins': origins, 'success': success}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=['focused', 'compatibility', 'negative', 'portability'])
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.output_root.is_absolute():
        parser.error('output root must be absolute')
    args.output_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix=args.mode + '-', dir=args.output_root))
    stdout, stderr = io.StringIO(), io.StringIO()
    record = {'argv': sys.argv, 'cwd': str(Path.cwd()), 'mode': args.mode, 'head': head(ROOT),
              'staged_base': PIN, 'source_sha256': {n: digest(ROOT / n) for n in (*AUTHORED, *PROTECTED) if (ROOT / n).is_file()}}
    attempts = []
    def forbidden(*unused_args, **unused_kwargs):
        attempts.append('offline seam invoked')
        raise RuntimeError('Offline acceptance forbids network, DNS and subprocesses')
    code = 1
    # Install before any candidate imports, not merely before test bodies.
    with contextlib.ExitStack() as stack:
        for obj, attr in ((socket, 'socket'), (socket, 'create_connection'), (socket, 'getaddrinfo'),
                          (socket, 'gethostbyname'), (socket, 'gethostbyname_ex'), (socket, 'gethostbyaddr'),
                          (subprocess, 'Popen'), (subprocess, 'run'), (subprocess, 'call'),
                          (subprocess, 'check_call'), (subprocess, 'check_output'), (os, 'system'), (os, 'popen')):
            stack.enter_context(patch.object(obj, attr, forbidden))
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                result = execute(args.mode, run)
                record.update(result)
                code = 0 if result['success'] and not attempts else 1
            except ModuleNotFoundError as error:
                print('INPUT_UNAVAILABLE missing module: ' + str(error.name), file=sys.stderr)
                record['missing_module'] = error.name
                code = 3
            except Exception as error:
                print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
                record['error_type'] = type(error).__name__
    (run / 'stdout.txt').write_text(stdout.getvalue())
    (run / 'stderr.txt').write_text(stderr.getvalue())
    record.update(exit=code, offline_attempts=len(attempts),
                  stdout_sha256=digest(run / 'stdout.txt'), stderr_sha256=digest(run / 'stderr.txt'))
    (run / 'receipt.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(stdout.getvalue(), end='')
    print(stderr.getvalue(), end='', file=sys.stderr)
    print('RECEIPT ' + str(run / 'receipt.json'))
    print('ACCEPTANCE_EXIT ' + str(code))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
