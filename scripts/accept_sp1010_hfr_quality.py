#!/usr/bin/env python3
"""Portable, offline SP-10-v1 evidence runner. A scoped pass requires review."""
import argparse
import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
from typing import cast
import unittest

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
BASE = '2979d59bfbb7d724eb83b34a48102b914ee8eaa3'
SOURCE = 'src/skippercast/pipeline/ocean.py'
SOURCE_HASH = '1315e6eceb51bb135afe43d1df11c8e43afd459de9e49ba7472ece22030c1b43'
TEST = 'tests/unit/test_sp1010_hfr_quality.py'
FIXTURES = 'tests/fixtures/sp1010_hfr_quality'
MODULE = 'tests.unit.test_sp1010_hfr_quality'
PAIR = [MODULE + '.RegressionTests.test_primary_regression', MODULE + '.RegressionTests.test_healthy_control']
FOCUSED = [MODULE + '.RegressionTests.' + name for name in (
    'test_all_empty_frames_retain_latest_grid',
    'test_each_invalid_hdop_isolated',
    'test_existing_radar_count_gates',
    'test_existing_sentinel_and_vector_validation',
    'test_finite_endpoints_and_nearby_values_keep_scale',
    'test_grid_stride_and_regional_selection_unchanged',
    'test_healthy_control',
    'test_latest_empty_frame_does_not_replace_last_observation',
    'test_mixed_cells_keep_exact_identities_and_counts',
    'test_primary_regression',
    'test_real_dap_arrays_and_dap_preserve_quality_tokens',
    'test_time_selection_keeps_six_frames_and_gaps')]
REGRESSION = ['tests.unit.test_pipeline_intelligence.IntelligenceTests.test_dap_parser_keeps_fill_and_zeros_and_current_direction_is_toward']
REGRESSION_HASH = 'c73eec393c941e30e64ad028a1651a3147a8f83c84304c1863594b398f15e176'
AUTHOR = {'model': 'gpt-6.1-sol', 'provider': 'openai-codex', 'profile': 'sol-reviewer',
          'task': 't_2f8b7877', 'run': 1705, 'basis': 'actual author runtime disclosed by builder'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def no_links(path):
    """Check lexical ancestry before resolving/creating synthetic resources."""
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        require(not part.is_symlink(), 'Symlink refused: ' + str(part))
    return path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with no_links(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def hashes():
    paths = [SOURCE, TEST, 'scripts/accept_sp1010_hfr_quality.py',
             'tests/unit/test_pipeline_intelligence.py', 'scripts/check_repository.py']
    root = no_links(REPO / FIXTURES)
    require(root.is_dir(), 'Missing synthetic fixture directory')
    for p in sorted(root.rglob('*')):
        no_links(p)
        if p.is_file():
            paths.append(p.relative_to(REPO).as_posix())
    return {p: sha(no_links(REPO / p)) for p in paths}


def git(*arguments):
    executable = shutil.which('git')
    if executable is None:
        raise RuntimeError('git unavailable')
    result = subprocess.run([executable, '-C', str(REPO), *arguments],
                            capture_output=True, text=True, check=False)
    require(result.returncode == 0, 'git failed: ' + result.stderr)
    return result.stdout.strip()


def manifest():
    path = no_links(CANDIDATE / 'SOURCE-MANIFEST.json')
    data = json.loads(path.read_text())
    require(data.get('schema') == 'agentorange.source-manifest/v1', 'Invalid manifest schema')
    require(data.get('head') == BASE, 'Wrong staged base')
    require(data.get('write_root') == str(CANDIDATE) and data.get('repo') == str(REPO), 'Manifest path mismatch')
    require(data.get('clean') is True, 'Staging was not admitted clean')
    require(git('merge-base', '--is-ancestor', BASE, 'HEAD') == '', 'HEAD not descended from base')
    runtime = data['runtime']
    for key in ('system_python3', 'credential_scan_python3', 'repo_venv'):
        require(Path(runtime[key]).is_absolute() and Path(runtime[key]).exists(), 'Missing manifest runtime: ' + key)
    require((REPO / '.venv').resolve() == Path(runtime['repo_venv']).resolve(), 'Wrong admitted shared venv')
    require((REPO / '.venv/bin/python3').is_file(), 'Staged Python missing')
    return data, sha(path)


def fixture_hashes(values):
    return {p: digest for p, digest in values.items() if p == TEST or p.startswith(FIXTURES + '/')}


def baseline_reference(current):
    for path in sorted((CANDIDATE / 'out').rglob('receipt.json')):
        no_links(path)
        record = json.loads(path.read_text())
        if (record.get('suite') == 'baseline' and record.get('status') == 'BASELINE_DEFECT_REPRODUCED'
                and record.get('head') == BASE and record.get('hashes', {}).get(SOURCE) == SOURCE_HASH
                and fixture_hashes(record['hashes']) == fixture_hashes(current)):
            return {'path': str(path), 'sha256': sha(path)}
    raise RuntimeError('No honest pre-edit baseline with the same test and fixture bytes')


def install_guards(run_root):
    """Child only: irreversible hook never leaks into ordinary test discovery."""
    violations = []
    blocked_imports = {'openai', 'anthropic', 'ollama', 'litellm'}

    def audit(event, args):
        denied = (event.startswith('socket.') or event in
                  {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'pty.spawn'})
        if event == 'import' and args and str(args[0]).split('.')[0] in blocked_imports:
            denied = True
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing:
                target = no_links(Path(os.fsdecode(args[0])))
                denied = not target.is_relative_to(run_root)
        if denied:
            violations.append(event)
            raise RuntimeError('SP1010 offline/filesystem tripwire: ' + event)

    sys.addaudithook(audit)
    return violations


class NamedResults(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started = []
        self.passed = []
        self.failure_types = []
        self.failure_messages = []

    def startTest(self, test):
        self.started.append(test.id())
        super().startTest(test)

    def addSuccess(self, test):
        self.passed.append(test.id())
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.failure_types.append({'test': test.id(), 'assertion': err[0] is not None and issubclass(err[0], AssertionError)})
        self.failure_messages.append(str(err[1]))
        super().addFailure(test, err)


def test_ids(tests):
    if isinstance(tests, unittest.TestSuite):
        return [name for group in tests for name in test_ids(group)]
    return [tests.id()]


def child(suite, run_root):
    run_root = no_links(run_root)
    require(run_root.is_relative_to(CANDIDATE / 'out') and run_root.is_dir(), 'Invalid child root')
    sys.dont_write_bytecode = True
    # All settings and tempfile routing precede target or test imports.
    os.environ['SKIPPERCAST_ROOT'] = str(REPO)
    for name, leaf in [('SKIPPERCAST_HTTP_CACHE', 'cache'), ('SKIPPERCAST_FORECAST_ROOT', 'forecast'),
                       ('TMPDIR', 'tmp')]:
        directory = no_links(run_root / leaf)
        directory.mkdir()
        os.environ[name] = str(directory)
    tempfile.tempdir = str(run_root / 'tmp')
    sys.path[:0] = [str(REPO), str(REPO / 'src')]
    violations = install_guards(run_root)
    result = {'suite': suite, 'argv': list(sys.orig_argv), 'cwd': str(Path.cwd()),
              'runtime': {'executable': sys.executable, 'version': sys.version, 'prefix': sys.prefix},
              'tripwire_violations': violations}
    exit_code = 2
    try:
        if suite == 'repository':
            # The parent selects ONLY manifest.runtime.credential_scan_python3.
            module = runpy.run_path(str(REPO / 'scripts/check_repository.py'))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exit_code = module['main']()
            output = buffer.getvalue()
            print(output, end='')
            count = re.search(r'^Checked (\d+) text files:', output, re.M)
            result.update(check_count=int(count[1]) if count else 0, tests_run=0,
                          checker=str(REPO / 'scripts/check_repository.py'))
            require(exit_code == 0 and count is not None, 'Repository scanner failed')
        else:
            ocean = importlib.import_module('skippercast.pipeline.ocean')
            contracts = importlib.import_module('skippercast.platform.contracts')
            settings = importlib.import_module('skippercast.pipeline.settings')
            local = importlib.import_module('skippercast.forecast.local')
            regulations = importlib.import_module('skippercast.pipeline.regulations')
            origins = {name: str(Path(str(mod.__file__)).resolve()) for name, mod in list(sys.modules.items())
                       if name == 'skippercast' or name.startswith('skippercast.')}
            require(all(Path(p).is_relative_to(REPO / 'src') for p in origins.values()), 'Shared editable import detected')
            require(contracts.REPO == REPO and local.REPO == REPO, 'Package root was not redirected')
            require(settings.settings.__defaults__ == ('morro-bay', REPO), 'Unexpected settings bound defaults')
            require(regulations.REGISTRY == REPO / 'dist/data/regulations.json', 'Unexpected registry root')
            require(ocean.hfr.__defaults__ == (6,), 'Unexpected HFR defaults')
            result.update(import_origins=origins, bound_defaults={'hfr_resolution': 6, 'settings_root': str(REPO)},
                          filesystem_calls='None in selected hfr/dap/vector functions or original compatibility selector')
            if suite == 'baseline':
                selectors = PAIR
                tests = unittest.defaultTestLoader.loadTestsFromNames(selectors)
            elif suite == 'focused':
                tests = unittest.defaultTestLoader.loadTestsFromName(MODULE)
                selectors = FOCUSED
                require(test_ids(tests) == FOCUSED, 'Frozen focused test inventory mismatch')
            else:
                selectors = REGRESSION
                tests = unittest.defaultTestLoader.loadTestsFromNames(selectors)
            report = cast(NamedResults, unittest.TextTestRunner(verbosity=2, resultclass=NamedResults).run(tests))
            result.update(selectors=selectors, named_tests=report.started, passed=report.passed,
                          tests_run=report.testsRun, failures=[t.id() for t, _ in report.failures],
                          errors=[t.id() for t, _ in report.errors], skipped=[str(t) for t, _ in report.skipped],
                          expected_failures=[str(t) for t, _ in report.expectedFailures],
                          unexpected_successes=[str(t) for t in report.unexpectedSuccesses],
                          failure_types=report.failure_types, failure_messages=report.failure_messages)
            exit_code = 0 if report.wasSuccessful() else 1
    except Exception as error:
        import traceback
        traceback.print_exc()
        result['harness_error'] = type(error).__name__ + ': ' + str(error)
        exit_code = 2
    result['exit_code'] = exit_code
    save(run_root / 'child-result.json', result)
    return exit_code


def accepted(suite, exit_code, result):
    if result.get('harness_error') or result.get('tripwire_violations') or result.get('exit_code') != exit_code:
        return False
    if suite == 'repository':
        return exit_code == 0 and result.get('check_count', 0) > 0
    if any(result.get(k) for k in ('errors', 'skipped', 'expected_failures', 'unexpected_successes')):
        return False
    if suite == 'baseline':
        return (exit_code == 1 and result['tests_run'] == 2 and result['named_tests'] == PAIR
                and result['passed'] == [PAIR[1]] and result['failures'] == [PAIR[0]]
                and result['failure_types'] == [{'test': PAIR[0], 'assertion': True}]
                and len(result.get('failure_messages', [])) == 1
                and 'A1 NaN must be excluded:' in result['failure_messages'][0])
    expected = result['selectors']
    return (exit_code == 0 and not result['failures'] and result['tests_run'] == len(expected)
            and len(expected) > 0 and result['named_tests'] == expected and result['passed'] == expected)


def parent(args):
    data, manifest_hash = manifest()
    current = hashes()
    require(current['tests/unit/test_pipeline_intelligence.py'] == REGRESSION_HASH, 'Original selector file changed')
    require(git('diff', BASE, '--', 'scripts/check_repository.py') == '', 'Repository checker changed')
    head = git('rev-parse', 'HEAD')
    baseline = None
    if args.suite == 'baseline':
        require(head == BASE and current[SOURCE] == SOURCE_HASH, 'Baseline must precede product edits at pinned base')
    else:
        baseline = baseline_reference(current)
    output = no_links(args.output)
    require(output.is_relative_to(CANDIDATE / 'out'), 'Evidence output must stay under candidate/out')
    output.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix=args.suite + '-', dir=output))
    python = (data['runtime']['credential_scan_python3'] if args.suite == 'repository'
              else str(REPO / '.venv/bin/python3'))
    argv = [python, '-B', str(Path(__file__).resolve()), '--child-suite', args.suite, '--run-root', str(run_root)]
    started = time.time()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(run_root))
    timed_out = False
    with (run_root / 'stdout.txt').open('x') as stdout, (run_root / 'stderr.txt').open('x') as stderr:
        try:
            process = subprocess.run(argv, cwd=REPO, env=env, stdout=stdout, stderr=stderr, timeout=180, check=False)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
    child_path = run_root / 'child-result.json'
    result = json.loads(child_path.read_text()) if child_path.is_file() else {'harness_error': 'Missing child result'}
    good = not timed_out and accepted(args.suite, exit_code, result)
    after = hashes()
    if current != after or head != git('rev-parse', 'HEAD') or sha(CANDIDATE / 'SOURCE-MANIFEST.json') != manifest_hash:
        good = False
    receipt = {'specification': 'SP-10-v1', 'item': 'SP1010-HFR-QUALITY', 'suite': args.suite,
               'phase': 'historical-before-edit' if args.suite == 'baseline' else 'scoped-acceptance',
               'status': ('BASELINE_DEFECT_REPRODUCED' if args.suite == 'baseline' else 'REVIEW_REQUIRED') if good else 'FAILED',
               'staged_base': BASE, 'head': head, 'hashes': current, 'hashes_after': after,
               'source_manifest_sha256': manifest_hash, 'baseline_reference': baseline,
               'material_author': AUTHOR, 'execution_actor': args.actor,
               'parent_argv': list(sys.orig_argv), 'parent_cwd': str(Path.cwd()),
               'parent_runtime': {'executable': sys.executable, 'version': sys.version},
               'child_argv': argv, 'child_cwd': str(REPO), 'child_exit': exit_code,
               'started_epoch': started, 'duration_seconds': time.time() - started, 'timeout': timed_out,
               'child_result': result, 'wrapper_exit': 0 if good else 1,
               'logs': {name: {'path': str(run_root / name), 'sha256': sha(run_root / name)}
                        for name in ('stdout.txt', 'stderr.txt')}}
    if child_path.is_file():
        receipt['child_result_sha256'] = sha(child_path)
    save(run_root / 'receipt.json', receipt)
    print(json.dumps({'status': receipt['status'], 'child_exit': exit_code, 'receipt': str(run_root / 'receipt.json'),
                      'receipt_sha256': sha(run_root / 'receipt.json'), 'tests_run': result.get('tests_run'),
                      'check_count': result.get('check_count')}, sort_keys=True))
    return receipt['wrapper_exit']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=['baseline', 'focused', 'regression', 'repository'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--actor', default='author:gpt-6.1-sol/openai-codex;run=1705')
    parser.add_argument('--child-suite', choices=['baseline', 'focused', 'regression', 'repository'], help=argparse.SUPPRESS)
    parser.add_argument('--run-root', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child_suite:
        require(args.run_root is not None and args.suite is None, 'Invalid child arguments')
        return child(args.child_suite, args.run_root)
    require(args.suite is not None and args.output is not None, '--suite and --output required')
    return parent(args)


if __name__ == '__main__':
    raise SystemExit(main())
