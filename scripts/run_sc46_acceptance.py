"""Offline SC46 acceptance; each invocation preserves a unique, hashed receipt.

Uses pytest in process, the complete candidate module, and inert metadata only.
The optional --expected-red switch selects just the admitted baseline witness;
it deliberately retains pytest's nonzero exit and is never final acceptance.
"""
import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
REGRESSION = 'tests/unit/test_sc46_regression.py'
COMPATIBILITY = 'tests/unit/test_coastal_vertical_deep_datums.py'
VERTICAL = 'src/skippercast/coastal/vertical.py'
RUNNER = 'scripts/run_sc46_acceptance.py'
INPUTS = (VERTICAL, REGRESSION, COMPATIBILITY, RUNNER, 'scripts/check_repository.py')
MUTATION_IDS = ('test_malformed_lineage[null]', 'test_valid_same_collaborators_and_resolution',
                'test_missing_lineage')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(root):
    return {name: sha(root / name) for name in INPUTS}


def git_head(root):
    git = root / '.git'
    if git.is_file():
        value = git.read_text().strip()
        require(value.startswith('gitdir: '), 'unrecognized git indirection')
        git = (root / value[8:]).resolve()
    value = (git / 'HEAD').read_text().strip()
    if value.startswith('ref: '):
        ref = value[5:]
        if (git / ref).exists():
            value = (git / ref).read_text().strip()
        else:
            common = git
            if (git / 'commondir').exists():
                common = (git / (git / 'commondir').read_text().strip()).resolve()
            if (common / ref).exists():
                value = (common / ref).read_text().strip()
            else:
                rows = (common / 'packed-refs').read_text().splitlines()
                matches = [line.split()[0] for line in rows if line.endswith(' ' + ref)]
                require(len(matches) == 1, 'cannot resolve exact HEAD')
                value = matches[0]
    require(re.fullmatch('[0-9a-f]{40}', value) is not None, 'invalid exact HEAD')
    return value


def select_root(root):
    # Remove any pre-existing editable-checkout package before candidate imports.
    for name in list(sys.modules):
        if name == 'skippercast' or name.startswith('skippercast.'):
            del sys.modules[name]
    sys.path[:0] = [str(root / 'src'), str(root)]
    importlib.invalidate_caches()
    module = importlib.import_module('skippercast.coastal.vertical')
    origins = {}
    for name, loaded in list(sys.modules.items()):
        if name == 'skippercast' or name.startswith('skippercast.'):
            path = Path(loaded.__file__).resolve()
            require(path.is_relative_to(root / 'src'), 'ambient package import: ' + name)
            origins[name] = str(path)
    require(Path(module.__file__).resolve() == root / VERTICAL, 'wrong vertical module')
    return module, origins


class Reports:
    def __init__(self):
        self.items = []
        self.reports = []
        self.collection_errors = []

    def pytest_collection_finish(self, session):
        self.items = [item.nodeid for item in session.items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append(str(report.longrepr))

    def pytest_runtest_logreport(self, report):
        self.reports.append({'nodeid': report.nodeid, 'when': report.when,
                             'outcome': report.outcome,
                             'detail': str(report.longrepr) if report.longrepr else None})

    def packet(self, code):
        calls = [r for r in self.reports if r['when'] == 'call']
        return {'exit': int(code), 'collected': len(self.items), 'items': self.items,
                'executed': len(calls), 'passed': sum(r['outcome'] == 'passed' for r in calls),
                'failed': sum(r['outcome'] == 'failed' for r in self.reports),
                'skipped': sum(r['outcome'] == 'skipped' for r in self.reports),
                'collection_errors': self.collection_errors, 'reports': self.reports}


def run_tests(root, selectors):
    import pytest
    reports = Reports()
    args = ['-vv', '-p', 'no:cacheprovider', '--noconftest', '-c', str(root / 'pyproject.toml'),
            '--rootdir', str(root)]
    args += [str(root / selector.split('::')[0]) + ('::' + selector.split('::', 1)[1]
             if '::' in selector else '') for selector in selectors]
    result = reports.packet(pytest.main(args, plugins=[reports]))
    result['pytest_argv'] = args
    return result


def all_passed(result):
    return (result['exit'] == 0 and result['executed'] > 0
            and result['executed'] == result['collected'] == result['passed']
            and result['failed'] == result['skipped'] == 0 and not result['collection_errors'])


def remove_shape_predicate(module):
    """Compile only the real function with exactly one in-process predicate removed."""
    tree = ast.parse((ROOT / VERTICAL).read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'normalized_from_raster')
    predicate = ast.dump(ast.parse('not isinstance(lineage, dict)', mode='eval').body)
    removed = 0
    for node in ast.walk(function):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            retained = [value for value in node.values if ast.dump(value) != predicate]
            removed += len(node.values) - len(retained)
            node.values = retained
    require(removed == 1, 'mutation must remove exactly the lineage shape predicate')
    namespace = dict(vars(module))
    compiled = ast.Module(body=[function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(compiled), str(ROOT / VERTICAL), 'exec'), namespace)
    # The real module globals preserve pytest collaborator monkeypatches.
    from types import FunctionType
    return FunctionType(namespace[function.name].__code__, vars(module), function.name,
                        namespace[function.name].__defaults__,
                        namespace[function.name].__closure__)


def portable_root(run):
    destination = run / ('relocated-sc46-' + uuid.uuid4().hex)
    destination.mkdir()
    closure = (REGRESSION, VERTICAL, RUNNER, 'pyproject.toml',
               'src/skippercast/__init__.py', 'src/skippercast/coastal/__init__.py')
    for name in closure:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        require(sha(target) == sha(ROOT / name), 'relocated input differs: ' + name)
    return destination, {name: sha(destination / name) for name in closure}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True,
                        choices=['regression', 'mutation', 'compatibility', 'portability'])
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--expected-red', action='store_true')
    args = parser.parse_args()
    require(not args.expected_red or args.mode == 'regression', 'red witness is regression only')
    require(Path.cwd().resolve() == ROOT, 'run from the exact candidate repository root')
    output = args.output_root.resolve()
    require(not output.is_relative_to(ROOT), 'evidence must be outside committed inputs')
    output.mkdir(parents=True, exist_ok=True)
    run = output / (args.mode + ('-expected-red-' if args.expected_red else '-') + uuid.uuid4().hex)
    run.mkdir()
    before = hashes(ROOT)
    head = git_head(ROOT)
    packet = {'schema': 'sc46-acceptance-v1', 'mode': args.mode, 'argv': sys.argv,
              'cwd': str(Path.cwd()), 'head': head, 'runtime': sys.executable,
              'expected_red': args.expected_red, 'source_hashes_before': before,
              'run_root': str(run), 'test_runs': [], 'status': 'UNVERIFIED', 'exit': 1}
    capture = io.StringIO()
    attempts = []

    def offline(event, values):
        if (event in {'socket.connect', 'socket.connect_ex', 'socket.bind', 'socket.getaddrinfo',
                      'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.sendto',
                      'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty'}
                or event.startswith('os.exec') or event.startswith('os.spawn')):
            attempts.append(event)
            raise RuntimeError('SC46 offline operation denied: ' + event)

    sys.addaudithook(offline)
    # These affect this invocation only; no service/profile/environment configuration changes.
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    os.environ.pop('PYTEST_ADDOPTS', None)
    os.environ.pop('PYTEST_PLUGINS', None)
    home = run / 'synthetic-home'
    home.mkdir()
    os.environ['HOME'] = str(home)
    os.environ['XDG_CACHE_HOME'] = str(home / 'cache')
    os.environ['TMPDIR'] = str(run)
    packet['home'] = str(home)
    try:
        with redirect_stdout(capture), redirect_stderr(capture):
            for name in (REGRESSION, RUNNER):
                require(re.search(rb'/(?:home|Users|tmp|var|opt|mnt|srv)/',
                                  (ROOT / name).read_bytes()) is None,
                        'box-only path in authored input: ' + name)
            module, origins = select_root(ROOT)
            packet['module_origins'] = origins
            if args.mode == 'mutation':
                original = module.normalized_from_raster
                selectors = [REGRESSION + '::' + name for name in MUTATION_IDS]
                try:
                    module.normalized_from_raster = remove_shape_predicate(module)
                    broken = run_tests(ROOT, selectors)
                    packet['test_runs'].append(dict(phase='broken-control', **broken))
                finally:
                    module.normalized_from_raster = original
                failures = [r for r in broken['reports'] if r['outcome'] == 'failed']
                require(broken['exit'] == 1 and broken['collected'] == broken['executed'] == 3
                        and broken['passed'] == 2 and broken['skipped'] == 0
                        and len(failures) == 1 and failures[0]['when'] == 'call'
                        and failures[0]['nodeid'].endswith('test_malformed_lineage[null]')
                        and "AttributeError: 'NoneType' object has no attribute 'get'" in failures[0]['detail'],
                        'broken null-lineage control was not detected with exact AttributeError')
                restored = run_tests(ROOT, selectors)
                packet['test_runs'].append(dict(phase='restored-control', **restored))
                require(module.normalized_from_raster is original and all_passed(restored),
                        'restored positive and missing controls failed')
            elif args.mode == 'portability':
                relocated, copied = portable_root(run)
                packet['relocated_root'] = str(relocated)
                packet['relocated_hashes'] = copied
                os.chdir(relocated)
                _, portable_origins = select_root(relocated)
                packet['portable_module_origins'] = portable_origins
                result = run_tests(relocated, [REGRESSION])
                packet['test_runs'].append(dict(phase='relocated-regression', **result))
                require(all_passed(result), 'relocated regression failed')
                require({name: sha(relocated / name) for name in copied} == copied,
                        'relocated inputs changed')
            else:
                selector = COMPATIBILITY if args.mode == 'compatibility' else REGRESSION
                if args.expected_red:
                    selector += '::test_malformed_lineage[null]'
                result = run_tests(ROOT, [selector])
                packet['test_runs'].append(dict(phase='expected-red' if args.expected_red else 'final', **result))
                if args.expected_red:
                    require(result['exit'] == 1 and result['executed'] == 1 and result['failed'] == 1
                            and "AttributeError: 'NoneType' object has no attribute 'get'" in
                            next(r['detail'] for r in result['reports'] if r['outcome'] == 'failed'),
                            'baseline did not reproduce the admitted defect')
                    packet['status'] = 'EXPECTED_RED_NOT_ACCEPTANCE'
                else:
                    require(all_passed(result), 'acceptance requires every selected case passing')
            require(hashes(ROOT) == before, 'original frozen inputs changed during acceptance')
            require(git_head(ROOT) == head, 'HEAD changed during acceptance')
            require(not attempts, 'network/subprocess operation was attempted')
            if not args.expected_red:
                packet.update(status='PASS_REVIEW_REQUIRED', exit=0)
    except Exception as error:
        import traceback
        capture.write(traceback.format_exc())
        packet['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        os.chdir(ROOT)
        packet['source_hashes_after'] = hashes(ROOT)
        packet['offline_attempts'] = attempts
        raw = run / 'raw.txt'
        raw.write_text(capture.getvalue())
        packet['raw_output'] = str(raw)
        packet['raw_sha256'] = sha(raw)
        receipt = run / 'receipt.json'
        receipt.write_text(json.dumps(packet, indent=2) + '\n')
        print(capture.getvalue(), end='')
        print(json.dumps({'status': packet['status'], 'exit': packet['exit'],
                          'head': head, 'receipt': str(receipt),
                          'receipt_sha256': sha(receipt), 'raw_sha256': packet['raw_sha256'],
                          'counts': [{key: row[key] for key in
                                      ('phase', 'collected', 'executed', 'passed', 'failed', 'skipped')}
                                     for row in packet['test_runs']]}, indent=2))
    return packet['exit']


if __name__ == '__main__':
    raise SystemExit(main())
