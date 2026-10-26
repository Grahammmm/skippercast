"""Offline, file-entry acceptance for SP73; receipts stay outside the repository."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import traceback
import unittest

REPO = Path(__file__).resolve().parents[1]
WRITE_ROOT = REPO.parent
BASE = 'a1f648632e64561d82dcbeb20d9bda19f812560a'
PRODUCT = 'src/skippercast/fleet/adapters/_html.py'
PRODUCT_HASH = 'aaf42a31d1721b50d26ffbe021a434aa996177045bbe87b105d28611030f29a0'
TEST_MODULE = 'tests.unit.test_sp73_html_skip'
PAIR = [TEST_MODULE + '.SkipTests.test_primary_unmatched_svg',
        TEST_MODULE + '.SkipTests.test_healthy_balanced_template']
REGRESSION = ['tests.unit.test_fleet_landings.ParserTests']
PHASES = ('baseline', 'focused', 'regression', 'repository')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def git(*args):
    child = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True, check=False)
    if child.returncode:
        raise RuntimeError('git preflight failed: ' + repr(args) + ': ' + child.stderr)
    return child.stdout.strip()


def module_path(name):
    stem = REPO / ('src' if name.startswith('skippercast') else '') / name.replace('.', '/')
    for path in (stem.with_suffix('.py'), stem / '__init__.py'):
        if path.is_file():
            return path
    return None


def inspect_closure(names):
    """Record complete local static imports (including package initializers).

    Child calls in the selected ParserTests class are inspected separately. Other
    suites in its module are NOT executed. The closure inventory records dormant
    child-process APIs; the child audit guard refuses any actual invocation.
    """
    pending, seen, inventory = list(names), set(), {}
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        path = module_path(name)
        if path is None:
            # A from-import can name a value rather than a module.
            continue
        parts = name.split('.')
        pending.extend('.'.join(parts[:n]) for n in range(1, len(parts)))
        text = path.read_text(encoding='utf-8')
        tree = ast.parse(text)
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names
                               if alias.name.split('.')[0] in {'skippercast', 'tests', 'scripts'})
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = parts if path.name == '__init__.py' else parts[:-1]
                    prefix = package[:len(package) - node.level + 1]
                    module = '.'.join(prefix + ([node.module] if node.module else []))
                else:
                    module = node.module or ''
                if module.split('.')[0] in {'skippercast', 'tests', 'scripts'}:
                    pending.append(module)
                    pending.extend(module + '.' + alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                call = ast.unparse(node.func)
                if any(word in call.lower() for word in ('subprocess', 'popen', 'spawn', 'exec',
                                                         'system', 'pool', 'pty', 'process')):
                    calls.append({'line': node.lineno, 'call': call})
        inventory[str(path.relative_to(REPO))] = {'sha256': sha(path), 'process_api_candidates': calls}
    regression = ast.parse((REPO / 'tests/unit/test_fleet_landings.py').read_text())
    classes = [node for node in regression.body if isinstance(node, ast.ClassDef) and node.name == 'ParserTests']
    if len(classes) != 1:
        raise RuntimeError('required literal regression class absent')
    methods = [node.name for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
    if len(methods) != 5:
        raise RuntimeError('pinned regression selector changed')
    for node in ast.walk(classes[0]):
        if isinstance(node, ast.Call):
            call = ast.unparse(node.func)
            if any(word in call.lower() for word in ('subprocess', 'popen', 'spawn', 'system', 'pool', 'pty', 'process')):
                raise RuntimeError('unadmitted selected child call: ' + call)
    return inventory, methods


def install_guards(output):
    """Process-local sentinels, before target imports; not a hostile-code sandbox."""
    attempts = []
    def audit(event, args):
        forbidden = event.startswith('socket.') or event in {
            'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty',
            'os.exec', 'pty.spawn', 'urllib.Request', 'sqlite3.connect'}
        if forbidden:
            attempts.append(event)
            raise RuntimeError('offline sentinel: ' + event)
        if event == 'open':
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing and not isinstance(path, int) and not Path(path).resolve().is_relative_to(output):
                attempts.append('write-outside-output')
                raise RuntimeError('write outside unique output')
    sys.addaudithook(audit)
    return attempts


def child_main(phase, output):
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(REPO), str(REPO / 'src')]
    os.environ['SKIPPERCAST_ROOT'] = str(REPO)
    os.environ.pop('SKIPPERCAST_HTTP_CACHE', None)
    os.environ['TMPDIR'] = str(output / 'tmp')
    tempfile.tempdir = str(output / 'tmp')
    attempts = install_guards(output)
    data = {'runtime': {'executable': sys.executable, 'version': sys.version},
            'cases': {'passed': 0, 'failed': 0, 'errors': 0, 'skips': 0}, 'guard_attempts': attempts}
    exit_code = 2
    try:
        if phase == 'repository':
            sys.argv = [str(REPO / 'scripts/check_repository.py')]
            try:
                runpy.run_path(sys.argv[0], run_name='__main__')
                exit_code = 0
            except SystemExit as result:
                exit_code = result.code if isinstance(result.code, int) else 2
            data['cases']['passed' if exit_code == 0 else 'failed'] = 1
        else:
            selectors = PAIR if phase == 'baseline' else REGRESSION if phase == 'regression' else [TEST_MODULE + '.SkipTests']
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromNames(selectors)
            def flatten(tests):
                for test in tests:
                    if isinstance(test, unittest.TestSuite):
                        yield from flatten(test)
                    else:
                        yield test.id()
            ids = list(flatten(suite))
            expected = 2 if phase == 'baseline' else 5 if phase == 'regression' else 43
            if loader.errors or len(ids) != expected or len(set(ids)) != expected:
                raise RuntimeError('missing/unavailable/duplicate selector or case: ' + repr(loader.errors))
            if phase == 'baseline' and ids != PAIR:
                raise RuntimeError('baseline must run the literal primary/control pair')
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            data.update({'selectors': selectors, 'executed_ids': ids, 'tests_run': result.testsRun,
                         'failure_ids': [test.id() for test, _ in result.failures],
                         'failures': [text for _, text in result.failures],
                         'error_ids': [test.id() for test, _ in result.errors]})
            data['cases'] = {'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
                             'failed': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped)}
            exit_code = 0 if (result.wasSuccessful() and not result.skipped and result.testsRun == expected) else 1
        # Record imported product module identities; none may come from shared installed source.
        imported = {}
        for name, module in list(sys.modules.items()):
            if name.startswith(('skippercast', 'tests.')) and getattr(module, '__file__', None):
                path = Path(module.__file__).resolve()
                if not path.is_relative_to(REPO):
                    raise RuntimeError('noncandidate import: ' + name)
                imported[name] = {'path': str(path.relative_to(REPO)), 'sha256': sha(path)}
        data['imported_modules'] = imported
    except Exception:
        traceback.print_exc()
        data['harness_error'] = traceback.format_exc()
        exit_code = 2
    if attempts:
        exit_code = 2
    data['exit'] = exit_code
    save(output / 'child-result.json', data)
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=PHASES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    parent = args.output.resolve()
    if not parent.is_relative_to(WRITE_ROOT) or parent.is_relative_to(REPO):
        parser.error('output must be inside write root and outside repo')
    if args.child:
        return child_main(args.suite, parent)
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=args.suite + '-', dir=parent))
    (output / 'tmp').mkdir()
    receipt = {'schema_version': 1, 'phase': args.suite, 'started_at': datetime.now(timezone.utc).isoformat(),
               'wrapper_argv': [sys.executable, *sys.argv], 'wrapper_cwd': str(Path.cwd()),
               'wrapper_runtime': sys.version, 'output': str(output), 'wrapper_exit': 2}
    try:
        manifest_path = WRITE_ROOT / 'SOURCE-MANIFEST.json'
        manifest = json.loads(manifest_path.read_text())
        if manifest['head'] != BASE:
            raise RuntimeError('staging base mismatch')
        git('merge-base', '--is-ancestor', BASE, 'HEAD')
        receipt.update({'staging_base': BASE, 'actual_head': git('rev-parse', 'HEAD'),
                        'status_porcelain': git('status', '--porcelain'), 'manifest_sha256': sha(manifest_path)})
        fixture_files = sorted((REPO / 'tests/fixtures/sp73_html_skip').rglob('*'))
        frozen = [REPO / 'tests/unit/test_sp73_html_skip.py'] + [p for p in fixture_files if p.is_file()]
        receipt['test_fixture_hashes'] = {str(p.relative_to(REPO)): sha(p) for p in frozen}
        receipt['source_hashes'] = {PRODUCT: sha(REPO / PRODUCT),
                                    'scripts/accept_sp73_html_skip.py': sha(Path(__file__))}
        inventory, methods = inspect_closure([TEST_MODULE, REGRESSION[0].rsplit('.', 1)[0], 'scripts.check_repository'])
        receipt.update({'import_closure': inventory, 'literal_regression_selectors': REGRESSION,
                        'regression_methods': methods})
        # Every existing member of the inspected local closure remains pinned, except the owned product.
        for relative, entry in inventory.items():
            if relative in {PRODUCT, 'tests/unit/test_sp73_html_skip.py'}:
                continue
            original = subprocess.run(['git', '-C', str(REPO), 'show', BASE + ':' + relative], capture_output=True, check=False)
            if original.returncode or hashlib.sha256(original.stdout).hexdigest() != entry['sha256']:
                raise RuntimeError('read-only closure member changed: ' + relative)
        if args.suite == 'baseline':
            if receipt['source_hashes'][PRODUCT] != PRODUCT_HASH:
                raise RuntimeError('baseline requires the complete unchanged pinned module')
        else:
            baselines = []
            for path in (WRITE_ROOT / 'out').rglob('receipt.json'):
                old = json.loads(path.read_text())
                if (old.get('status') == 'BASELINE_DEFECT_REPRODUCED' and old.get('wrapper_exit') == 0
                        and old.get('test_fixture_hashes') == receipt['test_fixture_hashes']
                        and old.get('source_hashes', {}).get(PRODUCT) == PRODUCT_HASH):
                    baselines.append({'path': str(path), 'sha256': sha(path)})
            if not baselines:
                raise RuntimeError('no retained matching before-repair baseline for frozen tests/fixtures')
            receipt['historical_baselines'] = baselines
        interpreter = (Path(manifest['runtime']['credential_scan_python3']) if args.suite == 'repository'
                       else REPO / '.venv/bin/python3')
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            raise RuntimeError('admitted interpreter unavailable')
        argv = [str(interpreter), '-B', str(Path(__file__).resolve()), '--child', '--suite', args.suite, '--output', str(output)]
        receipt.update({'child_argv': argv, 'child_cwd': str(REPO),
                        'interpreter_realpath': str(interpreter.resolve()),
                        'target_script': 'scripts/check_repository.py' if args.suite == 'repository' else None})
        with (output / 'stdout.txt').open('w') as stdout, (output / 'stderr.txt').open('w') as stderr:
            process = subprocess.run(argv, cwd=REPO, stdout=stdout, stderr=stderr, check=False, timeout=120)
        receipt['child_exit'] = process.returncode
        result = json.loads((output / 'child-result.json').read_text())
        receipt.update({'runtime': result['runtime'], 'cases': result['cases'], 'child_result': result})
        if args.suite == 'baseline':
            observations = [json.loads(line[len('OBSERVATION '):]) for line in (output / 'stdout.txt').read_text().splitlines()
                            if line.startswith('OBSERVATION ')]
            expected_observations = [
                {'case': 'primary_unmatched_svg', 'text': 'beforehiddenafter', 'exception': None},
                {'case': 'healthy_balanced_template', 'text': 'beforeafter', 'exception': None}]
            good = (process.returncode == 1 and result['exit'] == 1 and result['failure_ids'] == PAIR[:1]
                    and result['cases'] == {'passed': 1, 'failed': 1, 'errors': 0, 'skips': 0}
                    and len(result['failures']) == 1 and 'SKIP_TEXT_CONTRACT:primary_unmatched_svg' in result['failures'][0]
                    and observations == expected_observations and not result['guard_attempts'])
            status = 'BASELINE_DEFECT_REPRODUCED' if good else 'BASELINE_REJECTED'
        else:
            good = (process.returncode == 0 and result['exit'] == 0 and result['cases']['passed'] > 0
                    and not any(result['cases'][key] for key in ('failed', 'errors', 'skips'))
                    and not result['guard_attempts'])
            status = 'SCOPED_GREEN_REVIEW_REQUIRED' if good else 'FAILED'
        receipt.update({'status': status, 'wrapper_exit': 0 if good else 1})
    except Exception:
        receipt['harness_error'] = traceback.format_exc()
        receipt['status'] = 'HARNESS_ERROR'
        traceback.print_exc()
    finally:
        receipt['raw_output'] = {name: {'path': str(output / name), 'sha256': sha(output / name)}
                                 for name in ('stdout.txt', 'stderr.txt', 'child-result.json') if (output / name).exists()}
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        save(output / 'receipt.json', receipt)
    print(json.dumps({'status': receipt['status'], 'wrapper_exit': receipt['wrapper_exit'],
                      'child_exit': receipt.get('child_exit'), 'cases': receipt.get('cases'),
                      'receipt': str(output / 'receipt.json')}, sort_keys=True))
    return receipt['wrapper_exit']


if __name__ == '__main__':
    raise SystemExit(main())
