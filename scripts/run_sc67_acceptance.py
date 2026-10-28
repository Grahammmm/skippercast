"""Portable, offline SC67 acceptance. Outputs are exclusive, never overwritten.

The runner uses unittest's exact selectors, not broad discovery. It records the
static local import closure before any product import. Its audit hook is a
side-effect sentinel for this admitted closure, not a hostile-code sandbox:
any network, child-process or model-library event, and any write outside the
fresh run root, stops the run and fails it.
"""
import argparse
import ast
import contextlib
import hashlib
import importlib
import importlib.util
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
import uuid

BASE = 'de60e9c2efc706f23493e285376e0343e9d48e73'
PRODUCT = 'src/skippercast/seafloor/terrain_support.py'
PINS = {
    PRODUCT: '5647eab2e6cadb3ca75dbdc43200e090ae135f68d31a7412e4cbab7d7e1d088e',
    'tests/gis/test_seafloor_terrain_support.py': '8cf03683999818a9570b7a3ac726211f46c78c1868970f1b7f9e85a73aa03aae',
    'scripts/check_repository.py': 'cf39ee4dab44893fae58d4553c8a159942c5674f5ce33f22ca9c441d0a74dec8',
}
REGRESSION_MODULE = 'tests.gis.test_sc67_regression'
COMPATIBILITY_MODULE = 'tests.gis.test_seafloor_terrain_support'
PREFIX = REGRESSION_MODULE + '.SupportMaskTests.'
POSITIVE = ('reviewed_codes_under_boolean_mask', 'masked_off_rough_code_stays_false',
            'all_false_mask_has_no_support', 'empty_same_shape_masks_have_no_support',
            'reader_style_masks_remain_valid', 'invalid_codes_still_refused_under_boolean_mask')
REJECT = ('values_list', 'values_one_dimensional', 'values_three_dimensional', 'values_masked_array',
          'uint8_zero_one', 'uint8_255', 'signed_fancy_index', 'float', 'object', 'python_scalar',
          'numpy_scalar', 'zero_dimensional', 'list', 'one_dimensional', 'broadcast_row',
          'broadcast_column', 'transposed_shape', 'three_dimensional', 'masked_validity')
REGRESSION = [PREFIX + 'test_' + name for name in POSITIVE] + [PREFIX + 'test_reject_' + name for name in REJECT]
BASELINE = [PREFIX + 'test_reviewed_codes_under_boolean_mask', PREFIX + 'test_reject_uint8_zero_one',
            PREFIX + 'test_reject_signed_fancy_index']
COMPATIBILITY = [COMPATIBILITY_MODULE + '.NativeTerrainSupportTests.'
                 'test_exact_legend_preserves_zero_smooth_and_nodata_unknown']
NEW_FILES = ('scripts/run_sc67_acceptance.py', 'tests/gis/test_sc67_regression.py', 'tests/fixtures/sc67/factory.py')
HELD_ROOTS = {'h5py'}  # unresolved h5py/platform `uname -p` closure hold; never replayed here
MODEL_ROOTS = {'openai', 'anthropic', 'ollama', 'litellm', 'transformers'}
BOX_PATH = re.compile(r'/(?:home|Users)/[A-Za-z0-9_.-]+/')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write('\n')


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=True).stdout


def import_time_nodes(tree):
    """Statements executed on import: everything except function bodies."""
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        pending.extend(ast.iter_child_nodes(node))


def local_closure(repo, entries, *, import_time):
    """Conservative AST import closure. import_time=False also follows function-local imports."""
    pending = list(entries)
    found, external, defaults = {}, set(), {}

    def locate(module):
        for root in (repo / 'src', repo):
            candidate = root.joinpath(*module.split('.'))
            for path in (candidate.with_suffix('.py'), candidate / '__init__.py'):
                if path.is_file():
                    return path
        return None

    while pending:
        module = pending.pop()
        path = locate(module)
        if path is None:
            external.add(module.split('.')[0])
            continue
        relative = path.relative_to(repo).as_posix()
        if relative in found:
            continue
        source = path.read_bytes()
        found[relative] = digest(source)
        tree = ast.parse(source, filename=relative)
        package = module if path.name == '__init__.py' else module.rpartition('.')[0]
        bits = module.split('.')
        pending.extend('.'.join(bits[:i]) for i in range(1, len(bits)))
        nodes = import_time_nodes(tree) if import_time else ast.walk(tree)
        for node in nodes:
            if isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                name = node.module or ''
                if node.level:
                    name = importlib.util.resolve_name('.' * node.level + name, package)
                pending.append(name)
                pending.extend(name + '.' + alias.name for alias in node.names
                               if alias.name != '*' and locate(name + '.' + alias.name))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                values = list(node.args.defaults) + [x for x in node.args.kw_defaults if x]
                if values:
                    defaults[relative + ':' + node.name] = [ast.unparse(x) for x in values]
    return {'local_sha256': found, 'external_roots': sorted(external - {''}), 'bound_defaults': defaults}


class OfflineStop(BaseException):
    pass


def install_sentinels(run, counts):
    run = run.resolve()

    def stop(message):
        counts['refusals'].append(message)
        raise OfflineStop('STOP ' + message)

    def write_path(path):
        if isinstance(path, int):
            return
        resolved = Path(os.fsdecode(path)).resolve()
        if not resolved.is_relative_to(run):
            stop('out-of-run write: ' + str(resolved))

    def audit(event, args):
        if event.startswith('socket.'):
            counts['network_calls'] += 1
            stop('network operation: ' + event)
        if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.fork', 'pty.spawn'):
            counts['process_calls'] += 1
            stop('process operation: ' + event)
        if event == 'import' and str(args[0]).split('.')[0] in MODEL_ROOTS | HELD_ROOTS:
            counts['model_calls' if str(args[0]).split('.')[0] in MODEL_ROOTS else 'held_imports'] += 1
            stop('model/held import: ' + str(args[0]))
        if event == 'open':
            path, mode, flags = args
            if (mode and any(x in mode for x in 'wax+')) or (isinstance(flags, int) and flags & (
                    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                write_path(path)
        elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate'):
            write_path(args[0])
        elif event in ('os.rename', 'os.link', 'os.symlink'):
            for path in args[:2]:
                write_path(path)
    sys.addaudithook(audit)


class Results(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append({'id': test.id(), 'result': 'passed'})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append({'id': test.id(), 'result': 'failed', 'detail': self._exc_info_to_string(err, test)})

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append({'id': test.id(), 'result': 'error', 'detail': self._exc_info_to_string(err, test)})

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.rows.append({'id': subtest.id(), 'result': 'subtest-failed',
                              'detail': self._exc_info_to_string(err, test)})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.rows.append({'id': test.id(), 'result': 'skipped', 'reason': reason})

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.rows.append({'id': test.id(), 'result': 'xfail'})

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.rows.append({'id': test.id(), 'result': 'unexpected-success'})


def execute_tests(ids):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in ids)

    def flatten(item):
        if isinstance(item, unittest.TestSuite):
            return [name for child in item for name in flatten(child)]
        return [item.id()]

    actual = flatten(suite)
    if loader.errors or actual != ids or not actual:
        raise RuntimeError('missing/zero/unexpected test collection: ' + repr(actual) + repr(loader.errors))
    result = unittest.TextTestRunner(verbosity=2, resultclass=Results).run(suite)
    clean = (result.wasSuccessful() and not result.skipped and not result.expectedFailures
             and not result.unexpectedSuccesses and result.testsRun == len(ids))
    return {'expected_ids': ids, 'actual_ids': actual, 'expected_count': len(ids),
            'actual_count': result.testsRun, 'skips': len(result.skipped),
            'xfails': len(result.expectedFailures), 'rows': result.rows, 'exit': 0 if clean else 1}


def scan_box_paths(repo):
    for relative in NEW_FILES:
        if BOX_PATH.search((repo / relative).read_text()):
            raise RuntimeError('box-specific absolute path in ' + relative)
    return list(NEW_FILES)


def negative_control(repo):
    """Disable only the SC67 mask gate in an isolated copy of the submitted classify."""
    from skippercast.seafloor import terrain_support
    tree = ast.parse((repo / PRODUCT).read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'classify')
    gates = [n for n in function.body if isinstance(n, ast.If) and 'invalid_terrain_support_mask' in ast.unparse(n)]
    if len(gates) != 1:
        raise RuntimeError('cannot identify exactly one SC67 mask gate')
    function.body.remove(gates[0])
    namespace = dict(vars(terrain_support))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 '<sc67-isolated-gate-control>', 'exec'), namespace)
    original = terrain_support.classify
    try:
        terrain_support.classify = namespace['classify']
        result = execute_tests(BASELINE)
    finally:
        terrain_support.classify = original
    expected = {BASELINE[0]: 'passed', BASELINE[1]: 'failed', BASELINE[2]: 'failed'}
    observed = {row['id']: row['result'] for row in result['rows']}
    detected = (result['exit'] == 1 and observed == expected and
                all('ValueError not raised' in row.get('detail', '') for row in result['rows']
                    if row['result'] == 'failed'))
    result.update(inner_exit=result['exit'], exit=0 if detected else 1, expected_control_results=expected,
                  removed_gate=ast.unparse(gates[0]))
    return result


def run_suite(suite, repo, data_root, run):
    os.environ['SKIPPERCAST_ROOT'] = str(data_root)
    sys.path[:0] = [str(repo / 'src'), str(repo)]
    if suite == 'preflight':
        for name in ('numpy',):
            if importlib.util.find_spec(name) is None:
                raise RuntimeError('missing dependency: ' + name)
        importlib.import_module(REGRESSION_MODULE)  # complete selected closure, no test executed
        return {'exit': 0, 'checks': ['pins', 'manifest', 'runtime', 'static-closure', 'h5py-free-regression',
                                      'selected-imports'],
                'expected_count': 0, 'actual_count': 0, 'expected_ids': [], 'actual_ids': []}
    if suite in ('regression', 'portability', 'baseline'):
        scanned = None
        if suite == 'portability':
            alien = run / 'non-repository-cwd'
            alien.mkdir()
            os.chdir(alien)
            scanned = scan_box_paths(repo)
        result = execute_tests(BASELINE if suite == 'baseline' else REGRESSION)
        result.update(test_cwd=str(Path.cwd()), box_path_scan=scanned)
        if suite == 'baseline':
            observed = {row['id']: row['result'] for row in result['rows']}
            result['baseline_observed'] = observed
        return result
    if suite == 'compatibility':
        return execute_tests(COMPATIBILITY)
    if suite == 'negative-control':
        return negative_control(repo)
    raise ValueError('unknown suite')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=('preflight', 'baseline', 'regression', 'compatibility',
                                                           'negative-control', 'portability', 'credential-scan'))
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    args.out.mkdir(parents=True, exist_ok=True)
    run = args.out.resolve() / (args.suite + '-' + uuid.uuid4().hex)
    run.mkdir()  # Exclusive creation; prior attempts are never changed.
    receipt = {'suite': args.suite, 'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
               'run_root': str(run), 'exit': 1, 'skips': 0}
    stdout, stderr = io.StringIO(), io.StringIO()
    counts = {'network_calls': 0, 'process_calls': 0, 'model_calls': 0, 'held_imports': 0, 'refusals': []}
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            manifest_path = repo.parent / 'SOURCE-MANIFEST.json'
            manifest = json.loads(manifest_path.read_text())
            if manifest['head'] != BASE or manifest['clean'] is not True:
                raise RuntimeError('source manifest baseline mismatch')
            if manifest['runtime']['credential_scan_python3'] != str(Path.home() / 'agent-work/tools/venv-fullsuite/bin/python3'):
                raise RuntimeError('credential runtime differs from admitted path')
            if args.suite != 'credential-scan' and Path(sys.executable) != repo / '.venv/bin/python3':
                raise RuntimeError('not the staged interpreter')
            if (repo / '.venv').resolve() != Path(manifest['runtime']['repo_venv']).resolve():
                raise RuntimeError('staged venv differs from operator manifest')
            receipt['head'] = git(repo, 'rev-parse', 'HEAD').decode().strip()
            git(repo, 'merge-base', '--is-ancestor', BASE, 'HEAD')
            receipt['git_status'] = git(repo, 'status', '--porcelain').decode()
            for relative, expected in PINS.items():
                if digest(git(repo, 'show', BASE + ':' + relative)) != expected:
                    raise RuntimeError('baseline pin mismatch: ' + relative)
                if relative != PRODUCT and digest((repo / relative).read_bytes()) != expected:
                    raise RuntimeError('immutable source changed: ' + relative)
            receipt['product_sha256'] = digest((repo / PRODUCT).read_bytes())
            regression = local_closure(repo, (REGRESSION_MODULE,), import_time=False)
            compatibility = local_closure(repo, (COMPATIBILITY_MODULE,), import_time=True)
            compatibility_all = local_closure(repo, (COMPATIBILITY_MODULE,), import_time=False)
            write_json(run / 'import-closure.json', {'regression_all_scopes': regression,
                                                     'compatibility_import_time': compatibility,
                                                     'compatibility_all_scopes': compatibility_all})
            if set(regression['external_roots']) & (HELD_ROOTS | MODEL_ROOTS):
                raise RuntimeError('regression closure reaches a held/model dependency')
            receipt['source_sha256'] = regression['local_sha256']
            receipt['runner_sha256'] = digest(Path(__file__).read_bytes())
            receipt['manifest_sha256'] = digest(manifest_path.read_bytes())
            receipt['spec_sha256'] = digest((repo.parent / 'ACCEPTANCE-SPEC.json').read_bytes())
            if args.suite == 'compatibility':
                held = sorted(set(compatibility['external_roots']) & HELD_ROOTS)
                receipt['compatibility_import_time_external_roots'] = compatibility['external_roots']
                if held:
                    receipt['held'] = ('HELD before import: compatibility import-time closure reaches ' + ','.join(held) +
                                       ' (unresolved h5py/platform uname -p closure hold); not executed, not replayed')
                    raise RuntimeError(receipt['held'])
            if args.suite == 'credential-scan':
                command = [manifest['runtime']['credential_scan_python3'], str(repo / 'scripts/check_repository.py')]
                result = subprocess.run(command, cwd=repo, capture_output=True, text=True)
                stdout.write(result.stdout)
                stderr.write(result.stderr)
                receipt.update({'command': command, 'exit': result.returncode, 'actual_count': 1, 'expected_count': 1,
                                'expected_ids': ['repository-scan'], 'actual_ids': ['repository-scan']})
            else:
                data_root = run / 'data'
                data_root.mkdir()
                (run / 'tmp').mkdir()
                os.environ['TMPDIR'] = str(run / 'tmp')
                tempfile.tempdir = str(run / 'tmp')
                sys.dont_write_bytecode = True
                install_sentinels(run, counts)
                receipt.update(run_suite(args.suite, repo, data_root, run))
                if any(counts[k] for k in ('network_calls', 'process_calls', 'model_calls', 'held_imports')) \
                        or counts['refusals']:
                    receipt['exit'] = 1
    except BaseException as error:
        receipt['exception'] = type(error).__name__ + ': ' + str(error)
        traceback.print_exc(file=stderr)
        receipt['exit'] = 1
    finally:
        receipt['side_effects'] = counts
        for name, text in (('stdout', stdout.getvalue()), ('stderr', stderr.getvalue())):
            data = text.encode()
            with (run / (name + '.txt')).open('xb') as stream:
                stream.write(data)
            receipt[name + '_sha256'] = digest(data)
        write_json(run / 'receipt.json', receipt)
    print(json.dumps({'receipt': str(run / 'receipt.json'), 'exit': receipt['exit'],
                      'actual_count': receipt.get('actual_count'), 'exception': receipt.get('exception')}))
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())
