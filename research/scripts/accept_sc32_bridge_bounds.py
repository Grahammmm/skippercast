#!/usr/bin/env python3
"""Acceptance runner for SC32-BRIDGE-BOUNDS (malformed CRS84 boxes never plan a bridge).

Stdlib launcher for the literal tests in tests/unit/test_sc32_bridge_bounds.py and
the unchanged compatibility selectors, run in this process through the installed
pytest API. It never reimplements a check or makes up a result.

  --suite focused   every A1 and A2 row of the new test module
  --suite contract  the A4 rows, the original tests/unit/test_coastal_catalog_bridge.py
                    and tests/contract/test_research_boundary.py (unchanged)
  --suite negative  the test_mutation_controls_* rows, then one decisive in-memory
                    mutation of the staged catalog_bridge module (production bytes
                    are never edited):
                      legacy-overlaps   catalog_bridge._overlaps <- the test-local
                                        pre-SC32 float-coercing predicate
                                        (legacy_overlaps); the named typed/range
                                        detector cases must fail with their SC32
                                        marker while the valid-overlap and
                                        edge-adjacency controls stay green
                    followed by a clean restored rerun that must pass.

Order of operations: bytecode writing is turned off first. The import path is set
in code to this staged repository's src/ and root (plus its staged .venv
site-packages when that venv matches this interpreter; .pth files, including the
editable-install pointer, are NOT processed, so `skippercast` can only come from
this repository's src/). SKIPPERCAST_ROOT is pinned to this repository and
SKIPPERCAST_NETWORK is removed. Network, subprocess and process-spawn sentinels
(function doubles plus an audit hook) are installed and probed, and
TMPDIR/tempfile are redirected into the unique run directory, BEFORE pytest or any
project module is imported. No process call is let through.

Each run writes a NEW directory below --output (never reused) holding receipt.json
and the raw stdout/stderr of every pytest session. Exit 0 = PASS, 1 = FAIL,
3 = INPUT_UNAVAILABLE (a required dependency is absent; nothing is installed).
PASS is local scoped evidence: REVIEW REQUIRED, not CI or approval.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import contextlib  # noqa: E402
import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / 'src'
VENV = REPO / '.venv'
VENV_SITE = VENV / 'lib' / f'python{sys.version_info[0]}.{sys.version_info[1]}' / 'site-packages'
CARD = 'SC32-BRIDGE-BOUNDS'
TEST_FILE = 'tests/unit/test_sc32_bridge_bounds.py'
COMPAT = ['tests/unit/test_coastal_catalog_bridge.py', 'tests/contract/test_research_boundary.py']
MODULE = 'src/skippercast/coastal/coordinator/catalog_bridge.py'
MODULE_NAME = 'skippercast.coastal.coordinator.catalog_bridge'
FIXTURE_DIR = 'tests/fixtures/sc32_bridge_bounds'
OWNED = [MODULE, TEST_FILE, 'research/scripts/accept_sc32_bridge_bounds.py',
         'docs/engineering/sc32_bridge_bounds.md']
BASE_COMMIT = '59fca09b2cc7f5c81a4796902504e263d7f06960'
# Files that must still equal the card's frozen base pins.
PINS = {'tests/unit/test_coastal_catalog_bridge.py':
        '2db21189baf48f25777150dd996cf308659929a01e58a25f94776de9d3ded525'}
# The submitted patch changes catalog_bridge.py; its base pin is reported, not enforced.
BASE_PINS_REPORTED = {MODULE: '0bcc336a3e0459031d8b362b0f916f6e1a08701719a7a5ca20104fd76ed2f40e'}
EXPECTED = {
    'focused': [
        'test_a1_valid_candidate_extent_is_selected',
        'test_a1_edge_adjacent_and_disjoint_candidates_are_held',
        'test_a1_segment_boxes_on_exact_geographic_edges_plan_normally',
        'test_a1_overlap_predicate_is_positive_area_only_and_symmetric',
        'test_a1_ordinary_dry_run_keeps_its_receipt_shape',
        'test_a2_overlaps_rejects_a_malformed_coordinate',
        'test_a2_overlaps_rejects_a_malformed_shape',
        'test_a2_overlaps_rejects_tuples_and_numeric_string_boxes',
        'test_a2_malformed_segment_coordinate_is_refused_before_any_source_or_output',
        'test_a2_malformed_segment_shape_is_refused_before_any_source_or_output',
        'test_a2_malformed_candidate_coordinate_is_held',
        'test_a2_malformed_candidate_shape_is_held',
        'test_a2_nonfinite_candidate_extent_cannot_enter_a_frozen_catalog',
        'test_a2_candidate_failures_keep_the_existing_hold_vocabulary',
    ],
    'contract': [
        'test_a4_tests_import_the_complete_staged_production_module',
        'test_a4_new_test_module_is_discovered_by_configured_patterns',
    ],
    'negative': [
        'test_mutation_controls_legacy_predicate_accepts_what_production_refuses',
        'test_mutation_controls_legacy_and_production_agree_on_valid_boxes',
        'test_mutation_controls_production_predicate_is_not_the_legacy_callable',
    ],
}
# Exact focused parametrized case count recorded on the staged baseline red run
# (23 A1 cases + 170 A2 cases); fewer collected cases is a silent subset.
FOCUSED_MINIMUM = 193
# Minimum original compatibility test counts (honest collection; no silent subset).
COMPAT_MINIMUM = {'tests/unit/test_coastal_catalog_bridge.py': 71,
                  'tests/contract/test_research_boundary.py': 8}
CONTROLS = ['test_a1_valid_candidate_extent_is_selected',
            'test_a1_edge_adjacent_and_disjoint_candidates_are_held',
            'test_a1_overlap_predicate_is_positive_area_only_and_symmetric']
MUTATIONS = {
    'legacy-overlaps': dict(attribute='_overlaps', legacy='legacy_overlaps', detectors=[
        ('test_a2_overlaps_rejects_a_malformed_coordinate', 'west-numeric-string', 'SC32-OVERLAP-ACCEPTED'),
        ('test_a2_overlaps_rejects_a_malformed_coordinate', 'east-inf', 'SC32-OVERLAP-ACCEPTED'),
        ('test_a2_overlaps_rejects_a_malformed_coordinate', 'west-minus-inf', 'SC32-OVERLAP-ACCEPTED'),
        ('test_a2_overlaps_rejects_a_malformed_coordinate', 'north-huge-int', 'SC32-OVERLAP-RAISED'),
        ('test_a2_overlaps_rejects_a_malformed_shape', 'east-above-180', 'SC32-OVERLAP-ACCEPTED'),
        ('test_a2_malformed_candidate_coordinate_is_held', 'south-numeric-string', 'SC32-CANDIDATE-SELECTED'),
        ('test_a2_malformed_candidate_coordinate_is_held', 'east-huge-int', 'SC32-CANDIDATE-RAISED'),
        ('test_a2_malformed_candidate_shape_is_held', 'east-just-above-180', 'SC32-CANDIDATE-SELECTED'),
        ('test_a2_malformed_candidate_shape_is_held', 'north-just-above-90', 'SC32-CANDIDATE-SELECTED'),
    ]),
}
FORBIDDEN_MODULES = ('requests', 'urllib3', 'httpx', 'aiohttp', 'openai', 'anthropic', 'ollama',
                     'boto3', 'botocore', 'rasterio')
SENTINEL_EVENTS = ('socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                   'socket.gethostbyaddr', 'socket.sendto', 'subprocess.Popen', 'os.system',
                   'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork', 'os.forkpty',
                   'urllib.Request', 'http.client.connect', 'webbrowser.open')
TRIPS = []
ARMED = [False]


def sha256(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def watched_files():
    names = list(OWNED) + list(PINS) + [c for c in COMPAT if c not in PINS]
    names += ['pyproject.toml', 'tests/_coastal_catalog_fixture.py', 'tests/_support.py', 'tests/conftest.py',
              'tests/_coastal_operations.py', 'src/skippercast/http.py', 'src/skippercast/paths.py',
              'src/skippercast/coastal/coordinator/stages.py']
    fixture = REPO / FIXTURE_DIR
    if fixture.is_dir():
        names += sorted(p.relative_to(REPO).as_posix() for p in fixture.rglob('*') if p.is_file())
    return names


def no_symlink_ancestry(path):
    path = Path(path).absolute()
    if '..' in path.parts:
        return 'parent traversal'
    for component in list(reversed(path.parents)) + [path]:
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            return 'symlink in ancestry: ' + component.name
        if not stat.S_ISDIR(mode):
            return 'non-directory in ancestry: ' + component.name
    return None


def unique_dir(base):
    problem = no_symlink_ancestry(base)
    if problem:
        raise SystemExit('refused output base: ' + problem)
    base = Path(base).absolute()
    if base == REPO or REPO in base.parents:
        raise SystemExit('refused output base: run evidence must stay outside the repository')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = base / f'{stamp}-{os.getpid()}-{secrets.token_hex(4)}'
    path.mkdir(parents=True, exist_ok=False)
    return path


def git_head():
    """Read HEAD from the staged .git files (no git subprocess)."""
    git = REPO / '.git'
    try:
        if git.is_file():
            pointer = git.read_text().strip()
            if not pointer.startswith('gitdir: '):
                return None
            git = (REPO / pointer[8:]).resolve()
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
    if ARMED[0] and event in SENTINEL_EVENTS:
        TRIPS.append({'event': event, 'args': repr(args)[:200]})
        raise RuntimeError('offline sentinel: ' + event + ' is forbidden during acceptance')


def install_sentinels():
    """Function doubles plus an audit hook; regression guards, not a hostile-code sandbox."""
    import http.client
    import socket
    import subprocess
    import urllib.request

    def refuse(name):
        def refused(*args, **kwargs):
            TRIPS.append({'event': name, 'args': ''})
            raise RuntimeError('offline sentinel: ' + name + ' is forbidden during acceptance')
        return refused

    for owner, attr in ((socket, 'create_connection'), (socket, 'getaddrinfo'),
                        (socket, 'gethostbyname'), (socket, 'gethostbyaddr'),
                        (subprocess, 'Popen'), (subprocess, 'run'), (subprocess, 'call'),
                        (subprocess, 'check_call'), (subprocess, 'check_output'),
                        (os, 'system'), (os, 'popen'), (urllib.request, 'urlopen'),
                        (http.client.HTTPConnection, 'connect')):
        setattr(owner, attr, refuse(getattr(owner, '__name__', str(owner)) + '.' + attr))
    sys.addaudithook(audit)
    ARMED[0] = True
    return list(SENTINEL_EVENTS)


def probe_sentinels():
    """Prove the doubles refuse before any real call; the probe trips are then discarded."""
    import socket
    import subprocess
    results = {}
    for name, call in (('socket.create_connection', lambda: socket.create_connection(('127.0.0.1', 9), 0.01)),
                       ('socket.getaddrinfo', lambda: socket.getaddrinfo('localhost', 9)),
                       ('subprocess.run', lambda: subprocess.run(['true'], check=False)),
                       ('subprocess.Popen', lambda: subprocess.Popen(['true'])),
                       ('os.system', lambda: os.system('true'))):
        try:
            call()
            results[name] = 'NOT REFUSED'
        except RuntimeError as error:
            results[name] = 'refused' if 'offline sentinel' in str(error) else f'other: {error}'
        except Exception as error:  # noqa: BLE001 - recorded, counts as failure
            results[name] = f'other: {type(error).__name__}: {error}'
    del TRIPS[:]
    return results


def isolate_environment(out):
    """Path plumbing only: temp root, repository root pin, network opt-in removed."""
    tmp = out / 'tmp'
    tmp.mkdir(exist_ok=False)
    previous = {name: os.environ.get(name) for name in ('TMPDIR', 'SKIPPERCAST_ROOT', 'SKIPPERCAST_NETWORK')}
    os.environ['TMPDIR'] = str(tmp)
    tempfile.tempdir = str(tmp)
    os.environ['SKIPPERCAST_ROOT'] = str(REPO)
    os.environ.pop('SKIPPERCAST_NETWORK', None)
    return {'tempdir': str(tmp), 'SKIPPERCAST_ROOT': str(REPO), 'SKIPPERCAST_NETWORK': 'removed',
            'previous_values_present': {k: v is not None for k, v in previous.items()}}


def resolve_dependencies():
    """Import path from this staged repository only; never install anything."""
    info = {'repo_on_path': [str(SRC), str(REPO)], 'venv_site': None, 'pth_files_processed': False}
    for entry in (str(REPO), str(SRC)):
        while entry in sys.path:
            sys.path.remove(entry)
    venv_cfg = VENV / 'pyvenv.cfg'
    if VENV_SITE.is_dir() and venv_cfg.is_file():
        version = None
        for line in venv_cfg.read_text().splitlines():
            key, _, value = line.partition('=')
            if key.strip() == 'version':
                version = value.strip()
        current = '.'.join(map(str, sys.version_info[:3]))
        info['venv_version'] = version
        info['venv_resolved'] = str(VENV.resolve())
        if version == current:
            sys.path.insert(0, str(VENV_SITE))
            info['venv_site'] = str(VENV_SITE)
        else:
            info['venv_refused'] = f'staged venv {version} does not match interpreter {current}'
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(SRC))
    found, missing = {}, []
    import importlib.metadata
    for name in ('pytest',):
        try:
            module = __import__(name)
        except ImportError as error:
            missing.append(f'{name}: {error}')
            continue
        found[name] = {'version': importlib.metadata.version(name), 'file': module.__file__}
    info['modules'] = found
    info['sys_path_head'] = sys.path[:4]
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


def make_collector():
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
            if any(value == 'failed' for value in phases.values()):
                return 'failed'
            if any(value in ('skipped', 'xfail') for value in phases.values()):
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

    return Collector()


def make_mutation(pytest, attribute, legacy_name):
    class Mutation:
        """In-memory callable double: the test-local original predicate replaces one helper."""

        def __init__(self):
            self.calls = {}

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_call(self, item):
            module = sys.modules[MODULE_NAME]
            original = getattr(module, attribute)
            legacy = getattr(item.module, legacy_name)
            nodeid = item.nodeid

            def counted(*args, **kwargs):
                self.calls[nodeid] = self.calls.get(nodeid, 0) + 1
                return legacy(*args, **kwargs)

            setattr(module, attribute, counted)
            try:
                yield
            finally:
                setattr(module, attribute, original)

    return Mutation()


def function_name(nodeid):
    return nodeid.split('::', 1)[1].split('[', 1)[0] if '::' in nodeid else nodeid


def case_tokens(nodeid):
    if '[' not in nodeid:
        return ''
    return nodeid.split('[', 1)[1].rstrip(']')


def run_session(pytest, out, label, targets, extra_plugins=()):
    collector = make_collector()
    stdout_file, stderr_file = out / f'{label}.stdout.txt', out / f'{label}.stderr.txt'
    argv = ['-p', 'no:cacheprovider', '-v', '--rootdir', str(REPO), '-c', str(REPO / 'pyproject.toml'),
            '--basetemp', str(out / f'pytest-tmp-{label}'), *targets]
    before = set(sys.modules)
    with open(stdout_file, 'w', encoding='utf-8') as so, open(stderr_file, 'w', encoding='utf-8') as se:
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = int(pytest.main(argv, plugins=[collector, *extra_plugins]))
    results, counts = collector.summary()
    return {
        'label': label, 'pytest_argv': argv, 'exit': code, 'collected': collector.collected,
        'results': results, 'counts': counts, 'collect_errors': collector.collect_errors,
        'failures': collector.longrepr, 'imported_modules': sorted(set(sys.modules) - before),
        'stdout': stdout_file.name, 'stdout_sha256': sha256(stdout_file),
        'stderr': stderr_file.name, 'stderr_sha256': sha256(stderr_file),
    }


def clean(run, expected_functions, label=None):
    """Problems with a session that must pass completely, with exactly the expected new tests."""
    label = label or run['label']
    problems = []
    if run['exit'] != 0:
        problems.append(f'{label}: pytest exit {run["exit"]}')
    if run['collect_errors']:
        problems.append(f'{label}: collection errors {[e["nodeid"] for e in run["collect_errors"]]}')
    if not run['collected']:
        problems.append(f'{label}: nothing collected')
    bad = sorted(n for n, r in run['results'].items() if r != 'passed')
    if bad:
        problems.append(f'{label}: not passed {bad}')
    if expected_functions is not None:
        ours = {function_name(n) for n in run['collected'] if n.startswith(TEST_FILE + '::')}
        missing = sorted(set(expected_functions) - ours)
        extra = sorted(ours - set(expected_functions))
        if missing:
            problems.append(f'{label}: expected tests not collected {missing}')
        if extra:
            problems.append(f'{label}: unexpected tests collected {extra}')
    return problems


def targets_for(names):
    return [str(REPO / TEST_FILE) + '::' + name for name in names]


def negative_controls(pytest, out):
    runs, problems, detail = [], [], {}
    for label, spec in MUTATIONS.items():
        if not callable(getattr(sys.modules.get(MODULE_NAME), spec['attribute'], None)):
            problems.append(f'{label}: mutation target {MODULE_NAME}.{spec["attribute"]} is absent; '
                            'the mutation cannot be exercised')
            detail[label] = {'attribute': f'{MODULE_NAME}.{spec["attribute"]}', 'absent': True}
            continue
        detector_targets = [str(REPO / TEST_FILE) + f'::{fn}[{case}]' for fn, case, _ in spec['detectors']]
        mutation = make_mutation(pytest, spec['attribute'], spec['legacy'])
        mutated = run_session(pytest, out, 'mutated-' + label, detector_targets + targets_for(CONTROLS),
                              extra_plugins=[mutation])
        runs.append(mutated)
        row = {'attribute': f'{MODULE_NAME}.{spec["attribute"]}',
               'legacy_callable': f'{TEST_FILE}::{spec["legacy"]}', 'detectors': {}, 'controls': {}}
        if mutated['collect_errors']:
            problems.append(f'{label}: collection errors under mutation')
        for function, case, marker in spec['detectors']:
            ids = [n for n in mutated['collected'] if function_name(n) == function and case_tokens(n) == case]
            if len(ids) != 1:
                problems.append(f'{label}: detector case {function}[{case}] collected {len(ids)} times')
                continue
            nodeid = ids[0]
            text = mutated['failures'].get(nodeid, '')
            result = mutated['results'].get(nodeid)
            row['detectors'][nodeid] = {'result': result, 'legacy_calls': mutation.calls.get(nodeid, 0),
                                        'marker': marker, 'marker_found': marker in text}
            if result != 'failed':
                problems.append(f'{label}: detector {nodeid} did not fail ({result})')
            elif marker not in text:
                problems.append(f'{label}: detector {nodeid} failed without its marker {marker}')
            if mutation.calls.get(nodeid, 0) < 1:
                problems.append(f'{label}: legacy double never called by detector {nodeid}')
        control_ids = [n for n in mutated['collected'] if function_name(n) in CONTROLS]
        if len(control_ids) < len(CONTROLS):
            problems.append(f'{label}: controls not collected under mutation')
        for nodeid in control_ids:
            row['controls'][nodeid] = {'result': mutated['results'].get(nodeid),
                                       'legacy_calls': mutation.calls.get(nodeid, 0)}
            if mutated['results'].get(nodeid) != 'passed':
                problems.append(f'{label}: legitimate control {nodeid} did not stay green')
            if mutation.calls.get(nodeid, 0) < 1:
                problems.append(f'{label}: legacy double not exercised by control {nodeid}')
        restored = getattr(sys.modules[MODULE_NAME], spec['attribute'])
        row['restored_function'] = f'{restored.__module__}.{restored.__qualname__}'
        if row['restored_function'] != f'{MODULE_NAME}.{spec["attribute"]}':
            problems.append(f'{label}: the in-memory double was not removed after the mutated session')
        detail[label] = row
        restored_run = run_session(pytest, out, 'restored', detector_targets + targets_for(EXPECTED['negative']
                                                                                            + CONTROLS))
        runs.append(restored_run)
        problems += clean(restored_run, None)
        for function, case, _ in spec['detectors']:
            ids = [n for n in restored_run['collected']
                   if function_name(n) == function and case_tokens(n) == case]
            if len(ids) != 1 or restored_run['results'].get(ids[0]) != 'passed':
                problems.append(f'restored: detector {function}[{case}] not passed on the restored module')
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
        'argv': list(getattr(sys, 'orig_argv', [sys.executable, *sys.argv])), 'cwd': os.getcwd(),
        'python': sys.executable, 'python_version': sys.version, 'repo': str(REPO), 'output': str(out),
        'started_at': now(), 'git_head': git_head(), 'frozen_base': BASE_COMMIT,
        'dont_write_bytecode': sys.dont_write_bytecode,
        'hashes_before': {name: sha256(REPO / name) for name in watched},
        'full_discovery': 'operator-run (venv-fullsuite); not run by this runner',
        'status_meaning': 'PASS is local scoped evidence; REVIEW REQUIRED, not CI, source qualification or approval',
        'path_substitutions': ('SKIPPERCAST_ROOT pinned to this repository and SKIPPERCAST_NETWORK removed '
                               'before any project import (path plumbing only); catalog_bridge has no path '
                               'constants or path-valued defaults; every new test passes an explicit allowlist'),
    }
    problems, runs, status = [], [], None
    receipt['pins'] = {name: {'expected': pin, 'actual': receipt['hashes_before'].get(name)}
                       for name, pin in PINS.items()}
    receipt['base_pins_reported'] = {name: {'base': pin, 'current': receipt['hashes_before'].get(name)}
                                     for name, pin in BASE_PINS_REPORTED.items()}
    for name, row in receipt['pins'].items():
        if row['expected'] != row['actual']:
            problems.append(f'source pin mismatch: {name}')
    receipt['product_loaded_before_sentinels'] = any(
        n == 'pytest' or n == 'skippercast' or n.startswith('skippercast.') for n in sys.modules)
    if receipt['product_loaded_before_sentinels']:
        problems.append('pytest or skippercast was imported before the offline sentinels')
    receipt['sentinels'] = install_sentinels()
    receipt['sentinel_probe'] = probe_sentinels()
    if any(value != 'refused' for value in receipt['sentinel_probe'].values()):
        problems.append(f'offline sentinel probe did not refuse: {receipt["sentinel_probe"]}')
    receipt['environment'] = isolate_environment(out)
    modules_before = set(sys.modules)
    receipt['dependencies'], missing = resolve_dependencies()
    if missing:
        status = 'INPUT_UNAVAILABLE'
        problems.append(f'required dependencies absent (not installed by this runner): {missing}')
    else:
        import pytest
        if args.suite == 'focused':
            run = run_session(pytest, out, 'focused', targets_for(EXPECTED['focused']))
            runs.append(run)
            problems += clean(run, EXPECTED['focused'])
            if len(run['collected']) < FOCUSED_MINIMUM:
                problems.append(f'focused: collected {len(run["collected"])} < {FOCUSED_MINIMUM} cases')
        elif args.suite == 'contract':
            run = run_session(pytest, out, 'contract',
                              targets_for(EXPECTED['contract']) + [str(REPO / name) for name in COMPAT])
            runs.append(run)
            problems += clean(run, EXPECTED['contract'])
            receipt['compatibility_tests'] = {}
            for name, minimum in COMPAT_MINIMUM.items():
                count = len([n for n in run['collected'] if n.startswith(name + '::')])
                receipt['compatibility_tests'][name] = count
                if count < minimum:
                    problems.append(f'contract: {name} collected {count} < {minimum} original tests')
        else:
            first = run_session(pytest, out, 'negative', targets_for(EXPECTED['negative']))
            runs.append(first)
            problems += clean(first, EXPECTED['negative'])
            more, found, receipt['negative_controls'] = negative_controls(pytest, out)
            runs += more
            problems += found
        module = sys.modules.get(MODULE_NAME)
        receipt['production_module_file'] = getattr(module, '__file__', None)
        if module is None or Path(module.__file__).resolve() != (REPO / MODULE).resolve():
            problems.append('the staged production module was not the one imported')
        paths = sys.modules.get('skippercast.paths')
        receipt['skippercast_repo_root'] = str(paths.repo_root()) if paths else None
        if paths is not None and Path(paths.repo_root()).resolve() != REPO.resolve():
            problems.append('skippercast.paths.repo_root() is not this staged repository')
    files = {name: getattr(module, '__file__', None) for name, module in list(sys.modules.items())}
    receipt['imports_traced'] = {name: files[name] for name in sorted(set(files) - modules_before)}
    outside = sorted(n for n, f in receipt['imports_traced'].items() if not allowed_module_location(f, out))
    forbidden = sorted(n for n in files if n.split('.')[0] in FORBIDDEN_MODULES)
    receipt['imports_outside_allowed_roots'] = outside
    receipt['forbidden_modules_loaded'] = forbidden
    if outside:
        problems.append(f'imports outside the staged repository/interpreter roots: {outside}')
    if forbidden:
        problems.append(f'forbidden network/model/raster modules imported: {forbidden}')
    product = sorted(n for n, f in receipt['imports_traced'].items()
                     if (n == 'skippercast' or n.startswith('skippercast.')) and f is not None
                     and SRC.resolve() not in Path(f).resolve().parents)
    receipt['skippercast_outside_staged_src'] = product
    if product:
        problems.append(f'skippercast modules imported from outside the staged src/: {product}')
    if receipt['dependencies'].get('venv_site'):
        for name, row in receipt['dependencies'].get('modules', {}).items():
            if not str(Path(row['file']).resolve()).startswith(str(VENV_SITE.resolve())):
                problems.append(f'{name} did not resolve from the staged venv')
    ARMED[0] = False
    receipt['sentinel_trips'] = list(TRIPS)
    receipt['inert_process_allowlist'] = []
    if TRIPS:
        problems.append(f'offline sentinel tripped: {[t["event"] for t in TRIPS]}')
    receipt['hashes_after'] = {name: sha256(REPO / name) for name in watched}
    if receipt['hashes_after'] != receipt['hashes_before']:
        problems.append('a submitted or frozen file changed during the run')
        status = None
    receipt['test_counts'] = {r['label']: r['counts'] for r in runs}
    receipt['tests_total'] = sum(len(r['collected']) for r in runs)
    receipt['skipped_total'] = sum(r['counts'].get('skipped', 0) for r in runs)
    if receipt['skipped_total']:
        problems.append(f'unexpected skips: {receipt["skipped_total"]}')
    status = status or ('PASS' if not problems else 'FAIL')
    receipt.update({'runs': runs, 'problems': problems, 'status': status, 'finished_at': now(),
                    'exit': {'PASS': 0, 'FAIL': 1, 'INPUT_UNAVAILABLE': 3}[status]})
    text = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + '\n'
    receipt_path = out / 'receipt.json'
    with open(receipt_path, 'x', encoding='utf-8') as handle:
        handle.write(text)
    for run in runs:
        print(f'{run["label"]}: pytest exit {run["exit"]} {run["counts"]}')
    for problem in problems:
        print(f'problem: {problem}', file=sys.stderr)
    print(f'{args.suite}: {status} REVIEW REQUIRED receipt={receipt_path} sha256={sha256(receipt_path)}')
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
