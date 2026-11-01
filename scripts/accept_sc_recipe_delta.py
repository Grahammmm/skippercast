#!/usr/bin/env python3
"""Acceptance runner for SC-RECIPE-DELTA (two-snapshot coast recipe delta).

Stdlib launcher for the literal tests in tests/unit/test_sc_recipe_delta.py, run
in this process with pytest. It never reimplements a check or makes up a result.

  --suite focused   A1 rows of the new test module
  --suite contract  A2 rows plus the existing producer tests/unit/test_coast_recipe.py
  --suite negative  A3 rows, then the isolated negative control: an in-memory
                    double of recipe_delta._changes suppresses one real changed leaf.
                    The exact A1 regression must fail with its marker, the unchanged
                    control must stay green, and a clean rerun of the same tests must pass.

Order of operations: bytecode writing is turned off first. The import path is set
in code to this staged repository, plus its staged .venv site-packages when that
venv matches this interpreter (.pth files are NOT processed, so no editable install
of a shared checkout is activated). DNS, socket, HTTP, subprocess and process-spawn
sentinels (function doubles and an audit hook) are installed BEFORE pytest or
any project module is imported. pytest's temporary root (--basetemp) goes into the
unique run directory. The project defines no output-path constants or defaults to
redirect: every input and output path is explicit.

Each run writes a NEW directory below --output (it is never reused). The directory
holds receipt.json and the raw stdout/stderr of every pytest session. Exit 0 = PASS,
1 = FAIL, 3 = INPUT_UNAVAILABLE (a required dependency is absent; nothing is
installed). PASS is local scoped evidence: REVIEW REQUIRED, not CI or approval.
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
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
VENV = REPO / '.venv'
VENV_SITE = VENV / 'lib' / f'python{sys.version_info[0]}.{sys.version_info[1]}' / 'site-packages'
TEST_FILE = 'tests/unit/test_sc_recipe_delta.py'
PRODUCER_TEST = 'tests/unit/test_coast_recipe.py'
MODULE = 'scripts/coast_diagnostics/recipe_delta.py'
MODULE_NAME = 'scripts.coast_diagnostics.recipe_delta'
FIXTURE_DIR = 'tests/fixtures/sc_recipe_delta'
OWNED = [MODULE, TEST_FILE, 'scripts/accept_sc_recipe_delta.py', 'docs/engineering/sc_recipe_delta.md']
# Card source pins (Grahammmm/skippercast main 59fca09b2cc7f5c81a4796902504e263d7f06960),
# with the validator refreshed for SC-RECIPE-OFFLINE; snapshot pins are unchanged.
PINS = {
    # pin refreshed for OC-STATE slug admission
    'validate_recipe.py': '50d8f1e36e5edf9974d121d29349bd821c8bf08e2d3eaf20526b2bc7162b736f',
    'schemas/coast-recipe-v1.schema.json': 'a659d136536a553043fac917473428ae0c6e51bdb179cc66bdd295e09ebf1593',
    'regions/morro-bay/coast.json': 'dbe6ffebea0e6d4321c949ae42329db487448a251af695f060c1092366b6bc47',
    # repinned for NB-SC-06 and NB-SC-08: test_coast_recipe.py carries the new morro-bay and cambria region.json pins
    'tests/unit/test_coast_recipe.py': 'ef8da71a02e7f15aba877a104cffdb38c09002049fb112eccecfe0600c38d564',
}
EXPECTED = {
    'focused': [
        'test_a1_identical_snapshots_produce_no_changes',
        'test_a1_status_and_datum_snapshots_produce_exact_pointer_rows',
        'test_a1_reordered_sources_stay_an_ordered_change',
        'test_a1_every_input_hash_is_carried',
        'test_a1_recipe_metadata_mismatch_is_invalid_without_report',
    ],
    'contract': [
        'test_a2_source_pins_match_frozen_base',
        'test_a2_morro_bay_through_existing_validator_with_staged_metadata',
        'test_a2_metadata_only_change_reported_with_identical_recipe',
        'test_a2_cli_from_relocated_repository_copy',
        'test_a2_new_test_module_is_discovered_by_configured_patterns',
        'test_a2_standalone_relocated_tool_writes_no_bytecode',
    ],
    'negative': [
        'test_a3_invalid_inputs_exit_2_without_artifact',
        'test_a3_symlinked_inputs_refused_before_read',
        'test_a3_reads_outside_allowlist_refused',
        'test_a3_output_refusals_preserve_everything',
        'test_a3_size_row_and_output_caps',
        'test_a3_external_schema_references_refused_without_retrieval',
        'test_a3_internal_schema_fragment_reference_still_compares',
        'test_a3_report_write_failures_publish_nothing',
        'test_a3_mutation_suppressing_changed_leaf_is_detected',
        'test_a3_module_imports_are_offline_stdlib_only',
    ],
}
MUTATION_TARGET = '/metadata/catalog~1sources.json/sources/1/review_status'
MUTATION_DETECTOR = 'test_a1_status_and_datum_snapshots_produce_exact_pointer_rows'
MUTATION_CONTROL = 'test_a1_identical_snapshots_produce_no_changes'
REGRESSION_MARKER = 'SC-RECIPE-DELTA-A1-EXACT-ROWS'
FORBIDDEN_MODULES = ('skippercast', 'requests', 'urllib3', 'httpx', 'aiohttp', 'openai',
                     'anthropic', 'ollama', 'boto3', 'botocore', 'moto')
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
    names = list(OWNED) + list(PINS)
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
        loose = git / ref
        if loose.is_file():
            return loose.read_text().strip()
        common = git
        if (git / 'commondir').is_file():
            common = (git / (git / 'commondir').read_text().strip()).resolve()
        loose = common / ref
        if loose.is_file():
            return loose.read_text().strip()
        packed = common / 'packed-refs'
        for line in packed.read_text().splitlines():
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

    for owner, attr in ((socket, 'socket'), (socket, 'create_connection'), (socket, 'getaddrinfo'),
                        (socket, 'gethostbyname'), (socket, 'gethostbyaddr'),
                        (subprocess, 'Popen'), (subprocess, 'run'), (subprocess, 'call'),
                        (subprocess, 'check_call'), (subprocess, 'check_output'),
                        (os, 'system'), (os, 'popen'), (urllib.request, 'urlopen'),
                        (http.client.HTTPConnection, 'connect')):
        setattr(owner, attr, refuse(getattr(owner, '__name__', str(owner)) + '.' + attr))
    sys.addaudithook(audit)
    ARMED[0] = True
    return [event for event in SENTINEL_EVENTS]


def resolve_dependencies():
    """Import path from this staged repository only; never install anything."""
    info = {'repo_on_path': str(REPO), 'venv_site': None, 'pth_files_processed': False}
    if str(REPO) in sys.path:
        sys.path.remove(str(REPO))
    venv_cfg = VENV / 'pyvenv.cfg'
    if VENV_SITE.is_dir() and venv_cfg.is_file():
        version = None
        for line in venv_cfg.read_text().splitlines():
            key, _, value = line.partition('=')
            if key.strip() == 'version':
                version = value.strip()
        current = '.'.join(map(str, sys.version_info[:3]))
        info['venv_version'] = version
        if version == current:
            sys.path.insert(0, str(VENV_SITE))
            info['venv_site'] = str(VENV_SITE)
        else:
            info['venv_refused'] = f'staged venv {version} does not match interpreter {current}'
    sys.path.insert(0, str(REPO))
    found = {}
    missing = []
    for name in ('pytest', 'jsonschema'):
        try:
            module = __import__(name)
        except ImportError as error:
            missing.append(f'{name}: {error}')
            continue
        import importlib.metadata
        found[name] = {'version': importlib.metadata.version(name), 'file': module.__file__}
    info['modules'] = found
    return info, missing


def module_files():
    files = {}
    for name, module in list(sys.modules.items()):
        location = getattr(module, '__file__', None)
        files[name] = location
    return files


def allowed_module_location(location, run_dir=None):
    if location is None:
        return True
    path = Path(location).resolve()
    roots = [REPO.resolve(), Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()]
    if VENV_SITE.is_dir():
        roots.append(VENV_SITE.resolve())
    if run_dir is not None:   # relocated copies the A2 test stages under this run's --basetemp
        roots.append(Path(run_dir).resolve())
    return any(path == root or root in path.parents for root in roots)


def make_collector():
    class Collector:
        def __init__(self):
            self.collected = []
            self.phases = {}
            self.collect_errors = []
            self.longrepr = {}

        def pytest_collection_finish(self, session):
            self.collected = [item.nodeid for item in session.items]

        def pytest_collectreport(self, report):
            if report.failed:
                self.collect_errors.append({'nodeid': report.nodeid, 'longrepr': str(report.longrepr)[-4000:]})

        def pytest_runtest_logreport(self, report):
            outcome = report.outcome
            if hasattr(report, 'wasxfail'):
                outcome = 'xfail'
            self.phases.setdefault(report.nodeid, {})[report.when] = outcome
            if report.failed:
                self.longrepr[report.nodeid] = str(report.longrepr)[-6000:]

        def result(self, nodeid):
            phases = self.phases.get(nodeid, {})
            if any(value == 'failed' for value in phases.values()):
                return 'failed'
            if any(value in ('skipped', 'xfail') for value in phases.values()):
                return 'skipped'
            if phases.get('call') == 'passed' and phases.get('setup') == 'passed' \
                    and phases.get('teardown') == 'passed':
                return 'passed'
            return 'incomplete'

        def summary(self):
            results = {nodeid: self.result(nodeid) for nodeid in self.collected}
            counts = {}
            for value in results.values():
                counts[value] = counts.get(value, 0) + 1
            return results, counts

    return Collector()


def make_mutation(pytest):
    class Mutation:
        """In-memory callable double: suppress one real changed leaf; no child interpreter."""

        def __init__(self):
            self.suppressed = {}

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_call(self, item):
            module = sys.modules[MODULE_NAME]
            original = module._changes
            nodeid = item.nodeid

            def suppressing(before, after):
                rows = original(before, after)
                kept = [row for row in rows if row['pointer'] != MUTATION_TARGET]
                self.suppressed[nodeid] = self.suppressed.get(nodeid, 0) + len(rows) - len(kept)
                return kept

            module._changes = suppressing
            try:
                yield
            finally:
                module._changes = original

    return Mutation()


def function_name(nodeid):
    return nodeid.split('::', 1)[1].split('[', 1)[0] if '::' in nodeid else nodeid


def run_session(pytest, out, label, targets, extra_plugins=()):
    collector = make_collector()
    stdout_file = out / f'{label}.stdout.txt'
    stderr_file = out / f'{label}.stderr.txt'
    argv = ['-p', 'no:cacheprovider', '-v', '--rootdir', str(REPO), '-c', str(REPO / 'pyproject.toml'),
            '--basetemp', str(out / f'pytest-tmp-{label}'), *targets]
    before = set(sys.modules)
    with open(stdout_file, 'w', encoding='utf-8') as so, open(stderr_file, 'w', encoding='utf-8') as se:
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = int(pytest.main(argv, plugins=[collector, *extra_plugins]))
    results, counts = collector.summary()
    imported = sorted(set(sys.modules) - before)
    return {
        'label': label, 'pytest_argv': argv, 'exit': code, 'collected': collector.collected,
        'results': results, 'counts': counts, 'collect_errors': collector.collect_errors,
        'failures': collector.longrepr, 'imported_modules': imported,
        'stdout': stdout_file.name, 'stdout_sha256': sha256(stdout_file),
        'stderr': stderr_file.name, 'stderr_sha256': sha256(stderr_file),
    }


def clean(run, expected_functions, label=None):
    """Problems with a session that must pass completely, with exactly the expected tests."""
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


def discovery_check():
    """Verify the configured pytest discovery patterns select the new module (no CI map exists)."""
    import fnmatch
    import tomllib
    config = tomllib.loads((REPO / 'pyproject.toml').read_text(encoding='utf-8'))['tool']['pytest']['ini_options']
    name = Path(TEST_FILE).name
    detail = {
        'testpaths': config.get('testpaths'), 'python_files': config.get('python_files'),
        'under_testpath': any(TEST_FILE.startswith(p.rstrip('/') + '/') for p in config.get('testpaths', [])),
        'name_matches': any(fnmatch.fnmatch(name, p) for p in config.get('python_files', [])),
        'outside_gis_directory': 'gis' not in Path(TEST_FILE).parts,
        'ci_map_present': (REPO / '.github/scripts/ci.py').exists(),
        'full_discovery': 'operator-run (venv-fullsuite); not run by this runner',
    }
    problems = []
    if not (detail['under_testpath'] and detail['name_matches'] and detail['outside_gis_directory']):
        problems.append('new test module is not selected by configured pytest discovery')
    return detail, problems


def negative_control(pytest, out):
    runs, problems, detail = [], [], {'target_pointer': MUTATION_TARGET}
    mutation = make_mutation(pytest)
    mutated = run_session(pytest, out, 'mutated', targets_for([MUTATION_DETECTOR, MUTATION_CONTROL]),
                          extra_plugins=[mutation])
    runs.append(mutated)
    by_name = {function_name(n): r for n, r in mutated['results'].items()}
    detector_ids = [n for n in mutated['collected'] if function_name(n) == MUTATION_DETECTOR]
    detail['suppressed_rows'] = mutation.suppressed
    detail['mutated_results'] = by_name
    if by_name.get(MUTATION_DETECTOR) != 'failed':
        problems.append(f'mutant: the A1 exact-row regression did not fail ({by_name.get(MUTATION_DETECTOR)})')
    elif not any(REGRESSION_MARKER in mutated['failures'].get(n, '') for n in detector_ids):
        problems.append('mutant: the A1 regression failed for a reason other than its exact-row marker')
    if not any(mutation.suppressed.get(n, 0) >= 1 for n in detector_ids):
        problems.append('mutant: the double suppressed no real changed row (mutation not exercised)')
    if by_name.get(MUTATION_CONTROL) != 'passed':
        problems.append(f'mutant: the unchanged control did not stay green ({by_name.get(MUTATION_CONTROL)})')
    if mutated['collect_errors'] or set(by_name) != {MUTATION_DETECTOR, MUTATION_CONTROL}:
        problems.append(f'mutant: unexpected collection {sorted(by_name)} / {mutated["collect_errors"]}')
    restored = sys.modules[MODULE_NAME]._changes
    detail['restored_function'] = getattr(restored, '__qualname__', repr(restored))
    if detail['restored_function'] != '_changes':
        problems.append('mutant: the in-memory double was not removed after the mutated session')
    clean_run = run_session(pytest, out, 'restored',
                            targets_for(EXPECTED['negative'] + [MUTATION_DETECTOR, MUTATION_CONTROL]))
    runs.append(clean_run)
    problems += clean(clean_run, EXPECTED['negative'] + [MUTATION_DETECTOR, MUTATION_CONTROL])
    return runs, problems, detail


def main(argv):
    parser = argparse.ArgumentParser(description='SC-RECIPE-DELTA acceptance runner')
    parser.add_argument('--suite', required=True, choices=['focused', 'contract', 'negative'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    out = unique_dir(args.output)
    watched = watched_files()
    receipt = {
        'card': 'SC-RECIPE-DELTA', 'suite': args.suite, 'runner': str(Path(__file__).resolve()),
        'argv': list(getattr(sys, 'orig_argv', [sys.executable, *sys.argv])), 'cwd': os.getcwd(),
        'python': sys.executable, 'python_version': sys.version, 'repo': str(REPO), 'output': str(out),
        'started_at': now(), 'git_head': git_head(), 'dont_write_bytecode': sys.dont_write_bytecode,
        'hashes_before': {name: sha256(REPO / name) for name in watched},
        'status_meaning': 'PASS is local scoped evidence; REVIEW REQUIRED, not CI, source qualification or approval',
    }
    problems, runs, status = [], [], None
    receipt['pins'] = {name: {'expected': pin, 'actual': receipt['hashes_before'].get(name)}
                       for name, pin in PINS.items()}
    for name, row in receipt['pins'].items():
        if row['expected'] != row['actual']:
            problems.append(f'source pin mismatch: {name}')
    receipt['sentinels'] = install_sentinels()
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
        elif args.suite == 'contract':
            receipt['discovery'], found = discovery_check()
            problems += found
            run = run_session(pytest, out, 'contract',
                              targets_for(EXPECTED['contract']) + [str(REPO / PRODUCER_TEST)])
            runs.append(run)
            problems += clean(run, EXPECTED['contract'])
            producer = [n for n in run['collected'] if n.startswith(PRODUCER_TEST + '::')]
            receipt['producer_tests'] = len(producer)
            if not producer:
                problems.append('contract: existing producer tests were not collected')
        else:
            first = run_session(pytest, out, 'negative', targets_for(EXPECTED['negative']))
            runs.append(first)
            problems += clean(first, EXPECTED['negative'])
            more, found, receipt['negative_control'] = negative_control(pytest, out)
            runs += more
            problems += found
    files = module_files()
    receipt['imports_traced'] = {name: files[name] for name in sorted(set(files) - modules_before)}
    outside = sorted(n for n, f in receipt['imports_traced'].items() if not allowed_module_location(f, out))
    forbidden = sorted(n for n in files if n.split('.')[0] in FORBIDDEN_MODULES)
    receipt['imports_outside_allowed_roots'] = outside
    receipt['forbidden_modules_loaded'] = forbidden
    if outside:
        problems.append(f'imports outside the staged repository/interpreter roots: {outside}')
    if forbidden:
        problems.append(f'forbidden driver/network/model modules imported: {forbidden}')
    if receipt['dependencies'].get('venv_site'):
        for name, row in receipt['dependencies'].get('modules', {}).items():
            if not str(Path(row['file']).resolve()).startswith(str(VENV_SITE.resolve())):
                problems.append(f'{name} did not resolve from the staged venv')
    ARMED[0] = False
    receipt['sentinel_trips'] = list(TRIPS)
    if TRIPS:
        problems.append(f'offline sentinel tripped: {[t["event"] for t in TRIPS]}')
    receipt['hashes_after'] = {name: sha256(REPO / name) for name in watched}
    if receipt['hashes_after'] != receipt['hashes_before']:
        problems.append('a submitted or frozen file changed during the run')
        status = None
    tests_total = sum(len(r['collected']) for r in runs)
    receipt['test_counts'] = {r['label']: r['counts'] for r in runs}
    receipt['tests_total'] = tests_total
    receipt['skipped_total'] = sum(r['counts'].get('skipped', 0) for r in runs)
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
    print(f'{args.suite}: {status} receipt={receipt_path} sha256={sha256(receipt_path)}')
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
