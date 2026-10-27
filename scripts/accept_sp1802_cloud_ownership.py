#!/usr/bin/env python3
"""Offline, fail-closed SP1802 acceptance; each invocation retains unique receipts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
PRIMARY_SHA = '40920ae0fd169ea1b1ebd8bbd400e5139e6436a90d5f6cfe67704f8037a49906'
TEST = 'tests/test_sp1802_cloud_ownership.mjs'
FIXTURE = 'tests/fixtures/sp1802_cloud_ownership/index.json'
PRIMARY = '^primary regression A1: retire A before adopting B$'
HEALTHY = '^Healthy controller draws one cloud overlay and clears all timers on destroy$'
SPEC = 'SP-18-v1/SP1802-CLOUD-OWNERSHIP/amendment-1'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True)
    return result.stdout


def identity():
    names = ['web/map/clouds.ts', TEST, FIXTURE, 'scripts/accept_sp1802_cloud_ownership.py',
             'tests/test_clouds_layer.mjs', 'docs/engineering/sp1802_cloud_ownership.md']
    return {'head': git('rev-parse', 'HEAD').decode().strip(),
            'status': git('status', '--porcelain').decode(),
            'diff_sha256': digest(git('diff', BASE)),
            'files': {name: digest((ROOT / name).read_bytes()) for name in names if (ROOT / name).is_file()}}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.is_relative_to(ROOT.parent / 'out'), 'output must be below candidate out, not fixtures or repository')
    output.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix=args.phase + '-', dir=output))
    receipt = {'spec': SPEC, 'phase': args.phase, 'cwd': str(ROOT), 'run': str(run),
               'started_at': datetime.now(timezone.utc).isoformat(), 'children': [], 'status': 'UNVERIFIED'}

    def child(label, argv, tests=None):
        env = os.environ.copy()
        temporary = run / 'tmp'
        temporary.mkdir(exist_ok=True)
        env['TMPDIR'] = str(temporary)
        started = time.monotonic()
        result = subprocess.run([str(x) for x in argv], cwd=ROOT, env=env, capture_output=True, timeout=600)
        row = {'label': label, 'argv': [str(x) for x in argv], 'cwd': str(ROOT),
               'elapsed_seconds': time.monotonic() - started, 'exit': result.returncode,
               'runtime_executable': str(argv[0]), 'counts': None}
        for stream in ['stdout', 'stderr']:
            raw = getattr(result, stream)
            path = run / (label + '.' + stream + '.txt')
            path.write_bytes(raw)
            row[stream] = {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}
        text = result.stdout.decode(errors='replace')
        if tests is not None:
            counts = {}
            for name in ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo']:
                matches = re.findall(r'^# ' + name + r' (\d+)\s*$', text, re.MULTILINE)
                counts[name] = int(matches[-1]) if matches else None
            row['counts'] = counts
        elif label == 'repository':
            match = re.search(r'Checked (\d+) text files:', text)
            row['counts'] = {'text_files': int(match.group(1)) if match else None}
        else:
            row['counts'] = {'command_invocations': 1}
        receipt['children'].append(row)
        print(json.dumps(row), flush=True)
        if tests is not None:
            require(row['counts']['tests'] == tests, label + ': wrong/missing test count')
            require(all(row['counts'][name] == 0 for name in ['cancelled', 'skipped', 'todo']), label + ': cancelled/skipped/todo')
        return row, text, result.stderr.decode(errors='replace')

    def green(label, argv, tests=None):
        row, text, _ = child(label, argv, tests)
        require(row['exit'] == 0, label + ': nonzero child exit')
        if tests is not None:
            require(row['counts']['pass'] == tests and row['counts']['fail'] == 0, label + ': tests not all green')
        return row, text

    try:
        manifest_path = ROOT.parent / 'SOURCE-MANIFEST.json'
        manifest = json.loads(manifest_path.read_text())
        require(manifest.get('schema') == 'agentorange.source-manifest/v1', 'source manifest schema mismatch')
        require(Path(manifest['repo']).resolve() == ROOT and manifest['head'] == BASE, 'source manifest repo/base mismatch')
        require(manifest.get('card') == 'SP1802-CLOUD-OWNERSHIP', 'wrong staged card')
        scanner = manifest.get('runtime', {}).get('credential_scan_python3')
        require(scanner and Path(scanner).is_file(), 'missing explicitly staged scanner runtime')
        receipt['source_manifest_sha256'] = digest(manifest_path.read_bytes())
        receipt['source_before'] = identity()
        receipt['launcher_runtime'] = {'executable': sys.executable, 'version': sys.version}
        node = shutil.which('node')
        require(node is not None, 'installed Node missing; no install permitted')
        _, version = green('node-runtime', [node, '--version'])
        receipt['node_version'] = version.strip()
        require(tuple(int(x) for x in version.strip().lstrip('v').split('.')[:2]) >= (22, 18), 'unsupported Node runtime')
        guard = (ROOT / TEST).as_uri() + '?guard'
        command = [node, '--import', guard, '--test', '--test-reporter=tap']
        if args.phase == 'baseline':
            require(receipt['source_before']['head'] == BASE, 'baseline not at pinned head')
            require(receipt['source_before']['files']['web/map/clouds.ts'] == PRIMARY_SHA, 'baseline product source changed')
            red, text, errors = child('primary-red', command + ['--test-name-pattern=' + PRIMARY, TEST], 1)
            require(red['exit'] == 1 and red['counts']['fail'] == 1 and red['counts']['pass'] == 0, 'baseline must have exactly one failing primary test')
            require('SP1802_A1_RETIRED_OWNER_NOT_CLEARED' in text and 'ERR_ASSERTION' in text, 'missing exact A1 semantic failure')
            require('uncaughtException' not in text + errors and 'unhandledRejection' not in text + errors, 'baseline setup/unhandled failure')
            green('healthy-baseline', command + ['--test-name-pattern=' + HEALTHY, TEST], 1)
            receipt['status'] = 'BASELINE_GAP_REPRODUCED'
        elif args.phase == 'focused':
            green('primary-green', command + ['--test-name-pattern=' + PRIMARY, TEST], 1)
            green('healthy-green', command + ['--test-name-pattern=' + HEALTHY, TEST], 1)
            green('focused-all', command + [TEST], 6)
        elif args.phase == 'regression':
            green('clouds-compatibility', command + ['tests/test_clouds_layer.mjs'], 10)
        elif args.phase == 'repository':
            row, _ = green('repository', [scanner, 'scripts/check_repository.py'])
            require(row['counts']['text_files'] and row['counts']['text_files'] > 0, 'missing positive scanner count')
        elif args.phase == 'typecheck':
            pnpm = shutil.which('pnpm')
            require(pnpm is not None, 'installed pnpm missing')
            for index, project in enumerate(['tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json']):
                green('tsc-' + str(index), [pnpm, 'exec', 'tsc', '--noEmit', '--project', project])
        elif args.phase == 'build':
            pnpm = shutil.which('pnpm')
            require(pnpm is not None, 'installed pnpm missing')
            green('build', [pnpm, 'build'])
        receipt['source_after'] = identity()
        require(receipt['source_before'] == receipt['source_after'], 'source identity changed during acceptance')
        if args.phase != 'baseline':
            receipt['status'] = 'SCOPED_PASS_REVIEW_REQUIRED'
        return 0
    except Exception as exc:
        receipt['status'] = 'ERROR'
        receipt['error'] = str(exc)
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        receipt_path = run / 'receipt.json'
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'status': receipt['status'], 'receipt': str(receipt_path), 'sha256': digest(receipt_path.read_bytes())}))


if __name__ == '__main__':
    raise SystemExit(main())
