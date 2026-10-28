#!/usr/bin/env python3
"""Offline SP1505 argv launcher; stdlib only, immutable per-invocation receipts.

Suites: baseline (the primary regression / healthy control pair against the
unchanged pinned product module), focused (A1-A4), regression (the original
tests/test_advisor_pages.mjs unchanged), repository (unchanged
scripts/check_repository.py under the staged credential-scan interpreter),
typecheck (three separate pnpm exec tsc --noEmit runs) and build (pnpm build,
local only). Every child is an explicit argv list with checked exit handling.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
FIXTURE = REPO / 'tests/fixtures/sp1505_port_answer_lines'
PRIMARY = 'server/advisor/pages/port.ts'
TEST = 'tests/test_sp1505_port_answer_lines.mjs'
NOTE = 'docs/engineering/sp1505_port_answer_lines.md'
ORIGINALS = ['tests/test_advisor_pages.mjs']
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
PIN = 'e5c2d59800f971d8e175caa129f86186d1a25b76136eb3e58d657842dbd133a6'
AUTHOR = {'model': 'claude-opus-5-5', 'provider': 'anthropic', 'profile': 'opus-coder-bopus', 'task': 't_5e600d8a', 'run': 1857}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def no_links(path):
    """Check existing ancestry before reading or creating the owned path."""
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise ValueError(f'symlink ancestry refused: {part}')
    return path


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()


def hashes():
    paths = [REPO / PRIMARY, REPO / TEST, Path(__file__).resolve(), *[REPO / p for p in ORIGINALS]]
    paths += sorted(FIXTURE.rglob('*'))
    if (REPO / NOTE).exists():
        paths.append(REPO / NOTE)
    out = {}
    for path in paths:
        no_links(path)
        if path.is_file():
            out[path.relative_to(REPO).as_posix()] = digest(path.read_bytes())
    return out


def tap_summary(stdout):
    cases = [{'status': m[1], 'number': int(m[2]), 'name': m[3]}
             for m in re.finditer(r'^(ok|not ok) (\d+) - (.+)$', stdout, re.M)]
    totals = {k: int(v) for k, v in re.findall(r'^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$', stdout, re.M)}
    return {'cases': cases, 'totals': totals}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    no_links(CANDIDATE)
    no_links(FIXTURE)
    spec = json.loads((FIXTURE / 'spec.json').read_text())
    source_path = no_links(CANDIDATE / 'SOURCE-MANIFEST.json')
    source = json.loads(source_path.read_text())
    if (source.get('schema') != 'agentorange.source-manifest/v1' or source.get('head') != BASE
            or Path(source.get('repo', '')) != REPO or source.get('card') != spec['card']):
        raise ValueError('source manifest schema/repo/head/card mismatch')
    credential_python = source.get('runtime', {}).get('credential_scan_python3')
    if not credential_python or not Path(credential_python).is_file():
        raise ValueError('missing staged credential scan interpreter; no fallback')
    if not (REPO / '.venv').is_symlink() or not (REPO / 'node_modules').is_dir():
        raise ValueError('missing approved staged environment; no install or relink')
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=REPO, check=True)
    for name in ORIGINALS:
        original = subprocess.check_output(['git', 'show', f'{BASE}:{name}'], cwd=REPO)
        if digest((REPO / name).read_bytes()) != digest(original):
            raise ValueError(f'original compatibility test changed: {name}')
    output = no_links(args.output)
    out_root = no_links(CANDIDATE / 'out')
    if not output.is_relative_to(out_root) or output == out_root:
        raise ValueError('output must be a child of candidate/out')
    output.mkdir(parents=True, exist_ok=True)
    run = output / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex)
    run.mkdir(exist_ok=False)
    temp = run / 'tmp'
    temp.mkdir()
    node = shutil.which('node')
    pnpm = shutil.which('pnpm')
    if not node or not pnpm:
        raise ValueError('missing staged Node/pnpm runtime')
    env = os.environ.copy()
    env.update({'SP1505_SUITE': args.suite, 'SP1505_TEMP_ROOT': str(temp), 'TMPDIR': str(temp)})
    before = hashes()
    receipt = {
        'schema': 'sp1505.acceptance/v1', 'spec': spec['version'], 'card': spec['card'],
        'phase': args.suite, 'staged_base': BASE, 'head': git('rev-parse', 'HEAD'),
        'git_status_before': git('status', '--porcelain'), 'source_manifest_sha256': digest(source_path.read_bytes()),
        'file_sha256_before': before, 'spec_sha256': before['tests/fixtures/sp1505_port_answer_lines/spec.json'],
        'material_author': AUTHOR,
        'material_commits': git('log', '--format=%H%n%B', f'{BASE}..HEAD'),
        'launcher': {'argv': sys.argv, 'cwd': str(Path.cwd()), 'python': sys.executable,
                     'python_realpath': os.path.realpath(sys.executable), 'version': sys.version},
        'children': [],
    }
    bootstrap = str(FIXTURE / 'bootstrap.mjs')
    if args.suite in ('baseline', 'focused', 'regression'):
        tests = ORIGINALS if args.suite == 'regression' else [TEST]
        commands = [[node, '--import', bootstrap, '--test', '--test-reporter=tap', *tests]]
    elif args.suite == 'repository':
        commands = [[credential_python, str(REPO / 'scripts/check_repository.py')]]
    elif args.suite == 'typecheck':
        commands = [[pnpm, 'exec', 'tsc', '--noEmit', '-p', p] for p in ('tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json')]
    else:
        commands = [[pnpm, 'build']]
    receipt['node_version'] = subprocess.check_output([node, '--version'], cwd=REPO, text=True).strip()
    receipt['pnpm_version'] = subprocess.check_output([pnpm, '--version'], cwd=REPO, text=True).strip()
    receipt['runtime_resolved'] = {p: os.path.realpath(p) for p in (node, pnpm, credential_python)}
    for index, argv in enumerate(commands):
        result = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, timeout=1800)
        stdout = result.stdout.decode('utf-8', 'replace')
        child = {'argv': argv, 'cwd': str(REPO), 'exit': result.returncode,
                 'stdout_sha256': digest(result.stdout), 'stderr_sha256': digest(result.stderr),
                 'stdout': f'{index}.stdout.txt', 'stderr': f'{index}.stderr.txt', 'tap': tap_summary(stdout)}
        (run / child['stdout']).write_bytes(result.stdout)
        (run / child['stderr']).write_bytes(result.stderr)
        receipt['children'].append(child)
        print(f'child {index}: exit {result.returncode}; argv={json.dumps(argv)}')
        if args.suite in ('baseline', 'focused', 'regression'):
            print(json.dumps(child['tap'], ensure_ascii=False))
    after = hashes()
    receipt['file_sha256_after'] = after
    receipt['git_status_after'] = git('status', '--porcelain')
    valid = before == after
    if args.suite == 'baseline':
        c = receipt['children'][0]
        stdout = (run / c['stdout']).read_text()
        valid = valid and before[PRIMARY] == PIN
        valid = valid and c['exit'] == 1
        valid = valid and c['tap']['cases'] == [
            {'status': 'not ok', 'number': 1, 'name': 'primary regression'},
            {'status': 'ok', 'number': 2, 'name': 'healthy control'}]
        valid = valid and c['tap']['totals'] == {'tests': 2, 'pass': 1, 'fail': 1, 'cancelled': 0, 'skipped': 0, 'todo': 0}
        valid = valid and 'SP1505_PRIMARY_SEMANTIC_MISMATCH' in stdout and 'ERR_ASSERTION' in stdout
        receipt['verdict'] = 'BASELINE_GAP_REPRODUCED' if valid else 'BASELINE_INVALID_STOP'
    else:
        for c in receipt['children']:
            valid = valid and c['exit'] == 0
            if args.suite in ('focused', 'regression'):
                totals = c['tap']['totals']
                if args.suite == 'focused':
                    names = spec['focused_tests']
                    valid = valid and [x['name'] for x in c['tap']['cases']] == names
                    expected = len(names)
                else:
                    expected = sum(len(re.findall(r'^(?:dbTest|test)\(', (REPO / name).read_text(), re.M)) for name in ORIGINALS)
                valid = valid and totals.get('tests') == expected and len(c['tap']['cases']) == expected
                valid = valid and all(x['status'] == 'ok' for x in c['tap']['cases'])
                valid = valid and totals.get('pass') == expected and all(totals.get(k) == 0 for k in ('fail', 'cancelled', 'skipped', 'todo'))
        receipt['verdict'] = 'SCOPED_GREEN_REVIEW_REQUIRED' if valid else 'FAILED_STOP'
    receipt['valid'] = bool(valid)
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
    print(f"{receipt['verdict']}: {run / 'receipt.json'}")
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
