"""Portable, offline SP80 acceptance; historical expected-red is never final green."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

BASE = 'a1f648632e64561d82dcbeb20d9bda19f812560a'
ORIGINAL = '3ca536f2e4763ee5591e5f3c7a66a096ddb5db104d38e148230a506ed89c02bc'
REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
PRODUCT = 'packages/coast/src/coast3d/preferences.ts'
TEST = 'tests/test_sp80_home_geography.mjs'
FIXTURE = 'tests/fixtures/sp80_home_geography/cases.json'
REGRESSION = ['tests/test_home_port.mjs', 'tests/test_ports.mjs']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def closure(selectors):
    """Inventory local literal imports (including dynamic imports) before execution.

    Bare packages resolve via the already staged node_modules. Type-only imports
    are harmless but included where present. esbuild's existing synthetic stdin
    entry and server/coast-pages dynamic test import are explicitly inventoried.
    This inventory is not a general JavaScript sandbox or security parser.
    """
    pending = list(selectors)
    if 'tests/test_ports.mjs' in selectors:
        pending += ['web/landing/PortInput.tsx', 'web/app/FirstRun.tsx']
    seen, packages = {}, set()
    imports = re.compile(r'''(?:\bfrom[ \t]+|\bimport[ \t]*\([ \t]*|\bimport[ \t]+)['"]([@./a-zA-Z0-9_-]+)['"]''')
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        path = REPO / name
        require(path.is_file(), 'Missing import/selector: ' + name)
        require(path.resolve().is_relative_to(REPO), 'Local source escaped candidate')
        seen[name] = digest(path)
        text = path.read_text()
        for spec in imports.findall(text):
            if spec.startswith('.'):
                child = ((REPO if name == 'tests/test_ports.mjs' and spec.startswith('./web/') else path.parent) / spec).resolve()
                require(child.is_relative_to(REPO), 'Import escaped candidate: ' + spec)
                # CSS imported by TSX is consumed by esbuild, not Node.
                pending.append(child.relative_to(REPO).as_posix())
            elif not spec.startswith('node:'):
                package = '/'.join(spec.split('/')[:2]) if spec.startswith('@') else spec.split('/')[0]
                require((REPO / 'node_modules' / package / 'package.json').is_file(), 'Unavailable package: ' + package)
                packages.add(package)
    return {'local_sha256': dict(sorted(seen.items())), 'installed_packages': sorted(packages),
            'child_process_review': 'Original test_ports uses installed esbuild for synthetic TSX bundle only; no other child command in selectors. Original import closure inspected before execution.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    parent = args.output.resolve()
    require(parent.is_relative_to(ROOT / 'out'), 'Output must be under candidate out/')
    parent.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix=args.suite + '-', dir=parent))
    tmp = out / 'tmp'
    tmp.mkdir()
    receipt = {'schema_version': 1, 'phase': args.suite, 'started_at': datetime.now(timezone.utc).isoformat(),
               'wrapper_argv': [sys.executable, *sys.argv], 'wrapper_cwd': str(Path.cwd()),
               'staging_base': BASE, 'author_runtime': {'model': 'gpt-6.1-sol', 'provider': 'openai-codex', 'run_id': 1558},
               'children': [], 'wrapper_exit': 1, 'status': 'UNVERIFIED'}
    try:
        manifest_path = ROOT / 'SOURCE-MANIFEST.json'
        manifest = json.loads(manifest_path.read_text())
        require(manifest.get('head') == BASE, 'Staging base mismatch')
        require(subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=REPO).returncode == 0, 'HEAD does not descend from staging base')
        receipt['source_manifest_sha256'] = digest(manifest_path)
        receipt['actual_head'] = git('rev-parse', 'HEAD')
        receipt['git_status'] = git('status', '--porcelain')
        receipt['source_sha256'] = {PRODUCT: digest(REPO / PRODUCT)}
        receipt['test_fixture_sha256'] = {name: digest(REPO / name) for name in [TEST, FIXTURE, *REGRESSION]}
        receipt['launcher_sha256'] = digest(__file__)
        for name in REGRESSION:
            original = subprocess.check_output(['git', 'show', BASE + ':' + name], cwd=REPO)
            require(hashlib.sha256(original).hexdigest() == digest(REPO / name), 'Original selector changed: ' + name)
        if args.suite == 'baseline':
            require(receipt['source_sha256'][PRODUCT] == ORIGINAL, 'Baseline product was edited')
        else:
            baselines = []
            for path in (ROOT / 'out').rglob('receipt.json'):
                saved = json.loads(path.read_text())
                if saved.get('status') == 'BASELINE_DEFECT_REPRODUCED' and saved.get('test_fixture_sha256') == receipt['test_fixture_sha256']:
                    baselines.append(str(path))
            require(bool(baselines), 'Missing honest baseline for these exact tests/fixtures')
            receipt['historical_baseline_receipts'] = baselines
        env = dict(os.environ, TMPDIR=str(tmp), PYTHONDONTWRITEBYTECODE='1')
        # Do not modify interpreter search-path environment variables.
        node = shutil.which('node')
        require(bool(node), 'Qualified installed Node unavailable; no fallback')
        selectors = REGRESSION if args.suite == 'regression' else [TEST]
        receipt['import_closure'] = closure(selectors)
        env['SP80_GUARD_ONLY'] = '1' if args.suite == 'regression' else '0'
        env['SP80_BASELINE'] = '1' if args.suite == 'baseline' else '0'
        if args.suite == 'repository':
            runtime = Path(manifest['runtime']['credential_scan_python3'])
            require(runtime.is_file() and os.access(runtime, os.X_OK), 'Manifest scan interpreter unavailable')
            commands = [[str(runtime), str(REPO / 'scripts/check_repository.py')]]
            version_cmd = [str(runtime), '--version']
        else:
            commands = [[node, '--experimental-strip-types', '--import', './' + TEST, '--test', '--test-reporter=tap', name] if args.suite == 'regression'
                        else [node, '--experimental-strip-types', '--test', '--test-reporter=tap', TEST] for name in selectors]
            version_cmd = [node, '--version']
        version = subprocess.run(version_cmd, cwd=REPO, env=env, text=True, capture_output=True)
        require(version.returncode == 0, 'Runtime version check failed')
        receipt['runtime'] = {'argv': version_cmd, 'stdout': version.stdout, 'stderr': version.stderr, 'exit': version.returncode}
        for i, command in enumerate(commands):
            child = subprocess.run(command, cwd=REPO, env=env, text=True, capture_output=True)
            stdout, stderr = out / f'{i}.stdout', out / f'{i}.stderr'
            stdout.write_text(child.stdout)
            stderr.write_text(child.stderr)
            counts = {key: int(re.findall(r'^# ' + key + r' (\d+)$', child.stdout, re.M)[-1])
                      for key in ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'] if re.findall(r'^# ' + key + r' (\d+)$', child.stdout, re.M)}
            item = {'argv': command, 'cwd': str(REPO), 'child_exit': child.returncode, 'counts': counts,
                    'stdout': str(stdout), 'stdout_sha256': digest(stdout), 'stderr': str(stderr), 'stderr_sha256': digest(stderr)}
            receipt['children'].append(item)
            print(child.stdout, end='')
            print(child.stderr, end='', file=sys.stderr)
            if args.suite == 'repository':
                match = re.search(r'Checked (\d+) text files:', child.stdout)
                if child.returncode != 0 or match is None:
                    raise RuntimeError('Repository scanner failed or did not execute')
                item['files_checked'] = int(match.group(1))
            else:
                require(all(key in counts for key in ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo']), 'Missing TAP summary')
                require(counts['cancelled'] == counts['skipped'] == counts['todo'] == 0, 'Unexpected cancellation/skip/todo')
                if args.suite == 'baseline':
                    require(child.returncode == 1 and counts['tests'] == 2 and counts['pass'] == counts['fail'] == 1, 'Wrong baseline counts/exit')
                    require('not ok 1 - A4 primary explicit-region preserves geography' in child.stdout and 'ok 2 - A4 healthy bare-address restores home' in child.stdout, 'Wrong failing/control case')
                    require('A4_REGION_MUST_NOT_GAIN_HOME_PLACE' in child.stdout and "code: 'ERR_ASSERTION'" in child.stdout and 'SP80_OBSERVATION {"place":"morro"}' in child.stdout, 'Not the named semantic defect')
                    item['errors'] = 0
                else:
                    require(child.returncode == 0 and counts['tests'] == counts['pass'] and counts['pass'] > 0 and counts['fail'] == 0, 'Suite failed or unexecuted')
                    if args.suite == 'focused':
                        fixture = json.loads((REPO / FIXTURE).read_text())
                        expected = ['A4 primary explicit-region preserves geography', 'A4 healthy bare-address restores home',
                                    'A2 explicit empty profile wins presence-based rule on bare URL', 'A2 bare query/hash preserved with saved place and profile']
                        expected += [f"A1/A2 {row['id']} {profile}" for row in fixture['locations'] for profile in ['explicit-profile', 'saved-profile']]
                        expected += [f"A3 reset {row['id']} restores exactly home" for row in [*fixture['locations'], {'id': 'bare'}]]
                        actual = re.findall(r'^ok \d+ - (.+)$', child.stdout, re.M)
                        require(sorted(actual) == sorted(expected) and counts['tests'] == len(expected), 'Named focused assertions missing or unexpected')
                    item['errors'] = 0
        receipt['status'] = 'BASELINE_DEFECT_REPRODUCED' if args.suite == 'baseline' else 'GREEN_REVIEW_REQUIRED'
        receipt['wrapper_exit'] = 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        receipt['error'] = str(exc)
        print('SP80 acceptance refused:', exc, file=sys.stderr)
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('RECEIPT', out / 'receipt.json')
    return receipt['wrapper_exit']


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
