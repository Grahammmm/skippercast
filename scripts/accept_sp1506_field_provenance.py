#!/usr/bin/env python3
"""SP-15-v1 offline argv launcher. Zero means scoped evidence, never release."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT.parent
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
PRIMARY = 'server/fleet/admin/vessels.ts'
PRIMARY_BASE_HASH = 'ddee87e95edc89398525e828c10e6bfda63e4f28781f2a007705e6b0cca6b5cb'
TEST = 'tests/test_sp1506_field_provenance.mjs'
FIXTURE = 'tests/fixtures/sp1506_field_provenance'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()

def identity():
    paths = {PRIMARY, TEST, 'tests/test_fleet_admin.mjs', 'tests/_advisor_d1.mjs',
             'scripts/accept_sp1506_field_provenance.py', 'scripts/check_repository.py',
             'package.json', 'pnpm-lock.yaml', 'tsconfig.json', 'web/tsconfig.json',
             'packages/coast/tsconfig.json'}
    note = 'docs/engineering/sp1506_field_provenance.md'
    if (ROOT / note).is_file():
        paths.add(note)
    paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT / FIXTURE).rglob('*') if p.is_file())
    # Actual product import closure and migrations stay tied to these exact bytes.
    paths.update(git('ls-files', 'server', 'drizzle').splitlines())
    return {'head': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
            'status': git('status', '--porcelain'),
            'sha256': {p: digest(ROOT / p) for p in sorted(paths)}}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((CANDIDATE / 'out').resolve()):
        parser.error('output must be inside this candidate out directory')
    manifest = json.loads((CANDIDATE / 'SOURCE-MANIFEST.json').read_text())
    if manifest.get('schema') != 'agentorange.source-manifest/v1' or manifest.get('head') != BASE or Path(manifest['repo']).resolve() != ROOT:
        parser.error('staged source manifest mismatch')
    runtime = manifest['runtime']
    scan_python = runtime['credential_scan_python3']
    if not Path(scan_python).is_file():
        parser.error('missing admitted credential-scan runtime; no fallback permitted')
    node = shutil.which('node')
    pnpm = runtime['pnpm']
    if not node or not Path(pnpm).is_file():
        parser.error('missing installed runtime; no installation permitted')
    output.mkdir(parents=True, exist_ok=True)
    run = output / (time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex)
    run.mkdir()
    source = identity()
    if args.suite == 'baseline' and source['sha256'][PRIMARY] != PRIMARY_BASE_HASH:
        parser.error('baseline requires unchanged pinned product bytes')
    offline = './' + FIXTURE + '/offline.mjs'
    if args.suite == 'baseline':
        commands = [[node, '--import', offline, '--test', '--test-reporter=tap', FIXTURE + '/baseline.mjs']]
    elif args.suite in ('focused', 'regression'):
        selector = TEST if args.suite == 'focused' else 'tests/test_fleet_admin.mjs'
        commands = [[node, '--import', offline, '--test', '--test-reporter=tap', selector]]
    elif args.suite == 'repository':
        commands = [[scan_python, 'scripts/check_repository.py']]
    elif args.suite == 'typecheck':
        commands = [[pnpm, 'exec', 'tsc', '--noEmit', '-p', config] for config in ['tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json']]
    else:
        commands = [[pnpm, 'build']]
    receipt = {'spec': 'SP-15-v1', 'card': 'SP1506-FIELD-PROVENANCE', 'suite': args.suite,
               'source_manifest_sha256': digest(CANDIDATE / 'SOURCE-MANIFEST.json'),
               'source': source, 'runtime': {'launcher_python': sys.executable, 'python_version': sys.version,
               'node': subprocess.check_output([node, '--version'], text=True).strip(),
               'pnpm': subprocess.check_output([pnpm, '--version'], text=True).strip(),
               'credential_scan_python3': scan_python}, 'children': [], 'verdict': 'UNVERIFIED'}
    success = True
    for index, command in enumerate(commands):
        start = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, capture_output=True)
        stdout, stderr = run / f'{index}.stdout.txt', run / f'{index}.stderr.txt'
        stdout.write_bytes(result.stdout)
        stderr.write_bytes(result.stderr)
        text = result.stdout.decode(errors='replace')
        counts = {key: int(value) for key, value in re.findall(r'^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$', text, re.M)}
        if args.suite == 'baseline':
            passed = (result.returncode == 1 and counts == {'tests': 2, 'pass': 1, 'fail': 1, 'cancelled': 0, 'skipped': 0, 'todo': 0}
                      and re.search(r'^not ok 1 - primary regression$', text, re.M) is not None
                      and re.search(r'^ok 2 - healthy control$', text, re.M) is not None
                      and 'A1: current year_built provenance survives earlier-field cap' in text
                      and "code: 'ERR_ASSERTION'" in text
                      and "actual: ~" in text and "expected: '15060000000000000000000000000002'" in text)
        elif args.suite in ('focused', 'regression'):
            passed = (result.returncode == 0 and counts.get('tests', 0) > 0 and counts.get('pass') == counts.get('tests')
                      and all(counts.get(k) == 0 for k in ['fail', 'cancelled', 'skipped', 'todo']))
            if args.suite == 'focused':
                passed = passed and counts.get('tests') == 6
        else:
            passed = result.returncode == 0
        receipt['children'].append({'argv': command, 'cwd': str(ROOT), 'exit': result.returncode,
                                   'elapsed_seconds': time.monotonic() - start, 'counts': counts, 'accepted': bool(passed),
                                   'stdout': str(stdout), 'stdout_sha256': digest(stdout),
                                   'stderr': str(stderr), 'stderr_sha256': digest(stderr)})
        success = success and passed
        if not passed:
            break
    if identity() != source:
        success = False
        receipt['identity_changed'] = True
    receipt['verdict'] = ('BASELINE_GAP_REPRODUCED' if args.suite == 'baseline' else 'SCOPED_GREEN_REVIEW_REQUIRED') if success else 'FAILED'
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'verdict': receipt['verdict'], 'receipt': str(run / 'receipt.json'), 'children': receipt['children']}, indent=2))
    return 0 if success else 1

if __name__ == '__main__':
    raise SystemExit(main())
