"""Bounded, offline acceptance for SP77; expected-red baseline is not GREEN."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import traceback
import unittest
import uuid

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
BASE = 'a1f648632e64561d82dcbeb20d9bda19f812560a'
SOURCE = 'src/skippercast/forecast/ensemble.py'
SOURCE_HASH = '66f469764c2d089653bb306cc36044e4667619eed8f74ed140bed2e9cb889be2'
TEST = 'tests/unit/test_sp77_sea_nearest.py'
FIXTURE = 'tests/fixtures/sp77_sea_nearest'
FOCUSED = 'tests.unit.test_sp77_sea_nearest.NearestSeaTests'
REGRESSION = ('tests.unit.test_forecast_ensemble.LocationTests',)
PRIMARY = FOCUSED + '.test_primary_round_up_selects_column_zero'
CONTROL = FOCUSED + '.test_healthy_mask_control_selects_column_zero'
# Inspected local import/selected-call closure. build/eccodes/local imports are
# function-local, unreachable from these selectors, and explicitly denied below.
CLOSURE = (
    'src/skippercast/__init__.py', 'src/skippercast/forecast/__init__.py',
    SOURCE, 'src/skippercast/forecast/fetch.py', 'src/skippercast/forecast/models.py',
    'src/skippercast/http.py', 'src/skippercast/paths.py',
    'src/skippercast/util/__init__.py', 'src/skippercast/util/time.py',
    'tests/__init__.py', 'tests/unit/__init__.py',
    'tests/unit/test_forecast_ensemble.py', TEST,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def git(*args):
    result = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, check=False)
    require(result.returncode == 0, 'git preflight failed: ' + result.stderr.decode(errors='replace'))
    return result.stdout


def hashes():
    paths = {REPO / SOURCE, REPO / TEST, Path(__file__)}
    paths.update(p for p in (REPO / FIXTURE).rglob('*') if p.is_file())
    return {str(p.relative_to(REPO)): digest(p) for p in sorted(paths)}


def inspect_closure():
    """Retain imports and call names; refuse subprocess APIs before test import."""
    inspected = {}
    forbidden = {'Popen', 'run', 'call', 'check_call', 'check_output', 'system', 'popen',
                 'fork', 'spawn', 'execv', 'execve', 'Process', 'Pool', 'ProcessPoolExecutor',
                 'create_subprocess_exec', 'create_subprocess_shell', 'spawnv', 'spawnve'}
    # This helper owns the only subprocess boundary, not the selected tests.
    for name in (*CLOSURE, 'scripts/check_repository.py'):
        path = REPO / name
        tree = ast.parse(path.read_text(), filename=name)
        calls = sorted({n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
                        for n in ast.walk(tree) if isinstance(n, ast.Call)
                        and isinstance(n.func, (ast.Attribute, ast.Name))})
        require(not forbidden.intersection(calls), 'unadmitted process API in ' + name)
        if name not in {SOURCE, TEST}:
            require(hashlib.sha256(git('show', BASE + ':' + name)).hexdigest() == digest(path),
                    'unchanged closure file differs from base: ' + name)
        inspected[name] = {'sha256': digest(path), 'calls': calls,
                           'imports': [ast.unparse(n) for n in ast.walk(tree)
                                       if isinstance(n, (ast.Import, ast.ImportFrom))]}
    return inspected


def selected_ids(phase):
    if phase == 'baseline':
        return [PRIMARY, CONTROL]
    selector, path, klass = ((FOCUSED, TEST, 'NearestSeaTests') if phase == 'focused' else
                             (REGRESSION[0], 'tests/unit/test_forecast_ensemble.py', 'LocationTests'))
    tree = ast.parse((REPO / path).read_text())
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == klass]
    require(len(classes) == 1, 'missing required selector ' + selector)
    return sorted(selector + '.' + n.name for n in classes[0].body
                  if isinstance(n, ast.FunctionDef) and n.name.startswith('test_'))


def child(phase, out):
    """File-based unittest entry; all guards are installed BEFORE target imports."""
    sys.path[:0] = [str(REPO), str(REPO / 'src')]
    tempfile.tempdir = str(out / 'tmp')
    attempts = []

    def deny(*args, **kwargs):
        attempts.append('fetch/model/process API')
        raise RuntimeError('offline acceptance forbids fetch/model/process calls')

    def audit(event, args):
        if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                     'socket.bind', 'socket.gethostbyname', 'socket.gethostbyaddr',
                     'subprocess.Popen', 'os.system', 'os.fork', 'os.posix_spawn', 'os.exec',
                     'pty.spawn'}:
            attempts.append(event)
            raise RuntimeError('offline acceptance forbids ' + event)
        if event == 'open':
            filename, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing and isinstance(filename, (str, bytes, os.PathLike)):
                require(Path(os.fsdecode(filename)).resolve().is_relative_to(out), 'child write outside fresh output')

    sys.addaudithook(audit)
    # stdlib sockets are also denied above if an import attempts networking.
    from skippercast.forecast import ensemble
    from skippercast import http
    from skippercast import paths
    require(Path(ensemble.__file__).resolve() == REPO / SOURCE, 'wrong product module imported')
    http.default_session = deny
    http.Session.request = deny
    ensemble.fetch.http = deny
    ensemble.fetch.exists = deny
    ensemble.fetch.default_session = deny
    for name in ('decode_one', 'read_mask', 'fetch_member_step', 'collect', 'build', 'write', 'read', 'local_root'):
        setattr(ensemble, name, deny)
    # The original LocationTests invokes region_points() with a bound default.
    # Give it only the committed synthetic producer-shaped region, never regions/.
    synthetic = REPO / FIXTURE
    ensemble.ROOT = synthetic
    ensemble.region_points.__defaults__ = (synthetic,)
    paths.repo_root = lambda: synthetic
    http.repo_root = lambda: synthetic
    ids = selected_ids(phase)
    require(len(ids) == {'baseline': 2, 'focused': 13, 'regression': 4}[phase], 'unexpected assertion inventory')
    names = ids if phase == 'baseline' else ([FOCUSED] if phase == 'focused' else list(REGRESSION))
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    seen = []

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            seen.append(test.id())
            super().startTest(test)

    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    report = {'runtime': {'executable': sys.executable, 'version': sys.version},
              'selectors': names, 'expected_ids': ids, 'executed_ids': seen,
              'cases': {'run': result.testsRun,
                        'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
                        'failed': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped)},
              'failures': [{'id': test.id(), 'text': text} for test, text in result.failures],
              'errors': [{'id': test.id(), 'text': text} for test, text in result.errors],
              'sentinel_attempts': attempts, 'eccodes_imported': 'eccodes' in sys.modules}
    dump(out / 'child-result.json', report)
    valid = (sorted(seen) == sorted(ids) and not result.skipped and not attempts and not report['eccodes_imported'])
    return 0 if result.wasSuccessful() and valid else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('baseline', 'focused', 'regression', 'repository'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child', choices=('baseline', 'focused', 'regression'))
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    if args.child:
        require(args.run_dir is not None and args.run_dir.resolve().is_relative_to(ROOT / 'out'), 'invalid child root')
        return child(args.child, args.run_dir.resolve())
    require(args.suite is not None and args.output is not None, '--suite and --output required')
    parent = args.output.resolve()
    require(parent.is_relative_to(ROOT / 'out'), 'output must be below candidate out/')
    parent.mkdir(parents=True, exist_ok=True)
    out = parent / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex)
    out.mkdir()
    (out / 'tmp').mkdir()
    receipt = {'schema_version': 1, 'phase': args.suite, 'staging_base': BASE,
               'wrapper_argv': [sys.executable, *sys.argv], 'wrapper_cwd': str(Path.cwd()),
               'wrapper_runtime': sys.version, 'status': 'HARNESS_ERROR', 'wrapper_exit': 1,
               'output': str(out), 'child_exit': None}
    code = 1
    try:
        manifest_path = ROOT / 'SOURCE-MANIFEST.json'
        manifest = json.loads(manifest_path.read_text())
        receipt['manifest_sha256'] = digest(manifest_path)
        require(manifest['head'] == BASE, 'staging manifest head mismatch')
        require(git('merge-base', BASE, 'HEAD').decode().strip() == BASE, 'candidate not descended from pinned base')
        receipt['actual_head'] = git('rev-parse', 'HEAD').decode().strip()
        receipt['git_status'] = git('status', '--porcelain').decode()
        receipt['hashes'] = hashes()
        dump(out / 'closure.json', inspect_closure())
        receipt['closure_sha256'] = digest(out / 'closure.json')
        if args.suite == 'baseline':
            require(receipt['actual_head'] == BASE and receipt['hashes'][SOURCE] == SOURCE_HASH,
                    'baseline must run on unchanged pinned product')
        else:
            # Find the historical red receipt, never rewrite/reseal it as green.
            frozen = []
            for path in sorted((ROOT / 'out' / 'author-baseline').glob('*/receipt.json')):
                row = json.loads(path.read_text())
                if row.get('status') == 'BASELINE_DEFECT_REPRODUCED':
                    frozen.append((path, row))
            require(bool(frozen), 'missing before-repair baseline')
            path, row = frozen[-1]
            pinned = {k: v for k, v in row['hashes'].items() if k == TEST or k.startswith(FIXTURE + '/')}
            require(pinned == {k: v for k, v in receipt['hashes'].items() if k == TEST or k.startswith(FIXTURE + '/')},
                    'test/fixture bytes changed since baseline; new honest baseline required')
            receipt['historical_baseline'] = {'path': str(path), 'sha256': digest(path)}
        python = (Path(manifest['runtime']['credential_scan_python3']) if args.suite == 'repository'
                  else REPO / '.venv' / 'bin' / 'python3')
        require(python.is_file(), 'admitted interpreter is unavailable')
        version = subprocess.run([str(python), '--version'], cwd=REPO, capture_output=True, text=True, check=False)
        require(version.returncode == 0, 'interpreter version probe failed')
        receipt['runtime'] = {'argv_executable': str(python), 'resolved_executable': str(python.resolve()),
                              'version_argv': [str(python), '--version'], 'version': version.stdout.strip(),
                              'version_exit': version.returncode}
        argv = ([str(python), '-B', str(REPO / 'scripts' / 'check_repository.py')] if args.suite == 'repository'
                else [str(python), '-B', str(Path(__file__).resolve()), '--child', args.suite, '--run-dir', str(out)])
        receipt['child_argv'] = argv
        receipt['child_cwd'] = str(REPO)
        env = os.environ.copy()
        # No path/environment interpreter override; isolate only temp/live defaults.
        env['TMPDIR'] = str(out / 'tmp')
        for name in ('SKIPPERCAST_ROOT', 'SKIPPERCAST_HTTP_CACHE', 'SKIPPERCAST_FORECAST_ROOT'):
            env.pop(name, None)
        completed = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, check=False)
        (out / 'child.stdout').write_bytes(completed.stdout)
        (out / 'child.stderr').write_bytes(completed.stderr)
        receipt['child_exit'] = completed.returncode
        require(hashes() == receipt['hashes'], 'authored inputs changed during execution')
        if args.suite == 'repository':
            match = re.fullmatch(rb'Checked (\d+) text files: local Markdown links, release privacy rules and the Text Advisor and charter fleet fixture scans passed\.\n', completed.stdout)
            valid = completed.returncode == 0 and match is not None and not completed.stderr
            receipt['cases'] = {'checks_passed': int(match[1]) if match else 0, 'failed': 0 if valid else 1}
        else:
            report = json.loads((out / 'child-result.json').read_text())
            receipt['cases'] = report['cases']
            receipt['child_report_sha256'] = digest(out / 'child-result.json')
            inventory_valid = (sorted(report['executed_ids']) == sorted(report['expected_ids'])
                               and not report['sentinel_attempts'] and not report['eccodes_imported'])
            if args.suite == 'baseline':
                failures = report['failures']
                valid = (completed.returncode == 1 and inventory_valid
                         and report['cases'] == {'run': 2, 'passed': 1, 'failed': 1, 'errors': 0, 'skips': 0}
                         and len(failures) == 1 and failures[0]['id'] == PRIMARY
                         and '1 != 0 : SP77_PRIMARY_COLUMN_ZERO' in failures[0]['text']
                         and completed.stdout == b'PRIMARY_OBSERVATION=1\n')
            else:
                valid = (completed.returncode == 0 and inventory_valid and report['cases']['run'] > 0
                         and not any(report['cases'][k] for k in ('failed', 'errors', 'skips')))
        require(valid, 'acceptance contract did not pass; raw child evidence retained')
        receipt['status'] = 'BASELINE_DEFECT_REPRODUCED' if args.suite == 'baseline' else 'GREEN_REVIEW_REQUIRED'
        code = 0
    except Exception as error:
        receipt['error'] = type(error).__name__ + ': ' + str(error)
        (out / 'wrapper.stderr').write_text(traceback.format_exc())
    receipt['wrapper_exit'] = code
    for name in ('child.stdout', 'child.stderr', 'wrapper.stderr'):
        path = out / name
        if path.exists():
            receipt[name] = {'path': str(path), 'sha256': digest(path)}
    dump(out / 'receipt.json', receipt)
    message = json.dumps({'status': receipt['status'], 'wrapper_exit': code, 'receipt': str(out / 'receipt.json'),
                          'cases': receipt.get('cases'), 'error': receipt.get('error')}, sort_keys=True)
    (out / 'wrapper.stdout').write_text(message + '\n')
    print(message)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
