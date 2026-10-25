"""Portable, offline SC6a acceptance. All evidence goes to exclusive fresh run roots.

The attended continuation uses script files and unittest. Compatibility adapters
collect the three named unchanged pytest functions and call their unchanged
fixture body with an explicit synthetic root (and a minimal stdout capsys).
No pytest plugin discovery, acquisition CLI, renderer child or model is run.
"""
import argparse
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
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
BASE = 'de60e9c2efc706f23493e285376e0343e9d48e73'
MESH = 'src/skippercast/coastal/render/mesh.py'
COMPAT = 'research/tests/gis/test_check_terrain_acceptance_render.py'
TEST = 'tests/gis/test_sc6a_regression.py'
FACTORY = 'tests/fixtures/sc6a/factory.py'
RUNNER = 'scripts/run_sc6a_acceptance.py'
PINS = {MESH: 'c3a6f0678a693a7b0f0ada2d891add312bb3454548fea15f8fb68156cdc7d757',
        COMPAT: '80e586b410107147c3fc96dc36f4f96141baeaaa654366ad49eb42fdea1e4e1a',
        'scripts/check_repository.py': 'cf39ee4dab44893fae58d4553c8a159942c5674f5ce33f22ca9c441d0a74dec8'}
COMPAT_NAMES = ('test_rendered_cores_pass_and_report_holes_and_regions',
                'test_triangle_bridging_two_regions_fails', 'test_interpolated_hole_fails')
DEPENDENCIES = ('numpy', 'rasterio', 'jsonschema', 'pyproj', 'pytest')
# Complete selected repository import closure, audited before execution. Imports
# inside unselected acquisition/BAG/CLI functions are not invoked or admitted.
CLOSURE = (MESH, 'src/skippercast/coastal/render/align.py',
           'src/skippercast/coastal/handoff/common.py',
           'src/skippercast/coastal/render/terrain_only.py',
           'src/skippercast/coastal/render/preview.py',
           'src/skippercast/coastal/vertical.py', 'src/skippercast/coastal/receipts.py',
           'research/lib/paths.py', 'research/scripts/check_terrain_acceptance.py', COMPAT,
           'src/skippercast/__init__.py', 'src/skippercast/coastal/__init__.py',
           'src/skippercast/coastal/render/__init__.py',
           'src/skippercast/coastal/handoff/__init__.py',
           'src/skippercast/coastal/resources/__init__.py', TEST, FACTORY, RUNNER)


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def no_symlinks(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'symlink path refused: ' + str(part))
    return path


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def identity(repo):
    paths = set(CLOSURE) | set(PINS)
    resources = repo / 'src/skippercast/coastal/resources'
    paths.update(str(p.relative_to(repo)) for p in resources.glob('coastal-terrain-only-*.schema.json'))
    return dict(head=git(repo, 'rev-parse', 'HEAD'),
                status=git(repo, 'status', '--short'),
                source_hashes={p: sha(repo / p) for p in sorted(paths)})


def preflight(repo, data_root, suite):
    manifest_path = repo.parent / 'SOURCE-MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    require(manifest['head'] == BASE and manifest['clean'] is True, 'unmodified staged baseline required')
    spec = json.loads((repo.parent / 'ACCEPTANCE-SPEC.json').read_text())
    require(manifest['runtime']['credential_scan_python3'] == spec['credential_scan_python3'],
            'credential scan runtime mismatch')
    require(Path(sys.executable).absolute() == repo / '.venv/bin/python3', 'literal staged interpreter required')
    require((repo / '.venv').resolve() == Path(manifest['runtime']['repo_venv']).resolve(), 'venv identity mismatch')
    require(git(repo, 'merge-base', BASE, 'HEAD') == BASE, 'pinned base ancestry mismatch')
    for name, expected in PINS.items():
        actual = hashlib.sha256(subprocess.run(
            ['git', '-C', str(repo), 'show', BASE + ':' + name],
            capture_output=True, check=True).stdout).hexdigest()
        require(actual == expected, 'baseline pin mismatch: ' + name)
        if name != MESH or suite == 'baseline':
            require(sha(repo / name) == expected, 'unchanged source mismatch: ' + name)
    missing = [name for name in DEPENDENCIES if importlib.util.find_spec(name) is None]
    require(not missing, 'missing dependencies: ' + ','.join(missing))
    # Research paths has no import effects; redirect its constants BEFORE the
    # selected test module imports ROOT. No selected function has a bound cache,
    # data-root or source-path default. Source/schema reads still use __file__.
    return dict(manifest_sha256=sha(manifest_path), dependencies=list(DEPENDENCIES),
                selected_import_closure=list(CLOSURE), fixture_root=str(data_root),
                redirected_constants=['research.lib.paths.ROOT', 'research.lib.paths.RESEARCH',
                                      'tempfile.tempdir'],
                bound_operational_defaults=[],
                excluded=['BAG/h5py', 'acquisition', 'run-mode renderer/subprocess probes',
                          'live caches', 'pytest plugins'])


class OfflineStop(BaseException):
    """Terminal refusal: deliberately outside Exception catches in product code."""


class Offline:
    def __init__(self, run):
        self.run = run.resolve()
        self.counts = dict(network=0, model=0, child_process=0, outside_write=0)
        self.refusals = []
        self.imports = set()

    def stop(self, kind, detail):
        self.counts[kind] += 1
        message = 'STOP ' + kind + ': ' + str(detail)
        self.refusals.append(message)
        raise OfflineStop(message)

    def path(self, path):
        if isinstance(path, int):
            return  # standard pre-opened stream descriptor; no path acquisition
        target = Path(os.fsdecode(path)).absolute()
        if not target.resolve().is_relative_to(self.run):
            self.stop('outside_write', target)
        no_symlinks(target)

    def audit(self, event, args):
        if event == 'import':
            name = args[0]
            self.imports.add(name)
            if name.split('.')[0] in {'openai', 'anthropic', 'litellm', 'ollama', 'h5py'}:
                self.stop('model', name)
        if event.startswith('socket.') and event not in {'socket.__new__'}:
            self.stop('network', event)
        if event in {'subprocess.Popen', 'os.system', 'os.fork', 'os.posix_spawn', 'pty.spawn'}:
            self.stop('child_process', event)
        if event == 'open':
            path, mode, flags = args
            if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                self.path(path)
        if event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate'}:
            self.path(args[0])
        if event in {'os.rename', 'os.link', 'os.symlink'}:
            self.path(args[0])
            self.path(args[1])

    def install(self):
        sys.addaudithook(self.audit)
        tempfile.tempdir = str(self.run)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, 'missing loader: ' + name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def addSuccess(self, test):
        self.rows.append(dict(id=test.id(), outcome='passed'))
        super().addSuccess(test)

    def addError(self, test, err):
        if issubclass(err[0], OfflineStop):
            raise err[1]  # never continue the suite after any actual guard refusal
        self.rows.append(dict(id=test.id(), outcome='error', error_type=err[0].__name__,
                              message=str(err[1])))
        super().addError(test, err)

    def addFailure(self, test, err):
        self.rows.append(dict(id=test.id(), outcome='failed', error_type=err[0].__name__,
                              message=str(err[1])))
        super().addFailure(test, err)

    def addSkip(self, test, reason):
        self.rows.append(dict(id=test.id(), outcome='skipped', message=reason))
        super().addSkip(test, reason)


def run_tests(tests):
    expected = [test.id() for test in tests]
    require(expected and len(expected) == len(set(expected)), 'empty/duplicate test selection')
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(unittest.TestSuite(tests))
    require(result.testsRun == len(expected), 'test collection count mismatch')
    require(sorted(row['id'] for row in result.rows) == sorted(expected), 'test identity mismatch')
    require(not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses,
            'skips/expected failures are not qualification')
    return dict(expected_ids=expected, expected_count=len(expected), actual_count=result.testsRun,
                tests=result.rows, exit=0 if result.wasSuccessful() else 1, skips=len(result.skipped))


def compatibility(repo, data):
    module = load_module('sc6a_compat', repo / COMPAT)
    tests = []
    for name in COMPAT_NAMES:
        function = getattr(module, name, None)
        require(callable(function), 'missing selector: ' + name)

        def invoke(function=function, name=name):
            root = data / name
            root.mkdir()
            with contextlib.redirect_stdout(io.StringIO()) as output:
                prep = module.prep.__wrapped__(root)
                if name == COMPAT_NAMES[0]:
                    def readouterr():
                        value = output.getvalue()
                        output.seek(0)
                        output.truncate()
                        return SimpleNamespace(out=value, err='')
                    function(prep, SimpleNamespace(readouterr=readouterr))
                else:
                    function(prep)
        case = unittest.FunctionTestCase(invoke, description=COMPAT + '::' + name)
        case.id = lambda name=name: COMPAT + '::' + name
        tests.append(case)
    return run_tests(tests)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=('preflight', 'baseline', 'regression',
                        'compatibility', 'negative-control', 'portability'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo = no_symlinks(Path(__file__).resolve().parents[1])
    out = no_symlinks(args.out)
    require(not out.is_relative_to(repo), 'evidence must stay outside repository')
    out.mkdir(parents=True, exist_ok=True)
    run = out / (args.suite + '-' + uuid.uuid4().hex)
    run.mkdir(exist_ok=False)
    data = run / 'data'
    data.mkdir()
    stdout, stderr = io.StringIO(), io.StringIO()
    receipt = dict(suite=args.suite, argv=[sys.executable, *sys.argv], cwd=str(Path.cwd()),
                   exit=1, skips=0, expected_ids=[], expected_count=0, actual_count=0, tests=[])
    guard = Offline(run)
    code = 1
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            receipt.update(identity(repo))
            closure = preflight(repo, data, args.suite)
            dump(run / 'pre-import-closure.json', closure)
            receipt['closure_sha256'] = sha(run / 'pre-import-closure.json')
            spec_path = repo.parent / 'ACCEPTANCE-SPEC.json'
            spec = json.loads(spec_path.read_text())
            receipt['spec_sha256'] = sha(spec_path)
            sys.path.insert(0, str(repo / 'src'))
            sys.path.insert(0, str(repo))
            guard.install()  # before third-party imports OR any product import
            for name in DEPENDENCIES:
                importlib.import_module(name)
            import rasterio
            original_open = rasterio.open

            def synthetic_open(path, *a, **kw):
                # Native GDAL IO is not covered by Python's open audit event.
                # Restrict every dataset open to generated data in this run.
                target = Path(path).resolve()
                if not target.is_relative_to(data.resolve()):
                    guard.stop('outside_write', 'non-synthetic raster: ' + str(path))
                no_symlinks(path)
                return original_open(path, *a, **kw)

            rasterio.open = synthetic_open
            import research.lib.paths as paths
            paths.ROOT, paths.RESEARCH = data, data / 'research'
            module = load_module('sc6a_regression', repo / TEST)
            module.DATA_ROOT = data
            cls = module.MeshIntegerTests
            names = unittest.defaultTestLoader.getTestCaseNames(cls)
            all_ids = ['sc6a_regression.MeshIntegerTests.' + name for name in names]
            require(all_ids == spec['regression_ids'], 'frozen regression IDs changed')
            if args.suite == 'preflight':
                # Import the whole chosen closure without invoking operations.
                load_module('sc6a_compat', repo / COMPAT)
                receipt.update(expected_ids=['runtime_source_import_preflight'], expected_count=1,
                               actual_count=1, tests=[dict(id='runtime_source_import_preflight', outcome='passed')], exit=0)
            elif args.suite == 'compatibility':
                receipt.update(compatibility(repo, data))
            else:
                if args.suite == 'portability':
                    foreign = run / 'non-repo-cwd'
                    foreign.mkdir()
                    os.chdir(foreign)
                    receipt['execution_cwd'] = str(foreign)
                    for path in (repo / TEST, repo / FACTORY, repo / RUNNER):
                        require(not re.search(r'/(?:home|Users)/[A-Za-z0-9_.-]+/', path.read_text()),
                                'box-only path in committed code')
                selected = spec['control_names'] if args.suite in {'baseline', 'negative-control'} else names
                if args.suite == 'negative-control':
                    import numpy as np
                    original_cast = np.ma.MaskedArray.astype

                    def fill_before_cast(self, *a, **kw):
                        if self.dtype.kind in 'iu':
                            return self.filled(np.nan).astype(*a, **kw)
                        return original_cast(self, *a, **kw)

                    with patch.object(np.ma.MaskedArray, 'astype', fill_before_cast):
                        inner = run_tests([cls(name) for name in selected])
                    receipt['inner_result'] = inner
                    wanted = ['passed', 'error']
                    require([row['outcome'] for row in inner['tests']] == wanted,
                            'control did not isolate integer failure and float positive')
                    error = inner['tests'][1]
                    require(error['error_type'] == 'TypeError' and
                            error['message'] == 'Cannot convert fill_value nan to dtype int16',
                            'wrong control failure')
                    require(inner['exit'] == 1, 'broken control unexpectedly passed')
                    receipt.update(inner)
                    receipt['exit'] = 0
                    receipt['expected_inner_exit'] = 1
                else:
                    receipt.update(run_tests([cls(name) for name in selected]))
            require(not guard.refusals and not any(guard.counts.values()), 'offline refusal is terminal')
            require({p: sha(repo / p) for p in receipt['source_hashes']} == receipt['source_hashes'],
                    'source changed during acceptance')
            code = receipt['exit']
        except BaseException as error:
            traceback.print_exc()
            receipt['exception'] = dict(type=type(error).__name__, message=str(error))
            code = 1
        finally:
            receipt['exit'] = code
            receipt['guard_counts'] = guard.counts
            receipt['refusals'] = guard.refusals
            receipt['observed_imports'] = sorted(guard.imports)
    (run / 'stdout.txt').write_text(stdout.getvalue())
    (run / 'stderr.txt').write_text(stderr.getvalue())
    receipt['stdout_sha256'] = sha(run / 'stdout.txt')
    receipt['stderr_sha256'] = sha(run / 'stderr.txt')
    dump(run / 'receipt.json', receipt)
    print(json.dumps(dict(run=str(run), suite=args.suite, exit=code,
                         tests=receipt['actual_count'], skips=receipt['skips'])))
    print(stdout.getvalue(), end='')
    print(stderr.getvalue(), end='', file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
