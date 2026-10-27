"""SP-15-v1 offline acceptance launcher. Green receipts require independent review.

Each call retains raw child streams in a unique output child, with command,
source identity and hashes. No shell, inline interpreter or optional assertions.
"""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT.parent
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
PRIMARY_HASH = '51753eec1d0b5a6e3556f89ca5071496b013ae097938b835ecfdddc2e388d0f0'
SPEC = 'SP-15-v1'
CARD = 'SP1501-CHOP-COMPLETENESS'
TEST = 'tests/test_sp1501_chop_completeness.mjs'
PRODUCT = 'web/score.ts'
MANAGED = [PRODUCT, TEST, 'scripts/accept_sp1501_chop_completeness.py',
           'tests/fixtures/sp1501_chop_completeness/calm.json',
           'docs/engineering/sp1501_chop_completeness.md']
REGRESSION = ['tests/test_score.mjs', 'tests/test_brief_verdict.mjs']
DEPENDENCIES = ['web/brief/verdict.ts', 'web/map/forecast-grid.ts', 'web/map/surface-field.js',
                'scripts/check_repository.py', 'package.json', 'pnpm-lock.yaml',
                'tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def identity():
    paths = MANAGED + REGRESSION + DEPENDENCIES
    return {'head': git('rev-parse', 'HEAD'), 'status': git('status', '--porcelain'),
            'tracked_diff_sha256': hashlib.sha256(git('diff', 'HEAD').encode()).hexdigest(),
            'files': {p: digest(ROOT / p) for p in paths if (ROOT / p).is_file()},
            'author_runtime': {'model': 'gpt-6.1-sol', 'provider': 'openai-codex',
                               'profile': 'sol-reviewer', 'material_runs': [1843, 1969]}}


def tap_counts(text):
    result = {}
    for key in ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo']:
        matches = re.findall(r'^# ' + key + r' (\d+)\s*$', text, re.M)
        if len(matches) != 1:
            raise ValueError(f'missing/ambiguous TAP summary: {key}')
        result[key] = int(matches[0])
    return result


def require(value, message):
    if not value:
        raise ValueError(message)


def commands(suite, stage):
    node = shutil.which('node')
    pnpm = shutil.which('pnpm')
    if suite in {'baseline', 'focused', 'regression'}:
        require(node, 'installed Node required')
        selectors = REGRESSION if suite == 'regression' else [TEST]
        return [[node, '--test', '--test-reporter=tap', *(['--test-name-pattern=^(primary regression|healthy control)$'] if suite == 'baseline' else []), selector] for selector in selectors]
    if suite == 'repository':
        runtime = stage['runtime']['credential_scan_python3']
        require(Path(runtime).is_file(), 'staged credential runtime missing; no fallback')
        return [[runtime, str(Path(__file__).resolve()), '--check-credential-runtime'],
                [runtime, 'scripts/check_repository.py']]
    require(pnpm, 'installed pnpm required')
    if suite == 'typecheck':
        return [[pnpm, 'exec', 'tsc', '--noEmit', '-p', config] for config in ['tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json']]
    if suite == 'build':
        return [[pnpm, 'build']]
    raise ValueError('unsupported executable suite')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build', 'seal'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-credential-runtime', action='store_true')
    args = parser.parse_args()
    if args.check_credential_runtime:
        importlib.import_module('detect_secrets')
        print(json.dumps({'credential_scan_python3': sys.executable, 'detect_secrets': 'imported'}))
        return 0
    require(args.suite and args.output, '--suite and --output required')
    require(Path.cwd().resolve() == ROOT, 'run in the candidate repo cwd')
    output = args.output.resolve()
    require(output.is_relative_to((CANDIDATE / 'out').resolve()), 'output must be candidate-local out')
    output.mkdir(parents=True, exist_ok=True)
    run = output / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex)
    run.mkdir()
    receipt = {'schema': 'skippercast.sp1501-acceptance/v1', 'spec': SPEC, 'card': CARD,
               'suite': args.suite, 'launcher_argv': sys.argv, 'cwd': str(ROOT),
               'runtime': {'python': sys.version, 'executable': sys.executable},
               'commands': [], 'verdict': 'UNVERIFIED'}
    try:
        stage_path = CANDIDATE / 'SOURCE-MANIFEST.json'
        stage = json.loads(stage_path.read_text())
        require(stage['schema'] == 'agentorange.source-manifest/v1', 'source manifest schema mismatch')
        require(Path(stage['repo']).resolve() == ROOT and stage['head'] == BASE, 'stage repo/head mismatch')
        require(stage['runtime']['credential_scan_python3'], 'credential runtime unspecified')
        require(git('rev-parse', BASE) == BASE, 'base missing')
        receipt['source_manifest_sha256'] = digest(stage_path)
        receipt['source_before'] = identity()
        # Original selected compatibility sources must remain byte-identical.
        for name in REGRESSION + DEPENDENCIES:
            reference = subprocess.run(['git', 'show', f'{BASE}:{name}'], cwd=ROOT, capture_output=True, check=True).stdout
            require(hashlib.sha256(reference).hexdigest() == digest(ROOT / name), f'read-only source changed: {name}')
        if args.suite == 'baseline':
            require(digest(ROOT / PRODUCT) == PRIMARY_HASH, 'baseline product is not unchanged')
        if args.suite == 'seal':
            require(not git('status', '--porcelain'), 'seal requires clean final HEAD')
            receipts = sorted((CANDIDATE / 'out').rglob('receipt.json'))
            completed = [json.loads(p.read_text()) for p in receipts]
            for suite in ['focused', 'regression', 'repository', 'typecheck', 'build']:
                require(any(r['suite'] == suite and r['verdict'] == 'SCOPED_GREEN_REVIEW_REQUIRED' and r['source_before'] == receipt['source_before'] for r in completed), f'missing exact-head green {suite}')
            baselines = [r for r in completed if r['suite'] == 'baseline' and r['verdict'] == 'BASELINE_GAP_REPRODUCED']
            require(baselines, 'missing original baseline gap receipt')
            for name in [TEST, 'tests/fixtures/sp1501_chop_completeness/calm.json']:
                require(any(r['source_before']['files'][name] == digest(ROOT / name) for r in baselines), f'baseline frozen bytes changed: {name}')
            frozen = {}
            for path in sorted((CANDIDATE / 'out').rglob('*')):
                if path.is_file() and not path.is_relative_to(run):
                    frozen[str(path.relative_to(CANDIDATE))] = digest(path)
            dump(run / 'frozen-output-manifest.json', {'spec': SPEC, 'identity': receipt['source_before'], 'files': frozen})
            receipt['frozen_output_manifest_sha256'] = digest(run / 'frozen-output-manifest.json')
            receipt['verdict'] = 'PACKET_FROZEN_REVIEW_REQUIRED'
        else:
            for index, argv in enumerate(commands(args.suite, stage)):
                start = time.monotonic()
                child_env = dict(os.environ, SP1501_SUITE=args.suite)
                version = subprocess.run([argv[0], '--version'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
                result = subprocess.run(argv, cwd=ROOT, env=child_env, capture_output=True, timeout=900, check=False)
                stdout = run / f'{index:02d}.stdout.txt'
                stderr = run / f'{index:02d}.stderr.txt'
                stdout.write_bytes(result.stdout)
                stderr.write_bytes(result.stderr)
                row = {'argv': argv, 'cwd': str(ROOT), 'exit': result.returncode,
                       'runtime_seconds': time.monotonic() - start,
                       'executable_resolved': str(Path(argv[0]).resolve()),
                       'runtime_version': version, 'environment_overlay': {'SP1501_SUITE': args.suite},
                       'stdout': stdout.name, 'stderr': stderr.name,
                       'stdout_sha256': digest(stdout), 'stderr_sha256': digest(stderr)}
                receipt['commands'].append(row)
                text = result.stdout.decode(errors='replace')
                if args.suite in {'baseline', 'focused', 'regression'}:
                    counts = tap_counts(text)
                    row['counts'] = counts
                    require(counts['skipped'] == counts['cancelled'] == counts['todo'] == 0, 'skips/cancellations/todos forbidden')
                    if args.suite == 'baseline':
                        require(result.returncode == 1 and counts == {'tests': 2, 'pass': 1, 'fail': 1, 'cancelled': 0, 'skipped': 0, 'todo': 0}, 'unexpected baseline counts/exit')
                        require(re.search(r'^not ok \d+ - primary regression$', text, re.M), 'primary did not fail')
                        require(re.search(r'^ok \d+ - healthy control$', text, re.M), 'healthy did not pass')
                        require('A1_MISSING_CHOP_PERIOD_MUST_USE_LIMITED_PATH' in text and "code: 'ERR_ASSERTION'" in text, 'baseline did not fail at named semantic assertion')
                    else:
                        expected = 7 if args.suite == 'focused' else 12
                        require(result.returncode == 0 and counts['tests'] == counts['pass'] == expected and counts['fail'] == 0, 'selected test count/exit mismatch')
                else:
                    require(result.returncode == 0, 'required child command failed')
                    if args.suite == 'repository' and index == 1:
                        match = re.search(r'Checked (\d+) text files:', text)
                        require(match is not None, 'repository scan count missing')
                        if match is None:
                            raise ValueError('repository scan count missing')
                        row['checked_text_files'] = int(match.group(1))
            receipt['source_after'] = identity()
            require(receipt['source_after'] == receipt['source_before'], 'source identity changed during acceptance')
            receipt['verdict'] = 'BASELINE_GAP_REPRODUCED' if args.suite == 'baseline' else 'SCOPED_GREEN_REVIEW_REQUIRED'
        receipt['exit'] = 0
    except Exception as exc:
        receipt['verdict'] = 'FAILED_UNVERIFIED'
        receipt['error'] = f'{type(exc).__name__}: {exc}'
        receipt['exit'] = 1
    dump(run / 'receipt.json', receipt)
    print(json.dumps({'verdict': receipt['verdict'], 'receipt': str(run / 'receipt.json'), 'receipt_sha256': digest(run / 'receipt.json'), 'exit': receipt['exit']}))
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())
