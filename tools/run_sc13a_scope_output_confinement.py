"""Offline, single-file SC13a acceptance with retained per-invocation evidence.

Not a hostile-code sandbox or an integration/qualification gate. All process-wide
controls are installed here, never by the ordinarily discoverable test module.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import traceback
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
BASE = '33734f90073a2150eac5a418564ea314c4a591ac'
TEST = REPO / 'tests/gis/test_sc13a_scope_output_confinement.py'
FIXTURE = REPO / 'tests/fixtures/sc13a-scope-output-confinement/shapes.json'
SOURCE = REPO / 'src/skippercast/seafloor/scope_paths.py'
CLOSURE = ('skippercast', 'skippercast.paths', 'skippercast.platform',
           'skippercast.platform.contracts', 'skippercast.seafloor',
           'skippercast.seafloor.scope_paths', 'skippercast.util', 'skippercast.util.time')


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    # All child commands finish before guard installation and product imports.
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


def relative_under(path, root):
    return path == root or path.is_relative_to(root)


def guard_reason(event, args, run, source_reads, runtime_roots):
    """Pure decision function; its self-check uses inert event tuples only."""
    if event.startswith(('socket.', 'subprocess.', 'pty.', 'os.exec', 'os.spawn')):
        return 'network/model/product child forbidden'
    if event in {'os.system', 'os.fork', 'os.forkpty', 'os.posix_spawn', 'os.startfile'}:
        return 'product child forbidden'
    if event == 'import' and args[0].startswith('skippercast') and args[0] not in CLOSURE:
        return 'product import outside selected closure'
    if event == 'open':
        name, mode, flags = args
        if isinstance(name, int):
            return 'unexpected file descriptor open'
        path = Path(os.fsdecode(name)).resolve()
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or bool(
            flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if relative_under(path, run):
            return None
        if writing:
            return 'write outside fresh run'
        if path in source_reads:
            return None
        if path.suffix in {'.py', '.pyc', '.so'} and any(relative_under(path, r) for r in runtime_roots):
            return None
        return 'data read outside fixture tree'
    # Preserve containment at mutation and traversal APIs, not only open().
    positions = {'os.mkdir': (0,), 'os.remove': (0,), 'os.rmdir': (0,),
                 'os.rename': (0, 1), 'os.link': (0, 1), 'os.symlink': (1,),
                 'os.chmod': (0,), 'os.chown': (0,), 'os.truncate': (0,),
                 'os.utime': (0,)}
    if event in positions:
        for pos in positions[event]:
            path = Path(os.fsdecode(args[pos])).absolute()
            # Do not follow the symlink being created, but confine its parent.
            checked = path.parent.resolve() / path.name
            if not relative_under(checked, run):
                return 'filesystem mutation outside fresh run'
    if event in {'os.listdir', 'os.scandir'}:
        name = args[0]
        if isinstance(name, int):
            return 'unexpected directory descriptor'
        path = Path(os.fsdecode(name or '.')).resolve()
        if not (relative_under(path, run) or path in {REPO, REPO / 'tests', TEST.parent} or
                relative_under(path, REPO / 'src') or
                any(relative_under(path, r) for r in runtime_roots)):
            return 'directory traversal outside import/runtime/fixture closure'
    return None


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []
        self.subtests = []

    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)

    def addSubTest(self, test, subtest, err):
        self.subtests.append({'id': subtest.id(), 'passed': err is None})
        super().addSubTest(test, subtest, err)


def expected_ids(suite):
    """Expand the frozen spec's named rows independently of test discovery."""
    if suite == 'preflight':
        names = ['test_import_fixture_closure']
        cls = 'ScopePreflight'
    elif suite == 'compatibility':
        cls = 'ScopeCompatibility'
        names = ['test_explicit_central', 'test_relative_noncentral_config',
                 'test_invalid_ids', 'test_missing_and_mismatch', 'test_central_identity',
                 'test_explicit_config_confinement', 'test_json_contract', 'test_peer_isolation']
    elif suite == 'negative-control':
        cls, names = 'ScopeNegativeControl', ['test_old_resolver_detected']
    else:
        cls, names = 'ScopeRegression', ['test_root_alias']
        categories = ('reference_dir', 'ledger_path', 'reaches_path', 'cells_path',
                      'build_receipt_path', 'screen_dir')
        for layout in ('central', 'noncentral'):
            names.extend(f'test_{state}_{layout}' for state in ('absent', 'ordinary'))
            for category in categories:
                names.extend(f'test_{label}_{layout}_{category}_{state}'
                             for label in ('inroot', 'escape') for state in ('existing', 'dangling'))
        names.extend(f'test_ancestor_{ancestor}_{state}'
                     for ancestor in ('central_var', 'central_dist', 'central_reference',
                                      'noncentral_var', 'noncentral_scopes', 'noncentral_id')
                     for state in ('existing', 'dangling'))
    return sorted('sc13a_scope_tests.' + cls + '.' + name for name in names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True,
                        choices=('preflight', 'regression', 'compatibility', 'negative-control'))
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    candidate = REPO.parent
    spec = candidate / 'ACCEPTANCE-SPEC.json'
    # No product imports, mutations of staging, or operational discovery here.
    manifest = json.loads(args.source_manifest.read_text())
    require(manifest['schema'] == 'agentorange.source-manifest/v1', 'manifest schema')
    require(Path(manifest['write_root']) == candidate and Path(manifest['repo']) == REPO, 'manifest roots')
    require(args.source_manifest.resolve() == candidate / 'SOURCE-MANIFEST.json', 'manifest identity')
    require(manifest['head'] == BASE and manifest['clean'] is True, 'staged baseline')
    require((REPO / '.venv').is_symlink(), 'staged runtime is not a symlink')
    require((REPO / '.venv').resolve() == Path(manifest['runtime']['repo_venv']).resolve(), 'runtime identity')
    require(Path(sys.executable).absolute() == REPO / '.venv/bin/python3', 'exact repository interpreter required')
    require(manifest['runtime']['credential_scan_python3'] ==
            str(candidate.parents[1] / 'tools/venv-fullsuite/bin/python3'), 'scanner interpreter identity')
    head = git('rev-parse', 'HEAD')
    require(git('merge-base', BASE, head) == BASE, 'candidate not a descendant of base')
    require(git('rev-parse', BASE + '^{tree}') == manifest['tree'], 'base tree identity')
    tracked_status = git('status', '--porcelain', '--untracked-files=no')
    if head == BASE:
        require(sha(SOURCE) == '67c80c8355fe81757a4f7600018e4db500d6704fdf349ff47fc01a4d21c5f6e1',
                'baseline product bytes changed before deciding red evidence')
    else:
        require(not tracked_status, 'final tracked tree dirty')
        require('Signed-off-by:' in git('log', '-1', '--format=%B'), 'candidate commit not signed off')
    out = args.out.absolute()
    require(out.resolve().is_relative_to(candidate / 'out'), 'output prefix outside candidate out')
    out.mkdir(parents=True, exist_ok=True)
    run = out / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex)
    run.mkdir(exist_ok=False)
    work = run / 'test-work'
    work.mkdir()
    synthetic_default = run / 'import-root'
    synthetic_default.mkdir()
    source_reads = {TEST.resolve(), FIXTURE.resolve(), Path(__file__).resolve(),
                    (REPO / 'tests/__init__.py').resolve(),
                    (REPO / 'tests/gis/__init__.py').resolve(),
                    (REPO / 'tests/_support.py').resolve()}
    for name in CLOSURE:
        relative = Path(*name.split('.'))
        file = REPO / 'src' / relative.with_suffix('.py')
        if not file.exists():
            file = REPO / 'src' / relative / '__init__.py'
        require(file.is_file(), 'selected source module missing: ' + name)
        source_reads.add(file.resolve())
    hashes = {str(p.relative_to(REPO)): sha(p) for p in sorted(source_reads)}
    hashes['tools/' + Path(__file__).name] = sha(Path(__file__))
    identities = {'manifest_sha256': sha(args.source_manifest), 'spec_sha256': sha(spec),
                  'files': hashes}
    runtime_roots = tuple({Path(sysconfig.get_path('stdlib')).resolve(),
                           Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()})
    # Pure inert guard checks: no endpoint, child, or prohibited file is touched.
    require(guard_reason('socket.connect', (), run, source_reads, runtime_roots) is not None,
            'network decision missing')
    require(guard_reason('subprocess.Popen', (), run, source_reads, runtime_roots) is not None,
            'child decision missing')
    require(guard_reason('open', (str(candidate / 'not-read'), 'r', 0), run,
                         source_reads, runtime_roots) is not None, 'read decision missing')
    violations = []

    allowed_reads = source_reads | {args.source_manifest.resolve(), spec.resolve()}
    allowed_reads.update(Path(importlib.util.cache_from_source(str(p))).resolve()
                         for p in source_reads if p.suffix == '.py')

    def audit(event, event_args):
        reason = guard_reason(event, event_args, run, allowed_reads, runtime_roots)
        if reason:
            violations.append({'event': event, 'reason': reason})
            raise RuntimeError('SC13a offline guard STOP: ' + reason)

    sys.addaudithook(audit)
    stdout, stderr = io.StringIO(), io.StringIO()
    result = None
    code = 1
    module = None
    closure = {}
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            sys.path.insert(0, str(REPO))
            sys.path.insert(0, str(REPO / 'src'))
            import skippercast.paths as paths
            with patch.object(paths, 'repo_root', return_value=synthetic_default):
                import skippercast.platform.contracts as contracts
                require(contracts.REPO == synthetic_default, 'import default root not redirected')
                for name in ('load_catalogs', 'load_region', 'validate_region', 'requirement_report'):
                    require(synthetic_default in getattr(contracts, name).__defaults__, 'bound default not redirected: ' + name)
                spec_loader = importlib.util.spec_from_file_location('sc13a_scope_tests', TEST)
                module = importlib.util.module_from_spec(spec_loader)
                spec_loader.loader.exec_module(module)
                module.RUN_ROOT = work
                classes = {'preflight': module.ScopePreflight, 'regression': module.ScopeRegression,
                           'compatibility': module.ScopeCompatibility,
                           'negative-control': module.ScopeNegativeControl}
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(classes[args.suite])
                selected_count = suite.countTestCases()
                require(sorted(t.id() for t in suite) == expected_ids(args.suite),
                        'required frozen test IDs missing/changed')
                require(selected_count > 0, 'zero selected tests')
                result = unittest.TextTestRunner(stream=stderr, verbosity=2,
                                                resultclass=RecordingResult).run(suite)
                require(result.testsRun == selected_count and not result.skipped, 'incomplete/skip')
                require(result.wasSuccessful(), 'required test failure')
                if args.suite == 'negative-control':
                    require(module.NEGATIVE.get('mutant_detected') is True and
                            module.NEGATIVE.get('positive_passed') is True, 'negative control incomplete')
                for name, loaded in sorted(sys.modules.items()):
                    if name == 'skippercast' or name.startswith('skippercast.'):
                        require(name in CLOSURE, 'unexpected product module: ' + name)
                        path = Path(loaded.__file__).resolve()
                        require(path in source_reads, 'unexpected product source path')
                        closure[name] = {'path': str(path), 'sha256': sha(path)}
                require(set(closure) == set(CLOSURE), 'selected import closure incomplete')
                require(not violations, 'guard refusal recorded')
                code = 0
    except Exception:
        traceback.print_exc(file=stderr)
    # Evidence writers use the same checked fresh run root after tests finish.
    (run / 'stdout.txt').write_text(stdout.getvalue())
    (run / 'stderr.txt').write_text(stderr.getvalue())
    after = {str(p.relative_to(REPO)): sha(p) for p in sorted(source_reads)}
    after['tools/' + Path(__file__).name] = sha(Path(__file__))
    require(identities['manifest_sha256'] == sha(args.source_manifest), 'manifest changed during invocation')
    require(identities['spec_sha256'] == sha(spec), 'spec changed during invocation')
    require(identities['files'] == after, 'source/fixture bytes changed during invocation')
    receipt = {'schema': 'sc13a.acceptance/v1', 'suite': args.suite,
               'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
               'interpreter': sys.executable, 'base_head': BASE, 'candidate_head': head,
               'tracked_status_before': tracked_status, 'identity': identities,
               'source_after': after, 'run_root': str(run),
               'tests_run': result.testsRun if result else 0,
               'test_ids': result.ids if result else [],
               'subtests': result.subtests if result else [],
               'failures': [{'id': t.id(), 'traceback': text} for t, text in result.failures] if result else [],
               'errors': [{'id': t.id(), 'traceback': text} for t, text in result.errors] if result else [],
               'skips': [(t.id(), reason) for t, reason in result.skipped] if result else [],
               'import_closure': closure, 'guard_violations': violations,
               'guard_decisions_checked_without_execution': ['network', 'child', 'external-read'],
               'negative_control': module.NEGATIVE if module else {},
               'preservation': module.PRESERVATION if module else [],
               'exit_code': code, 'stdout_sha256': sha(run / 'stdout.txt'),
               'stderr_sha256': sha(run / 'stderr.txt'),
               'limits': 'Offline synthetic direct API only. Full exact-head CI OWED to operator; no scientific/source/legal/live acceptance.'}
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'suite': args.suite, 'exit_code': code, 'tests_run': receipt['tests_run'],
                      'failures': len(receipt['failures']), 'errors': len(receipt['errors']),
                      'skips': len(receipt['skips']), 'head': head,
                      'receipt': str(run / 'receipt.json'),
                      'receipt_sha256': sha(run / 'receipt.json')}))
    if code:
        print(stderr.getvalue(), file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
