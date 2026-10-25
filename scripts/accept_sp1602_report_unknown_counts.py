#!/usr/bin/env python3
"""Offline, evidence-producing acceptance launcher for SP1602."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
MANIFEST = ROOT.parent / 'SOURCE-MANIFEST.json'
TEST = ROOT / 'tests/test_sp1602_report_unknown_counts.mjs'
REGRESSION = ROOT / 'tests/test_advisor_pages.mjs'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = Path(args.output).resolve() / f"run-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex}"
    out.mkdir(parents=True, exist_ok=False)
    commands = []
    if args.suite == 'baseline':
        commands = [(['node', '--experimental-strip-types', '--test', '--test-name-pattern=primary regression|healthy control', str(TEST)], 1)]
    elif args.suite == 'focused':
        commands = [(['node', '--experimental-strip-types', '--test', str(TEST)], 0)]
    elif args.suite == 'regression':
        commands = [(['node', '--experimental-strip-types', '--test', str(REGRESSION)], 0)]
    elif args.suite == 'repository':
        manifest = json.loads(MANIFEST.read_text())
        if manifest.get('schema') != 'agentorange.source-manifest/v1' or Path(manifest.get('repo', '')).resolve() != ROOT:
            raise SystemExit('invalid source manifest schema or repository identity')
        credential_python = manifest.get('runtime', {}).get('credential_scan_python3')
        if not credential_python:
            raise SystemExit('source manifest lacks runtime.credential_scan_python3')
        commands = [([credential_python, 'scripts/check_repository.py'], 0)]
    elif args.suite == 'typecheck':
        commands = [(['pnpm', 'exec', 'tsc', '--noEmit', '-p', project], 0) for project in ('tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json')]
    elif args.suite == 'build':
        commands = [(['pnpm', 'build'], 0)]
    records = []
    for index, (argv, expected) in enumerate(commands, 1):
        started = time.monotonic()
        proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
        elapsed = time.monotonic() - started
        stdout = proc.stdout.encode()
        stderr = proc.stderr.encode()
        (out / f'{index}.stdout').write_bytes(stdout)
        (out / f'{index}.stderr').write_bytes(stderr)
        record = {'argv': argv, 'cwd': str(ROOT), 'runtime_seconds': elapsed, 'exit': proc.returncode,
                  'expected_exit': expected, 'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
                  'stderr_sha256': hashlib.sha256(stderr).hexdigest(), 'source_head': subprocess.run(
                      ['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()}
        records.append(record)
        if proc.returncode != expected:
            raise SystemExit(f"unexpected exit {proc.returncode}; evidence: {out}")
        if args.suite == 'baseline':
            text = proc.stdout + proc.stderr
            if 'unmeasured catch rendered as "0 lingcod"' not in text or '# tests 2' not in text or '# pass 1' not in text or '# fail 1' not in text or '# skipped 0' not in text:
                raise SystemExit(f"baseline did not produce exact semantic red/control green; evidence: {out}")
    manifest = {'suite': args.suite, 'run_dir': str(out), 'script_sha256': digest(SCRIPT),
                'test_sha256': digest(TEST), 'records': records}
    (out / 'receipt.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
