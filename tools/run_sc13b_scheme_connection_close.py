"""SC13B standalone offline acceptance; run only this card's named tests."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
import uuid
from unittest.mock import patch

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
BASE = '33734f90073a2150eac5a418564ea314c4a591ac'
FILES = ['src/skippercast/seafloor/reference.py',
         'tests/gis/test_sc13b_scheme_connection_close.py',
         'tools/run_sc13b_scheme_connection_close.py']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def install_guards(run, readable, violations):
    """Defense in depth, not a sandbox; no prohibited guard-control probes."""
    def within(path, roots):
        return any(path == root or path.is_relative_to(root) for root in roots)

    def refuse(event, target):
        violations.append({'event': event, 'target': str(target)})
        raise PermissionError(f'SC13B offline boundary: {event}: {target}')

    def audit(event, args):
        if (event.startswith(('socket.', 'subprocess.', 'os.spawn', 'os.exec'))
                or event in {'os.system', 'os.fork', 'os.forkpty', 'pty.spawn'}):
            refuse(event, args[0] if args else '')
        if event == 'import' and str(args[0]).split('.')[0] in {
                'openai', 'anthropic', 'ollama', 'transformers', 'torch', 'litellm'}:
            refuse(event, args[0])
        if event == 'open' and not isinstance(args[0], int):
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if not within(path, [run] if writing else readable):
                refuse(event, path)
        if event == 'sqlite3.connect':
            raw = str(args[0])
            path = Path(raw[5:].split('?', 1)[0] if raw.startswith('file:') else raw).resolve()
            if not within(path, [run]):
                refuse(event, path)
        if event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate', 'os.rename', 'os.link', 'os.symlink'}:
            targets = args[:2] if event in {'os.rename', 'os.link', 'os.symlink'} else args[:1]
            for target in targets:
                if not within(Path(os.fsdecode(target)).resolve(), [run]):
                    refuse(event, target)
    sys.addaudithook(audit)


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []

    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)


def execute(module, names, directory):
    directory.mkdir()
    module.FIXTURE_ROOT = directory
    stream = io.StringIO()
    suite = unittest.TestSuite(module.SchemeConnectionTests(name) for name in names)
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Result).run(suite)
    text = stream.getvalue()
    print(text, end='')
    return {'ids': result.ids, 'tests': result.testsRun,
            'failures': [(t.id(), detail) for t, detail in result.failures],
            'errors': [(t.id(), detail) for t, detail in result.errors],
            'skips': [(t.id(), why) for t, why in result.skipped],
            'passed': result.wasSuccessful() and result.testsRun == len(names)
                      and bool(names) and not result.skipped}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', required=True,
                        choices=['preflight', 'regression', 'compatibility', 'negative-control'])
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = REPO.parent
    manifest = json.loads(args.source_manifest.read_text())
    require(manifest['schema'] == 'agentorange.source-manifest/v1', 'manifest schema')
    require(Path(manifest['write_root']).resolve() == root, 'write root identity')
    require(Path(manifest['repo']).resolve() == REPO, 'repository identity')
    require(manifest['head'] == BASE and manifest['clean'] is True, 'admitted base')
    require((REPO / '.venv').is_symlink(), 'missing staged runtime symlink')
    require((REPO / '.venv').resolve() == Path(manifest['runtime']['repo_venv']).resolve(), 'runtime identity')
    scan = root.parents[1] / 'tools' / 'venv-fullsuite' / 'bin' / 'python3'
    require(manifest['runtime']['credential_scan_python3'] == str(scan), 'scan interpreter identity')
    require(Path(sys.prefix).resolve() == (REPO / '.venv').resolve(), 'wrong actual runtime')
    require(Path.cwd().resolve() == REPO, 'acceptance cwd')
    # Only read-only git commands, all before product/test imports and guards.
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    status = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=REPO, text=True)
    require(not status, 'tracked files dirty; freeze commit before acceptance')
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, head], cwd=REPO, check=True)
    if head == BASE:
        require(sha(REPO / FILES[0]) == '3374fc9fb09c886ef4469d24ce9a280023e0a6cef807ee4fe5777720b8316a90', 'baseline source pin')
    spec_path = root / 'ACCEPTANCE-SPEC.json'
    spec = json.loads(spec_path.read_text())
    require(spec['base'] == BASE, 'spec base')
    names = spec['suites'][args.suite]
    require(args.out.resolve().is_relative_to(root / 'out'), 'output confinement')
    args.out.mkdir(parents=True, exist_ok=True)
    run = args.out / uuid.uuid4().hex
    run.mkdir(exist_ok=False)
    fixtures = run / 'fixtures'
    fixtures.mkdir()
    before = {f: sha(REPO / f) for f in FILES}
    before['ACCEPTANCE-SPEC.json'] = sha(spec_path)
    before['SOURCE-MANIFEST.json'] = sha(args.source_manifest)
    receipt = {'schema': 'sc13b.receipt/v1', 'suite': args.suite,
               'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
               'interpreter': sys.executable, 'resolved_prefix': str(Path(sys.prefix).resolve()),
               'base': BASE, 'head': head, 'tracked_status': status, 'hashes_before': before,
               'run': str(run), 'fixture_root': str(fixtures), 'exit': 1,
               'guards': [], 'results': []}
    stdout, stderr = io.StringIO(), io.StringIO()
    # Stdlib/runtime/selected source are read-only. Product data is run-confined.
    readable = [run, REPO / 'src', REPO / 'tests' / 'gis', REPO / 'tools',
                spec_path, args.source_manifest.resolve(), Path(sys.prefix).resolve(),
                Path(sys.base_prefix).resolve(), Path('/usr/lib'), Path('/lib'),
                Path('/usr/share/proj'), Path('/usr/share/gdal'), Path('/proc')]
    install_guards(run, readable, receipt['guards'])
    sys.path.insert(0, str(REPO / 'src'))
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            import skippercast.paths as paths
            with patch.object(paths, 'repo_root', return_value=fixtures):
                import skippercast.seafloor.reference as reference
            from skippercast.platform import contracts
            require(contracts.REPO == fixtures, 'contracts import default not redirected')
            test_path = REPO / FILES[1]
            module_spec = importlib.util.spec_from_file_location('sc13b_tests', test_path)
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            receipt['import_closure'] = {name: str(getattr(mod, '__file__', ''))
                                         for name, mod in sorted(sys.modules.items())
                                         if name.startswith(('skippercast', 'numpy', 'pyproj', 'rasterio', 'shapely', 'shapefile'))}
            if args.suite == 'negative-control':
                positive = execute(module, names, fixtures / 'positive-before')
                receipt['results'].append(positive)
                require(positive['passed'], 'positive before mutant failed')
                with patch.object(reference, 'scheme_tiles', module.context_manager_only):
                    mutant = execute(module, names, fixtures / 'mutant')
                receipt['results'].append(mutant)
                detected = (mutant['tests'] == 1 and len(mutant['failures']) == 1
                            and not mutant['errors'] and not mutant['skips']
                            and 'ProgrammingError not raised' in mutant['failures'][0][1])
                receipt['mutant_detected'] = detected
                require(detected, 'negative control failed to isolate lifetime defect')
                after = execute(module, names, fixtures / 'positive-after')
                receipt['results'].append(after)
                receipt['positive_passed'] = positive['passed'] and after['passed']
                require(after['passed'], 'restored positive failed')
            else:
                result = execute(module, names, fixtures / 'tests')
                receipt['results'].append(result)
                require(result['passed'], 'required acceptance assertions failed')
            require(not receipt['guards'], 'offline boundary violation')
            receipt['exit'] = 0
    except Exception:
        with redirect_stderr(stderr):
            traceback.print_exc()
    after_hashes = {f: sha(REPO / f) for f in FILES}
    after_hashes['ACCEPTANCE-SPEC.json'] = sha(spec_path)
    after_hashes['SOURCE-MANIFEST.json'] = sha(args.source_manifest)
    receipt['hashes_after'] = after_hashes
    if before != after_hashes:
        receipt['exit'] = 1
    receipt['fixture_hashes'] = {str(p.relative_to(run)): sha(p)
                                 for p in fixtures.rglob('*') if p.is_file()}
    receipt['tests'] = sum(result['tests'] for result in receipt['results'])
    receipt['test_ids'] = [i for r in receipt['results'] for i in r['ids']]
    (run / 'stdout.txt').write_text(stdout.getvalue())
    (run / 'stderr.txt').write_text(stderr.getvalue())
    receipt['stdout_sha256'] = sha(run / 'stdout.txt')
    receipt['stderr_sha256'] = sha(run / 'stderr.txt')
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(stdout.getvalue(), end='')
    print(stderr.getvalue(), end='', file=sys.stderr)
    print(json.dumps({'receipt': str(run / 'receipt.json'), 'exit': receipt['exit'], 'tests': receipt['tests']}))
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())
