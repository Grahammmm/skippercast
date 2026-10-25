#!/usr/bin/env python3
"""Fresh-process offline SC111 acceptance with explicit test IDs and sealed receipts.

Suites: regression (every test_regression method), compatibility (every
test_compatibility method plus two unchanged original selectors) and
negative-control (reversible in-memory seam that disables only the new count
predicate). Only main() installs the irreversible audit hook; importing this
file (as the seal regression does) changes nothing. Guards are defense in
depth, not a hostile-code sandbox. Output is REVIEW REQUIRED, never acceptance.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import sysconfig
import tempfile
import traceback
import unittest
import uuid

BASE = '2979d59bfbb7d724eb83b34a48102b914ee8eaa3'
SCAN_SUFFIX = ('agent-work', 'tools', 'venv-fullsuite', 'bin', 'python3')
TEST_MODULE = 'tests.unit.test_sc111_qualify_counts'
OWNED = ('src/skippercast/seafloor/manifest.py',
         'tests/unit/test_sc111_qualify_counts.py',
         'tests/fixtures/sc111-qualify-counts/qualification.json',
         'tools/run_sc111_qualify_counts.py')
CATALOG = ('catalog/surveys.json', 'catalog/survey.schema.json')
EXPECTED = {
    'regression': (
        'test_regression_boolean_shallow_count_refused',
        'test_regression_caller_inputs_unchanged_on_success_and_refusal',
        'test_regression_equal_shallow_and_valid_counts_qualify',
        'test_regression_existing_source_hash_and_rights_refusals_preserved',
        'test_regression_larger_valid_counts_preserve_source_and_review_fields',
        'test_regression_minimum_counts_of_one_qualify',
        'test_regression_public_and_physical_only_construction',
        'test_regression_seal_rejects_missing_changed_and_late_append_logs',
        'test_regression_shallow_greater_than_valid_refused',
        'test_regression_shallow_pixels_malformed_refused',
        'test_regression_source_bytes_malformed_refused',
        'test_regression_valid_pixels_malformed_refused',
        'test_regression_zero_shallow_count_refused',
        'test_regression_zero_source_bytes_refused'),
    'compatibility': (
        'test_compatibility_committed_catalog_rows_requalify_unchanged',
        'test_compatibility_producer_shaped_receipts_drop_unreviewed_extras'),
    'negative-control': ('test_negative_control_count_predicate_seam',),
}
ORIGINAL_SELECTORS = (
    'test_qualify_requires_rights_matching_source_and_shallow_pixels',
    'test_private_native_review_does_not_grant_public_source_rights')
SEALED = ('stdout.txt', 'stderr.txt', 'receipt.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seal(run):
    """Bind final complete log bytes after every writer has closed."""
    run = Path(run)
    entries = {}
    for name in SEALED:
        data = (run / name).read_bytes()
        entries[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    path = run / 'seal.json'
    require(not path.exists(), 'seal already exists; evidence is never resealed')
    path.write_text(json.dumps({'schema': 'skippercast.sc111.seal/v1', 'files': entries},
                               indent=2, sort_keys=True) + '\n')
    return entries


def verify_seal(run):
    """Reject a missing, changed or late-appended sealed log."""
    run = Path(run)
    path = run / 'seal.json'
    require(path.is_file(), 'seal missing')
    document = json.loads(path.read_text())
    require(document.get('schema') == 'skippercast.sc111.seal/v1'
            and set(document.get('files', {})) == set(SEALED), 'seal malformed')
    for name, expected in document['files'].items():
        target = run / name
        require(target.is_file() and not target.is_symlink(), 'sealed log missing: ' + name)
        data = target.read_bytes()
        require({'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} == expected,
                'sealed log changed: ' + name)
    return document['files']


def no_links(path):
    path = Path(os.path.abspath(path))
    for component in [*reversed(path.parents), path]:
        require(not component.is_symlink(), 'symlink outside admitted runtime: ' + str(component))
    return path


def head_at(repo):
    git = repo / '.git'
    if git.is_file():
        text = git.read_text().strip()
        require(text.startswith('gitdir: '), 'invalid gitdir')
        git = (repo / text[8:]).resolve()
    value = (git / 'HEAD').read_text().strip()
    if value.startswith('ref: '):
        name = value[5:]
        require('..' not in Path(name).parts and not Path(name).is_absolute(), 'invalid ref')
        target = git / name
        if target.exists():
            value = target.read_text().strip()
        else:
            matches = [line.split()[0] for line in (git / 'packed-refs').read_text().splitlines()
                       if line.endswith(' ' + name)]
            require(len(matches) == 1, 'unresolved HEAD')
            value = matches[0]
    require(len(value) == 40 and all(c in '0123456789abcdef' for c in value), 'invalid HEAD')
    return value


class BoundaryError(RuntimeError):
    pass


class Boundary:
    def __init__(self, repo, run, temp, fixture, compatibility):
        self.repo, self.run, self.temp, self.fixture = repo, run, temp, fixture
        self.catalog = {repo / name for name in CATALOG} if compatibility else set()
        paths = sysconfig.get_paths()
        self.libraries = {Path(paths[k]).resolve() for k in ('stdlib', 'platstdlib', 'purelib', 'platlib')}
        self.libraries |= {Path(sys.base_prefix).resolve() / 'lib'}
        self.violations = []
        self.active = True

    def path(self, path, write=False, delete=False):
        if isinstance(path, int):
            return  # existing stdout/stderr or descriptors opened through this hook
        raw = Path(os.fsdecode(path)).absolute()
        resolved = raw.resolve()
        if delete:
            # Only fixture-owned temporary files may be removed; retained evidence never.
            if raw.is_relative_to(self.temp) and resolved.is_relative_to(self.temp) and raw != self.temp:
                no_links(raw.parent)
                return
            raise BoundaryError('SC111 retained outputs cannot be deleted: ' + str(raw))
        if raw.is_relative_to(self.run) and resolved.is_relative_to(self.run):
            no_links(raw)
            return
        if not write:
            if raw in self.catalog or raw.is_relative_to(self.fixture):
                no_links(raw)
                return
            if raw.is_relative_to(self.repo) and raw.suffix in {'.py', '.pyc'}:
                no_links(raw)
                return
            if any(resolved.is_relative_to(library) for library in self.libraries):
                return  # installed files are read-only and only for normal imports
        raise BoundaryError('SC111 denied ' + ('write: ' if write else 'read: ') + str(raw))

    def audit(self, event, args, control=False):
        if not self.active:
            return
        try:
            if (event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn', 'os.posix_spawn',
                                  'urllib.', 'http.', 'ftplib.', 'smtplib.'))
                    or event in {'os.system', 'os.fork', 'os.forkpty', 'pty.spawn', 'ctypes.dlopen'}):
                raise BoundaryError('SC111 denied event: ' + event)
            if event == 'open':
                mode, flags = args[1], args[2]
                write = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or bool(
                    (flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
                self.path(args[0], write)
            elif event in {'os.mkdir', 'os.chmod', 'os.truncate'}:
                self.path(args[0], True)
            elif event in {'os.remove', 'os.rmdir'}:
                self.path(args[0], True, delete=True)
            elif event in {'os.rename', 'os.link', 'os.symlink'}:
                self.path(args[0], True)
                self.path(args[1], True)
                if event != 'os.rename':
                    raise BoundaryError('SC111 links cannot be created')
        except (BoundaryError, ValueError) as error:
            if not control:
                self.violations.append({'event': event, 'error': str(error)})
            raise


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self.subtests = []

    def record(self, test, status):
        self.records.append({'test_id': test.id(), 'outcome': status})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, 'passed')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, 'failed')

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, 'error')

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, 'skipped')

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.record(test, 'expected-failure')

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.record(test, 'unexpected-success')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.subtests.append({'test_id': subtest.id(), 'outcome': 'passed' if err is None else 'failed'})

    def stopTest(self, test):
        # A test whose subtests failed gets no addFailure/addSuccess of its own.
        if not any(r['test_id'] == test.id() for r in self.records):
            self.record(test, 'subtest-failed')
        super().stopTest(test)


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=tuple(EXPECTED), required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo = no_links(Path(__file__).resolve().parents[1])
    write_root = repo.parent
    source_path = no_links(args.source_manifest)
    require(source_path == write_root / 'SOURCE-MANIFEST.json', 'source manifest not candidate bound')
    source = json.loads(source_path.read_text())
    require(source['schema'] == 'agentorange.source-manifest/v1', 'source schema')
    require(Path(source['repo']) == repo and Path(source['write_root']) == write_root, 'candidate identity')
    require(source['head'] == BASE and source.get('clean') is True, 'admitted base mismatch')
    venv = repo / '.venv'
    require(venv.is_symlink() and venv.resolve() == Path(source['runtime']['repo_venv']).resolve(),
            'linked runtime mismatch')
    require(Path(sys.prefix).resolve() == venv.resolve(), 'wrong acceptance interpreter')
    require(Path(source['runtime']['credential_scan_python3']) == Path.home().joinpath(*SCAN_SUFFIX),
            'scan interpreter mismatch')
    head = head_at(repo)
    out = no_links(args.out)
    require(out.is_relative_to(write_root / 'out'), 'output must be under candidate/out')
    out.mkdir(parents=True, exist_ok=True)
    run = out / uuid.uuid4().hex
    run.mkdir(exist_ok=False)
    synthetic = run / 'synthetic'
    synthetic.mkdir()
    temp = synthetic / 'tmp'
    temp.mkdir()
    fixture = repo / 'tests/fixtures/sc111-qualify-counts'
    fixture_before = {p.relative_to(fixture).as_posix(): sha(no_links(p)) for p in fixture.rglob('*') if p.is_file()}
    source_hashes = {name: sha(no_links(repo / name)) for name in OWNED}
    stdout, stderr = run / 'stdout.txt', run / 'stderr.txt'
    receipt = {'schema': 'skippercast.sc111.receipt/v1', 'argv': [sys.executable, *sys.argv],
               'cwd': str(Path.cwd()), 'interpreter': sys.executable, 'suite': args.suite,
               'head': head, 'admitted_base': BASE, 'source_manifest_sha256': sha(source_path),
               'source_hashes': source_hashes, 'fixture_before': fixture_before,
               'expected_test_ids': [], 'run': str(run), 'status': 'REVIEW REQUIRED', 'events': [],
               'full_discovery': 'operator-run (not part of this suite)'}
    boundary = Boundary(repo, run, temp, fixture, args.suite == 'compatibility')
    previous_tempdir = tempfile.tempdir
    tempfile.tempdir = str(temp)
    sys.path[:0] = [str(repo / 'src'), str(repo)]
    old_stdout, old_stderr = sys.stdout, sys.stderr
    exit_code = 1
    with stdout.open('w') as output, stderr.open('w') as errors:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            # No-network, no-model and no-subprocess sentinels precede product imports.
            sys.addaudithook(boundary.audit)
            try:
                import skippercast.paths as paths
                original_root = paths.repo_root
                paths.repo_root = lambda: synthetic
                from skippercast.platform import contracts
                from skippercast.seafloor import manifest
                require(contracts.REPO == synthetic, 'pre-import root redirection failed')
                require(Path(manifest.__file__).resolve() == repo / 'src/skippercast/seafloor/manifest.py',
                        'wrong product source')
                require(manifest.load_manifest.__defaults__ == (synthetic,), 'load default escaped')
                require(manifest.promote_draft.__kwdefaults__['root'] == synthetic, 'promote default escaped')
                module = __import__(TEST_MODULE, fromlist=['QualifyCountsTests'])
                require(Path(module.__file__).resolve() == repo / 'tests/unit/test_sc111_qualify_counts.py',
                        'wrong test module')
                cls = module.QualifyCountsTests
                origins = {'skippercast.paths': paths.__file__, 'skippercast.platform.contracts': contracts.__file__,
                           'skippercast.seafloor.manifest': manifest.__file__, TEST_MODULE: module.__file__}
                tc = unittest.TestCase()
                loader = unittest.TestLoader()
                prefix = {'regression': 'test_regression', 'compatibility': 'test_compatibility',
                          'negative-control': 'test_negative_control'}[args.suite]
                present = tuple(sorted(n for n in loader.getTestCaseNames(cls) if n.startswith(prefix)))
                require(present == tuple(sorted(EXPECTED[args.suite])), 'test inventory mismatch: ' + repr(present))
                tests = [cls(name) for name in present]
                expected_ids = [t.id() for t in tests]

                def inert_denied():
                    # Direct event simulation, never a real forbidden operation.
                    for event in ('socket.connect', 'subprocess.Popen', 'urllib.Request'):
                        with tc.assertRaisesRegex(BoundaryError, 'denied event'):
                            boundary.audit(event, ('inert-denied-sentinel',), control=True)
                    with tc.assertRaisesRegex(BoundaryError, 'denied read'):
                        boundary.audit('open', (repo / 'SC111-INERT-DENIED-SENTINEL', 'r', 0), control=True)
                    with tc.assertRaisesRegex(BoundaryError, 'cannot be deleted'):
                        boundary.audit('os.remove', (stdout, -1), control=True)

                def roots():
                    tc.assertEqual(run.parent, out)
                    tc.assertTrue(temp.is_relative_to(synthetic))
                    tc.assertEqual(tempfile.gettempdir(), str(temp))
                    tc.assertEqual(contracts.REPO, synthetic)

                isolation = [unittest.FunctionTestCase(inert_denied, description='sc111.isolation.inert-denied-events'),
                             unittest.FunctionTestCase(roots, description='sc111.isolation.candidate-unique-root')]
                for case, ident in zip(isolation, ('sc111.isolation.inert-denied-events',
                                                   'sc111.isolation.candidate-unique-root')):
                    case.id = (lambda ident=ident: ident)
                    expected_ids.append(ident)
                tests += isolation
                if args.suite == 'compatibility':
                    catalog_before = {name: sha(repo / name) for name in CATALOG}
                    from tests.contract import test_seafloor_manifest as originals
                    import jsonschema
                    require(originals.ROOT == repo, 'original ROOT must remain staged checkout')
                    require(originals.Draft202012Validator is not None, 'jsonschema required; no skip waiver')
                    origins['tests.contract.test_seafloor_manifest'] = originals.__file__
                    origins['jsonschema'] = jsonschema.__file__
                    for name in ORIGINAL_SELECTORS:
                        test = originals.SchemaTests(name)
                        tests.append(test)
                        expected_ids.append(test.id())
                    receipt['original_fixture_redirection'] = (
                        'None: tests._support.ROOT remains the staged checkout (read-only catalog); '
                        'contracts REPO and bound defaults are synthetic.')
                receipt['expected_test_ids'] = expected_ids
                receipt['module_origins'] = origins
                cls.events = receipt['events']
                runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, resultclass=RecordedResult)
                try:
                    result = runner.run(unittest.TestSuite(tests))
                finally:
                    cls.events = None
                receipt['tests'] = result.records
                receipt['subtests'] = result.subtests
                receipt['tests_run'] = result.testsRun
                receipt['subtests_run'] = len(result.subtests)
                receipt['failures'] = len(result.failures)
                receipt['errors'] = len(result.errors)
                receipt['skips'] = len(result.skipped)
                actual_ids = [r['test_id'] for r in result.records]
                receipt['actual_test_ids'] = actual_ids
                require(sorted(actual_ids) == sorted(expected_ids) and len(actual_ids) == len(set(actual_ids)),
                        'executed IDs differ from expected IDs')
                fixture_after = {p.relative_to(fixture).as_posix(): sha(p) for p in fixture.rglob('*') if p.is_file()}
                receipt['fixture_after'] = fixture_after
                require(fixture_after == fixture_before, 'authored fixtures changed')
                require({name: sha(repo / name) for name in OWNED} == source_hashes, 'source bytes changed during execution')
                if args.suite == 'compatibility':
                    catalog_after = {name: sha(repo / name) for name in CATALOG}
                    receipt['catalog_before'], receipt['catalog_after'] = catalog_before, catalog_after
                    require(catalog_before == catalog_after, 'catalog bytes changed')
                ok = result.wasSuccessful() and not result.skipped and result.testsRun == len(expected_ids)
                if args.suite == 'negative-control':
                    control = [e for e in receipt['events'] if 'mutant_detected' in e]
                    receipt['mutant_detected'] = bool(control) and all(e['mutant_detected'] is True for e in control)
                    receipt['positive_passed'] = bool(control) and all(e['positive_passed'] is True for e in control)
                    ok = ok and len(control) == 1 and receipt['mutant_detected'] and receipt['positive_passed']
                if args.suite == 'regression':
                    seal_events = [e for e in receipt['events'] if e.get('late_append_rejected') is True]
                    ok = ok and len(seal_events) == 1
                require(not boundary.violations, 'unexpected guard event')
                exit_code = 0 if ok else 1
                paths.repo_root = original_root
            except Exception:
                traceback.print_exc()
                receipt['fatal_error'] = traceback.format_exc()
            finally:
                receipt['guard_violations'] = boundary.violations
                # The hook stays installed but inert; no product/test work follows.
                boundary.active = False
                tempfile.tempdir = previous_tempdir
    require(sys.stdout is old_stdout and sys.stderr is old_stderr, 'stdio restoration')
    receipt['exit_code'] = exit_code
    receipt['stdout_sha256'], receipt['stderr_sha256'] = sha(stdout), sha(stderr)
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    sealed = seal(run)
    verify_seal(run)
    print(json.dumps({'receipt': str(run / 'receipt.json'), 'seal_sha256': sha(run / 'seal.json'),
                      'sealed': sealed, 'suite': args.suite, 'head': head, 'exit_code': exit_code,
                      'tests_run': receipt.get('tests_run'), 'subtests_run': receipt.get('subtests_run'),
                      'failures': receipt.get('failures'), 'errors': receipt.get('errors'),
                      'skips': receipt.get('skips'), 'mutant_detected': receipt.get('mutant_detected'),
                      'positive_passed': receipt.get('positive_passed')}, sort_keys=True))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
