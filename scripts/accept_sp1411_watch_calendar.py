#!/usr/bin/env python3
"""SP-14-v1 scoped acceptance runner; all evidence is kept under --output."""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import uuid

REPO = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
MANIFEST = CANDIDATE / 'SOURCE-MANIFEST.json'
SPEC = 'SP-14-v1'
CARD = 'SP1411-WATCH-CALENDAR'
TEST = 'tests/test_sp1411_watch_calendar.mjs'
ORIGINAL = 'tests/test_fleet_watch.mjs'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return digest(path.read_bytes())


def run(argv, cwd, env, folder, label):
    folder.mkdir(parents=True, exist_ok=False)
    proc = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True)
    stdout = proc.stdout.encode()
    stderr = proc.stderr.encode()
    (folder / 'stdout.txt').write_bytes(stdout)
    (folder / 'stderr.txt').write_bytes(stderr)
    text = stdout.decode(errors='replace')
    counts = {}
    for key in ('tests', 'pass', 'fail', 'skipped', 'cancelled', 'todo'):
        for line in text.splitlines():
            if line.startswith('# ' + key + ' '):
                try: counts[key] = int(line.rsplit(' ', 1)[1])
                except ValueError: pass
    node_probe = subprocess.run(['node', '--version'], cwd=cwd, text=True, capture_output=True)
    node_probe_stdout = node_probe.stdout.encode()
    node_probe_stderr = node_probe.stderr.encode()
    (folder / 'node-version.stdout.txt').write_bytes(node_probe_stdout)
    (folder / 'node-version.stderr.txt').write_bytes(node_probe_stderr)
    receipt = {
        'spec': SPEC, 'card': CARD, 'phase': label,
        'argv': argv, 'cwd': str(cwd), 'exit': proc.returncode,
        'test_counts': counts,
        'test_names': [line[2:] for line in text.splitlines() if line.startswith('# Subtest: ')],
        'stdout_sha256': digest(stdout), 'stderr_sha256': digest(stderr),
        'stdout': 'stdout.txt', 'stderr': 'stderr.txt',
        'runtime': {
            'python': sys.executable,
            'node': node_probe.stdout.strip(),
            'node_probe': {'argv': ['node', '--version'], 'cwd': str(cwd), 'exit': node_probe.returncode,
                           'stdout_sha256': digest(node_probe_stdout), 'stderr_sha256': digest(node_probe_stderr),
                           'stdout': 'node-version.stdout.txt', 'stderr': 'node-version.stderr.txt'},
        },
        'head': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True, capture_output=True).stdout.strip(),
        'source_sha256': sha_file(REPO / 'server/fleet/watch.ts'),
        'test_sha256': sha_file(REPO / TEST),
        'fixture_sha256': {},
    }
    fixture = REPO / 'tests/fixtures/sp1411_watch_calendar'
    if fixture.exists():
        for path in sorted(fixture.rglob('*')):
            if path.is_file():
                receipt['fixture_sha256'][path.relative_to(REPO).as_posix()] = sha_file(path)
    (folder / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return proc.returncode, stdout.decode(errors='replace'), stderr.decode(errors='replace'), receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = pathlib.Path(args.output).resolve()
    if not root.is_relative_to(CANDIDATE / 'out'):
        raise SystemExit('output must be below candidate out/')
    root.mkdir(parents=True, exist_ok=True)
    runroot = root / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex)
    runroot.mkdir()
    manifest = json.loads(MANIFEST.read_text())
    if manifest.get('schema') != 'agentorange.source-manifest/v1' or manifest.get('repo') != str(REPO):
        raise SystemExit('source manifest schema or repo mismatch')
    env = os.environ.copy()
    results = []

    def invoke(argv, label, extra_env=None):
        child_env = env.copy()
        if extra_env:
            child_env.update(extra_env)
        result = run(argv, REPO, child_env, runroot / f'{len(results):02d}-{label}', label)
        results.append({'label': label, 'argv': argv, 'exit': result[0], 'receipt': result[3]})
        print(f'{label}: exit={result[0]} stdout_sha256={result[3]["stdout_sha256"]} stderr_sha256={result[3]["stderr_sha256"]}')
        return result

    if args.suite == 'baseline':
        code, out, err, _ = invoke(['node', '--experimental-strip-types', '--test', TEST], 'baseline', {'SP1411_BASELINE': '1'})
        good = code == 1 and 'not ok 1 - primary regression:' in out and 'ok 2 - healthy control:' in out and '# tests 2' in out and '# pass 1' in out and '# fail 1' in out and '# skipped 0' in out and 'ReferenceError' not in out and 'ERR_MODULE' not in out
        if not good:
            raise SystemExit('baseline did not match the sole expected semantic red plus healthy control')
        status = 'BASELINE_GAP_REPRODUCED'
    elif args.suite in ('focused', 'regression'):
        files = [TEST] if args.suite == 'focused' else [ORIGINAL]
        for filename in files:
            code, out, err, _ = invoke(['node', '--experimental-strip-types', '--test', filename], args.suite)
            if code != 0 or '# fail 0' not in out or '# skipped 0' not in out:
                raise SystemExit(f'{args.suite} failed or had skips')
        status = 'SCOPED_PASS_REVIEW_REQUIRED'
    elif args.suite == 'repository':
        python = manifest['runtime']['credential_scan_python3']
        code, out, err, _ = invoke([python, 'scripts/check_repository.py'], 'repository')
        if code != 0:
            raise SystemExit('repository check failed')
        status = 'SCOPED_PASS_REVIEW_REQUIRED'
    elif args.suite == 'typecheck':
        for config in ['tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json']:
            code, out, err, _ = invoke(['pnpm', 'exec', 'tsc', '--noEmit', '-p', config], 'typecheck-' + config.replace('/', '-'))
            if code != 0:
                raise SystemExit('typecheck failed: ' + config)
        status = 'SCOPED_PASS_REVIEW_REQUIRED'
    else:
        code, out, err, _ = invoke(['pnpm', 'build'], 'build')
        if code != 0:
            raise SystemExit('build failed')
        status = 'SCOPED_PASS_REVIEW_REQUIRED'
    summary = {'spec': SPEC, 'card': CARD, 'suite': args.suite, 'status': status, 'head': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True, capture_output=True).stdout.strip(), 'results': results}
    (runroot / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
