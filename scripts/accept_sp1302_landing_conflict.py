#!/usr/bin/env python3
"""Portable, offline, append-only SP-13-v2 acceptance receipts (not release approval)."""
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
BASE = '2979d59bfbb7d724eb83b34a48102b914ee8eaa3'
PRIMARY = 'server/fleet/pairing.ts'
TEST = 'tests/test_sp1302_landing_conflict.mjs'
FIXTURE = 'tests/fixtures/sp1302_landing_conflict'
ORIGINAL = 'tests/test_fleet_pairing.mjs'
PRIMARY_SHA = '39e9f4d093f76528a4285ded58c9f858d84ed7f44c0c841f964b3ce5d023804f'
ORIGINAL_SHA = '7814621d86baf1a31b93c5a44b37832789285aefe6ef2e6a9170109c9a2922d3'
AUTHOR = {'model': 'gpt-6.1-sol', 'provider': 'openai-codex', 'profile': 'sol-reviewer', 'role': 'material author, not independent reviewer'}
ORIGINAL_NAMES = [
    'N2 check: a synthetic trip plus a landing report writes one fleet_trip_reports row, and a re-run keeps it',
    "landing reports pair only on a sole vessel name, the trip's port and its local date",
    'an unreadable feed skips landing pairs and the run still records processed',
    'advisor reports pair on the window when published and linked, and the sweep drops them once withdrawn',
    'a report pairs with one trip: two same-day trips and one report give one row (most fishing time, then earliest)',
    'nameNorm matches the Python name_norm (tests/unit/test_fleet_resolve.py cases)',
]
NAMES = [
    'primary regression', 'healthy control',
    'A1 every A-B-A permutation is withheld and A-A agrees',
    'A2 independent name port date conflicts within and across two valid feeds',
    'A2 eligibility and distinct healthy IDs survive conflict and unavailable feeds',
    'A3 D1 conflict omission preserves stored pairs and healthy ranking and advisor attribution',
]

def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def no_symlinks(path):
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        require(not part.is_symlink(), f'symlinked ancestry refused: {part}')
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


def hashes():
    files = [REPO / PRIMARY, REPO / TEST, Path(__file__), REPO / ORIGINAL]
    note = REPO / 'docs/engineering/sp1302_landing_conflict.md'
    if note.exists():
        files.append(note)
    for path in (REPO / FIXTURE).rglob('*'):
        no_symlinks(path)
        if path.is_file():
            files.append(path)
    return {str(p.relative_to(REPO)): sha(no_symlinks(p)) for p in sorted(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    no_symlinks(CANDIDATE)
    no_symlinks(REPO / FIXTURE)
    manifest_path = no_symlinks(CANDIDATE / 'SOURCE-MANIFEST.json')
    manifest = json.loads(manifest_path.read_text())
    require(manifest['schema'] == 'agentorange.source-manifest/v1', 'wrong manifest schema')
    require(Path(manifest['repo']) == REPO and Path(manifest['write_root']) == CANDIDATE, 'wrong staged root')
    require(manifest['head'] == BASE, 'wrong staged base')
    require(sha(REPO / ORIGINAL) == ORIGINAL_SHA, 'original regression drift')
    head = git('rev-parse', 'HEAD')
    require(git('merge-base', BASE, head) == BASE, 'HEAD not based on pinned source')
    if args.suite == 'baseline':
        require(head == BASE and sha(REPO / PRIMARY) == PRIMARY_SHA, 'baseline requires untouched pinned product')
    output = no_symlinks(args.output)
    require(output.is_relative_to(CANDIDATE / 'out'), 'output must be candidate-local out child')
    output.mkdir(parents=True, exist_ok=True)
    run = output / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:12])
    run.mkdir()
    temp = run / 'tmp'
    temp.mkdir()
    home = temp / 'home'
    home.mkdir()
    # Deliberately do not inherit credentials, service configuration or NODE_OPTIONS.
    env = {'PATH': os.environ.get('PATH', os.defpath), 'HOME': str(home),
           'TMPDIR': str(temp), 'TMP': str(temp), 'TEMP': str(temp),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
           'SP1302_OFFLINE': '1', 'SP1302_BASELINE': '1' if args.suite == 'baseline' else '0',
           'NODE_OPTIONS': '--import=' + str(REPO / FIXTURE / 'offline.mjs'),
           'CI': '1', 'NO_COLOR': '1'}
    node = shutil.which('node')
    require(node is not None, 'installed node required')
    before = hashes()
    commits = []
    for commit in git('rev-list', '--reverse', BASE + '..HEAD').splitlines():
        message = git('show', '-s', '--format=%B', commit)
        commits.append({'head': commit, 'message': message,
                        'model': re.findall(r'^Material-Author-Model: (.+)$', message, re.M),
                        'provider': re.findall(r'^Material-Author-Provider: (.+)$', message, re.M)})
    receipt = {'specification': 'SP-13-v2', 'card': 'SP1302-LANDING-CONFLICT', 'phase': args.suite,
               'staged_base': BASE, 'head': head, 'source_manifest_sha256': sha(manifest_path),
               'material_author': AUTHOR, 'commits': commits,
               'source_test_fixture_hashes': before, 'cwd': str(REPO),
               'parent_runtime': {'executable': sys.executable, 'version': sys.version, 'argv': sys.argv},
               'environment': env, 'children': [], 'case_map': {'A1': NAMES[2], 'A2': NAMES[3:5], 'A3': NAMES[5], 'A4': NAMES[:2]}}

    def child(argv, label):
        result = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, timeout=300)
        stdout, stderr = run / (label + '.stdout.txt'), run / (label + '.stderr.txt')
        stdout.write_bytes(result.stdout)
        stderr.write_bytes(result.stderr)
        row = {'argv': argv, 'cwd': str(REPO), 'exit': result.returncode,
               'stdout': str(stdout), 'stdout_sha256': sha(stdout),
               'stderr': str(stderr), 'stderr_sha256': sha(stderr)}
        receipt['children'].append(row)
        return result, row

    ok = False
    try:
        runtime, _ = child([node, '--version'], 'node-version')
        require(runtime.returncode == 0, 'cannot measure node version')
        if args.suite in {'baseline', 'focused', 'regression'}:
            selector = ORIGINAL if args.suite == 'regression' else TEST
            result, row = child([node, '--experimental-strip-types', '--test', '--test-reporter=tap', selector], 'tests')
            text = result.stdout.decode('utf8', errors='replace')
            counts = {k: int(v) for k, v in re.findall(r'^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$', text, re.M)}
            names = re.findall(r'^# Subtest: (.+)$', text, re.M)
            row.update({'counts': counts, 'test_names': names, 'not_executed': []})
            expected_names = ORIGINAL_NAMES if args.suite == 'regression' else NAMES[:2] if args.suite == 'baseline' else NAMES
            expected = len(expected_names)
            require(counts.get('tests') == expected and len(names) == expected, 'missing or extra tests')
            require(all(counts.get(k) == 0 for k in ['cancelled', 'skipped', 'todo']), 'cancelled/skipped/todo is not acceptance')
            require(names == expected_names, 'test identity mismatch')
            if args.suite == 'baseline':
                require(result.returncode == 1 and counts.get('fail') == 1 and counts.get('pass') == 1, 'baseline must be exactly one fail and one pass')
                require('not ok 1 - primary regression' in text and 'ok 2 - healthy control' in text, 'wrong failing control')
                require("code: 'ERR_ASSERTION'" in text and "failureType: 'testCodeFailure'" in text,
                        'baseline requires semantic assertion, not harness error')
                require('conflicting normalized names must withhold this report ID' in text, 'wrong semantic assertion')
                receipt['result'] = 'BASELINE_GAP_REPRODUCED (historical only, not acceptance)'
            else:
                require('observed product exception:' not in text, 'product exception cannot be accepted after repair')
                require(result.returncode == 0 and counts.get('fail') == 0 and counts.get('pass') == expected, 'selected assertions failed')
                receipt['result'] = 'PASS_REVIEW_REQUIRED'
        elif args.suite == 'repository':
            interpreter = manifest['runtime']['credential_scan_python3']
            require(Path(interpreter).is_file(), 'manifest credential-scan interpreter missing; no fallback')
            version, _ = child([interpreter, '--version'], 'credential-python-version')
            require(version.returncode == 0, 'cannot measure credential interpreter')
            # This unchanged file has no network/model calls or mutable bound live defaults.
            result, row = child([interpreter, str(REPO / 'scripts/check_repository.py')], 'repository')
            require(result.returncode == 0, 'unchanged repository check failed')
            row['checks'] = result.stdout.decode('utf8', errors='replace').splitlines()
            receipt['result'] = 'PASS_REVIEW_REQUIRED'
        else:
            pnpm = manifest['runtime']['pnpm']
            require(Path(pnpm).is_file(), 'installed manifest pnpm required')
            version, _ = child([pnpm, 'exec', 'tsc', '--version'], 'typescript-version')
            require(version.returncode == 0, 'cannot measure TypeScript runtime')
            exits = []
            for index, config in enumerate(['tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json']):
                result, _ = child([pnpm, 'exec', 'tsc', '--noEmit', '-p', config], 'typecheck-' + str(index))
                exits.append(result.returncode)
            require(all(code == 0 for code in exits), 'one or more declared typecheck programs failed')
            receipt['result'] = 'PASS_REVIEW_REQUIRED'
        require(before == hashes(), 'source/test/fixture changed during acceptance')
        require(head == git('rev-parse', 'HEAD'), 'HEAD changed during acceptance')
        ok = True
    except Exception as error:
        receipt['result'] = 'FAIL'
        receipt['error'] = str(error)
    receipt['passed_contract'] = ok
    receipt['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt['git_status'] = git('status', '--porcelain')
    target = run / 'receipt.json'
    target.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'result': receipt['result'], 'receipt': str(target), 'sha256': sha(target), 'error': receipt.get('error')}, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
