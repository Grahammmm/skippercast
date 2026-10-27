"""SP-18-v1 offline acceptance; every invocation retains a new evidence child.

The child bootstrap is a script-file equivalent of unittest module execution:
anchor candidate imports, install safety before product imports, run real suites.
No shell, package installation, source copies or live defaults are used.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
PRIMARY = 'src/skippercast/pipeline/regulation_review.py'
PRIMARY_SHA = 'c6dd2e53f85a43d3e85bf9b74429097069d01e8ff1f3bc23de8d239b20f5a1b6'
TEST = 'tests/unit/test_sp1808_reg_scope_status.py'
PREFIX = 'tests.unit.test_sp1808_reg_scope_status'
PAIR = [PREFIX + '.BaselineTests.test_primary_regression', PREFIX + '.BaselineTests.test_healthy_control']
OLD = ['tests.contract.test_pipeline_regulation_review', 'tests.contract.test_pipeline_regulations']
MARKER = 'SP1808_RESULT='


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True)
    return result.stdout.decode().strip()


def source_identity():
    paths = [PRIMARY, TEST, 'scripts/accept_sp1808_reg_scope_status.py',
             'src/skippercast/pipeline/regulations.py', 'scripts/check_repository.py',
             'tests/contract/test_pipeline_regulation_review.py',
             'tests/contract/test_pipeline_regulations.py']
    paths += [p.relative_to(ROOT).as_posix() for p in sorted(
        (ROOT / 'tests/fixtures/sp1808_reg_scope_status').rglob('*')) if p.is_file()]
    note = 'docs/engineering/sp1808_reg_scope_status.md'
    if (ROOT / note).exists():
        paths.append(note)
    return {'head': git('rev-parse', 'HEAD'), 'status': git('status', '--porcelain'),
            'base': BASE, 'files_sha256': {p: digest((ROOT / p).read_bytes()) for p in paths}}


def child(selectors):
    """Fresh-process guards only; ordinary test discovery never adds audit hooks."""
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
    # No writes, subprocesses, sockets or reads of live/default/private stores.
    # Runtime libraries are read-only; the only data tree is the staged clone.
    allowed_runtime = [Path('/usr'), Path('/lib'), Path(sys.prefix).resolve(),
                       Path(sys.base_prefix).resolve(), Path('/etc/ssl')]
    violations = []

    def refuse(event):
        violations.append(event)
        raise RuntimeError('SP1808 child safety boundary: ' + event)

    def audit(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.bind',
                     'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
            refuse(event)
        if event in {'os.remove', 'os.rmdir', 'os.rename', 'os.mkdir', 'os.link', 'os.symlink'}:
            refuse(event)
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                refuse('file-write')
            if path.is_relative_to(ROOT / 'var'):
                refuse('live-store-read')
            if not (path.is_relative_to(ROOT) or any(path.is_relative_to(p) for p in allowed_runtime)
                    or path in {Path('/etc/localtime'), Path('/dev/null')}):
                refuse('non-fixture-read')

    sys.addaudithook(audit)
    from tests.unit.test_sp1808_reg_scope_status import OfflineSandbox
    with OfflineSandbox(block_gate=all(s.startswith(PREFIX) for s in selectors)):
        suite = unittest.defaultTestLoader.loadTestsFromNames(selectors)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {'tests': result.testsRun, 'failures': [t.id() for t, _ in result.failures],
               'errors': [t.id() for t, _ in result.errors], 'skips': len(result.skipped),
               'expected_failures': len(result.expectedFailures),
               'unexpected_successes': len(result.unexpectedSuccesses),
               'safety_violations': violations, 'python': sys.version,
               'executable': sys.executable, 'selectors': selectors}
    print(MARKER + json.dumps(summary, sort_keys=True))
    return 0 if result.wasSuccessful() and not violations else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['baseline', 'focused', 'regression', 'repository'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child', nargs='+')
    args = parser.parse_args()
    if args.child:
        return child(args.child)
    if args.phase is None or args.output is None:
        parser.error('--phase and --output are required')
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('evidence must be outside the repository and fixture inputs')
    output.mkdir(parents=True, exist_ok=True)
    run = output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex)
    run.mkdir(exist_ok=False)
    receipt = {'schema': 'sp1808.acceptance/v1', 'spec': 'SP-18-v1',
               'card': 'SP1808-REG-SCOPE-STATUS', 'phase': args.phase,
               'started_at': datetime.now(timezone.utc).isoformat(), 'commands': [],
               'status': 'INCOMPLETE', 'launcher_runtime': sys.version}

    def save():
        (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def invoke(label, argv, *, tests=False, expected_exit=0):
        start = time.monotonic()
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=600)
        stdout, stderr = run / (label + '.stdout'), run / (label + '.stderr')
        stdout.write_bytes(result.stdout)
        stderr.write_bytes(result.stderr)
        row = {'label': label, 'argv': [str(v) for v in argv], 'cwd': str(ROOT),
               'exit': result.returncode, 'expected_exit': expected_exit,
               'elapsed_seconds': time.monotonic() - start,
               'stdout': str(stdout), 'stderr': str(stderr),
               'stdout_sha256': digest(result.stdout), 'stderr_sha256': digest(result.stderr)}
        receipt['commands'].append(row)
        if tests:
            summaries = [line[len(MARKER):] for line in result.stdout.decode().splitlines()
                         if line.startswith(MARKER)]
            if len(summaries) != 1:
                save()
                raise RuntimeError(label + ': missing unique unittest summary')
            row['counts'] = json.loads(summaries[0])
            count = row['counts']
            if (count['tests'] <= 0 or count['errors'] or count['skips'] or count['safety_violations']
                    or count['expected_failures'] or count['unexpected_successes']):
                save()
                raise RuntimeError(label + ': invalid/empty/skipped/error/safety result')
            if expected_exit == 0 and count['failures']:
                save()
                raise RuntimeError(label + ': failing tests')
        else:
            row['checks'] = 1
            match = re.search(rb'Checked (\d+) text files:', result.stdout)
            if match:
                row['text_files_checked'] = int(match[1])
        save()
        if result.returncode != expected_exit:
            raise RuntimeError(label + ': unexpected child exit ' + str(result.returncode))
        return row

    try:
        manifest_path = ROOT.parent / 'SOURCE-MANIFEST.json'
        manifest = json.loads(manifest_path.read_text())
        if (manifest.get('schema') != 'agentorange.source-manifest/v1'
                or manifest.get('head') != BASE
                or Path(manifest.get('repo', '')).resolve() != ROOT
                or not manifest.get('runtime', {}).get('credential_scan_python3')):
            raise RuntimeError('Invalid standard source manifest or scanner runtime')
        if git('merge-base', BASE, 'HEAD') != BASE:
            raise RuntimeError('Candidate does not descend from the admitted base')
        python = ROOT / '.venv/bin/python3'
        if not python.is_file():
            raise RuntimeError('Missing staged repository Python; installs forbidden')
        receipt['source_manifest_sha256'] = digest(manifest_path.read_bytes())
        receipt['source_before'] = source_identity()
        receipt['runtime_manifest'] = manifest['runtime']
        save()
        bootstrap = [str(python), str(Path(__file__).resolve()), '--child']
        if args.phase == 'baseline':
            if digest((ROOT / PRIMARY).read_bytes()) != PRIMARY_SHA:
                raise RuntimeError('Baseline requires unchanged pinned product source')
            red = invoke('primary-red', bootstrap + [PAIR[0]], tests=True, expected_exit=1)
            if (red['counts']['tests'] != 1 or red['counts']['failures'] != [PAIR[0]]
                    or b'AssertionError:' not in (run / 'primary-red.stderr').read_bytes()
                    or b'A1_MISSING_SCOPED_ASSESSMENT' not in (run / 'primary-red.stderr').read_bytes()):
                raise RuntimeError('Baseline did not isolate the exact frozen A1 assertion')
            healthy = invoke('healthy-control', bootstrap + [PAIR[1]], tests=True)
            if healthy['counts']['tests'] != 1:
                raise RuntimeError('Healthy control count changed')
            receipt['status'] = 'BASELINE_GAP_REPRODUCED'
        elif args.phase == 'focused':
            pair = invoke('frozen-pair-green', bootstrap + PAIR, tests=True)
            focused = invoke('all-focused', bootstrap + [PREFIX], tests=True)
            if pair['counts']['tests'] != 2 or focused['counts']['tests'] != 5:
                raise RuntimeError('Frozen focused test count changed')
            receipt['status'] = 'PASS_REVIEW_REQUIRED'
        elif args.phase == 'regression':
            for index, selector in enumerate(OLD):
                invoke('compatibility-' + str(index + 1), bootstrap + [selector], tests=True)
            receipt['status'] = 'PASS_REVIEW_REQUIRED'
        else:
            scanner = manifest['runtime']['credential_scan_python3']
            if not Path(scanner).is_file():
                raise RuntimeError('Missing admitted scanner runtime; no substitution')
            invoke('repository', [scanner, 'scripts/check_repository.py'])
            pnpm = manifest['runtime'].get('pnpm', 'pnpm')
            for index, project in enumerate(('tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json')):
                invoke('typecheck-' + str(index + 1), [pnpm, 'exec', 'tsc', '--noEmit', '--project', project])
            invoke('build', [pnpm, 'build'])
            receipt['status'] = 'PASS_REVIEW_REQUIRED'
        receipt['source_after'] = source_identity()
        if receipt['source_before'] != receipt['source_after']:
            raise RuntimeError('Source identity changed during acceptance')
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
        print(json.dumps({'status': receipt['status'], 'receipt': str(run / 'receipt.json'),
                          'commands': len(receipt['commands'])}))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        receipt['status'] = 'FAILED_INTERNAL_DISPOSITION_REQUIRED'
        receipt['error'] = str(error)
        save()
        print(json.dumps({'status': receipt['status'], 'receipt': str(run / 'receipt.json'),
                          'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
