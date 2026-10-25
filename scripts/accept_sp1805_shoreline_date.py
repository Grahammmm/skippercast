#!/usr/bin/env python3
"""Offline, receipt-producing acceptance runner for SP1805-SHORELINE-DATE."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
WRITE_ROOT = ROOT.parent
MANIFEST = WRITE_ROOT / 'SOURCE-MANIFEST.json'
TEST = ROOT / 'tests/test_sp1805_shoreline_date.mjs'
BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'


def run(argv, cwd):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)


def runtime(executable, version_args):
    resolved = shutil.which(executable) if not Path(executable).is_absolute() else executable
    if not resolved or not Path(resolved).exists():
        raise RuntimeError(f'runtime not found: {executable}')
    resolved = str(Path(resolved).absolute())
    proc = run([resolved, *version_args], ROOT)
    if proc.returncode:
        raise RuntimeError(f'runtime version failed: {resolved}: {proc.stderr}')
    return {'path': resolved, 'version': (proc.stdout or proc.stderr).strip(), 'version_exit': proc.returncode}


def tap_counts(stdout):
    counts = {key: int(value) for key, value in re.findall(r'^# (tests|pass|fail|skipped|cancelled|todo) (\d+)$', stdout, re.MULTILINE)}
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    out = output_root / f'{args.phase}-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}-{uuid.uuid4().hex}'
    out.mkdir(parents=False, exist_ok=False)

    manifest_bytes = MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get('schema') != 'agentorange.source-manifest/v1':
        raise RuntimeError('unexpected source manifest schema')
    if Path(manifest.get('repo', '')).resolve() != ROOT:
        raise RuntimeError('source manifest repo identity mismatch')
    if manifest.get('head') != BASE:
        raise RuntimeError('source manifest pinned head mismatch')
    ancestor = run(['git', 'merge-base', '--is-ancestor', manifest['head'], 'HEAD'], ROOT)
    if ancestor.returncode:
        raise RuntimeError('manifest head is not an ancestor of candidate HEAD')

    node_runtime = runtime('node', ['--version'])
    pnpm_path = manifest['runtime']['pnpm']
    pnpm_runtime = runtime(pnpm_path, ['--version'])
    python_path = manifest['runtime']['credential_scan_python3']
    python_runtime = runtime(python_path, ['--version'])
    records = []
    node = [node_runtime['path'], '--experimental-strip-types', '--test']

    if args.phase == 'baseline':
        source = out / 'base-source'
        source.mkdir()
        archive = subprocess.run(['git', 'archive', '--format=tar', manifest['head']], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if archive.returncode:
            raise RuntimeError(f'git archive failed: {archive.stderr.decode(errors="replace")}')
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode='r:') as bundle:
            bundle.extractall(source)
        baseline_test = source / 'tests/test_sp1805_shoreline_date.mjs'
        baseline_test.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEST, baseline_test)
        fixture_src = ROOT / 'tests/fixtures/sp1805_shoreline_date'
        fixture_dst = source / 'tests/fixtures/sp1805_shoreline_date'
        fixture_dst.mkdir(parents=True, exist_ok=True)
        shutil.copytree(fixture_src, fixture_dst, dirs_exist_ok=True)
        (source / 'node_modules').symlink_to(ROOT / 'node_modules', target_is_directory=True)
        jobs = [('primary', node + ['--test-name-pattern', 'A1 primary regression', str(baseline_test)], source),
                ('healthy', node + ['--test-name-pattern', 'A1 healthy control', str(baseline_test)], source)]
    elif args.phase == 'focused':
        jobs = [('focused', node + [str(TEST)], ROOT)]
    elif args.phase == 'regression':
        jobs = [('map_layers', node + [str(ROOT / 'tests/test_map_layers.mjs')], ROOT)]
    elif args.phase == 'repository':
        jobs = [('repository', [python_runtime['path'], str(ROOT / 'scripts/check_repository.py')], ROOT)]
    elif args.phase == 'typecheck':
        jobs = [('typecheck-root', [pnpm_runtime['path'], 'exec', 'tsc', '--noEmit', '--project', 'tsconfig.json'], ROOT),
                ('typecheck-web', [pnpm_runtime['path'], 'exec', 'tsc', '--noEmit', '--project', 'web/tsconfig.json'], ROOT),
                ('typecheck-coast', [pnpm_runtime['path'], 'exec', 'tsc', '--noEmit', '--project', 'packages/coast/tsconfig.json'], ROOT)]
    else:
        jobs = [('build', [pnpm_runtime['path'], 'build'], ROOT)]

    for name, argv, cwd in jobs:
        started = time.time()
        proc = run(argv, cwd)
        stdout = proc.stdout.encode()
        stderr = proc.stderr.encode()
        (out / f'{name}.stdout').write_bytes(stdout)
        (out / f'{name}.stderr').write_bytes(stderr)
        counts = tap_counts(proc.stdout)
        record = {'name': name, 'argv': argv, 'cwd': str(cwd.resolve()), 'runtime': {'path': str(Path(argv[0]).absolute()), 'version': node_runtime['version'] if Path(argv[0]).absolute() == Path(node_runtime['path']) else pnpm_runtime['version'] if Path(argv[0]).absolute() == Path(pnpm_runtime['path']) else python_runtime['version']}, 'started_epoch': started, 'exit': proc.returncode, 'counts': counts, 'stdout_sha256': hashlib.sha256(stdout).hexdigest(), 'stderr_sha256': hashlib.sha256(stderr).hexdigest()}
        if name in ('primary', 'healthy'):
            record['failure_id'] = 'A1 primary assertion' if name == 'primary' and ('ERR_ASSERTION' in proc.stdout or 'ERR_ASSERTION' in proc.stderr) and '2026-02-31 is not a real calendar date' in proc.stdout + proc.stderr and 'A1 primary regression' in proc.stdout + proc.stderr else None
        records.append(record)

    payload = {'phase': args.phase, 'repo': str(ROOT), 'head': run(['git', 'rev-parse', 'HEAD'], ROOT).stdout.strip(), 'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(), 'manifest_schema': manifest['schema'], 'manifest_repo': manifest['repo'], 'manifest_head': manifest['head'], 'tests_sha256': hashlib.sha256(TEST.read_bytes()).hexdigest(), 'runtimes': {'node': node_runtime, 'pnpm': pnpm_runtime, 'credential_scan_python3': python_runtime}, 'records': records}
    (out / 'receipt.json').write_text(json.dumps(payload, indent=2) + '\n')

    if args.phase == 'baseline':
        primary, healthy = records
        pcounts, hcounts = primary['counts'], healthy['counts']
        primary_ok = (primary['exit'] == 1 and pcounts.get('tests', 0) >= 1 and pcounts.get('fail', 0) >= 1 and pcounts.get('skipped', 0) == 0 and primary['failure_id'] == 'A1 primary assertion')
        healthy_ok = (healthy['exit'] == 0 and hcounts.get('tests', 0) >= 1 and hcounts.get('pass', 0) == hcounts.get('tests', 0) and hcounts.get('skipped', 0) == 0)
        ok = primary_ok and healthy_ok
        print('BASELINE_GAP_REPRODUCED' if ok else 'BASELINE_CONTRACT_FAILED')
        return 0 if ok else 1

    ok = True
    for record in records:
        counts = record['counts']
        if record['exit'] != 0:
            ok = False
        if args.phase in ('focused', 'regression') and not (counts.get('tests', 0) > 0 and counts.get('fail', 0) == 0 and counts.get('skipped', 0) == 0 and counts.get('cancelled', 0) == 0 and counts.get('todo', 0) == 0):
            ok = False
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
