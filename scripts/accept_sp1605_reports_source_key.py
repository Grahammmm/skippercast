"""SP-16-v1 offline acceptance; explicit subprocess argv, unique raw receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
PRODUCT = 'web/app/views/Reports.tsx'
REGRESSION = 'tests/test_reports_view.mjs'
FIXTURE = 'tests/fixtures/sp1605_reports_source_key'
TEST = 'tests/test_sp1605_reports_source_key.mjs'
PINS = {PRODUCT: '8ef399a5024b6bf2b232934647c40029674e8f661ea3391b037460ca66246af1',
        REGRESSION: '2ccee6f484847a28e9487a6af4cbf45d369a97c0ffb86d134f1628797db3e771'}
BASELINE_FILES = [TEST] + [f'{FIXTURE}/{name}' for name in ('harness.mjs', 'entry.ts', 'effects.ts', 'offline.mjs')]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def identities():
    paths = [PRODUCT, REGRESSION, TEST, 'scripts/accept_sp1605_reports_source_key.py']
    paths += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / FIXTURE).rglob('*')) if p.is_file()]
    note = ROOT / 'docs/engineering/sp1605_reports_source_key.md'
    if note.exists():
        paths.append(note.relative_to(ROOT).as_posix())
    return {p: digest(ROOT / p) for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    out = args.output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex)
    out.mkdir()
    receipt = {'spec': 'SP-16-v1', 'card': 'SP1605-REPORTS-SOURCE-KEY', 'suite': args.suite,
               'cwd': str(ROOT), 'started_at': datetime.now(timezone.utc).isoformat(), 'children': [], 'status': 'FAIL'}
    try:
        manifest = json.loads((ROOT.parent / 'SOURCE-MANIFEST.json').read_text())
        if manifest.get('schema') != 'agentorange.source-manifest/v1' or manifest.get('head') != BASE:
            raise RuntimeError('standard-stage schema/head mismatch')
        if Path(manifest['repo']).resolve() != ROOT or manifest.get('card') != receipt['card']:
            raise RuntimeError('standard-stage repository/card mismatch')
        scan_python = manifest['runtime']['credential_scan_python3']
        if not Path(scan_python).is_file() or not (ROOT / '.venv').is_dir() or not (ROOT / 'node_modules').is_dir():
            raise RuntimeError('missing approved staged runtime/dependencies')
        if git('rev-parse', f'{BASE}^{{commit}}') != BASE:
            raise RuntimeError('missing staged base')
        for path, expected in PINS.items():
            blob = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT)
            if hashlib.sha256(blob).hexdigest() != expected:
                raise RuntimeError(f'base pin mismatch: {path}')
        if digest(ROOT / REGRESSION) != PINS[REGRESSION]:
            raise RuntimeError('original regression changed')
        receipt.update(head=git('rev-parse', 'HEAD'), base=BASE, git_status=git('status', '--porcelain'),
                       source_hashes=identities(), runtime={'python': sys.version, 'executable': sys.executable,
                       'credential_scan_python3': scan_python}, baseline_hashes={p: digest(ROOT / p) for p in BASELINE_FILES})
        if args.suite == 'baseline' and digest(ROOT / PRODUCT) != PINS[PRODUCT]:
            raise RuntimeError('baseline requires unchanged pinned product')
        if args.suite == 'focused':
            frozen = json.loads((ROOT / FIXTURE / 'baseline-pins.json').read_text())
            if receipt['baseline_hashes'] != frozen:
                raise RuntimeError('frozen baseline test/fixture bytes changed')
        node = shutil.which('node')
        pnpm = manifest['runtime']['pnpm']
        if not node:
            raise RuntimeError('missing installed node')
        env = os.environ.copy()
        env['TMPDIR'] = str(out / 'tmp')
        Path(env['TMPDIR']).mkdir()
        env['SP1605_SUITE'] = args.suite
        guard = str(ROOT / FIXTURE / 'offline.mjs')
        if args.suite in ('baseline', 'focused'):
            commands = [[node, '--test', '--test-reporter=tap', TEST]]
        elif args.suite == 'regression':
            commands = [[node, '--import', guard, '--test', '--test-reporter=tap', REGRESSION]]
        elif args.suite == 'repository':
            commands = [[scan_python, 'scripts/check_repository.py']]
        elif args.suite == 'typecheck':
            commands = [[pnpm, 'exec', 'tsc', '--noEmit', '-p', config] for config in ('tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json')]
        else:
            commands = [[pnpm, 'build']]
        for i, command in enumerate(commands):
            stdout, stderr = out / f'{i}-stdout.txt', out / f'{i}-stderr.txt'
            start = time.monotonic()
            with stdout.open('wb') as of, stderr.open('wb') as ef:
                child = subprocess.run(command, cwd=ROOT, env=env, stdout=of, stderr=ef, check=False)
            text = stdout.read_text(errors='replace')
            counts = {name: int(value) for name, value in re.findall(r'^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$', text, re.M)}
            record = {'argv': command, 'cwd': str(ROOT), 'exit': child.returncode, 'seconds': time.monotonic() - start,
                      'counts': counts, 'stdout': str(stdout), 'stderr': str(stderr),
                      'stdout_sha256': digest(stdout), 'stderr_sha256': digest(stderr)}
            if args.suite == 'repository':
                record['checked_files'] = re.findall(r'Checked (\d+)', text)
            receipt['children'].append(record)
            if args.suite in ('baseline', 'focused', 'regression'):
                expected_tests = {'baseline': 2, 'focused': 9, 'regression': 8}[args.suite]
                if counts.get('tests') != expected_tests or any(counts.get(k) != 0 for k in ('cancelled', 'skipped', 'todo')):
                    raise RuntimeError('unexpected tests, skips or setup/teardown errors')
                if args.suite == 'baseline':
                    if child.returncode != 1 or counts.get('pass') != 1 or counts.get('fail') != 1:
                        raise RuntimeError('unexpected baseline exit/counts')
                    if not re.search(r'^not ok 1 - primary regression$', text, re.M) or not re.search(r'^ok 2 - healthy control$', text, re.M):
                        raise RuntimeError('wrong baseline failing/healthy cases')
                    if not re.search(r'^    A1_SOURCE_IDENTITY: null-to-path must load current charter evidence$', text, re.M) or "code: 'ERR_ASSERTION'" not in text:
                        raise RuntimeError('baseline not exact semantic assertion')
                elif child.returncode != 0 or counts.get('fail') != 0 or counts.get('pass') != expected_tests:
                    raise RuntimeError('test acceptance failed')
            elif child.returncode != 0:
                raise RuntimeError(f'{args.suite} child failed')
        if identities() != receipt['source_hashes']:
            raise RuntimeError('source bytes changed during acceptance')
        receipt['status'] = 'BASELINE_GAP_REPRODUCED' if args.suite == 'baseline' else 'PASS_REVIEW_REQUIRED'
    except Exception as error:
        receipt['error'] = str(error)
    receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
    target = out / 'receipt.json'
    target.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'receipt': str(target), 'receipt_sha256': digest(target), 'error': receipt.get('error')}))
    return 0 if receipt['status'] != 'FAIL' else 1


if __name__ == '__main__':
    sys.exit(main())
