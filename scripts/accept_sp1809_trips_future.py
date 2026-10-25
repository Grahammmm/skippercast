#!/usr/bin/env python3
"""Offline SP-18-v1 acceptance; receipts are evidence, never release approval."""
import argparse
import datetime as dt
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

ROOT = Path(__file__).resolve().parents[1]
BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
PRIMARY = 'server/advisor/tools/get_trips.ts'
TEST = 'tests/test_sp1809_trips_future.mjs'
FIXTURE = 'tests/fixtures/sp1809_trips_future'
BASE_PRIMARY = '14dbbbe3238744fdb1aae5ab02bdb62a93fa79b0e894df60a8f6b40cbd2b30ee'
PINS = {
    'tests/test_advisor_tools.mjs': '8f926981e36d3c456764e3486fab5550ad86f0ce86a00961cb7dabc5d881f285',
    'tests/test_advisor_skippers.mjs': 'f9aa47c4ba2a9c8c1ceb87be31c43c2398d53aa7faab4905706a961405210ab5',
    'scripts/check_repository.py': 'cf39ee4dab44893fae58d4553c8a159942c5674f5ce33f22ca9c441d0a74dec8',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    p = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=False)
    if p.returncode:
        raise RuntimeError(f'git {args} failed with exit {p.returncode}')
    return p.stdout


def identity():
    paths = [PRIMARY, TEST, 'scripts/accept_sp1809_trips_future.py',
             'docs/engineering/sp1809_trips_future.md', *PINS]
    paths += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / FIXTURE).rglob('*')) if p.is_file()]
    return {
        'head': git('rev-parse', 'HEAD').decode().strip(),
        'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
        'status': git('status', '--porcelain').decode(),
        'diff_sha256': digest(git('diff', '--binary', BASE)),
        'files': {p: digest((ROOT / p).read_bytes()) for p in paths if (ROOT / p).is_file()},
    }


def counts(text):
    out = {}
    for key in ('tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'):
        hits = re.findall(rf'^# {key} (\d+)\s*$', text, re.M)
        if len(hits) != 1:
            raise RuntimeError(f'Missing or ambiguous TAP summary: {key}')
        out[key] = int(hits[0])
    return out


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    require(not output.is_relative_to(ROOT), 'Evidence must be outside repo and fixture inputs')
    run = output / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': 'sp1809.acceptance/v1', 'spec': 'SP-18-v1', 'card': 'SP1809-TRIPS-FUTURE',
               'phase': args.phase, 'cwd': str(ROOT), 'commands': [], 'status': 'UNVERIFIED',
               'author_runtime': {'model': 'gpt-6.1-sol', 'provider': 'openai-codex',
                                  'scope': 'Authored material, not a claim about the runner or independent review'}}

    def child(label, argv, *, selection=None, tap=False):
        env = dict(os.environ)
        # Do not inherit credentials into offline fixtures/build tools.
        for key in list(env):
            if re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', key, re.I):
                env.pop(key)
        env.pop('SP1809_CASE', None)
        if selection:
            env['SP1809_CASE'] = selection
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        start = time.monotonic()
        timed_out = False
        try:
            p = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, timeout=600, check=False)
            stdout, stderr, exit_code = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired as e:
            stdout, stderr, exit_code = e.stdout or b'', e.stderr or b'', None
            timed_out = True
        except OSError as e:
            stdout, stderr, exit_code = b'', str(e).encode(), None
        record = {'label': label, 'argv': argv, 'cwd': str(ROOT), 'started_utc': started,
                  'elapsed_seconds': time.monotonic() - start, 'exit': exit_code, 'timed_out': timed_out,
                  'selection': selection, 'stdout': f'{label}.stdout', 'stderr': f'{label}.stderr',
                  'stdout_sha256': digest(stdout), 'stderr_sha256': digest(stderr)}
        (run / record['stdout']).write_bytes(stdout)
        (run / record['stderr']).write_bytes(stderr)
        receipt['commands'].append(record)
        if tap:
            record['counts'] = counts(stdout.decode(errors='replace'))
        print(f'{label}: exit={exit_code} counts={record.get("counts", "not a test runner")}', flush=True)
        return record, stdout.decode(errors='replace')

    def positive(label, argv, *, selection=None, expected=None):
        r, text = child(label, argv, selection=selection, tap=expected is not None)
        require(r['exit'] == 0, f'{label}: unexpected child exit {r["exit"]}; see raw output')
        if expected is not None:
            c = r['counts']
            n = c['tests'] if expected == 'positive' else expected
            require(n > 0 and c == {'tests': n, 'pass': n, 'fail': 0, 'cancelled': 0, 'skipped': 0, 'todo': 0},
                    f'{label}: counts differ from frozen contract: {c}')
        return r, text

    try:
        manifest_path = ROOT.parent / 'SOURCE-MANIFEST.json'
        manifest = json.loads(manifest_path.read_text())
        require(manifest.get('schema') == 'agentorange.source-manifest/v1', 'Invalid staging manifest schema')
        require(manifest.get('head') == BASE and Path(manifest['repo']).resolve() == ROOT, 'Staged repo/head mismatch')
        require(manifest.get('card') == 'SP1809-TRIPS-FUTURE', 'Staged card mismatch')
        require(bool(manifest.get('runtime', {}).get('credential_scan_python3')), 'Missing credential_scan_python3')
        receipt['staging_manifest_sha256'] = digest(manifest_path.read_bytes())
        for path, expected in PINS.items():
            require(digest((ROOT / path).read_bytes()) == expected, f'Unchanged compatibility pin mismatch: {path}')
        git('merge-base', '--is-ancestor', BASE, 'HEAD')
        receipt['source_before'] = identity()
        node = shutil.which('node')
        pnpm = manifest['runtime'].get('pnpm') or shutil.which('pnpm')
        require(node is not None, 'Installed Node required; no install or substitute')
        require(pnpm is not None, 'Installed pnpm required; no install or substitute')
        for label, argv in [('node-runtime', [node, '--version']), ('python-runtime', [sys.executable, '--version']),
                            ('pnpm-runtime', [pnpm, '--version'])]:
            positive(label, argv)
        receipt['runtime'] = {'node': node, 'python': sys.executable, 'pnpm': pnpm,
                              'credential_scan_python3': manifest['runtime']['credential_scan_python3']}
        node_test = [node, '--import', './' + FIXTURE + '/offline.mjs', '--test', '--test-reporter=tap']
        if args.phase == 'baseline':
            require(receipt['source_before']['files'][PRIMARY] == BASE_PRIMARY, 'Baseline requires unchanged product source')
            require(receipt['source_before']['head'] == BASE, 'Baseline requires staged base HEAD')
            positive('healthy-control', [*node_test, TEST], selection='control', expected=1)
            r, text = child('primary-regression', [*node_test, TEST], selection='primary', tap=True)
            require(r['exit'] == 1, 'Baseline primary must preserve child exit 1')
            require(r['counts'] == {'tests': 1, 'pass': 0, 'fail': 1, 'cancelled': 0, 'skipped': 0, 'todo': 0}, 'Not the exact isolated baseline failure')
            require('SP1809_A1_FUTURE_INVARIANCE' in text and 'ERR_ASSERTION' in text,
                    'Baseline must fail the named semantic assertion, not setup/import')
            require('not ok 1 - SP1809 A1 primary regression:' in text, 'Wrong failing test ID')
            receipt['status'] = 'BASELINE_GAP_REPRODUCED'
        elif args.phase == 'focused':
            positive('healthy-control', [*node_test, TEST], selection='control', expected=1)
            positive('primary-regression', [*node_test, TEST], selection='primary', expected=1)
            positive('all-focused', [*node_test, TEST], expected=9)
        elif args.phase == 'regression':
            # Each unchanged suite runs separately, with positive real counts and zero skips.
            for label, path in [('advisor-tools', 'tests/test_advisor_tools.mjs'),
                                ('advisor-skippers', 'tests/test_advisor_skippers.mjs')]:
                positive(label, [*node_test, path], expected='positive')
        elif args.phase == 'repository':
            _, text = positive('repository', [manifest['runtime']['credential_scan_python3'], 'scripts/check_repository.py'])
            m = re.search(r'^Checked (\d+) text files:', text, re.M)
            require(m is not None and int(m[1]) > 0, 'Missing positive repository check count')
            receipt['checked_text_files'] = int(m[1])
        elif args.phase == 'typecheck':
            for label, project in [('root', 'tsconfig.json'), ('web', 'web/tsconfig.json'), ('coast', 'packages/coast/tsconfig.json')]:
                positive('typecheck-' + label, [pnpm, 'exec', 'tsc', '--noEmit', '--project', project])
            receipt['checked_projects'] = 3
        elif args.phase == 'build':
            _, text = positive('build', [pnpm, 'build'])
            require('Built shared regional Worker and public assets' in text, 'Missing build completion marker')
            receipt['completed_builds'] = 1
        receipt['source_after'] = identity()
        require(receipt['source_after'] == receipt['source_before'], 'Source changed during acceptance')
        if receipt['status'] == 'UNVERIFIED':
            receipt['status'] = 'SCOPED_PASS_REVIEW_REQUIRED'
        result = 0
    except Exception as e:
        receipt['status'] = 'ERROR'
        receipt['error'] = f'{type(e).__name__}: {e}'
        print(receipt['error'], file=sys.stderr)
        result = 1
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'{receipt["status"]}: {run / "receipt.json"}')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
