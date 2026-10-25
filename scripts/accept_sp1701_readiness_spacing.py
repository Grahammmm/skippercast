"""SP-17-v1 offline acceptance runner. Each invocation retains a unique receipt.

The regression child is a file-based clone-anchored bootstrap of unittest's
module entry point; no installation, environment search-path override or shell.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
BASE_PRODUCT = '343cf14bd9fcaa17d69aadb5da4382a3215b4ffc858d1072e42a6132015b94d7'
PRODUCT = 'src/skippercast/platform/readiness.py'
TEST = 'tests.unit.test_sp1701_readiness_spacing'
OWNED = [PRODUCT, 'tests/unit/test_sp1701_readiness_spacing.py',
         'scripts/accept_sp1701_readiness_spacing.py',
         'docs/engineering/sp1701_readiness_spacing.md']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def identity():
    paths = [ROOT / name for name in OWNED]
    paths += sorted((ROOT / 'tests/fixtures/sp1701_readiness_spacing').rglob('*'))
    return {'head': git('rev-parse', 'HEAD').decode().strip(), 'base': BASE,
            'status': git('status', '--porcelain').decode(),
            'diff_sha256': sha(git('diff', '--binary', BASE)),
            'files': {p.relative_to(ROOT).as_posix(): sha(p.read_bytes())
                      for p in paths if p.is_file()}}


def unittest_child(selector):
    # This fresh child only: no persistent hooks or monkeypatches in peer discovery.
    def offline(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen',
                     'os.system', 'sqlite3.connect'}:
            raise RuntimeError('SP1701 offline child forbids external/model/process/live-store access')
    sys.addaudithook(offline)
    sys.path.insert(0, str(ROOT / 'src'))
    os.environ['SKIPPERCAST_ROOT'] = str(ROOT)
    sys.argv = ['unittest', '-v', selector]
    runpy.run_module('unittest', run_name='__main__', alter_sys=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('baseline', 'focused', 'regression', 'repository'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--unittest-child')
    args = parser.parse_args()
    if args.unittest_child:
        unittest_child(args.unittest_child)
        return 2
    if not args.phase or args.output is None:
        parser.error('--phase and --output are required')
    output = args.output.resolve() / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'spec': 'SP-17-v1', 'card': 'SP1701-READINESS-SPACING',
               'phase': args.phase, 'cwd': str(ROOT), 'runtime': sys.version,
               'launcher_argv': sys.argv, 'children': [], 'passed': False}
    errors = []
    try:
        manifest = json.loads((ROOT.parent / 'SOURCE-MANIFEST.json').read_text())
        if (manifest.get('schema') != 'agentorange.source-manifest/v1'
                or Path(manifest['repo']).resolve() != ROOT
                or manifest.get('head') != BASE
                or manifest.get('card') != 'SP1701-READINESS-SPACING'
                or not manifest.get('runtime', {}).get('credential_scan_python3')):
            raise RuntimeError('Standard source-manifest identity/runtime mismatch')
        git('merge-base', '--is-ancestor', BASE, 'HEAD')
        receipt['source_before'] = identity()
        receipt['source_manifest_sha256'] = sha((ROOT.parent / 'SOURCE-MANIFEST.json').read_bytes())
        if args.phase == 'baseline' and sha((ROOT / PRODUCT).read_bytes()) != BASE_PRODUCT:
            raise RuntimeError('Baseline requires unchanged pinned product source')
        if args.phase == 'baseline':
            commands = [('primary-regression', ['python3', '-m', 'unittest', '-v', TEST + '.BaselineTests.test_primary_regression'], 'red'),
                        ('healthy-control', ['python3', '-m', 'unittest', '-v', TEST + '.BaselineTests.test_healthy_control'], 'green')]
        elif args.phase == 'focused':
            commands = [('focused', ['python3', '-m', 'unittest', '-v', TEST], 'green')]
        elif args.phase == 'regression':
            commands = [('original-atlas-readiness', ['python3', str(Path(__file__).resolve()), '--unittest-child', 'tests.contract.test_atlas_readiness'], 'green')]
        else:
            commands = [('repository', [manifest['runtime']['credential_scan_python3'], str(ROOT / 'scripts/check_repository.py')], 'scan')]
        for label, argv, expected in commands:
            env = dict(os.environ)
            work = output / label
            work.mkdir()
            env['SP1701_TEST_OUTPUT'] = str(work / 'synthetic-roots')
            env['TMPDIR'] = str(work)
            child = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, check=False)
            stdout, stderr = work / 'stdout.txt', work / 'stderr.txt'
            stdout.write_bytes(child.stdout)
            stderr.write_bytes(child.stderr)
            text = (child.stdout + child.stderr).decode(errors='replace')
            match = re.search(r'Ran (\d+) tests? in ', text)
            count = int(match.group(1)) if match else None
            failure = re.search(r'^FAILED \(([^\n]+)\)', text, re.M)
            failures = dict(re.findall(r'(\w+)=(\d+)', failure.group(1))) if failure else {}
            skipped = int(failures.get('skipped', 0))
            ok = False
            if expected == 'red':
                ok = (child.returncode == 1 and count == 1 and failures == {'failures': '1'}
                      and 'FAIL: test_primary_regression' in text
                      and 'AssertionError:' in text
                      and 'SP1701_A1_ZERO_SPACING_MUST_NOT_BECOME_FINE_LEAD' in text
                      and 'ERROR:' not in text)
            elif expected == 'green':
                expected_count = 1 if args.phase == 'baseline' else (2 if args.phase == 'regression' else 8)
                ok = child.returncode == 0 and count == expected_count and bool(re.search(r'^OK\s*$', text, re.M)) and not failure and 'skipped' not in text
            elif expected == 'scan':
                scan = re.search(r'Checked (\d+) text files:', text)
                count = int(scan.group(1)) if scan else None
                ok = child.returncode == 0 and count is not None and count > 0
            row = {'label': label, 'argv': argv, 'cwd': str(ROOT), 'exit': child.returncode,
                   'count': count, 'skips': skipped, 'expected': expected, 'contract_passed': ok,
                   'stdout': str(stdout), 'stdout_sha256': sha(child.stdout),
                   'stderr': str(stderr), 'stderr_sha256': sha(child.stderr)}
            receipt['children'].append(row)
            print(json.dumps(row, sort_keys=True), flush=True)
            if not ok:
                errors.append(label + ': diagnostic/acceptance contract not met')
                break
        receipt['source_after'] = identity()
        if receipt['source_before'] != receipt['source_after']:
            errors.append('Source identity changed during acceptance')
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        errors.append(type(error).__name__ + ': ' + str(error))
    receipt['errors'] = errors
    receipt['passed'] = bool(receipt['children']) and not errors
    receipt_path = output / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(receipt_path), 'sha256': sha(receipt_path.read_bytes()),
                      'passed': receipt['passed'], 'errors': errors}), flush=True)
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
