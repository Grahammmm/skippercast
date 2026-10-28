"""Offline SC115 acceptance runner. All hooks are confined to main's process."""
import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

BASE = '2979d59bfbb7d724eb83b34a48102b914ee8eaa3'
REPO = Path(__file__).resolve().parents[1]
NEW_TESTS = REPO / 'tests/gis/test_sc115_normalized_packing.py'
FIXTURES = REPO / 'tests/fixtures/sc115-normalized-packing'
REGRESSION = [
    'test_regression_equal_samples_nonunit_scale_rejected',
    'test_regression_every_band_real_packing',
    'test_regression_synthetic_headers_reject_before_read',
    'test_regression_unpacked_lossless_positive',
]
COMPATIBILITY = [
    'test_compatibility_baseline_digest',
    'test_compatibility_complete_log_binding',
    'test_compatibility_existing_metadata_masks_and_errors',
]
ORIGINAL = [
    'test_different_lossless_encodings_have_identical_reviewed_science',
    'test_changed_depth_uncertainty_mask_grid_or_datum_is_rejected',
    'test_legacy_review_requires_exact_encoded_bytes',
]


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def bind_logs(paths):
    return {str(p): {'sha256': file_hash(p), 'bytes': Path(p).stat().st_size} for p in paths}


def verify_logs(binding):
    for path, expected in binding.items():
        if bind_logs([Path(path)])[path] != expected:
            raise ValueError('log changed: ' + path)


def head():
    git = REPO / '.git'
    if git.is_file():
        git = Path(git.read_text().strip().removeprefix('gitdir: '))
    value = (git / 'HEAD').read_text().strip()
    if value.startswith('ref: '):
        value = (git / value[5:]).read_text().strip()
    if len(value) != 40 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Cannot bind exact head')
    return value


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Tee:
    def __init__(self, stream, log):
        self.stream, self.log = stream, log
    def write(self, value):
        self.log.write(value)
        return self.stream.write(value)
    def flush(self):
        self.log.flush()
        self.stream.flush()


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed = []
        self.outcomes = []
    def startTest(self, test):
        self.executed.append(test.id())
        super().startTest(test)
    def addSuccess(self, test):
        self.outcomes.append({'id': test.id(), 'status': 'PASS'})
        super().addSuccess(test)
    def addFailure(self, test, err):
        self.outcomes.append({'id': test.id(), 'status': 'FAIL',
                              'traceback': self._exc_info_to_string(err, test)})
        super().addFailure(test, err)
    def addError(self, test, err):
        self.outcomes.append({'id': test.id(), 'status': 'ERROR',
                              'traceback': self._exc_info_to_string(err, test)})
        super().addError(test, err)
    def addSubTest(self, test, subtest, err):
        self.outcomes.append({'id': subtest.id(), 'status': 'FAIL' if err else 'PASS'})
        super().addSubTest(test, subtest, err)


def run_cases(cases):
    return unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(
        unittest.TestSuite(cases))


def result_data(result):
    return {'executed_ids': result.executed, 'count': result.testsRun,
            'outcomes': result.outcomes, 'skips': result.skipped,
            'failures': result.failures, 'errors': result.errors}


def inputs():
    paths = [REPO / 'src/skippercast/seafloor/normalized.py', NEW_TESTS,
             REPO / 'tests/gis/test_seafloor_normalized.py', Path(__file__),
             REPO / 'scripts/check_repository.py'] + sorted(FIXTURES.glob('*'))
    return {str(p.relative_to(REPO)): file_hash(p) for p in paths if p.is_file()}


def validate_manifest(path):
    data = json.loads(path.read_text())
    if (data.get('schema') != 'agentorange.source-manifest/v1' or
            Path(data['repo']).resolve() != REPO or
            Path(data['write_root']).resolve() != REPO.parent or
            data.get('head') != BASE or data.get('clean') is not True or
            (REPO / '.venv').resolve() != Path(data['runtime']['repo_venv']).resolve() or
            Path(sys.prefix).resolve() != Path(data['runtime']['repo_venv']).resolve()):
        raise ValueError('Staging manifest mismatch')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True,
                        choices=['baseline', 'regression', 'compatibility', 'negative-control'])
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    manifest = validate_manifest(args.source_manifest)
    prefix = args.out.resolve()
    if not prefix.is_relative_to(REPO.parent / 'out'):
        raise ValueError('Output must be beneath candidate out')
    prefix.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='run-', dir=prefix))
    temporary = root / 'temporary'
    temporary.mkdir()
    before = inputs()
    receipt = {'schema': 'skippercast.sc115.offline/v1', 'base': BASE, 'head': head(),
               'suite': args.suite, 'argv': sys.argv, 'cwd': str(Path.cwd()),
               'interpreter': sys.executable, 'manifest_sha256': file_hash(args.source_manifest),
               'runtime': manifest['runtime'], 'source_hashes_before': before,
               'run_root': str(root), 'exit': 1}
    violations = []
    def audit(event, arguments):
        if (event.startswith(('socket.connect', 'socket.getaddrinfo', 'subprocess.',
                              'os.exec', 'os.spawn')) or
                event in ('os.system', 'os.fork', 'os.posix_spawn', 'pty.spawn') or
                (event == 'import' and str(arguments[0]).split('.')[0] in
                 {'openai', 'ollama', 'anthropic', 'litellm'})):
            violations.append({'event': event, 'arguments': repr(arguments)})
            raise RuntimeError('SC115 offline audit sentinel: ' + event)
    # An audit hook is irreversible, hence ONLY in this explicit runner process.
    sys.addaudithook(audit)
    stdout_path, stderr_path = root / 'stdout.log', root / 'stderr.log'
    tests = None
    with stdout_path.open('x') as out, stderr_path.open('x') as err:
        with redirect_stdout(Tee(sys.stdout, out)), redirect_stderr(Tee(sys.stderr, err)):
            try:
                with ExitStack() as scope:
                    sys.path.insert(0, str(REPO / 'src'))
                    constructors = load_file('sc115_runner_constructors', FIXTURES / 'constructors.py')
                    scope.enter_context(constructors.offline_scope())
                    scope.enter_context(patch.object(tempfile, 'tempdir', str(temporary)))
                    # No contracts module is needed. Redirect before any optional io/http imports.
                    from skippercast import paths
                    scope.enter_context(patch.object(paths, 'repo_root', return_value=root / 'synthetic'))
                    tests = load_file('sc115_tests', NEW_TESTS)
                    tests.RUN_ROOT = root / 'cases'
                    actual_regression = sorted(n for n in dir(tests.PackingTests)
                                               if n.startswith('test_regression'))
                    actual_compatibility = sorted(n for n in dir(tests.PackingTests)
                                                  if n.startswith('test_compatibility'))
                    if actual_regression != sorted(REGRESSION) or actual_compatibility != sorted(COMPATIBILITY):
                        raise ValueError('Missing or unregistered required test')
                    if args.suite == 'negative-control':
                        from skippercast.seafloor import normalized
                        deciding = REGRESSION[0]
                        positive = 'test_regression_unpacked_lossless_positive'
                        # Same deciding regression; only the new header check is disabled.
                        with patch.object(normalized, '_validate_packing', lambda ds: None):
                            mutant = run_cases([tests.PackingTests(deciding)])
                            mutant_positive = run_cases([tests.PackingTests(positive)])
                        restored_positive = run_cases([tests.PackingTests(positive)])
                        restored_regression = run_cases([tests.PackingTests(deciding)])
                        detected = (mutant.testsRun == 1 and len(mutant.failures) == 1 and
                                    not mutant.errors and not mutant.skipped and
                                    'AssertionError: ValueError not raised' in mutant.failures[0][1])
                        positive_passed = all(r.wasSuccessful() and r.testsRun == 1 and not r.skipped
                                              for r in (mutant_positive, restored_positive, restored_regression))
                        expected_ids = [tests.PackingTests(n).id() for n in
                                        (deciding, positive, positive, deciding)]
                        actual_ids = [i for r in (mutant, mutant_positive, restored_positive,
                                                  restored_regression) for i in r.executed]
                        receipt.update(mutant_detected=detected, positive_passed=positive_passed,
                                       expected_ids=expected_ids, actual_ids=actual_ids,
                                       expected_count=4, actual_count=sum(r.testsRun for r in
                                           (mutant, mutant_positive, restored_positive, restored_regression)),
                                       results=[result_data(r) for r in
                                           (mutant, mutant_positive, restored_positive, restored_regression)])
                        receipt['exit'] = 0 if (detected and positive_passed and
                                               actual_ids == expected_ids) else 1
                    else:
                        names = (REGRESSION if args.suite == 'regression' else COMPATIBILITY
                                 if args.suite == 'compatibility' else
                                 [REGRESSION[0], 'test_regression_unpacked_lossless_positive'])
                        cases = [tests.PackingTests(name) for name in names]
                        if args.suite == 'compatibility':
                            original = load_file('sc115_original', REPO / 'tests/gis/test_seafloor_normalized.py')
                            cases += [original.NormalizedTests(name) for name in ORIGINAL]
                        expected_ids = [case.id() for case in cases]
                        result = run_cases(cases)
                        receipt.update(expected_ids=expected_ids, expected_count=len(expected_ids),
                                       actual_count=result.testsRun, result=result_data(result))
                        receipt['exit'] = 0 if (result.wasSuccessful() and not result.skipped and
                                               result.executed == expected_ids and len(expected_ids) > 0) else 1
                    receipt['events'] = tests.EVENTS
            except Exception:
                traceback.print_exc()
                receipt['exit'] = 1
            receipt['module_origins'] = {n: str(getattr(m, '__file__', None))
                                         for n, m in sorted(sys.modules.items())
                                         if n.startswith(('skippercast', 'rasterio', 'numpy', 'sc115'))}
            receipt['source_hashes_after'] = inputs()
            receipt['sentinel_violations'] = violations
            if violations or before != receipt['source_hashes_after']:
                receipt['exit'] = 1
    # Internal logs are closed; the external caller seals command/exit-hook logs AFTER exit.
    receipt['internal_logs'] = bind_logs([stdout_path, stderr_path])
    verify_logs(receipt['internal_logs'])
    (root / 'receipt.json').write_text(json.dumps(receipt, indent=2, default=str) + '\n')
    print(json.dumps({'receipt': str(root / 'receipt.json'), 'exit': receipt['exit'],
                      'count': receipt.get('actual_count'),
                      'mutant_detected': receipt.get('mutant_detected'),
                      'positive_passed': receipt.get('positive_passed')}))
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())
