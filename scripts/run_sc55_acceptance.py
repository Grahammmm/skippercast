"""Offline SC55 acceptance. Each invocation retains its own immutable run evidence."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import traceback

sys.dont_write_bytecode = True

BASE_HEAD = 'f8bc7d365c0c5aa4a2e59ba576a95146c92a0367'
REGRESSION = [
    'test_exact_level_extrema_emit_no_lines',
    'test_real_geometry_and_order_are_preserved',
    'test_specific_positive_shapes',
    'test_duplicate_nodes_are_collapsed_without_reordering',
]
COMPATIBILITY = [
    'test_levels_are_interval_multiples_on_the_shelf',
    'test_trace_a_slope_gives_one_straight_line_per_depth',
    'test_trace_stops_at_a_gap_and_never_bridges_it',
    'test_trace_a_pit_is_a_closed_ring_and_a_saddle_splits_by_the_mean',
    'test_check_accepts_a_complete_contour_set',
    'test_check_rejects_gaps',
    'test_check_rejects_a_source_that_is_not_an_approved_binding',
    'test_review_expires_is_a_year_after_the_oldest_review',
    'test_overview_drops_short_lines_and_keeps_properties',
]
FILES = [
    'tests/unit/test_sc55_regression.py', 'tests/unit/test_depth_contours.py',
    'scripts/run_sc55_acceptance.py', 'scripts/check_repository.py',
    'pyproject.toml', 'conftest.py', 'tests/conftest.py', 'tests/_support.py',
    'tests/__init__.py', 'tests/unit/__init__.py',
]


def repository_root():
    return Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identities(root):
    paths = list((root / 'src').rglob('*.py')) + [root / name for name in FILES]
    return {path.relative_to(root).as_posix(): digest(path)
            for path in sorted(set(paths)) if path.is_file()}


def head(root):
    git = root / '.git'
    if git.is_file():
        target = git.read_text().strip().removeprefix('gitdir: ')
        git = (root / target).resolve()
    value = (git / 'HEAD').read_text().strip()
    if not value.startswith('ref: '):
        return value
    ref = value.removeprefix('ref: ')
    if (git / ref).is_file():
        return (git / ref).read_text().strip()
    for line in (git / 'packed-refs').read_text().splitlines():
        if line.endswith(' ' + ref):
            return line.split()[0]
    raise RuntimeError('Cannot resolve staged HEAD')


def install_guards(events):
    """Before third-party or candidate imports; unexpected attempted I/O is fatal."""
    prohibited = {'subprocess.Popen', 'os.system', 'os.fork', 'os.forkpty',
                  'os.posix_spawn', 'os.exec', 'os.spawn',
                  'socket.connect', 'socket.bind', 'socket.sendto',
                  'socket.getaddrinfo', 'socket.gethostbyname',
                  'socket.gethostbyaddr', 'socket.getnameinfo'}

    def audit(event, args):
        if event in prohibited:
            events.append(event)
            raise RuntimeError('SC55 offline boundary: ' + event)
    sys.addaudithook(audit)


class Tee(io.TextIOBase):
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        self.log.write(text)
        self.console.write(text)
        return len(text)

    def flush(self):
        self.log.flush()
        self.console.flush()


class Results:
    def __init__(self):
        self.collected, self.reports = [], []

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report):
        self.reports.append({'nodeid': report.nodeid, 'phase': report.when,
                             'outcome': report.outcome})


def run_tests(mode, run, receipt):
    root = repository_root()
    os.chdir(root)
    sys.path[:0] = [str(root / 'src'), str(root)]
    for name in ('numpy', 'rasterio', 'pytest', 'jsonschema'):
        module = importlib.import_module(name)
        receipt.setdefault('runtime', {})[name] = {
            'origin': module.__file__, 'version': importlib.metadata.version(name)}
    import pytest
    from skippercast.platform import depth_contours as dc
    if Path(dc.__file__).resolve() != root / 'src/skippercast/platform/depth_contours.py':
        raise RuntimeError('Ambient tracer import refused')
    from skippercast.platform import contracts
    if contracts.REPO != root:
        raise RuntimeError('Ambient import-time repository root refused')
    # These paths may never be exercised by this offline tracer acceptance.
    def not_admitted(*args, **kwargs):
        raise RuntimeError('Reader/publisher is not admitted in SC55 acceptance')
    dc.publish_depth_contours = not_admitted
    dc.read_json = not_admitted
    receipt['execution_root'] = str(root)
    receipt['runner_origin'] = str(Path(__file__).resolve())
    receipt['synthetic_home'] = str(Path.home())
    if Path.home() != run / 'synthetic-home':
        raise RuntimeError('HOME was not redirected before imports')
    if mode == 'compatibility':
        selectors = ['tests/unit/test_depth_contours.py::' + name for name in COMPATIBILITY]
        expected = 21
    else:
        names = ['test_mutation_control'] if mode == 'mutation' else REGRESSION
        selectors = ['tests/unit/test_sc55_regression.py::' + name for name in names]
        expected = 1 if mode == 'mutation' else 12
    args = ['-vv', '-p', 'no:cacheprovider', '--basetemp', str(run / 'pytest-temp'), *selectors]
    receipt['pytest_argv'] = args
    results = Results()
    code = int(pytest.main(args, plugins=[results]))
    receipt['pytest_exit'] = code
    receipt['collected'] = results.collected
    receipt['reports'] = results.reports
    receipt['test_count'] = len(results.collected)
    receipt['passed_calls'] = sum(r['phase'] == 'call' and r['outcome'] == 'passed'
                                  for r in results.reports)
    receipt['skips'] = [r for r in results.reports if r['outcome'] == 'skipped']
    origins = {name: str(Path(module.__file__).resolve())
               for name, module in sorted(sys.modules.items())
               if (name == 'skippercast' or name.startswith('skippercast.')
                   or name == 'tests' or name.startswith('tests.'))
               and getattr(module, '__file__', None)}
    receipt['module_origins'] = origins
    if any(not Path(path).is_relative_to(root) for path in origins.values()):
        raise RuntimeError('Ambient candidate/test module import refused')
    if code or receipt['skips'] or len(results.collected) != expected or receipt['passed_calls'] != expected:
        raise RuntimeError(f'Acceptance failed: exit={code}, collected={len(results.collected)}, '
                           f'passed={receipt["passed_calls"]}, expected={expected}, skips={len(receipt["skips"])}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['regression', 'mutation', 'compatibility', 'portability'], required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    root = repository_root()
    output = args.output_root.resolve()
    if output.is_relative_to(root):
        raise RuntimeError('Output must be outside the committed repository')
    output.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='sc55-' + args.mode + '-', dir=output))
    receipt = {'mode': args.mode, 'argv': sys.argv, 'cwd': str(Path.cwd()),
               'base_head': BASE_HEAD, 'staged_head': head(root), 'run': str(run),
               'source_before': identities(root), 'exit': 1, 'boundary_attempts': []}
    install_guards(receipt['boundary_attempts'])
    os.environ['HOME'] = str(run / 'synthetic-home')
    Path(os.environ['HOME']).mkdir()
    os.environ['TMPDIR'] = str(run)
    tempfile.tempdir = str(run)
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    # Do not inherit an ambient product-root override from a job environment.
    os.environ.pop('SKIPPERCAST_ROOT', None)
    original_cwd = Path.cwd()
    relocated = None
    raw = run / 'raw-output.txt'
    with raw.open('w') as log, contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
        try:
            print('SC55 mode:', args.mode, 'run:', run, flush=True)
            if args.mode == 'portability':
                relocated = run / 'different-test-local-name'
                relocated.mkdir()
                shutil.copytree(root / 'src', relocated / 'src', ignore=shutil.ignore_patterns('__pycache__'))
                for name in FILES:
                    source = root / name
                    if source.is_file():
                        target = relocated / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
                before = identities(relocated)
                if before != receipt['source_before']:
                    raise RuntimeError('Relocated candidate is not byte-identical')
                # Execute the identical runner from its relocated __file__, in process.
                namespace = runpy.run_path(str(relocated / 'scripts/run_sc55_acceptance.py'), run_name='sc55_portable_runner')
                namespace['run_tests']('regression', run, receipt)
                receipt['relocated_preserved'] = identities(relocated) == before
                if not receipt['relocated_preserved']:
                    raise RuntimeError('Relocated inputs changed')
            else:
                run_tests(args.mode, run, receipt)
            if receipt['boundary_attempts']:
                raise RuntimeError('Unexpected offline boundary attempt')
            receipt['exit'] = 0
        except Exception:
            traceback.print_exc()
        finally:
            os.chdir(original_cwd)
            receipt['source_after'] = identities(root)
            receipt['inputs_preserved'] = receipt['source_before'] == receipt['source_after']
            if not receipt['inputs_preserved']:
                receipt['exit'] = 1
            print('SC55 result:', receipt['exit'], 'tests:', receipt.get('test_count', 0),
                  'inputs preserved:', receipt['inputs_preserved'], flush=True)
    receipt['raw_output_sha256'] = digest(raw)
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Evidence:', run / 'receipt.json')
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())
