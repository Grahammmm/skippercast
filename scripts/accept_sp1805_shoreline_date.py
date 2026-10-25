#!/usr/bin/env python3
"""Offline, receipt-producing acceptance runner for SP1805-SHORELINE-DATE."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT.parent / 'SOURCE-MANIFEST.json'
TEST = ROOT / 'tests/test_sp1805_shoreline_date.mjs'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    records = []
    repo = ROOT
    node = ['node', '--experimental-strip-types', '--test']
    jobs = []
    if args.phase == 'baseline':
        jobs = [('primary', node + ['--test-name-pattern', 'A1 primary regression', str(TEST)]), ('healthy', node + ['--test-name-pattern', 'A1 healthy control', str(TEST)])]
    elif args.phase == 'focused':
        jobs = [('focused', node + [str(TEST)])]
    elif args.phase == 'regression':
        jobs = [('map_layers', node + [str(ROOT / 'tests/test_map_layers.mjs')])]
    elif args.phase == 'repository':
        manifest = json.loads(MANIFEST.read_text())
        jobs = [('repository', [manifest['runtime']['credential_scan_python3'], str(ROOT / 'scripts/check_repository.py'), '--manifest', str(MANIFEST)])]
    elif args.phase == 'typecheck':
        jobs = [('typecheck-root', ['pnpm', 'exec', 'tsc', '--noEmit', '--project', 'tsconfig.json']), ('typecheck-web', ['pnpm', 'exec', 'tsc', '--noEmit', '--project', 'web/tsconfig.json']), ('typecheck-coast', ['pnpm', 'exec', 'tsc', '--noEmit', '--project', 'packages/coast/tsconfig.json'])]
    else:
        jobs = [('build', ['pnpm', 'build'])]
    for name, argv in jobs:
        started = time.time()
        proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False)
        stdout = proc.stdout.encode()
        stderr = proc.stderr.encode()
        (out / f'{name}.stdout').write_bytes(stdout)
        (out / f'{name}.stderr').write_bytes(stderr)
        records.append({'name': name, 'argv': argv, 'cwd': str(repo), 'runtime': sys.executable if argv[0].endswith('python3') else argv[0], 'started_epoch': started, 'exit': proc.returncode, 'stdout_sha256': hashlib.sha256(stdout).hexdigest(), 'stderr_sha256': hashlib.sha256(stderr).hexdigest()})
    payload = {'phase': args.phase, 'repo': str(repo), 'head': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True, check=True).stdout.strip(), 'tests_sha256': hashlib.sha256(TEST.read_bytes()).hexdigest(), 'records': records}
    (out / 'receipt.json').write_text(json.dumps(payload, indent=2) + '\n')
    if args.phase == 'baseline':
        ok = records[0]['exit'] == 1 and records[1]['exit'] == 0
        print('BASELINE_GAP_REPRODUCED' if ok else 'BASELINE_CONTRACT_FAILED')
        return 0 if ok else 1
    return 0 if all(item['exit'] == 0 for item in records) else 1

if __name__ == '__main__':
    raise SystemExit(main())
