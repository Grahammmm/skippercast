#!/usr/bin/env python3
"""SP-14-v1 scoped acceptance runner; all evidence is kept under --output."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import uuid

REPO = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
MANIFEST = CANDIDATE / 'SOURCE-MANIFEST.json'
SPEC = 'SP-14-v1'
CARD = 'SP1411-WATCH-CALENDAR'
MATERIAL_AUTHOR = {'profile': 'sol-reviewer', 'model': 'gpt-6.1-sol', 'provider': 'openai-codex', 'run': 2292}
STAGED_BASE = '33734f90073a2150eac5a418564ea314c4a591ac'
# Grouped public source fingerprint, not a credential.
BASE_PRIMARY_SHA256 = ''.join('6ae1571c 90fe12e8 bfd84bf6 73a24263 f0aa5e0b 352712c4 fe2366f0 d0be0bf0'.split())
LUNA_COMMITS = ['a63a4172046028e09304ca63f43e7760a41496d1', '522675edd18bd9b815c1997844a1624ab57f15cf']
TEST = 'tests/test_sp1411_watch_calendar.mjs'
ORIGINAL = 'tests/test_fleet_watch.mjs'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    return digest(path.read_bytes())


def git(*args):
    return subprocess.run(['git', *args], cwd=REPO, check=True, capture_output=True).stdout


def preflight():
    manifest = json.loads(MANIFEST.read_text())
    if manifest.get('schema') != 'agentorange.source-manifest/v1' or manifest.get('repo') != str(REPO):
        raise SystemExit('source manifest schema or repo mismatch')
    if manifest.get('head') != STAGED_BASE:
        raise SystemExit('source manifest head does not match staged base')
    python = manifest.get('runtime', {}).get('credential_scan_python3')
    if not isinstance(python, str) or not pathlib.Path(python).is_absolute() or not os.access(python, os.X_OK):
        raise SystemExit('source manifest credential_scan_python3 must name an executable absolute path')
    base_primary = digest(git('show', STAGED_BASE + ':server/fleet/watch.ts'))
    if base_primary != BASE_PRIMARY_SHA256:
        raise SystemExit('staged base primary bytes do not match source pin')
    git('merge-base', '--is-ancestor', STAGED_BASE, 'HEAD')
    commits = []
    for commit in git('rev-list', '--reverse', STAGED_BASE + '..HEAD').decode().splitlines():
        if commit in LUNA_COMMITS:
            author = {'profile': 'luna-worker', 'model': 'gpt-6-luna', 'provider': 'openai-codex', 'run': 1816}
        else:
            message = git('show', '-s', '--format=%B', commit).decode()
            if 'Material-model: gpt-6.1-sol' not in message or 'Material-provider: openai-codex' not in message:
                raise SystemExit('material runtime missing for commit ' + commit)
            author = MATERIAL_AUTHOR
        commits.append({'commit': commit, 'author': author})
    fixture = REPO / 'tests/fixtures/sp1411_watch_calendar'
    fixture_paths = [fixture, *fixture.rglob('*')]
    for ancestor in fixture.parents:
        if ancestor == REPO:
            break
        fixture_paths.append(ancestor)
    for path in fixture_paths:
        if path.is_symlink() or not path.resolve().is_relative_to(REPO):
            raise SystemExit('fixture must stay inside the staged repository without symlinks')
    return manifest, {'staged_base': STAGED_BASE, 'base_primary_sha256': base_primary,
                      'source_manifest_sha256': sha_file(MANIFEST), 'material_commits': commits}


def run(argv, cwd, env, folder, label, identity):
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
    node_argv = [shutil.which('node') or 'node', '--version']
    node_probe = subprocess.run(node_argv, cwd=cwd, text=True, capture_output=True)
    node_probe_stdout = node_probe.stdout.encode()
    node_probe_stderr = node_probe.stderr.encode()
    (folder / 'node-version.stdout.txt').write_bytes(node_probe_stdout)
    (folder / 'node-version.stderr.txt').write_bytes(node_probe_stderr)
    receipt = {
        'spec': SPEC, 'card': CARD, 'phase': label, **identity,
        'material_author': MATERIAL_AUTHOR,
        'argv': argv, 'cwd': str(cwd), 'exit': proc.returncode,
        'test_counts': counts,
        'test_names': [line[2:] for line in text.splitlines() if line.startswith('# Subtest: ')],
        'stdout_sha256': digest(stdout), 'stderr_sha256': digest(stderr),
        'stdout': 'stdout.txt', 'stderr': 'stderr.txt',
        'runtime': {
            'python': sys.executable,
            'node': node_probe.stdout.strip(),
            'node_probe': {'argv': node_argv, 'cwd': str(cwd), 'exit': node_probe.returncode,
                           'stdout_sha256': digest(node_probe_stdout), 'stderr_sha256': digest(node_probe_stderr),
                           'stdout': 'node-version.stdout.txt', 'stderr': 'node-version.stderr.txt'},
        },
        'head': git('rev-parse', 'HEAD').decode().strip(),
        'source_sha256': sha_file(REPO / 'server/fleet/watch.ts'),
        'test_sha256': {p: sha_file(REPO / p) for p in argv if p in (TEST, ORIGINAL)},
        'executed_files_sha256': {p: sha_file(REPO / p) for p in argv[1:] if (REPO / p).is_file()},
        'acceptance_helper_sha256': sha_file(pathlib.Path(__file__)),
        'acceptance_note_sha256': sha_file(REPO / 'docs/engineering/sp1411_watch_calendar.md'),
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
    requested = pathlib.Path(args.output).absolute()
    for path in [requested, *requested.parents]:
        if path == CANDIDATE:
            break
        if path.is_symlink():
            raise SystemExit('output ancestry must not contain symlinks')
    root = requested.resolve()
    if not root.is_relative_to(CANDIDATE / 'out'):
        raise SystemExit('output must be below candidate out/')
    root.mkdir(parents=True, exist_ok=True)
    runroot = root / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex)
    runroot.mkdir()
    manifest, identity = preflight()
    if args.suite == 'baseline' and (git('rev-parse', 'HEAD').decode().strip() != STAGED_BASE or sha_file(REPO / 'server/fleet/watch.ts') != BASE_PRIMARY_SHA256):
        raise SystemExit('baseline requires the unchanged pinned source; preserve historical baseline receipts')
    env = os.environ.copy()
    results = []

    def invoke(argv, label, extra_env=None):
        executable = shutil.which(argv[0])
        if not executable:
            raise SystemExit('missing installed executable: ' + argv[0])
        argv = [executable, *argv[1:]]
        child_env = env.copy()
        if extra_env:
            child_env.update(extra_env)
        result = run(argv, REPO, child_env, runroot / f'{len(results):02d}-{label}', label, identity)
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
            code, out, err, receipt = invoke(['node', '--experimental-strip-types', '--test', filename], args.suite)
            expected = 4 if args.suite == 'focused' else 7
            counts = receipt['test_counts']
            if code != 0 or counts.get('tests') != expected or counts.get('pass') != expected or any(counts.get(k) != 0 for k in ('fail', 'skipped', 'cancelled', 'todo')):
                raise SystemExit(f'{args.suite} failed, had skips, or did not execute the complete selected suite')
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
    summary = {'spec': SPEC, 'card': CARD, **identity, 'suite': args.suite, 'status': status,
               'head': git('rev-parse', 'HEAD').decode().strip(), 'results': results}
    (runroot / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
