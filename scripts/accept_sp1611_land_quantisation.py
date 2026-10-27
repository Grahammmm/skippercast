#!/usr/bin/env python3
"""Offline, per-run acceptance launcher for SP1611-LAND-QUANTISATION."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
WRITE_ROOT = REPO.parent
MANIFEST = WRITE_ROOT / 'SOURCE-MANIFEST.json'
TEST_MODULE = 'tests.unit.test_sp1611_land_quantisation'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def run_child(label, argv, cwd, child_dir):
    started = time.monotonic()
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    elapsed = time.monotonic() - started
    stdout = proc.stdout.encode()
    stderr = proc.stderr.encode()
    (child_dir / f'{label}.stdout').write_bytes(stdout)
    (child_dir / f'{label}.stderr').write_bytes(stderr)
    combined = proc.stdout + proc.stderr
    count = re.search(r'Ran (\d+) tests?', combined)
    skips = re.search(r'OK \(skipped=(\d+)\)', combined)
    failures = re.search(r'failures=(\d+)', combined)
    errors = re.search(r'errors=(\d+)', combined)
    return {'label': label, 'argv': argv, 'cwd': str(cwd), 'exit': proc.returncode,
            'runtime_seconds': round(elapsed, 6), 'test_count': int(count.group(1)) if count else None,
            'skip_count': int(skips.group(1)) if skips else 0,
            'failure_count': int(failures.group(1)) if failures else 0,
            'error_count': int(errors.group(1)) if errors else 0,
            'stdout_sha256': sha256(stdout), 'stderr_sha256': sha256(stderr),
            'stdout': proc.stdout, 'stderr': proc.stderr}


def baseline_result(run):
    text = run['stdout'] + run['stderr']
    return (run['exit'] == 1 and 'Ran 2 tests' in text and 'FAILED (failures=1)' in text and
            'test_healthy_control' in text and 'test_healthy_control (tests.unit.test_sp1611_land_quantisation.BaselineTest.test_healthy_control) ... ok' in text and
            'test_primary_regression' in text and "AssertionError: 'available' != 'unavailable'" in text and
            'ModuleNotFoundError' not in text and 'ERROR:' not in text and 'skipped' not in text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=('baseline', 'focused', 'regression', 'repository'), required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    if manifest.get('schema') != 'agentorange.source-manifest/v1' or manifest.get('repo') != str(REPO):
        raise SystemExit('SOURCE-MANIFEST identity/schema mismatch')
    if manifest.get('head') != '8a805820c30895f5f037e26af9079fd3dc015b0f':
        raise SystemExit('SOURCE-MANIFEST pinned base head mismatch')
    identity = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True, text=True, check=False)
    if identity.returncode:
        raise SystemExit('cannot resolve candidate HEAD')
    actual_head = identity.stdout.strip()
    ancestry = subprocess.run(['git', 'merge-base', '--is-ancestor', manifest['head'], actual_head],
                              cwd=REPO, capture_output=True, text=True, check=False)
    if ancestry.returncode:
        raise SystemExit('candidate HEAD is not descended from the staged manifest base')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    child_dir = output / f'{args.suite}-{time.strftime("%Y%m%dT%H%M%S")}-{uuid.uuid4().hex}'
    child_dir.mkdir()
    bootstrap = child_dir / 'bootstrap.py'
    bootstrap.write_text(
        'import sys, unittest\n'
        f'ROOT = {str(REPO)!r}\n'
        'sys.path.insert(0, ROOT)\n'
        'sys.path.insert(0, ROOT + "/src")\n'
        'suite = unittest.defaultTestLoader.loadTestsFromName(sys.argv[1])\n'
        'result = unittest.TextTestRunner(verbosity=2).run(suite)\n'
        'raise SystemExit(0 if result.wasSuccessful() else 1)\n'
    )
    if args.suite in ('baseline', 'focused'):
        target = TEST_MODULE + '.BaselineTest' if args.suite == 'baseline' else TEST_MODULE
        argv = [sys.executable, str(bootstrap), target]
        run = run_child('baseline-pair' if args.suite == 'baseline' else 'focused-a1-a4', argv, REPO, child_dir)
        if args.suite == 'baseline':
            ok = baseline_result(run)
            outcome = 'BASELINE_GAP_REPRODUCED' if ok else 'BASELINE_CONTRACT_FAILED'
        else:
            ok = run['exit'] == 0 and 'Ran 6 tests' in run['stderr'] + run['stdout'] and 'skipped' not in run['stdout'] + run['stderr']
            outcome = 'FOCUSED_A1_A4_PASS' if ok else 'FOCUSED_A1_A4_FAIL'
        records = [run]
    elif args.suite == 'regression':
        argv = [sys.executable, str(bootstrap), 'tests.unit.test_land_water.BuilderTest']
        run = run_child('original-builder-regression', argv, REPO, child_dir)
        ok = run['exit'] == 0 and 'Ran 12 tests' in run['stdout'] + run['stderr'] and 'skipped' not in run['stdout'] + run['stderr']
        outcome = 'REGRESSION_PASS' if ok else 'REGRESSION_FAIL'
        records = [run]
    else:
        runtime = manifest['runtime']['credential_scan_python3']
        argv = [runtime, str(REPO / 'scripts/check_repository.py')]
        run = run_child('repository-check', argv, REPO, child_dir)
        ok = run['exit'] == 0
        outcome = 'REPOSITORY_PASS' if ok else 'REPOSITORY_FAIL'
        records = [run]
    receipt = {'spec_version': 'SP-16-v1', 'suite': args.suite, 'outcome': outcome,
               'repo': str(REPO), 'manifest_base_head': manifest['head'], 'actual_head': actual_head,
               'child_dir': str(child_dir),
               'runs': [{k: v for k, v in r.items() if k not in ('stdout', 'stderr')} for r in records]}
    raw = json.dumps(receipt, sort_keys=True, indent=2).encode() + b'\n'
    (child_dir / 'receipt.json').write_bytes(raw)
    (child_dir / 'receipt.sha256').write_text(sha256(raw) + '  receipt.json\n')
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
