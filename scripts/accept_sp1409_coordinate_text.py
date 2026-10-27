"""Portable, offline SP1409 acceptance launcher; scoped green requires review."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
FIXTURES = REPO / 'tests/fixtures/sp1409_coordinate_text'
PRIMARY = 'server/advisor/answers/advice.ts'
BASE = '33734f90073a2150eac5a418564ea314c4a591ac'
BASE_HASH = '6dee4f8a557ff2209a7a75f752bc4be719aad24660aad73ef2f1b0c648fe33df'
TEST = 'tests/test_sp1409_coordinate_text.mjs'
BOOTSTRAP = 'tests/fixtures/sp1409_coordinate_text/offline-bootstrap.mjs'
AUTHOR = {'model': 'gpt-6.1-sol', 'provider': 'openai-codex', 'profile': 'sol-reviewer', 'run': 1808}


def checked_path(path, within):
    """Reject lexical escapes and symlink ancestry before touching inputs/outputs."""
    path = Path(os.path.abspath(path))
    within = Path(os.path.abspath(within))
    if not path.is_relative_to(within):
        raise ValueError('path is outside admitted ancestry')
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f'symlink ancestry refused: {part.name}')
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError('non-directory ancestor refused')
    return path


def digest(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'not a regular input: {path.name}')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()


def identity(spec):
    files = [PRIMARY, TEST, 'scripts/accept_sp1409_coordinate_text.py']
    files += [p.relative_to(REPO).as_posix() for p in sorted(FIXTURES.rglob('*')) if p.is_file()]
    files += ['tests/test_advisor_tools.mjs', 'tests/_advisor_d1.mjs']
    files += git('ls-files', 'catalog', 'drizzle').splitlines()
    note = REPO / 'docs/engineering/sp1409_coordinate_text.md'
    if note.exists():
        files.append(note.relative_to(REPO).as_posix())
    hashes = {p: digest(checked_path(REPO / p, REPO)) for p in sorted(set(files))}
    commits = git('log', '--reverse', '--format=%H%x09%an <%ae>%x09%B%x1e', f'{BASE}..HEAD')
    return {'head': git('rev-parse', 'HEAD'), 'staged_base': BASE,
            'status_porcelain': git('status', '--porcelain'), 'file_sha256': hashes,
            'spec_sha256': hashes['tests/fixtures/sp1409_coordinate_text/requirements.json'],
            'material_author_runtime': AUTHOR, 'material_commit_provenance': commits,
            'source_manifest_sha256': digest(CANDIDATE / 'SOURCE-MANIFEST.json'),
            'spec': spec['spec'], 'card': spec['card']}


def tap_summary(text):
    counts = {}
    for key in ['tests', 'suites', 'pass', 'fail', 'cancelled', 'skipped', 'todo']:
        matches = re.findall(rf'^# {key} (\d+)\s*$', text, re.M)
        counts[key] = int(matches[-1]) if matches else None
    counts['names'] = re.findall(r'^# Subtest: (.+)$', text, re.M)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    checked_path(FIXTURES, REPO)
    manifest_path = checked_path(CANDIDATE / 'SOURCE-MANIFEST.json', CANDIDATE)
    staging = json.loads(manifest_path.read_text())
    if staging.get('schema') != 'agentorange.source-manifest/v1' or staging.get('head') != BASE or Path(staging.get('repo', '')) != REPO:
        raise ValueError('staging manifest identity mismatch')
    scanner = staging.get('runtime', {}).get('credential_scan_python3')
    if not scanner or not Path(scanner).is_file():
        raise ValueError('missing admitted credential scanner interpreter')
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=REPO, check=True)
    spec = json.loads((FIXTURES / 'requirements.json').read_text())
    if spec['spec'] != 'SP-14-v1' or spec['card'] != 'SP1409-COORDINATE-TEXT' or spec['staged_base'] != BASE:
        raise ValueError('frozen specification identity mismatch')
    if args.suite == 'baseline' and (git('rev-parse', 'HEAD') != BASE or digest(REPO / PRIMARY) != BASE_HASH):
        raise ValueError('baseline must run the unchanged pinned product')
    output = checked_path(args.output, CANDIDATE / 'out')
    output.mkdir(parents=True, exist_ok=True)
    checked_path(output, CANDIDATE / 'out')
    run = output / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex)
    run.mkdir(exist_ok=False)
    before = identity(spec)
    node = shutil.which('node')
    pnpm = shutil.which('pnpm')
    env = os.environ.copy()
    env['SP1409_SUITE'] = args.suite
    if env.get('NODE_OPTIONS'):
        raise ValueError('ambient NODE_OPTIONS is not admitted')
    commands = []
    files = []
    expected_names = None
    if args.suite in ['baseline', 'focused', 'regression']:
        if not node:
            raise ValueError('missing installed Node runtime')
        files = [TEST] if args.suite != 'regression' else spec['regression_files']
        commands = [[node, '--experimental-strip-types', '--import', str(REPO / BOOTSTRAP), '--test', '--test-reporter=tap', *files]]
        if args.suite != 'regression':
            expected_names = spec[f'{args.suite}_test_names']
    elif args.suite == 'repository':
        commands = [[scanner, str(REPO / 'scripts/check_repository.py')]]
    elif args.suite == 'typecheck':
        if not pnpm:
            raise ValueError('missing installed pnpm')
        commands = [[pnpm, 'exec', 'tsc', '--noEmit', '-p', p] for p in ['tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json']]
    else:
        if not pnpm:
            raise ValueError('missing installed pnpm')
        commands = [[pnpm, 'build']]
    probes = []
    for executable in [node, pnpm]:
        if executable:
            version = subprocess.run([executable, '--version'], cwd=REPO, capture_output=True, text=True, check=True)
            probes.append({'argv': [executable, '--version'], 'cwd': str(REPO),
                           'resolved_executable': str(Path(executable).resolve()),
                           'exit': version.returncode, 'stdout': version.stdout, 'stderr': version.stderr})
    receipt = {'schema': 'sp1409.acceptance/v1', 'spec': spec['spec'], 'card': spec['card'],
               'phase': args.suite, 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'identity_before': before, 'launcher_argv': [sys.executable, *sys.argv], 'launcher_cwd': str(Path.cwd()),
               'runtime': {'python': sys.executable, 'python_version': sys.version,
                           'node': node, 'pnpm': pnpm, 'version_probes': probes,
                           'credential_scan_python3': scanner,
                           'credential_scan_python3_realpath': str(Path(scanner).resolve())},
               'children': [], 'status': 'UNVERIFIED'}
    all_ok = True
    for number, command in enumerate(commands, 1):
        child = {'argv': command, 'cwd': str(REPO), 'env_overrides': {'SP1409_SUITE': args.suite}}
        try:
            result = subprocess.run(command, cwd=REPO, env=env, capture_output=True, timeout=600)
            stdout, stderr, exitcode = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, exitcode = exc.stdout or b'', exc.stderr or b'', 124
            child['timeout'] = True
        out = run / f'{number:02d}-stdout.txt'
        err = run / f'{number:02d}-stderr.txt'
        out.write_bytes(stdout)
        err.write_bytes(stderr)
        text = stdout.decode(errors='replace')
        child.update({'exit': exitcode, 'stdout': str(out), 'stdout_sha256': digest(out),
                      'stderr': str(err), 'stderr_sha256': digest(err)})
        ok = exitcode == 0
        if args.suite in ['baseline', 'focused', 'regression']:
            counts = tap_summary(text)
            child['counts'] = counts
            clean = all(counts[k] == 0 for k in ['cancelled', 'skipped', 'todo'])
            if args.suite == 'baseline':
                failures = re.findall(r'^not ok \d+ - (.+)$', text, re.M)
                ok = (exitcode == 1 and clean and counts['tests'] == 2 and counts['pass'] == 1
                      and counts['fail'] == 1 and counts['names'] == expected_names
                      and failures == ['primary regression']
                      and 'SP1409_PRIMARY_SEMANTIC_MISMATCH' in text
                      and "code: 'ERR_ASSERTION'" in text
                      and 'Fish at 35 10.5 N, 120 49.0 W. Use a slow drift.' in text
                      and not re.search(r'hookFailed|testCodeFailure.*import|SP1409_UNEXPECTED_OFFLINE_ATTEMPTS', text))
            else:
                expected_count = len(expected_names) if expected_names else len(re.findall(r'^(?:test|dbTest)\(', (REPO / files[0]).read_text(), re.M))
                ok = (ok and clean and counts['tests'] == expected_count and counts['pass'] == expected_count
                      and counts['fail'] == 0 and (expected_names is None or counts['names'] == expected_names))
        child['accepted'] = ok
        receipt['children'].append(child)
        all_ok = all_ok and ok
        print(f'{args.suite} child {number}: exit={exitcode} accepted={ok}')
        if not ok:
            break
    after = identity(spec)
    receipt['identity_after'] = after
    if before != after:
        all_ok = False
        receipt['identity_drift'] = True
    receipt['check_steps_executed'] = len(receipt['children'])
    receipt['check_steps_required'] = len(commands)
    receipt['status'] = ('BASELINE_GAP_REPRODUCED' if args.suite == 'baseline' else 'SCOPED_PASS_REVIEW_REQUIRED') if all_ok else 'FAIL'
    receipt['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f"{receipt['status']} {run / 'receipt.json'}")
    return 0 if all_ok else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f'ACCEPTANCE_SETUP_FAILURE: {error}', file=sys.stderr)
        sys.exit(2)
