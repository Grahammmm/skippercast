#!/usr/bin/env python3
"""Offline acceptance launcher for SP1704-TRIP-RETURN-DISTANCE (spec SP-17-v1).

    python3 scripts/accept_sp1704_trip_return_distance.py --phase baseline|focused|regression|repository --output DIR

Every phase creates a new unique run directory below DIR (which must lie outside
this repository) and writes receipt.json there plus the raw stdout/stderr of
each child command. Children are explicit argv lists run without a shell; their
exit statuses are checked here and decide this launcher's exit (0 PASS, 1 FAIL,
2 refused input, 3 a staged runtime is unavailable; nothing is ever installed).

  baseline    Stages a copy of the product sources, the new test module and its
              fixtures into the run directory, with src/skippercast/fleet/ais/segment.py
              taken from the SOURCE-MANIFEST base commit, and runs the frozen
              selector pair. PASS only when the primary regression FAILs on its
              named assertion and the healthy control passes (child exit 1, no
              errors, no skips): the defect is reproduced, not repaired.
  focused     The whole new module (the frozen pair plus A1-A4) on this checkout:
              every named test must pass, zero skips.
  regression  The unchanged original selector tests.unit.test_fleet_classify on
              this checkout (verified byte-equal to the base commit), zero skips.
  repository  The unchanged scripts/check_repository.py in the repository with the
              SOURCE-MANIFEST runtime.credential_scan_python3 interpreter.

Unit-test children run ``python -m unittest`` (through runpy, inside this file's
--unittest-child mode) under the staged shared .venv interpreter, after this
file has anchored sys.path to the checkout under test, disabled bytecode,
redirected temp files, the repository root and the fleet store into the run
directory, and installed audit-hook sentinels against network, subprocess,
model-client imports and writes outside the run directory. The sentinels are a
tripwire, not a hostile-code sandbox. A pass is REVIEW REQUIRED: scoped local
evidence only, not full-repository CI or semantic acceptance.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
WRITE_ROOT = REPO.parent
CARD, SPEC = 'SP1704-TRIP-RETURN-DISTANCE', 'SP-17-v1'
PRODUCT = 'src/skippercast/fleet/ais/segment.py'
TEST = 'tests/unit/test_sp1704_trip_return_distance.py'
TEST_MODULE = 'tests.unit.test_sp1704_trip_return_distance'
FIXTURE_DIR = 'tests/fixtures/sp1704_trip_return_distance'
LAUNCHER = 'scripts/accept_sp1704_trip_return_distance.py'
DOC = 'docs/engineering/sp1704_trip_return_distance.md'
REGRESSION = ['tests.unit.test_fleet_classify']
REGRESSION_FILES = ['tests/unit/test_fleet_classify.py']
PRIMARY = TEST_MODULE + '.BaselineTests.test_primary_regression'
CONTROL = TEST_MODULE + '.BaselineTests.test_healthy_control'
BASELINE = [PRIMARY, CONTROL]
FOCUSED = [PRIMARY, CONTROL] + [TEST_MODULE + '.' + name for name in (
    'ClosedReturnLegTests.test_a1_harbor_fixes_after_return_not_counted',
    'ClosedReturnLegTests.test_a1_return_into_another_port',
    'ClosedReturnLegTests.test_a1_return_leg_counted_once',
    'OpenAndTruncationTests.test_a2_gap_truncation_unchanged',
    'OpenAndTruncationTests.test_a2_open_age_truncation_unchanged',
    'OpenAndTruncationTests.test_a2_unknown_start_truncation_unchanged',
    'OpenAndTruncationTests.test_a2_zero_length_final_leg_adds_zero',
    'ReturnConfirmationTests.test_a3_in_port_hint_is_not_a_return',
    'ReturnConfirmationTests.test_a3_order_and_replayed_duplicates_do_not_matter',
    'ReturnConfirmationTests.test_a3_short_dip_is_debounced',
    'EquivalenceTests.test_a4_classifier_segmentation_unchanged',
    'EquivalenceTests.test_a4_every_other_trip_field_matches_base',
    'EquivalenceTests.test_a4_no_pre_departure_harbor_travel',
    'EquivalenceTests.test_a4_only_closed_distance_changes',
)]
DEFECT_MARKER = 'SP1704_RETURN_LEG_OMITTED'
# What the baseline stage needs besides the whole src/ tree.
STAGE_FILES = ['tests/__init__.py', 'tests/unit/__init__.py', 'tests/_support.py', TEST, 'regions/CA/fleet.json',
               LAUNCHER]
CHILD_IMPORTS = 'SP1704_CHILD_IMPORTS '
# unittest -v result lines: "name (module.Class.name) ... ok|FAIL|ERROR|skipped '...'|expected failure|..."
RESULT = re.compile(r'^(\w+) \(([\w.]+)\)(?:\n.*)? \.\.\. (ok|FAIL|ERROR|skipped|expected failure|unexpected success)',
                    re.M)
RAN = re.compile(r'^Ran (\d+) tests? in ', re.M)
HEADER = re.compile(r'^(FAIL|ERROR): \w+ \(([\w.]+)\)', re.M)

BLOCKED_EVENTS = {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
                  'socket.bind', 'socket.sendto', 'socket.sendmsg', 'urllib.Request', 'http.client.connect',
                  'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork',
                  'os.forkpty', 'pty.spawn', 'webbrowser.open', 'sqlite3.connect'}
MODEL_IMPORTS = {'openai', 'anthropic', 'ollama', 'google.generativeai', 'litellm'}
WRITE_EVENTS = {'os.mkdir', 'os.symlink', 'os.link', 'os.rename', 'os.remove', 'os.rmdir', 'os.truncate',
                'os.chmod', 'os.chown', 'os.utime', 'shutil.rmtree', 'shutil.copyfile', 'shutil.move'}


# ---------------------------------------------------------------- child mode

def unittest_child(root: Path, run_dir: Path, selectors: list[str]) -> None:
    """Run ``python -m unittest -v <selectors>`` against ``root`` with sentinels; never returns normally."""
    sys.dont_write_bytecode = True
    import runpy
    import tempfile
    tmp = run_dir / 'tmp'
    tempfile.tempdir = str(tmp)
    os.environ.update(TMPDIR=str(tmp), SKIPPERCAST_ROOT=str(root),
                      SKIPPERCAST_FLEET_VAR=str(run_dir / 'fleet-var'))
    os.environ.pop('SKIPPERCAST_NETWORK', None)
    script_dir = str(Path(__file__).resolve().parent)
    sys.path[:] = [str(root / 'src'), str(root)] + [p for p in sys.path if p not in ('', script_dir, str(root),
                                                                                      str(root / 'src'))]
    allowed = str(run_dir) + os.sep
    fired: list[str] = []

    def under_run(path) -> bool:
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if isinstance(path, int):
            return True  # an already-open descriptor
        if not isinstance(path, str) or not os.path.isabs(path):
            path = os.path.abspath(str(path))
        return (os.path.normpath(path) + os.sep).startswith(allowed) or path == os.devnull

    def hook(event, args):
        if event in BLOCKED_EVENTS:
            fired.append(event)
            raise RuntimeError('SP1704 sentinel: blocked ' + event)
        if event == 'import' and args and args[0] in MODEL_IMPORTS:
            fired.append('import ' + args[0])
            raise RuntimeError('SP1704 sentinel: model client import ' + args[0])
        if event == 'open' and len(args) >= 3:
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and bool(set(mode) & set('wax+'))) or \
                      (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND |
                                                           os.O_TRUNC))
            if writing and not under_run(args[0]):
                fired.append('write ' + repr(args[0])[:160])
                raise RuntimeError('SP1704 sentinel: write outside the run directory')
        if event in WRITE_EVENTS and args and not under_run(args[0]):
            fired.append(event + ' ' + repr(args[0])[:160])
            raise RuntimeError('SP1704 sentinel: filesystem change outside the run directory ' + event)

    sys.addaudithook(hook)
    sys.argv = ['python -m unittest', '-v', *selectors]
    code = 1
    try:
        runpy.run_module('unittest', run_name='__main__', alter_sys=True)
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else 1
    finally:
        imported = {name: getattr(module, '__file__', None) for name, module in sorted(sys.modules.items())
                    if name == 'skippercast' or name.startswith('skippercast.') or name == 'tests'
                    or name.startswith('tests.')}
        sys.stdout.write('\n' + CHILD_IMPORTS + json.dumps({'imports': imported, 'sentinels': fired},
                                                           sort_keys=True) + '\n')
        sys.stdout.flush()
    raise SystemExit(code)


# ---------------------------------------------------------------- launcher helpers

class Refused(Exception):
    """Unsafe or unusable input: nothing ran."""


class Unavailable(Exception):
    """A staged runtime this phase needs is missing."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git(*args: str, binary: bool = False):
    proc = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout if binary else proc.stdout.decode().strip()


def load_manifest() -> tuple[dict, str]:
    path = WRITE_ROOT / 'SOURCE-MANIFEST.json'
    if not path.is_file():
        raise Refused(f'missing {path}')
    data = path.read_bytes()
    manifest = json.loads(data)
    if manifest.get('schema') != 'agentorange.source-manifest/v1':
        raise Refused('SOURCE-MANIFEST.json schema is not agentorange.source-manifest/v1')
    if Path(manifest.get('repo', '')).resolve() != REPO:
        raise Refused(f"SOURCE-MANIFEST.json repo {manifest.get('repo')} is not this checkout {REPO}")
    base = manifest.get('head', '')
    if not re.fullmatch(r'[0-9a-f]{40}', base):
        raise Refused('SOURCE-MANIFEST.json head is not a full commit id')
    if subprocess.run(['git', '-C', str(REPO), 'merge-base', '--is-ancestor', base, 'HEAD']).returncode != 0:
        raise Refused('HEAD does not descend from the SOURCE-MANIFEST base')
    return manifest, sha256_bytes(data)


def unique_run_dir(output: Path, phase: str) -> Path:
    parent = Path(os.path.abspath(output))
    if parent == REPO or parent.is_relative_to(REPO):
        raise Refused(f'--output {parent} must lie outside the repository {REPO}')
    for ancestor in [parent, *parent.parents]:
        if ancestor.is_symlink():
            raise Refused(f'--output passes through a symlink at {ancestor}')
    parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run = parent / f'{phase}-{stamp}-{os.getpid()}-{secrets.token_hex(3)}'
    run.mkdir(exist_ok=False)
    (run / 'tmp').mkdir()
    (run / 'fleet-var').mkdir()
    return run


def venv_python() -> Path:
    path = REPO / '.venv' / 'bin' / 'python3'
    if not path.exists() or not os.access(path, os.X_OK):
        raise Unavailable(f'staged shared interpreter {path} is unavailable')
    return path


def run_child(label: str, argv: list[str], cwd: Path, run: Path, env: dict | None = None) -> dict:
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=1800, env=env)
    out, err = run / f'{label}.stdout.txt', run / f'{label}.stderr.txt'
    out.write_bytes(proc.stdout)
    err.write_bytes(proc.stderr)
    return {'label': label, 'argv': argv, 'cwd': str(cwd), 'exit': proc.returncode,
            'stdout': out.name, 'stdout_sha256': sha256_bytes(proc.stdout), 'stdout_bytes': len(proc.stdout),
            'stderr': err.name, 'stderr_sha256': sha256_bytes(proc.stderr), 'stderr_bytes': len(proc.stderr),
            '_stdout': proc.stdout.decode(errors='replace'), '_stderr': proc.stderr.decode(errors='replace')}


def unittest_run(label: str, root: Path, run: Path, selectors: list[str]) -> dict:
    python = venv_python()
    argv = [str(python), str(root / LAUNCHER), '--unittest-child', '--root', str(root), '--run-dir', str(run),
            '--', *selectors]
    env = {k: v for k, v in os.environ.items() if not k.startswith('SKIPPERCAST_')}
    child = run_child(label, argv, root, run, env)
    results = {name_id: status for _, name_id, status in RESULT.findall(child['_stderr'])}
    # A test whose subtests failed has no status on its own line; its FAIL/ERROR header decides it.
    for status, name_id in HEADER.findall(child['_stderr']):
        results[name_id] = status
    ran = RAN.findall(child['_stderr'])
    report = None
    for line in child['_stdout'].splitlines():
        if line.startswith(CHILD_IMPORTS):
            report = json.loads(line[len(CHILD_IMPORTS):])
    statuses = list(results.values())
    child.update(results=results, counts={
        'ran': int(ran[-1]) if ran else None, 'parsed': len(results),
        'passed': statuses.count('ok'), 'failed': statuses.count('FAIL'), 'errors': statuses.count('ERROR'),
        'skipped': statuses.count('skipped'),
        'other': len(statuses) - sum(statuses.count(s) for s in ('ok', 'FAIL', 'ERROR', 'skipped'))},
        child_report=report)
    return child


def common_problems(child: dict, root: Path) -> list[str]:
    problems = []
    report = child['child_report']
    if report is None:
        return [f"{child['label']}: child import/sentinel report missing (setup failure?)"]
    if report['sentinels']:
        problems.append(f"{child['label']}: sentinels fired {report['sentinels']}")
    for name, path in report['imports'].items():
        if path and not Path(path).resolve().is_relative_to(root):
            problems.append(f"{child['label']}: {name} imported from outside {root}: {path}")
    if not any(name.startswith('skippercast.fleet.ais.segment') for name in report['imports']):
        problems.append(f"{child['label']}: skippercast.fleet.ais.segment was never imported")
    counts = child['counts']
    if counts['ran'] is None or counts['ran'] != counts['parsed']:
        problems.append(f"{child['label']}: unittest ran {counts['ran']} but {counts['parsed']} results parsed")
    if counts['skipped'] or counts['other']:
        problems.append(f"{child['label']}: skipped={counts['skipped']} other={counts['other']}")
    return problems


def stage_baseline(run: Path, base: str) -> tuple[Path, dict]:
    """A copy of the inputs the frozen pair reads, with the product file restored to the base blob."""
    stage = run / 'stage'
    shutil.copytree(REPO / 'src', stage / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in STAGE_FILES:
        (stage / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, stage / name)
    shutil.copytree(REPO / FIXTURE_DIR, stage / FIXTURE_DIR)
    blob = git('show', f'{base}:{PRODUCT}', binary=True)
    (stage / PRODUCT).write_bytes(blob)
    detail = {'stage': str(stage), 'base_product_sha256': sha256_bytes(blob),
              'checkout_product_sha256': sha256_file(REPO / PRODUCT),
              'checkout_product_is_base': sha256_file(REPO / PRODUCT) == sha256_bytes(blob),
              'staged_test_sha256': sha256_file(stage / TEST),
              'staged_fixture_sha256': {p.name: sha256_file(p) for p in sorted((stage / FIXTURE_DIR).iterdir())}}
    if sha256_file(stage / PRODUCT) != detail['base_product_sha256']:
        raise Refused('staged product does not match the base blob')
    return stage, detail


def historical_baselines(fingerprint: dict) -> list[str]:
    found = []
    out_root = WRITE_ROOT / 'out'
    if out_root.is_dir():
        for path in sorted(out_root.rglob('receipt.json')):
            try:
                saved = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if saved.get('phase') == 'baseline' and saved.get('status') == 'PASS' and \
                    saved.get('test_fixture_sha256') == fingerprint:
                found.append(str(path))
    return found


# ---------------------------------------------------------------- phases

def phase_unittest(phase: str, run: Path, base: str, receipt: dict) -> list[str]:
    if phase == 'baseline':
        root, receipt['baseline_stage'] = stage_baseline(run, base)
        selectors = BASELINE
    elif phase == 'focused':
        root, selectors = REPO, FOCUSED
    else:
        root, selectors = REPO, REGRESSION
        for name in REGRESSION_FILES:
            if git('show', f'{base}:{name}', binary=True) != (REPO / name).read_bytes():
                raise Refused(f'original selector file changed from the base: {name}')
    child = unittest_run(phase, root, run, selectors)
    receipt['children'].append(child)
    problems = common_problems(child, root)
    results, counts = child['results'], child['counts']
    if phase == 'baseline':
        primary = results.get(PRIMARY)
        control = results.get(CONTROL)
        if child['exit'] != 1:
            problems.append(f"baseline: child exit {child['exit']}, expected 1 (the regression's assertion)")
        if counts['ran'] != 2 or primary != 'FAIL' or control != 'ok' or counts['errors']:
            problems.append(f'baseline: wanted primary FAIL + control ok, got {results} {counts}')
        stderr = child['_stderr']
        if 'AssertionError' not in stderr or DEFECT_MARKER not in stderr:
            problems.append('baseline: the failure is not the named SP1704_RETURN_LEG_OMITTED assertion')
        observation = re.search(r'^SP1704_OBSERVATION (\{.*\})$', child['_stdout'], re.M)
        receipt['baseline_observation'] = json.loads(observation.group(1)) if observation else None
        if not observation:
            problems.append('baseline: positive SP1704_OBSERVATION output missing')
    else:
        if child['exit'] != 0:
            problems.append(f"{phase}: child exit {child['exit']}")
        if counts['failed'] or counts['errors'] or not counts['ran'] or counts['passed'] != counts['ran']:
            problems.append(f'{phase}: not every test passed {counts}')
        if phase == 'focused':
            missing = sorted(set(FOCUSED) - {k for k, v in results.items() if v == 'ok'})
            extra = sorted(set(results) - set(FOCUSED))
            if missing or extra:
                problems.append(f'focused: missing {missing} unexpected {extra}')
            receipt['historical_baseline_receipts'] = historical_baselines(receipt['test_fixture_sha256'])
    return problems


def phase_repository(run: Path, manifest: dict, receipt: dict) -> list[str]:
    python = Path(manifest.get('runtime', {}).get('credential_scan_python3', ''))
    if not python.is_file() or not os.access(python, os.X_OK):
        raise Unavailable(f'SOURCE-MANIFEST runtime.credential_scan_python3 unavailable: {python}')
    version = run_child('repository-python-version', [str(python), '--version'], REPO, run)
    child = run_child('repository', [str(python), str(REPO / 'scripts' / 'check_repository.py')], REPO, run)
    receipt['children'] += [version, child]
    problems = []
    if version['exit'] != 0:
        problems.append('repository: interpreter version check failed')
    if child['exit'] != 0:
        problems.append(f"repository: check_repository.py exit {child['exit']}")
    checked = re.search(r'Checked (\d+) text files', child['_stdout'] + child['_stderr'])
    child['files_checked'] = int(checked.group(1)) if checked else None
    if checked is None:
        problems.append('repository: scanner summary line missing; it may not have run')
    return problems


def main(argv: list[str]) -> int:
    if argv and argv[0] == '--unittest-child':
        child = argparse.ArgumentParser()
        child.add_argument('--unittest-child', action='store_true')
        child.add_argument('--root', required=True, type=Path)
        child.add_argument('--run-dir', required=True, type=Path)
        child.add_argument('selectors', nargs='+')
        args = child.parse_args(argv)
        unittest_child(args.root.resolve(), args.run_dir.resolve(), args.selectors)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--phase', required=True, choices=['baseline', 'focused', 'regression', 'repository'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        run = unique_run_dir(args.output, args.phase)
    except (Refused, OSError) as error:
        print(f'REFUSED: {error}', file=sys.stderr)
        return 2
    watched = [PRODUCT, TEST, LAUNCHER, DOC, *REGRESSION_FILES, 'tests/_support.py']
    receipt: dict = {
        'schema': 'sp1704-trip-return-distance-acceptance/v1', 'card': CARD, 'spec': SPEC, 'phase': args.phase,
        'launcher_argv': [sys.executable, *sys.argv], 'launcher_cwd': os.getcwd(), 'launcher_python': sys.version,
        'repo': str(REPO), 'run_dir': str(run), 'started_at': utc(), 'children': [], 'problems': [],
        'review_status': 'REVIEW REQUIRED',
        'scope': 'scoped local acceptance only; not full-repository CI, exact-head CI or semantic acceptance'}
    status = 'FAIL'
    try:
        manifest, receipt['source_manifest_sha256'] = load_manifest()
        base = manifest['head']
        receipt.update(base=base, head=git('rev-parse', 'HEAD'),
                       git_status=git('status', '--porcelain', '--untracked-files=all'),
                       source_sha256={name: sha256_file(REPO / name) for name in watched},
                       base_product_sha256=sha256_bytes(git('show', f'{base}:{PRODUCT}', binary=True)),
                       test_fixture_sha256={name: sha256_file(REPO / name) for name in
                                            [TEST, *(f'{FIXTURE_DIR}/{p.name}' for p in
                                                     sorted((REPO / FIXTURE_DIR).iterdir()))]})
        if args.phase == 'repository':
            problems = phase_repository(run, manifest, receipt)
        else:
            problems = phase_unittest(args.phase, run, base, receipt)
        after = {name: sha256_file(REPO / name) for name in watched}
        if after != receipt['source_sha256']:
            problems.append('a watched source file changed during the run')
        receipt['problems'] = problems
        status = 'PASS' if not problems else 'FAIL'
    except Refused as error:
        receipt['problems'].append('refused: ' + str(error))
        status = 'REFUSED'
    except Unavailable as error:
        receipt['problems'].append('unavailable: ' + str(error))
        status = 'INPUT_UNAVAILABLE'
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        receipt['problems'].append(f'error: {type(error).__name__}: {error}')
        status = 'FAIL'
    for child in receipt['children']:
        child.pop('_stdout', None)
        child.pop('_stderr', None)
    exit_code = {'PASS': 0, 'FAIL': 1, 'REFUSED': 2, 'INPUT_UNAVAILABLE': 3}[status]
    receipt.update(status=status, exit=exit_code, finished_at=utc())
    if args.phase == 'baseline' and status == 'PASS':
        receipt['meaning'] = 'BASELINE_DEFECT_REPRODUCED: the frozen primary regression is red on the base product'
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    for child in receipt['children']:
        print(f"{child['label']}: exit {child['exit']} counts={child.get('counts')} "
              f"stdout_sha256={child['stdout_sha256']} stderr_sha256={child['stderr_sha256']}")
    for problem in receipt['problems']:
        print('problem: ' + problem, file=sys.stderr)
    print(f"{args.phase}: {status} exit={exit_code} receipt={run / 'receipt.json'} "
          f"sha256={sha256_file(run / 'receipt.json')} (REVIEW REQUIRED)")
    return exit_code


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main(sys.argv[1:]))
