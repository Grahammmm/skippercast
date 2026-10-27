"""Offline, receipt-producing acceptance runner for SP1703-QUALIFIED-COVERAGE (spec SP-17-v1).

    python3 scripts/accept_sp1703_qualified_coverage.py --phase baseline|focused|regression|repository --output DIR

Each phase creates a new unique run directory under DIR (which must sit inside
the write root and outside the repository) and writes receipt.json plus the raw
child stdout/stderr. Every child is one explicit argv list without a shell.
Python tests run through ``unittest.main`` (what ``python3 -m unittest`` runs)
inside a file-based bootstrap child of this same script: it anchors sys.path to
this clone, redirects temporary files into the run directory and installs
network/process/model/write sentinels before any project import.

baseline    The frozen pair on the pinned-base qualified_scope.py. When the
            working copy still holds the base bytes they run in tree; otherwise
            the base Git blob is overlaid as the module for this child only.
            Exits 0 only when the primary regression fails by assertion and the
            healthy control passes, with no error or skip.
focused     The whole new module (frozen pair plus A1-A4): all green, zero skips.
regression  The unchanged tests.integration.test_qualified_scope selector.
repository  The unchanged scripts/check_repository.py under the manifest's
            runtime.credential_scan_python3 interpreter.

A pass is GREEN_SCOPED_REVIEW_REQUIRED: not full-repository CI, publication,
survey, legal or semantic acceptance. No Node source is in scope for this card.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import ast  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[1]
WRITE_ROOT = REPO.parent
MANIFEST = WRITE_ROOT / 'SOURCE-MANIFEST.json'
SPEC = 'SP-17-v1'
CARD = 'SP1703-QUALIFIED-COVERAGE'
PRODUCT = 'src/skippercast/platform/qualified_scope.py'
NEW_TEST = 'tests/unit/test_sp1703_qualified_coverage.py'
FIXTURE_DIR = 'tests/fixtures/sp1703_qualified_coverage'
DOC = 'docs/engineering/sp1703_qualified_coverage.md'
HELPER = 'scripts/accept_sp1703_qualified_coverage.py'
MODULE = 'tests.unit.test_sp1703_qualified_coverage'
PRIMARY = MODULE + '.BaselineTests.test_primary_regression'
CONTROL = MODULE + '.BaselineTests.test_healthy_control'
REGRESSION = 'tests.integration.test_qualified_scope'
FOCUSED = [PRIMARY, CONTROL] + [MODULE + '.' + name for name in (
    'CoverageGateTests.test_a1_all_nodata_claiming_full_coverage_is_rejected_with_intact_integrity',
    'CoverageGateTests.test_a2_largest_raster_rounds_like_the_producer',
    'CoverageGateTests.test_a2_matching_fractions_pass',
    'CoverageGateTests.test_a2_every_target_view_is_bound_independently',
    'CoverageGateTests.test_a2_wrong_nonzero_fraction_fails_even_when_tile_and_index_agree',
    'CoverageGateTests.test_a2_zero_actual_coverage_cannot_claim_positive_coverage',
    'RasterDecodeTests.test_a3_existing_raster_refusals_are_preserved',
    'RasterDecodeTests.test_a3_signed_little_endian_samples_are_decoded',
    'ValidatorPreservationTests.test_a4_held_original_survey_still_blocks_before_coverage',
    'ValidatorPreservationTests.test_a4_native_depth_and_footprint_checks_still_block',
    'ValidatorPreservationTests.test_a4_ready_result_keeps_limited_scope',
    'ValidatorPreservationTests.test_a4_tile_identity_and_artifact_integrity_still_bound')]
# Only these paths may differ from the pinned base (brief: product + new files).
ALLOWED = {PRODUCT, NEW_TEST, DOC, HELPER}
# Unchanged originals every phase depends on. Every other path outside ALLOWED
# (including the research producer and publisher) is covered by the scope check.
ORIGINALS = ['tests/integration/test_qualified_scope.py', 'tests/_support.py', 'tests/__init__.py',
             'tests/unit/__init__.py', 'tests/integration/__init__.py', 'scripts/check_repository.py',
             'src/skippercast/platform/bottom_targets.py', 'src/skippercast/platform/contracts.py']
BLOCKED_EVENTS = {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
                  'socket.bind', 'socket.sendto', 'socket.sendmsg', 'urllib.Request', 'http.client.connect',
                  'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork',
                  'os.forkpty', 'pty.spawn', 'webbrowser.open', 'ftplib.connect', 'smtplib.connect'}
MODEL_IMPORTS = {'openai', 'anthropic', 'ollama', 'litellm', 'google.generativeai'}
WRITE_EVENTS = {'os.mkdir', 'os.symlink', 'os.link', 'os.rename', 'os.remove', 'os.rmdir', 'os.truncate',
                'os.chmod', 'os.chown', 'os.utime', 'shutil.rmtree', 'shutil.copyfile', 'shutil.move'}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- child bootstrap

def child_main(run_dir, overlay, selectors):
    """Runs inside the child process: guards first, then unittest.main."""
    run_dir = Path(run_dir).resolve(strict=True)
    tmp = run_dir / 'tmp'
    violations = []
    tempfile.tempdir = str(tmp)
    for key in ('TMPDIR', 'TMP', 'TEMP'):
        os.environ[key] = str(tmp)
    sys.path[:] = [str(REPO), str(REPO / 'src')] + [p for p in sys.path
                                                    if p not in ('', str(SCRIPT.parent), str(REPO), str(REPO / 'src'))]
    allowed = str(run_dir) + os.sep

    def under_run(path, dir_fd=None):
        if isinstance(path, int):
            return True  # an already-open descriptor
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if not isinstance(path, str):
            return False
        if not os.path.isabs(path) and isinstance(dir_fd, int) and dir_fd >= 0:
            # shutil.rmtree and friends act relative to a directory descriptor.
            path = os.path.join(os.readlink(f'/proc/self/fd/{dir_fd}'), path)
        return (os.path.normpath(os.path.abspath(path)) + os.sep).startswith(allowed)

    def hook(event, args):
        if event in BLOCKED_EVENTS:
            violations.append({'event': event, 'detail': repr(args)[:200]})
            raise RuntimeError('sentinel: blocked ' + event)
        if event == 'import' and args and args[0] in MODEL_IMPORTS:
            violations.append({'event': 'model-import', 'detail': args[0]})
            raise RuntimeError('sentinel: model client import ' + args[0])
        if event == 'open' and len(args) >= 3:
            mode, flags = args[1], args[2]
            writes = (isinstance(flags, int) and flags & WRITE_FLAGS) or (isinstance(mode, str) and set(mode) & set('wax+'))
            if writes and not under_run(args[0]):
                violations.append({'event': 'write-outside-run', 'detail': repr(args[0])[:200]})
                raise RuntimeError('sentinel: write outside run directory')
        if event in WRITE_EVENTS and args:
            dir_fd = args[-1] if len(args) > 1 and isinstance(args[-1], int) else None
            if event == 'os.rename' and len(args) == 4:
                dir_fd = args[2]
            if not under_run(args[0], dir_fd):
                violations.append({'event': event, 'detail': repr(args)[:200]})
                raise RuntimeError('sentinel: filesystem change outside run directory ' + event)

    sys.addaudithook(hook)
    import importlib.util
    import unittest
    if overlay:
        import skippercast.platform  # noqa: F401  (package from this clone; module replaced below)
        name = 'skippercast.platform.qualified_scope'
        spec = importlib.util.spec_from_file_location(name, overlay)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        sys.modules['skippercast.platform'].qualified_scope = module

    successes = []

    class Result(unittest.TextTestResult):
        def addSuccess(self, test):
            super().addSuccess(test)
            successes.append(test.id())

    class Runner(unittest.TextTestRunner):
        resultclass = Result

    program = unittest.main(module=None, argv=['python3 -m unittest', '-v', *selectors],
                            testRunner=Runner(verbosity=2), exit=False)
    result = program.result
    imported = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if name.split('.')[0] in ('skippercast', 'tests', 'research') and path:
            imported[name] = path
            if not (Path(path).resolve().is_relative_to(REPO) or (overlay and Path(path) == Path(overlay))):
                violations.append({'event': 'foreign-checkout-import', 'detail': f'{name}: {path}'})
    record = {'tests_run': result.testsRun, 'successes': successes,
              'failures': [{'id': t.id(), 'traceback': tb} for t, tb in result.failures],
              'errors': [{'id': t.id(), 'traceback': tb} for t, tb in result.errors],
              'skipped': [{'id': t.id(), 'reason': r} for t, r in result.skipped],
              'expected_failures': [t.id() for t, _ in result.expectedFailures],
              'unexpected_successes': [t.id() for t in result.unexpectedSuccesses],
              'qualified_scope_file': getattr(sys.modules.get('skippercast.platform.qualified_scope'), '__file__', None),
              'imported_project_modules': imported, 'sentinel_violations': violations}
    fd = os.open(str(run_dir / 'child-result.json'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w') as handle:
        handle.write(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return 0 if result.wasSuccessful() and not violations else 1


# ---------------------------------------------------------------- parent phases

def run(argv, cwd=REPO, env=None):
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, check=False)
    return result.returncode, result.stdout, result.stderr


def git(*args):
    code, out, err = run(['git', *args])
    if code != 0:
        raise RuntimeError(f'git {args} failed: {err.decode(errors="replace")[:300]}')
    return out


def check_sources(base, receipt):
    """Bind identity and confine every difference from the base to the admitted paths."""
    head = git('rev-parse', 'HEAD').decode().strip()
    git('merge-base', '--is-ancestor', base, head)
    status = git('status', '--porcelain', '--untracked-files=all').decode()
    changed = set(git('diff', '--name-only', base).decode().split())
    untracked = {line[3:] for line in status.splitlines() if line.startswith('?? ')}
    outside = sorted(p for p in changed | untracked
                     if p not in ALLOWED and not p.startswith(FIXTURE_DIR + '/'))
    if outside:
        raise RuntimeError(f'Changes outside the admitted paths: {outside}')
    for name in ORIGINALS:
        if git('show', f'{base}:{name}') != (REPO / name).read_bytes():
            raise RuntimeError(f'Required original file changed: {name}')
    fixtures = sorted((REPO / FIXTURE_DIR).rglob('*'))
    receipt.update(actual_head=head, git_status_porcelain=status, changed_vs_base=sorted(changed),
                   untracked=sorted(untracked),
                   source_hashes={PRODUCT: sha(REPO / PRODUCT),
                                  PRODUCT + '@base': hashlib.sha256(git('show', f'{base}:{PRODUCT}')).hexdigest()},
                   test_fixture_hashes={NEW_TEST: sha(REPO / NEW_TEST),
                                        **{p.relative_to(REPO).as_posix(): sha(p) for p in fixtures if p.is_file()}},
                   helper_sha256=sha(SCRIPT), doc_sha256=sha(REPO / DOC) if (REPO / DOC).is_file() else None,
                   original_hashes={name: sha(REPO / name) for name in ORIGINALS})
    return head


def unittest_child(out, selectors, overlay=None):
    argv = [sys.executable, '-B', str(SCRIPT), '--child', '--run-dir', str(out),
            '--overlay', str(overlay or ''), '--', *selectors]
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'LD_'))}
    env.update(TMPDIR=str(out / 'tmp'), TMP=str(out / 'tmp'), TEMP=str(out / 'tmp'), PYTHONDONTWRITEBYTECODE='1')
    code, stdout, stderr = run(argv, env=env)
    result_path = out / 'child-result.json'
    result = json.loads(result_path.read_text()) if result_path.is_file() else None
    return argv, code, stdout, stderr, result


def expected_regression_ids(base):
    """Test ids of the unchanged regression module, read from its base blob."""
    tree = ast.parse(git('show', f'{base}:tests/integration/test_qualified_scope.py').decode())
    return sorted(f'{REGRESSION}.{cls.name}.{fn.name}' for cls in tree.body if isinstance(cls, ast.ClassDef)
                  for fn in cls.body if isinstance(fn, ast.FunctionDef) and fn.name.startswith('test'))


def frozen_baselines(receipt):
    found = []
    for path in sorted((WRITE_ROOT / 'out').glob('*/baseline-*/receipt.json')):
        old = json.loads(path.read_text())
        if old.get('status') == 'BASELINE_DEFECT_REPRODUCED' and old.get('wrapper_exit') == 0:
            found.append((path, old))
    if not found:
        raise RuntimeError('No honest historical baseline receipt under the write root out/ directory')
    matching = [(p, o) for p, o in found if o['test_fixture_hashes'] == receipt['test_fixture_hashes']]
    if not matching:
        raise RuntimeError('Frozen tests/fixtures differ from every reproduced baseline')
    receipt['historical_baselines'] = [{'path': str(p), 'sha256': sha(p), 'actual_head': o['actual_head'],
                                        'product_mode': o.get('product_mode')} for p, o in matching]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--phase', choices=['baseline', 'focused', 'regression', 'repository'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--run-dir', help=argparse.SUPPRESS)
    parser.add_argument('--overlay', help=argparse.SUPPRESS)
    parser.add_argument('selectors', nargs='*', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return child_main(args.run_dir, args.overlay, args.selectors)
    if not args.phase or not args.output:
        parser.error('--phase and --output are required')
    parent = args.output.resolve()
    if not parent.is_relative_to(WRITE_ROOT) or parent.is_relative_to(REPO):
        parser.error('--output must be inside the write root and outside the repository')
    parent.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix=args.phase + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-',
                                dir=parent))
    (out / 'tmp').mkdir()
    receipt = {'schema': 'sp1703-qualified-coverage-acceptance/v1', 'spec': SPEC, 'card': CARD, 'phase': args.phase,
               'started_at': now(), 'wrapper_argv': [sys.executable, *sys.argv], 'wrapper_cwd': os.getcwd(),
               'wrapper_runtime': {'executable': sys.executable, 'version': sys.version}, 'output': str(out),
               'review_status': 'REVIEW REQUIRED', 'wrapper_exit': 1, 'status': 'FAIL',
               'scope': 'Scoped acceptance only; not full-repository CI, publication, survey, legal or semantic acceptance.'}
    try:
        manifest = json.loads(MANIFEST.read_text())
        if (manifest.get('schema') != 'agentorange.source-manifest/v1' or Path(manifest.get('repo', '')) != REPO
                or Path(manifest.get('write_root', '')) != WRITE_ROOT or manifest.get('card') != CARD):
            raise RuntimeError('SOURCE-MANIFEST.json schema, repo, write root or card identity mismatch')
        base = manifest['head']
        receipt.update(source_manifest_sha256=sha(MANIFEST), staging_base=base)
        check_sources(base, receipt)
        overlay = None
        if args.phase == 'repository':
            interpreter = manifest['runtime']['credential_scan_python3']
            if not Path(interpreter).is_file() or not os.access(interpreter, os.X_OK):
                raise RuntimeError('Manifest credential_scan_python3 unavailable; no substitute interpreter')
            code, version, _ = run([interpreter, '--version'])
            child_argv = [interpreter, 'scripts/check_repository.py']
            receipt['runtime'] = {'interpreter': interpreter, 'resolved': str(Path(interpreter).resolve()),
                                  'version': version.decode().strip()}
            code, stdout, stderr = run(child_argv)
            result = None
        else:
            if args.phase == 'baseline':
                selectors = [PRIMARY, CONTROL]
                if receipt['source_hashes'][PRODUCT] == receipt['source_hashes'][PRODUCT + '@base']:
                    receipt['product_mode'] = 'unchanged-in-tree'
                else:
                    overlay = out / 'base_qualified_scope.py'
                    overlay.write_bytes(git('show', f'{base}:{PRODUCT}'))
                    receipt['product_mode'] = 'base-blob-overlay'
                    receipt['overlay_sha256'] = sha(overlay)
            elif args.phase == 'focused':
                selectors = [MODULE]
                frozen_baselines(receipt)
            else:
                selectors = [REGRESSION]
            receipt['runtime'] = {'interpreter': sys.executable, 'version': sys.version}
            child_argv, code, stdout, stderr, result = unittest_child(out, selectors, overlay)
        receipt['child'] = {'argv': child_argv, 'cwd': str(REPO), 'exit': code}
        for stream, data in (('stdout', stdout), ('stderr', stderr)):
            path = out / ('child.' + stream)
            path.write_bytes(data)
            receipt['child'][stream] = {'path': str(path), 'sha256': sha(path), 'bytes': len(data)}
        if result is not None:
            receipt['child']['result_sha256'] = sha(out / 'child-result.json')
            receipt['child']['qualified_scope_file'] = result['qualified_scope_file']
            receipt['child']['sentinel_violations'] = result['sentinel_violations']
            counts = {'run': result['tests_run'], 'passed': len(result['successes']),
                      'failed': len(result['failures']), 'errors': len(result['errors']),
                      'skipped': len(result['skipped']), 'expected_failures': len(result['expected_failures']),
                      'unexpected_successes': len(result['unexpected_successes'])}
            receipt['counts'] = counts
            receipt['passed_ids'] = sorted(result['successes'])
            receipt['failed_ids'] = sorted(f['id'] for f in result['failures'])
            if result['sentinel_violations']:
                raise RuntimeError('Offline sentinel fired')
            if counts['errors'] or counts['skipped'] or counts['expected_failures'] or counts['unexpected_successes']:
                raise RuntimeError('Unexpected error, skip, expected failure or unexpected success')
            if args.phase == 'baseline':
                primary = result['failures'][0]['traceback'] if result['failures'] else ''
                expected_file = str(overlay) if overlay else str(REPO / PRODUCT)
                if not (code == 1 and counts['run'] == 2 and receipt['failed_ids'] == [PRIMARY]
                        and receipt['passed_ids'] == [CONTROL] and result['qualified_scope_file'] == expected_file
                        and 'AssertionError: ValueError not raised' in primary
                        and 'FAILED (failures=1)' in stderr.decode()):
                    raise RuntimeError('Not the exact declared baseline: primary assertion red plus healthy green')
                receipt['primary_failure_traceback'] = primary
                receipt['status'] = 'BASELINE_DEFECT_REPRODUCED'
            else:
                expected = sorted(FOCUSED) if args.phase == 'focused' else expected_regression_ids(base)
                if not (code == 0 and counts['failed'] == 0 and counts['run'] == len(expected)
                        and receipt['passed_ids'] == expected and result['qualified_scope_file'] == str(REPO / PRODUCT)):
                    raise RuntimeError('Required tests missing, extra or not all green')
                receipt['status'] = 'GREEN_SCOPED_REVIEW_REQUIRED'
        else:
            match = re.fullmatch(r'Checked (\d+) text files: .+ passed\.\n', stdout.decode())
            if code != 0 or stderr or not match:
                raise RuntimeError('Repository scan failed or its completion marker is absent')
            receipt['counts'] = {'passed': 1, 'failed': 0, 'errors': 0, 'skipped': 0,
                                 'text_files_checked': int(match.group(1))}
            receipt['status'] = 'GREEN_SCOPED_REVIEW_REQUIRED'
        receipt['wrapper_exit'] = 0
    except Exception as error:  # Recorded, never converted into a pass.
        receipt['error'] = f'{type(error).__name__}: {error}'
    receipt['finished_at'] = now()
    fd = os.open(str(out / 'receipt.json'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w') as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'phase': args.phase, 'status': receipt['status'], 'wrapper_exit': receipt['wrapper_exit'],
                      'counts': receipt.get('counts'), 'error': receipt.get('error'),
                      'receipt': str(out / 'receipt.json'), 'receipt_sha256': sha(out / 'receipt.json')}))
    return receipt['wrapper_exit']


if __name__ == '__main__':
    raise SystemExit(main())
