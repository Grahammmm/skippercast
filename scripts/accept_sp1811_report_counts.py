#!/usr/bin/env python3
"""Offline acceptance recorder for SP1811-REPORT-COUNTS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO.parent / 'SOURCE-MANIFEST.json'
BASELINE = '67ff9bcf34257698a41585bc2ad163171dc68259'
TEST = 'tests/test_sp1811_report_counts.mjs'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(argv, cwd, out, name, expected=None):
    started = time.time()
    proc = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    elapsed = time.time() - started
    (out / f'{name}.stdout').write_bytes(proc.stdout)
    (out / f'{name}.stderr').write_bytes(proc.stderr)
    stdout = proc.stdout.decode('utf-8', 'replace')
    stderr = proc.stderr.decode('utf-8', 'replace')
    counts = {}
    for line in stdout.splitlines():
        if line.startswith('# tests '): counts['tests'] = int(line.rsplit(' ', 1)[1])
        elif line.startswith('# pass '): counts['pass'] = int(line.rsplit(' ', 1)[1])
        elif line.startswith('# fail '): counts['fail'] = int(line.rsplit(' ', 1)[1])
        elif line.startswith('# skipped '): counts['skipped'] = int(line.rsplit(' ', 1)[1])
    record = {'name': name, 'argv': argv, 'cwd': str(cwd),
              'exit': proc.returncode, 'elapsed_seconds': round(elapsed, 6), 'counts': counts,
              'runtime': argv[0], 'launcher_runtime': sys.executable,
              'stdout_sha256': digest(proc.stdout), 'stderr_sha256': digest(proc.stderr),
              'expected_exit': expected}
    records.append(record)
    if expected is not None and proc.returncode != expected:
        raise RuntimeError(f'{name}: expected exit {expected}, got {proc.returncode}; {stderr[-1000:]}')
    return proc.returncode, stdout, stderr, counts


def node_test(out, name, selector=None):
    argv = ['node', '--test']
    if selector:
        argv.extend(['--test-name-pattern', selector])
    argv.append(TEST)
    return run(argv, REPO, out, name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    out = root / f'{args.phase}-{time.strftime("%Y%m%dT%H%M%S")}-{uuid.uuid4().hex[:8]}'
    out.mkdir()
    identity = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True, capture_output=True, check=True).stdout.strip()
    manifest = json.loads(MANIFEST.read_text())
    source = REPO / 'server/advisor/tools/get_port_report.ts'
    meta = {'phase': args.phase, 'identity': identity, 'manifest_schema': manifest.get('schema'),
            'manifest_head': manifest.get('head'), 'source_sha256': digest(source.read_bytes()),
            'runtime': sys.executable, 'cwd': str(REPO), 'created_at_epoch': time.time()}
    (out / 'identity.json').write_text(json.dumps(meta, indent=2) + '\n')

    if args.phase == 'baseline':
        rc, stdout, stderr, counts = node_test(out, 'A1-regression', 'A1 invalid negative')
        if rc == 0 or counts.get('fail', 0) < 1 or counts.get('skipped', 0) != 0:
            raise RuntimeError('BASELINE_GAP_NOT_REPRODUCED: A1 must fail in an executed assertion without skips')
        if 'AssertionError' not in stdout + stderr:
            raise RuntimeError('BASELINE_GAP_NOT_REPRODUCED: failure was not an assertion')
        run(['node', '--test', '--test-name-pattern', 'healthy control preserves', TEST], REPO, out, 'healthy-control', expected=0)
        meta['disposition'] = 'BASELINE_GAP_REPRODUCED'
    elif args.phase == 'focused':
        _, stdout, stderr, counts = node_test(out, 'focused')
        if counts.get('fail') != 0 or counts.get('skipped') != 0 or counts.get('pass', 0) < 8:
            raise RuntimeError(f'focused tests not all positive/no-skip: {counts}; {stderr[-1000:]}')
    elif args.phase == 'regression':
        for name in ['tests/test_advisor_tools.mjs', 'tests/test_advisor_reports.mjs']:
            run(['node', '--test', name], REPO, out, Path(name).stem, expected=0)
    elif args.phase == 'repository':
        runtime = manifest['runtime']['credential_scan_python3']
        run([runtime, 'scripts/check_repository.py'], REPO, out, 'repository', expected=0)
    elif args.phase == 'typecheck':
        pnpm = manifest['runtime']['pnpm']
        for name, project in [('root', 'tsconfig.json'), ('web', 'web/tsconfig.json'), ('coast', 'packages/coast/tsconfig.json')]:
            run([pnpm, 'exec', 'tsc', '--noEmit', '--project', project], REPO, out, f'typecheck-{name}', expected=0)
    elif args.phase == 'build':
        run([manifest['runtime']['pnpm'], 'build'], REPO, out, 'build', expected=0)

    meta['records'] = records
    (out / 'identity.json').write_text(json.dumps(meta, indent=2) + '\n')
    print(json.dumps({'phase': args.phase, 'output': str(out), 'identity': identity, 'records': records}, indent=2))


records = []
if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ACCEPTANCE_FAILED: {exc}', file=sys.stderr)
        sys.exit(1)
