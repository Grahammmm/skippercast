"""Portable, scoped offline acceptance. Every invocation retains a fresh receipt.

The parent records the complete chosen project import closure before starting a
fresh guarded worker. The worker never invokes build/acquisition entrypoints.
This is an accidental-side-effect sentinel, not a hostile-code sandbox.
"""
import argparse
import ast
import contextlib
import hashlib
import importlib
import importlib.abc
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
BASE = 'de60e9c2efc706f23493e285376e0343e9d48e73'
GRID = 'src/skippercast/seafloor/grid.py'
ORIGINAL = 'tests/gis/test_seafloor_grid.py'
SCANNER = 'scripts/check_repository.py'
PINS = {GRID: '0b4ff703febcf919b78d5becb64cd475a2a9adabfa0bcc49440fcaf187a97089',
        ORIGINAL: 'de9750130b491b205d704bfb419d792cc51d066c82fc217b3b29a86962e63c16',
        SCANNER: 'cf39ee4dab44893fae58d4553c8a159942c5674f5ce33f22ca9c441d0a74dec8'}
CLOSURE = [
    'src/skippercast/__init__.py', 'src/skippercast/paths.py',
    'src/skippercast/platform/__init__.py', 'src/skippercast/platform/contracts.py',
    'src/skippercast/seafloor/__init__.py', GRID,
    'src/skippercast/seafloor/reference.py', 'src/skippercast/seafloor/io.py',
    'src/skippercast/http.py', 'src/skippercast/util/__init__.py',
    'src/skippercast/util/hashing.py', 'src/skippercast/util/time.py',
    'tests/__init__.py', 'tests/_support.py', ORIGINAL,
    'tests/gis/test_sc62_regression.py', 'tests/fixtures/sc62/factory.py',
    'scripts/run_sc62_acceptance.py', SCANNER,
]
PACKAGES = {'numpy': 'numpy', 'pyproj': 'pyproj', 'rasterio': 'rasterio',
            'shapefile': 'pyshp', 'shapely': 'shapely'}
PREFIX = 'tests.gis.test_sc62_regression.ReferencePairingTests.'
NAMES = [
    'test_both_empty_preserves_grid', 'test_complete_two_pair_mosaic',
    'test_empty_samples_rejected_before_work', 'test_empty_tiles_rejected_before_work',
    'test_extra_samples_rejected_before_work', 'test_fewer_samples_rejected_before_work',
    'test_iterable_forms_materialized_once', 'test_mismatched_single_pass_inputs',
    'test_resolution_date_id_precedence', 'test_same_length_reordered_pairs_not_rematched',
]
COMPAT = ['tests.gis.test_seafloor_grid.ReferenceGridTests.' + name for name in (
    'test_fine_valid_overwrites_coarse_and_holes_remain_unknown',
    'test_band_area_is_fractional_and_overlap_is_not_added')]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def expected_ids(suite):
    if suite == 'compatibility':
        return COMPAT
    if suite == 'negative-control':
        return [PREFIX + 'test_complete_two_pair_mosaic', PREFIX + 'test_fewer_samples_rejected_before_work']
    return [PREFIX + name for name in NAMES]


class OfflineStop(BaseException):
    pass


class ModelSentinel(importlib.abc.MetaPathFinder):
    def __init__(self, stop):
        self.stop = stop

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'litellm', 'transformers'}:
            self.stop('model', fullname)
        return None


def guard(run_root):
    counts = {'network': 0, 'model': 0, 'outside_write': 0, 'process': 0}
    violations = []

    def stop(kind, detail):
        counts[kind] += 1
        violations.append({'kind': kind, 'detail': str(detail)})
        raise OfflineStop(f'STOP {kind}: {detail}')

    def writable(value):
        if isinstance(value, int):
            return
        path = Path(os.fsdecode(value)).resolve()
        if not path.is_relative_to(run_root):
            stop('outside_write', path)

    def audit(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                     'socket.sendto', 'urllib.Request', 'http.client.connect'}:
            stop('network', event)
        if event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.fork', 'pty.spawn'}:
            stop('process', event)
        if event == 'open':
            path, mode, flags = args
            if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                writable(path)
        if event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate'}:
            writable(args[0])
        if event in {'os.rename', 'os.link', 'os.symlink'}:
            writable(args[0])
            writable(args[1])
    sys.addaudithook(audit)
    sys.meta_path.insert(0, ModelSentinel(stop))
    return counts, violations


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def startTest(self, test):
        super().startTest(test)
        self.rows.append({'id': test.id(), 'status': 'started'})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows[-1]['status'] = 'passed'

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows[-1].update(status='failed', error=self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.rows[-1].update(status='error', error=self._exc_info_to_string(err, test))
        if issubclass(err[0], OfflineStop):
            self.stop()

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.rows[-1].update(status='error' if not issubclass(err[0], AssertionError) else 'failed',
                                 error=self._exc_info_to_string(err, test))
            if issubclass(err[0], OfflineStop):
                self.stop()


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()


def broken_zip(grid):
    # Isolate only the new cardinality gate in a disposable function namespace.
    # Pair materialization and all real projection/NPZ/precedence code stay intact.
    tree = ast.parse(Path(grid.__file__).read_text())
    target = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'mosaic_reference')
    gates = [n for n in target.body if isinstance(n, ast.If) and
             'reference_tile_sample_count_mismatch' in ast.unparse(n)]
    if len(gates) != 1:
        raise RuntimeError('negative control requires exactly one cardinality gate')
    target.body.remove(gates[0])
    isolated = ast.Module(body=[target], type_ignores=[])
    namespace = dict(vars(grid))
    exec(compile(ast.fix_missing_locations(isolated), '<sc62-broken-zip>', 'exec'), namespace)
    return namespace['mosaic_reference']


def worker(repo, run_root, suite):
    os.environ['SKIPPERCAST_ROOT'] = str(run_root / 'operational')
    os.environ['SKIPPERCAST_HTTP_CACHE'] = '0'
    os.environ['PROJ_NETWORK'] = 'OFF'
    os.environ['TMPDIR'] = str(run_root / 'tmp')
    os.environ['XDG_CACHE_HOME'] = str(run_root / 'cache')
    os.environ['SC62_DATA_ROOT'] = str(run_root / 'data')
    for name in ('operational', 'tmp', 'cache', 'data'):
        (run_root / name).mkdir()
    tempfile.tempdir = str(run_root / 'tmp')
    sys.path[:0] = [str(repo / 'src'), str(repo)]
    counts, violations = guard(run_root)
    report = {'expected_ids': expected_ids(suite), 'tests': [], 'counts': counts,
              'violations': violations, 'skips': [], 'exit': 1}
    try:
        # Redirect repo_root before contracts.REPO and grid.build's default bind.
        paths = importlib.import_module('skippercast.paths')
        with patch.object(paths, 'repo_root', return_value=run_root / 'operational'):
            grid = importlib.import_module('skippercast.seafloor.grid')
            contracts = importlib.import_module('skippercast.platform.contracts')
        if contracts.REPO != run_root / 'operational' or grid.build.__defaults__[0] != contracts.REPO:
            raise RuntimeError('operational default redirect failed')
        if not Path(grid.__file__).resolve().is_relative_to(repo):
            raise RuntimeError('wrong product import')
        support = importlib.import_module('tests._support')
        support.ROOT = run_root / 'operational'
        support.FIXTURES = run_root / 'operational' / 'tests' / 'fixtures'
        loader = unittest.TestLoader()
        selected = loader.loadTestsFromNames(report['expected_ids'])
        actual_ids = list(flatten(selected))
        report['actual_ids'] = actual_ids
        report['collected_count'] = len(actual_ids)
        if loader.errors or actual_ids != report['expected_ids'] or not actual_ids:
            raise RuntimeError('missing selector or collection error: ' + repr(loader.errors))
        if suite == 'preflight':
            report['exit'] = 0
        else:
            context = patch.object(grid, 'mosaic_reference', broken_zip(grid)) if suite == 'negative-control' else contextlib.nullcontext()
            with context:
                result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(selected)
            report.update(tests=result.rows, actual_count=result.testsRun,
                          skips=[(t.id(), reason) for t, reason in result.skipped],
                          expected_failures=len(result.expectedFailures),
                          unexpected_successes=len(result.unexpectedSuccesses))
            good = result.wasSuccessful() and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses
            if suite == 'negative-control':
                positive, negative = result.rows
                good = (positive['status'] == 'passed' and negative['status'] == 'failed'
                        and 'ValueError not raised' in negative.get('error', '')
                        and len(result.failures) == 1 and not result.errors and not result.skipped)
                report['expected_inner_exit'] = 1
                report['actual_inner_exit'] = 0 if result.wasSuccessful() else 1
            report['exit'] = 0 if good and result.testsRun == len(actual_ids) else 1
        if violations or any(counts.values()):
            report['exit'] = 1
    except BaseException:
        report['exception'] = traceback.format_exc()
        print(report['exception'], file=sys.stderr)
    finally:
        write_json(run_root / 'worker.json', report)
    return report['exit']


def parent(repo, out, suite):
    out.mkdir(parents=True, exist_ok=True)
    run_root = out / (suite + '-' + uuid.uuid4().hex)
    run_root.mkdir(exist_ok=False)
    receipt = {'suite': suite, 'argv': sys.argv, 'cwd': os.getcwd(),
               'run_root': str(run_root), 'expected_ids': expected_ids(suite), 'exit': 1}
    stdout, stderr = '', ''
    try:
        manifest_path = repo.parent / 'SOURCE-MANIFEST.json'
        manifest = json.loads(manifest_path.read_text())
        spec_path = repo.parent / 'ACCEPTANCE-SPEC.json'
        spec = json.loads(spec_path.read_text())
        head = git(repo, 'rev-parse', 'HEAD')
        if manifest['head'] != BASE or manifest['clean'] is not True or spec['base'] != BASE:
            raise RuntimeError('source manifest/spec baseline mismatch')
        if git(repo, 'rev-parse', BASE) != BASE:
            raise RuntimeError('missing baseline')
        if Path(sys.prefix).resolve() != Path(manifest['runtime']['repo_venv']).resolve():
            raise RuntimeError('runtime mismatch')
        if manifest['runtime']['credential_scan_python3'] != spec['credential_scan_python3']:
            raise RuntimeError('credential scanner interpreter mismatch')
        for path, pin in PINS.items():
            baseline = subprocess.check_output(['git', '-C', str(repo), 'show', BASE + ':' + path])
            if hashlib.sha256(baseline).hexdigest() != pin:
                raise RuntimeError('baseline source hash mismatch: ' + path)
            if path != GRID and digest(repo / path) != pin:
                raise RuntimeError('unchanged source hash mismatch: ' + path)
        versions = {name: importlib.metadata.version(dist) for name, dist in PACKAGES.items()}
        hashes = {path: digest(repo / path) for path in CLOSURE}
        receipt.update(head=head, source_hashes=hashes, runtime=sys.executable,
                       versions=versions, source_manifest_sha256=digest(manifest_path),
                       acceptance_spec_sha256=digest(spec_path), closure=CLOSURE,
                       working_tree=git(repo, 'status', '--short'))
        # This durable import plan precedes every product import in the child.
        write_json(run_root / 'preimport.json', receipt)
        if suite == 'portability':
            pattern = re.compile(r'/(?:' + 'home|Users' + r')/[A-Za-z0-9_.-]+/')
            for path in (CLOSURE[-3], CLOSURE[-4], CLOSURE[-2]):
                if pattern.search((repo / path).read_text()):
                    raise RuntimeError('box-only path in ' + path)
            cwd = run_root / 'foreign-cwd'
            cwd.mkdir()
        else:
            cwd = repo
        command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                   '--suite', suite, '--repo', str(repo), '--run-root', str(run_root)]
        receipt['worker_argv'] = command
        receipt['worker_cwd'] = str(cwd)
        process = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        stdout, stderr = process.stdout, process.stderr
        report = json.loads((run_root / 'worker.json').read_text())
        receipt['worker'] = report
        receipt['exit'] = process.returncode
        if process.returncode != report['exit'] or report['violations']:
            receipt['exit'] = 1
        if hashes != {path: digest(repo / path) for path in CLOSURE}:
            raise RuntimeError('source changed during acceptance')
    except BaseException:
        stderr += traceback.format_exc()
        receipt['exit'] = 1
    (run_root / 'stdout.txt').write_text(stdout)
    (run_root / 'stderr.txt').write_text(stderr)
    receipt.update(stdout_sha256=digest(run_root / 'stdout.txt'),
                   stderr_sha256=digest(run_root / 'stderr.txt'))
    write_json(run_root / 'receipt.json', receipt)
    print(stdout, end='')
    print(stderr, end='', file=sys.stderr)
    print(json.dumps({'suite': suite, 'exit': receipt['exit'], 'receipt': str(run_root / 'receipt.json')}))
    return receipt['exit']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=(
        'preflight', 'regression', 'compatibility', 'negative-control', 'portability', 'baseline'))
    parser.add_argument('--out', type=Path)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--run-root', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if args.worker:
        if args.repo.resolve() != repo or not args.run_root.is_absolute():
            parser.error('worker requires its exact repository and absolute run root')
        return worker(repo, args.run_root.resolve(), args.suite)
    if args.out is None:
        parser.error('--out is required')
    return parent(repo, args.out.resolve(), args.suite)


if __name__ == '__main__':
    raise SystemExit(main())
