#!/usr/bin/env python3
"""Acceptance runner for SC-PNG-DTYPE (uint8-only fixed-format coastal preview PNG).

Runs the literal tests through the installed pytest API inside this process; it never
re-implements a check or invents a result.

  --suite focused   every test in tests/gis/test_sc_png_dtype.py (A1, A2, A3, A4)
  --suite contract  exactly the original compatibility files
                    tests/gis/test_coastal_terrain_admission.py and
                    tests/contract/test_research_boundary.py, with exact collection counts
  --suite negative  the A3 rows, then the decisive mutation: the test module's local
                    copy of the base (unguarded) write_png is swapped in memory for
                    mesh.write_png. The uint16 regression must fail with the independent
                    output-contract marker, the uint8 baseline control must stay green,
                    and a clean rerun after restoration must pass.

Order: bytecode writing is disabled first; the import path is set in code to this
repository (root, src/) plus its staged .venv site-packages when that venv reports
this interpreter's exact version (.pth files are not processed, so no editable install
of another checkout is activated). Network/process sentinels (function doubles plus an
audit hook) are armed before pytest or any project module is imported. pytest's
temporary root lives in the unique run directory below --output.

Exit 0 = PASS, 1 = FAIL, 3 = INPUT_UNAVAILABLE (a required dependency such as NumPy is
absent; nothing is installed or skipped). PASS is local scoped evidence only:
REVIEW REQUIRED, not full CI, source, live or semantic acceptance.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import contextlib  # noqa: E402
import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import importlib.metadata  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import stat  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / 'src'
VENV = REPO / '.venv'
VENV_SITE = VENV / 'lib' / f'python{sys.version_info[0]}.{sys.version_info[1]}' / 'site-packages'
CARD = 'SC-PNG-DTYPE'
BASE_COMMIT = '59fca09b2cc7f5c81a4796902504e263d7f06960'
TEST_FILE = 'tests/gis/test_sc_png_dtype.py'
MODULE = 'src/skippercast/coastal/render/mesh.py'
MODULE_NAME = 'skippercast.coastal.render.mesh'
FIXTURE_DIR = 'tests/fixtures/sc_png_dtype'
OWNED = [MODULE, TEST_FILE, 'research/scripts/accept_sc_png_dtype.py', 'docs/engineering/sc_png_dtype.md']
COMPAT = ['tests/gis/test_coastal_terrain_admission.py', 'tests/contract/test_research_boundary.py']
# Unchanged original files: the card pins the first; the second was measured at the base.
PINS = {'tests/gis/test_coastal_terrain_admission.py':
        'a52b0ef22aa33e7d4069fa1b2d9cbd81c7d81aefde9cea147527e5c08a71cfcc',
        'tests/contract/test_research_boundary.py':
        '769ea500d46ec3bdbb8c615c558b59cd6c11d8bf2a63b51d653cf014a26c945a'}
BASE_PINS_REPORTED = {MODULE: 'c3a6f0678a693a7b0f0ada2d891add312bb3454548fea15f8fb68156cdc7d757'}
SUPPORT_FILES = ['pyproject.toml', 'conftest.py', 'tests/conftest.py', 'tests/_support.py']
DTYPES = ['uint16', '>u2', 'uint32', 'uint64', 'int8', 'int16', 'int32', 'int64',
          'float16', 'float32', 'float64', 'complex64', 'bool', 'S1', 'object']
SHAPES = ['480x640x4', '480x640x1', '640x480x3', '479x640x3', '480x640', '480x640x3x1']
FOCUSED = (['test_a1_all_zero_matches_frozen_baseline', 'test_a1_pattern_matches_frozen_baseline',
            'test_a1_noncontiguous_column_view_keeps_logical_order',
            'test_a1_reversed_channel_and_row_views_keep_logical_order',
            'test_a1_fortran_order_and_readonly_arrays_keep_logical_order',
            'test_a1_valid_array_still_replaces_an_existing_target']
           + [f'test_a2_incompatible_dtype_refused_before_encoding_or_open[{d}]' for d in DTYPES]
           + [f'test_a2_incompatible_dtype_keeps_existing_target_bytes[{d}]' for d in DTYPES]
           + ['test_a2_uint16_refused_before_encoding']
           + [f'test_a2_wrong_shape_still_refused[{d}-{s}]' for d in ('uint8', 'uint16') for s in SHAPES]
           + ['test_a3_bypass_writes_invalid_uint16_scanlines',
              'test_a3_bypass_and_production_agree_on_valid_uint8',
              'test_a3_contract_checker_detects_tampering',
              'test_a4_tests_import_the_complete_staged_production_module',
              'test_a4_new_test_file_matches_configured_discovery',
              'test_a4_offline_sentinels_are_installed'])
NEGATIVE = ['test_a3_bypass_writes_invalid_uint16_scanlines',
            'test_a3_bypass_and_production_agree_on_valid_uint8',
            'test_a3_contract_checker_detects_tampering']
# Exact original collection at the base (measured; no silent subset).
COMPAT_COUNTS = {'tests/gis/test_coastal_terrain_admission.py': 8,
                 'tests/contract/test_research_boundary.py': 8}
MUTATION_DETECTOR = 'test_a2_uint16_refused_before_encoding'
MUTATION_CONTROL = 'test_a1_pattern_matches_frozen_baseline'
CONTRACT_MARKER = 'SC-PNG-DTYPE-CONTRACT'
LEGACY_CALLABLE = 'legacy_write_png_without_dtype_guard'
REQUIRED = ('numpy', 'pytest')
FORBIDDEN_MODULES = ('requests', 'urllib3', 'httpx', 'aiohttp', 'openai', 'anthropic', 'ollama',
                     'boto3', 'botocore')
SENTINEL_EVENTS = ('socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                   'socket.gethostbyaddr', 'socket.sendto', 'subprocess.Popen', 'os.system',
                   'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork', 'os.forkpty',
                   'urllib.Request', 'http.client.connect', 'webbrowser.open')
TRIPS = []
ARMED = [False]
# No process allowance. The compatibility imports (rasterio -> h5py) read
# platform.uname().processor; on Linux the stdlib computes that lazily by running
# `uname -p` (platform._Processor.from_subprocess). Before any import, that lookup is
# replaced by a deterministic test-local double that runs no child process and returns ''
# (the stdlib's own "undetermined" value). Each use is recorded; every real process
# attempt stays fatal.
PROCESSOR_DOUBLE_VALUE = ''
PROCESSOR_DOUBLE_CALLS = []
TEMP_EVENTS = ('tempfile.mkdtemp', 'tempfile.mkstemp')
TEMP_CREATIONS = []


def sha256(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def watched_files():
    names = OWNED + COMPAT + SUPPORT_FILES
    fixture = REPO / FIXTURE_DIR
    if fixture.is_dir():
        names += sorted(p.relative_to(REPO).as_posix() for p in fixture.rglob('*') if p.is_file())
    names += ['src/skippercast/coastal/render/terrain_only.py', 'src/skippercast/coastal/render/__init__.py']
    return list(dict.fromkeys(names))


def unique_dir(base):
    base = Path(base).absolute()
    if '..' in base.parts:
        raise SystemExit('refused output base: parent traversal')
    for component in list(reversed(base.parents)) + [base]:
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise SystemExit(f'refused output base: symlink or non-directory at {component}')
    if base == REPO or REPO in base.parents:
        raise SystemExit('refused output base: run evidence must stay outside the repository')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = base / f'{stamp}-{os.getpid()}-{secrets.token_hex(4)}'
    path.mkdir(parents=True, exist_ok=False)
    return path


def git_head():
    """HEAD from the staged .git files (no git subprocess)."""
    git = REPO / '.git'
    try:
        if git.is_file():
            pointer = git.read_text().strip()
            git = (REPO / pointer.removeprefix('gitdir: ')).resolve()
        head = (git / 'HEAD').read_text().strip()
        if not head.startswith('ref: '):
            return head
        ref = head[5:]
        common = git
        if (git / 'commondir').is_file():
            common = (git / (git / 'commondir').read_text().strip()).resolve()
        for root in (git, common):
            if (root / ref).is_file():
                return (root / ref).read_text().strip()
        for line in (common / 'packed-refs').read_text().splitlines():
            if line.endswith(' ' + ref):
                return line.split(' ', 1)[0]
    except OSError:
        return None
    return None


def audit(event, args):
    if event in TEMP_EVENTS:
        TEMP_CREATIONS.append({'event': event, 'path': str(args[0]) if args else None})
    if ARMED[0] and event in SENTINEL_EVENTS:
        TRIPS.append({'event': event, 'args': repr(args)[:200]})
        raise RuntimeError(f'offline sentinel: {event} is forbidden during acceptance')


def redirect_tempfile(out):
    """Point stdlib temporary-directory resolution at a fresh directory in this run.

    Done before pytest or any project module is imported. tempfile.tempdir is assigned
    directly, so an interpreter-cached earlier value cannot survive; TMPDIR/TEMP/TMP are
    set for anything that re-resolves. Every mkdtemp/mkstemp is recorded by the audit hook
    and must stay inside this root.
    """
    import tempfile
    root = out / 'tmp'
    root.mkdir(exist_ok=False)
    # Deliberately resolve (and so cache) the ambient value first, so the override is
    # proven against the previously cached tempfile.tempdir case on every run.
    ambient = tempfile.gettempdir()
    info = {'root': str(root), 'ambient_cached_before': ambient, 'cached_before': tempfile.tempdir,
            'env_before': {k: os.environ.get(k) for k in ('TMPDIR', 'TEMP', 'TMP')}}
    for key in ('TMPDIR', 'TEMP', 'TMP'):
        os.environ[key] = str(root)
    tempfile.tempdir = str(root)
    info['gettempdir_after'] = tempfile.gettempdir()
    if Path(info['gettempdir_after']).resolve() != root.resolve():
        raise SystemExit('tempfile redirection failed')
    return info


def temp_problems(root):
    root = Path(root).resolve()
    stray = [c for c in TEMP_CREATIONS
             if c['path'] is None or root not in Path(c['path']).resolve().parents]
    return [f'temporary paths created outside the run tmp root: {stray}'] if stray else []


def install_sentinels():
    """Function doubles plus an audit hook: regression guards, not a hostile-code sandbox."""
    import http.client
    import platform
    import socket
    import subprocess
    import urllib.request

    def refuse(name):
        def refused(*args, **kwargs):
            TRIPS.append({'event': name, 'args': ''})
            raise RuntimeError(f'offline sentinel: {name} is forbidden during acceptance')
        return refused

    def processor_double():
        """Test-local double for platform._Processor.from_subprocess: no child process."""
        caller = sys._getframe(1).f_globals.get('__file__')
        PROCESSOR_DOUBLE_CALLS.append({'caller': caller, 'returned': PROCESSOR_DOUBLE_VALUE, 'at': now()})
        return PROCESSOR_DOUBLE_VALUE

    platform._Processor.from_subprocess = staticmethod(processor_double)
    for owner, attr in ((socket, 'create_connection'), (socket, 'getaddrinfo'),
                        (socket, 'gethostbyname'), (socket, 'gethostbyaddr'),
                        (subprocess, 'run'), (subprocess, 'call'),
                        (subprocess, 'check_call'), (subprocess, 'check_output'),
                        (subprocess, 'getoutput'), (subprocess, 'getstatusoutput'),
                        (os, 'system'), (os, 'popen'), (urllib.request, 'urlopen'),
                        (http.client.HTTPConnection, 'connect')):
        setattr(owner, attr, refuse(f'{getattr(owner, "__name__", owner)}.{attr}'))
    # Direct subprocess.Popen construction is refused by the audit hook's subprocess.Popen event.
    sys.addaudithook(audit)
    ARMED[0] = True
    return {'events': list(SENTINEL_EVENTS), 'process_allowance': None,
            'processor_double': 'platform._Processor.from_subprocess -> '
                                f'{PROCESSOR_DOUBLE_VALUE!r} (no child process)'}


def resolve_dependencies():
    """Import path from this staged repository only; nothing is installed."""
    info = {'repo_on_path': [str(REPO), str(SRC)], 'venv_site': None, 'pth_files_processed': False}
    for entry in (str(REPO), str(SRC)):
        while entry in sys.path:
            sys.path.remove(entry)
    cfg = VENV / 'pyvenv.cfg'
    current = '.'.join(map(str, sys.version_info[:3]))
    if VENV_SITE.is_dir() and cfg.is_file():
        version = None
        for line in cfg.read_text().splitlines():
            key, _, value = line.partition('=')
            if key.strip() == 'version':
                version = value.strip()
        info['venv_version'] = version
        if version == current:
            sys.path.insert(0, str(VENV_SITE))
            info.update(venv_site=str(VENV_SITE), venv_site_resolved=str(VENV_SITE.resolve()),
                        venv_is_symlink=VENV.is_symlink())
        else:
            info['venv_refused'] = f'staged venv {version} does not match interpreter {current}'
    else:
        info['venv_refused'] = 'no staged .venv site-packages'
    sys.path.insert(0, str(SRC))
    sys.path.insert(0, str(REPO))
    found, missing = {}, []
    for name in REQUIRED:
        try:
            module = __import__(name)
        except ImportError as error:
            missing.append(f'{name}: {error}')
            continue
        found[name] = {'version': importlib.metadata.version(name), 'file': module.__file__}
    info['modules'] = found
    try:
        from tests import _support
        info['missing_gis_packages'] = _support.missing_gis_packages()
    except ImportError as error:
        info['missing_gis_packages'] = [f'tests._support: {error}']
    missing += [f'GIS stack: {name}' for name in info['missing_gis_packages']]
    return info, missing


def allowed_module_location(location, run_dir=None):
    if location is None:
        return True
    path = Path(location).resolve()
    roots = [REPO.resolve(), Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()]
    if VENV_SITE.is_dir():
        roots.append(VENV_SITE.resolve())
    if run_dir is not None:
        roots.append(Path(run_dir).resolve())
    return any(path == root or root in path.parents for root in roots)


class Collector:
    def __init__(self):
        self.collected, self.phases, self.collect_errors, self.longrepr = [], {}, [], {}

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.collect_errors.append({'nodeid': report.nodeid, 'longrepr': str(report.longrepr)[-4000:]})

    def pytest_runtest_logreport(self, report):
        outcome = 'xfail' if hasattr(report, 'wasxfail') else report.outcome
        self.phases.setdefault(report.nodeid, {})[report.when] = outcome
        if report.failed:
            self.longrepr[report.nodeid] = str(report.longrepr)[-6000:]

    def result(self, nodeid):
        phases = self.phases.get(nodeid, {})
        if 'failed' in phases.values():
            return 'failed'
        if {'skipped', 'xfail'} & set(phases.values()):
            return 'skipped'
        if all(phases.get(when) == 'passed' for when in ('setup', 'call', 'teardown')):
            return 'passed'
        return 'incomplete'

    def summary(self):
        results = {nodeid: self.result(nodeid) for nodeid in self.collected}
        counts = {}
        for value in results.values():
            counts[value] = counts.get(value, 0) + 1
        return results, counts


def make_mutation(pytest):
    class Mutation:
        """In-memory callable double: the base (unguarded) write_png replaces mesh.write_png."""

        def __init__(self):
            self.calls = {}

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_call(self, item):
            module = sys.modules[MODULE_NAME]
            original = module.write_png
            legacy = getattr(item.module, LEGACY_CALLABLE)
            nodeid = item.nodeid

            def counted(*args, **kwargs):
                self.calls[nodeid] = self.calls.get(nodeid, 0) + 1
                return legacy(*args, **kwargs)

            module.write_png = counted
            try:
                yield
            finally:
                module.write_png = original

    return Mutation()


def test_id(nodeid):
    return nodeid.split('::', 1)[1] if '::' in nodeid else nodeid


def run_session(pytest, out, label, targets, plugins=()):
    collector = Collector()
    stdout_file, stderr_file = out / f'{label}.stdout.txt', out / f'{label}.stderr.txt'
    argv = ['-p', 'no:cacheprovider', '-v', '--rootdir', str(REPO), '-c', str(REPO / 'pyproject.toml'),
            '--basetemp', str(out / f'pytest-tmp-{label}'), *targets]
    before = set(sys.modules)
    with open(stdout_file, 'w', encoding='utf-8') as so, open(stderr_file, 'w', encoding='utf-8') as se:
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = int(pytest.main(argv, plugins=[collector, *plugins]))
    results, counts = collector.summary()
    return {'label': label, 'pytest_argv': argv, 'exit': code, 'collected': collector.collected,
            'results': results, 'counts': counts, 'collect_errors': collector.collect_errors,
            'failures': collector.longrepr, 'imported_modules': sorted(set(sys.modules) - before),
            'stdout': stdout_file.name, 'stdout_sha256': sha256(stdout_file),
            'stderr': stderr_file.name, 'stderr_sha256': sha256(stderr_file)}


def clean(run, expected_ids):
    """Problems for a session that must pass completely with exactly the expected new tests."""
    label, problems = run['label'], []
    if run['exit'] != 0:
        problems.append(f'{label}: pytest exit {run["exit"]}')
    if run['collect_errors']:
        problems.append(f'{label}: collection errors {[e["nodeid"] for e in run["collect_errors"]]}')
    if not run['collected']:
        problems.append(f'{label}: nothing collected')
    bad = sorted(n for n, r in run['results'].items() if r != 'passed')
    if bad:
        problems.append(f'{label}: not passed {bad}')
    if expected_ids is not None:
        ours = {test_id(n) for n in run['collected'] if n.startswith(TEST_FILE + '::')}
        if sorted(set(expected_ids) - ours):
            problems.append(f'{label}: expected tests not collected {sorted(set(expected_ids) - ours)}')
        if sorted(ours - set(expected_ids)):
            problems.append(f'{label}: unexpected tests collected {sorted(ours - set(expected_ids))}')
    return problems


def targets_for(ids):
    functions = list(dict.fromkeys(i.split('[', 1)[0] for i in ids))
    return [f'{REPO / TEST_FILE}::{name}' for name in functions]


def negative_control(pytest, out):
    runs, problems, detail = [], [], {'legacy_callable': f'{TEST_FILE}::{LEGACY_CALLABLE}'}
    mutation = make_mutation(pytest)
    mutated = run_session(pytest, out, 'mutated', targets_for([MUTATION_DETECTOR, MUTATION_CONTROL]),
                          plugins=[mutation])
    runs.append(mutated)
    by_id = {test_id(n): r for n, r in mutated['results'].items()}
    detail.update(legacy_calls=mutation.calls, mutated_results=by_id)
    detector = [n for n in mutated['collected'] if test_id(n) == MUTATION_DETECTOR]
    control = [n for n in mutated['collected'] if test_id(n) == MUTATION_CONTROL]
    if by_id.get(MUTATION_DETECTOR) != 'failed':
        problems.append(f'mutant: the uint16 regression did not fail ({by_id.get(MUTATION_DETECTOR)})')
    elif not any(f'AssertionError: {CONTRACT_MARKER}: scanline bytes' in mutated['failures'].get(n, '')
                 for n in detector):
        problems.append('mutant: the uint16 regression failed for a reason other than the output contract')
    for ids, what in ((detector, 'regression'), (control, 'control')):
        if not any(mutation.calls.get(n, 0) >= 1 for n in ids):
            problems.append(f'mutant: the unguarded double was never called by the {what}')
    if by_id.get(MUTATION_CONTROL) != 'passed':
        problems.append(f'mutant: the uint8 baseline control did not stay green ({by_id.get(MUTATION_CONTROL)})')
    if mutated['collect_errors'] or set(by_id) != {MUTATION_DETECTOR, MUTATION_CONTROL}:
        problems.append(f'mutant: unexpected collection {sorted(by_id)} / {mutated["collect_errors"]}')
    restored = sys.modules[MODULE_NAME].write_png
    detail['restored_function'] = f'{restored.__module__}.{restored.__qualname__}'
    if detail['restored_function'] != MODULE_NAME + '.write_png':
        problems.append('mutant: the in-memory double was not removed after the mutated session')
    rerun = run_session(pytest, out, 'restored', targets_for(NEGATIVE + [MUTATION_DETECTOR, MUTATION_CONTROL]))
    runs.append(rerun)
    problems += clean(rerun, NEGATIVE + [MUTATION_DETECTOR, MUTATION_CONTROL])
    return runs, problems, detail


def main(argv):
    parser = argparse.ArgumentParser(description=f'{CARD} acceptance runner')
    parser.add_argument('--suite', required=True, choices=['focused', 'contract', 'negative'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    out = unique_dir(args.output)
    watched = watched_files()
    receipt = {
        'card': CARD, 'suite': args.suite, 'runner': str(Path(__file__).resolve()),
        'runner_sha256': sha256(Path(__file__).resolve()),
        'argv': list(getattr(sys, 'orig_argv', [sys.executable, *sys.argv])), 'cwd': os.getcwd(),
        'python': sys.executable, 'python_version': sys.version, 'repo': str(REPO), 'output': str(out),
        'started_at': now(), 'git_head': git_head(), 'frozen_base': BASE_COMMIT,
        'dont_write_bytecode': sys.dont_write_bytecode,
        'hashes_before': {name: sha256(REPO / name) for name in watched},
        'full_discovery': 'operator-run (venv-fullsuite / exact-head CI); not run by this runner',
        'status_meaning': 'PASS is local scoped evidence; REVIEW REQUIRED, not CI, source or live acceptance',
    }
    problems, runs, status = [], [], None
    receipt['pins'] = {n: {'expected': p, 'actual': receipt['hashes_before'].get(n)} for n, p in PINS.items()}
    receipt['base_pins_reported'] = {n: {'base': p, 'current': receipt['hashes_before'].get(n)}
                                     for n, p in BASE_PINS_REPORTED.items()}
    problems += [f'source pin mismatch: {n}' for n, row in receipt['pins'].items() if row['expected'] != row['actual']]
    receipt['tempfile'] = redirect_tempfile(out)
    receipt['sentinels'] = install_sentinels()
    modules_before = set(sys.modules)
    receipt['dependencies'], missing = resolve_dependencies()
    if missing:
        status = 'INPUT_UNAVAILABLE'
        problems.append(f'required dependencies absent (nothing installed, nothing skipped): {missing}')
    else:
        import pytest
        if args.suite == 'focused':
            run = run_session(pytest, out, 'focused', [str(REPO / TEST_FILE)])
            runs.append(run)
            problems += clean(run, FOCUSED)
        elif args.suite == 'contract':
            run = run_session(pytest, out, 'contract', [str(REPO / name) for name in COMPAT])
            runs.append(run)
            problems += clean(run, [])
            receipt['compatibility_tests'] = {}
            for name in COMPAT:
                count = len([n for n in run['collected'] if n.startswith(name + '::')])
                receipt['compatibility_tests'][name] = count
                if count == 0 or (COMPAT_COUNTS[name] is not None and count != COMPAT_COUNTS[name]):
                    problems.append(f'contract: {name} collected {count}, expected {COMPAT_COUNTS[name]}')
            if len(run['collected']) != sum(receipt['compatibility_tests'].values()):
                problems.append('contract: collected tests outside the two compatibility files')
        else:
            first = run_session(pytest, out, 'negative', targets_for(NEGATIVE))
            runs.append(first)
            problems += clean(first, NEGATIVE)
            more, found, receipt['negative_control'] = negative_control(pytest, out)
            runs += more
            problems += found
        module = sys.modules.get(MODULE_NAME)
        receipt['production_module_file'] = getattr(module, '__file__', None)
        if args.suite != 'contract' or module is not None:
            if module is None or Path(module.__file__).resolve() != (REPO / MODULE).resolve():
                problems.append('the staged production module was not the one imported')
    files = {name: getattr(module, '__file__', None) for name, module in list(sys.modules.items())}
    receipt['imports_traced'] = {name: files[name] for name in sorted(set(files) - modules_before)}
    outside = sorted(n for n, f in receipt['imports_traced'].items() if not allowed_module_location(f, out))
    forbidden = sorted(n for n in files if n.split('.')[0] in FORBIDDEN_MODULES)
    receipt.update(imports_outside_allowed_roots=outside, forbidden_modules_loaded=forbidden)
    if outside:
        problems.append(f'imports outside the staged repository/interpreter roots: {outside}')
    if forbidden:
        problems.append(f'forbidden network/model modules imported: {forbidden}')
    if receipt['dependencies'].get('venv_site'):
        for name, row in receipt['dependencies'].get('modules', {}).items():
            if not str(Path(row['file']).resolve()).startswith(str(VENV_SITE.resolve())):
                problems.append(f'{name} did not resolve from the staged venv')
    ARMED[0] = False
    receipt['sentinel_trips'] = list(TRIPS)
    receipt['allowed_process_calls'] = []
    receipt['processor_double_calls'] = list(PROCESSOR_DOUBLE_CALLS)
    receipt['temp_creations'] = list(TEMP_CREATIONS)
    problems += temp_problems(receipt['tempfile']['root'])
    if args.suite == 'contract' and not missing and not TEMP_CREATIONS:
        problems.append('contract: no compatibility TemporaryDirectory creation was observed')
    if TRIPS:
        problems.append(f'offline sentinel tripped: {[t["event"] for t in TRIPS]}')
    receipt['hashes_after'] = {name: sha256(REPO / name) for name in watched}
    if receipt['hashes_after'] != receipt['hashes_before']:
        problems.append('a submitted or frozen file changed during the run')
        status = None
    pycache = sorted(p.relative_to(REPO).as_posix() for p in SRC.rglob('__pycache__'))
    receipt['src_pycache_dirs'] = pycache
    if pycache:
        problems.append(f'bytecode caches present under src/: {pycache}')
    receipt['test_counts'] = {r['label']: r['counts'] for r in runs}
    receipt['tests_total'] = sum(len(r['collected']) for r in runs)
    receipt['skipped_total'] = sum(r['counts'].get('skipped', 0) for r in runs)
    if receipt['skipped_total']:
        problems.append(f'unexpected skips: {receipt["skipped_total"]}')
    status = status or ('PASS' if not problems else 'FAIL')
    receipt.update(runs=runs, problems=problems, status=status, finished_at=now(),
                   exit={'PASS': 0, 'FAIL': 1, 'INPUT_UNAVAILABLE': 3}[status])
    receipt_path = out / 'receipt.json'
    with open(receipt_path, 'x', encoding='utf-8') as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + '\n')
    for run in runs:
        print(f'{run["label"]}: pytest exit {run["exit"]} {run["counts"]}')
    for problem in problems:
        print(f'problem: {problem}', file=sys.stderr)
    print(f'{args.suite}: {status} REVIEW REQUIRED receipt={receipt_path} sha256={sha256(receipt_path)}')
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
