"""SP-BAR-EVENTS offline acceptance. No installs, downloads or inline child code."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import uuid

REPO = Path(__file__).resolve().parents[1]
BASE = 'f8bc7d365c0c5aa4a2e59ba576a95146c92a0367'
NODE = Path.home() / '.local/bin/node'  # Operator-staged executable; never PATH fallback.
NODE_SHA256 = '3517c2df0b2f8cd7f422b4b8450ef81c6889f08eb03e281d6de9079b15e6a327'
TEST = 'tests/test_sp_bar_events.mjs'
FIXTURE = 'tests/fixtures/sp_bar_events/events.json'
REGRESSIONS = ['tests/test_bar_conditions.mjs', 'tests/test_window_hazards.mjs']
NEGATIVE_IDS = ['A4-X-to-H', 'A4-permutation-invariance', 'control-unknown-permutation', 'control-ebb', 'control-flood', 'null-observation']
FOCUSED_IDS = NEGATIVE_IDS + ['A1-malformed-rows', 'A1-nonfinite-and-missing-boundaries', 'A2-conflict-at-either-chosen-boundary', 'A2-duplicates-same-type-and-input-preservation', 'A3-thresholds-rounding-and-exact-events', 'A3-consumer-hazard-and-unknown-never-safe']
UNKNOWN = {'stage': None, 'midEbb': False, 'fraction': None}
FLOOD = {'stage': 'flood', 'midEbb': False, 'fraction': 0.5}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=['focused', 'regression', 'negative'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out_root = REPO.parent / 'out'
    # Authored fixtures and source must never become output; reject symlink ancestry.
    parent = args.output.absolute()
    if '..' in parent.parts or not parent.is_relative_to(out_root) or parent == out_root:
        parser.error('output must be a child of the candidate out directory')
    for path in (parent, *parent.parents):
        if path.is_symlink():
            parser.error('output ancestry may not contain symlinks')
    run = parent / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    receipt = {'schema_version': 1, 'suite': args.suite, 'candidate_head': None, 'baseline_head': BASE,
               'spec_sha256': digest(REPO / TEST), 'spec_definition': 'Named frozen behavior assertions in ' + TEST,
               'runtime': {'python': sys.version, 'python_executable': sys.executable, 'node': str(NODE)},
               'commands': [], 'counts': {'test_cases': 0, 'assertion_checks': 0, 'intended_negative_failures': 0, 'unexpected_failures': 0, 'skips': 0},
               'source_hashes': {p: digest(REPO / p) for p in ['packages/coast/src/bar-conditions.ts', TEST, FIXTURE, 'scripts/accept_sp_bar_events.py', *REGRESSIONS, 'package.json', 'pnpm-lock.yaml']},
               'verdict': 'FAIL', 'wrapper_exit': 1}

    def command(argv, cwd=REPO):
        number = len(receipt['commands'])
        stdout = run / f'{number:02d}.stdout.txt'
        stderr = run / f'{number:02d}.stderr.txt'
        with stdout.open('wb') as so, stderr.open('wb') as se:
            child = subprocess.run([str(x) for x in argv], cwd=cwd, stdout=so, stderr=se, check=False)
        entry = {'argv': [str(x) for x in argv], 'cwd': str(cwd), 'exit': child.returncode,
                 'stdout_file': stdout.name, 'stderr_file': stderr.name,
                 'stdout_sha256': digest(stdout), 'stderr_sha256': digest(stderr)}
        receipt['commands'].append(entry)
        return child.returncode, stdout.read_text()

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    try:
        code, text = command(['git', 'rev-parse', 'HEAD'])
        require(code == 0, 'candidate identity query failed')
        receipt['candidate_head'] = text.strip()
        code, text = command(['git', 'status', '--porcelain'])
        require(code == 0, 'candidate status query failed')
        receipt['candidate_status'] = text
        code, text = command([NODE, '--version'])
        require(code == 0 and text.strip() == 'v22.23.2' and digest(NODE) == NODE_SHA256, 'operator-pinned Node runtime mismatch')
        receipt['runtime'].update(node_version=text.strip(), node_sha256=digest(NODE))
        require((REPO / 'node_modules').is_dir(), 'missing operator-staged node_modules; no installation allowed')
        commands = []
        if args.suite == 'negative':
            archive = run / 'baseline.tar'
            code, _ = command(['git', 'archive', '--format=tar', '--output', archive, BASE])
            require(code == 0, 'full baseline archive failed')
            snapshot = run / 'baseline'
            snapshot.mkdir()
            with tarfile.open(archive) as bundle:
                bundle.extractall(snapshot, filter='data')
            # Freeze the entire unchanged committed tree BEFORE adding only the test harness.
            baseline_files = {p.relative_to(snapshot).as_posix(): digest(p) for p in sorted(snapshot.rglob('*')) if p.is_file() and not p.is_symlink()}
            require(baseline_files.get('packages/coast/src/bar-conditions.ts') == '8464852d7301c7eab9371c8eee46d0473adac547e0ded559b977a8ab021bed31', 'baseline primary source pin mismatch')
            (run / 'baseline-files.json').write_text(json.dumps(baseline_files, indent=2) + '\n')
            for name in [TEST, FIXTURE]:
                target = snapshot / name
                require(not target.exists(), 'baseline already contains candidate test harness')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / name, target)
            (snapshot / 'node_modules').symlink_to((REPO / 'node_modules').resolve(), target_is_directory=True)
            receipt['baseline_snapshot'] = {'archive_file': 'baseline.tar', 'archive_sha256': digest(archive),
                                            'files_manifest': 'baseline-files.json', 'files_manifest_sha256': digest(run / 'baseline-files.json'),
                                            'file_count': len(baseline_files), 'module_root': 'baseline', 'added_test_files': [TEST, FIXTURE]}
            commands = [([NODE, '--experimental-strip-types', TEST, '--negative'], snapshot)]
        elif args.suite == 'focused':
            commands = [([NODE, '--experimental-strip-types', '--test', TEST], REPO)]
        else:
            commands = [([NODE, '--experimental-strip-types', '--import', './' + TEST, '--test', name], REPO) for name in REGRESSIONS]
        for argv, cwd in commands:
            code, stdout = command(argv, cwd)
            markers = [json.loads(line.split('SP_BAR_EVENTS_JSON ', 1)[1]) for line in stdout.splitlines() if 'SP_BAR_EVENTS_JSON ' in line]
            require(len(markers) == 1, 'missing or duplicate test assertion receipt')
            marker = markers[0]
            require(marker['fetch_calls'] == 0, 'offline fetch sentinel was called')
            require(marker['runtime'] == receipt['runtime']['node_version'], 'child runtime mismatch')
            receipt['counts']['assertion_checks'] += marker['assertion_checks']
            require(marker['assertion_checks'] > 0, 'no assertion checks executed')
            taps = {key: int(value) for key, value in re.findall(r'^# (tests|pass|fail|skipped|cancelled|todo) (\d+)$', stdout, re.M)}
            require(all(k in taps for k in ['tests', 'pass', 'fail', 'skipped', 'cancelled', 'todo']), 'missing TAP totals')
            receipt['counts']['test_cases'] += taps['tests']
            receipt['counts']['skips'] += taps['skipped'] + taps['cancelled'] + taps['todo']
            require(receipt['counts']['skips'] == 0, 'skipped, cancelled or todo assertions')
            if args.suite == 'regression':
                require(code == 0 and taps['fail'] == 0 and taps['pass'] == taps['tests'] and taps['tests'] > 0, 'regression failure')
                continue
            results = marker['results']
            expected = NEGATIVE_IDS if args.suite == 'negative' else FOCUSED_IDS
            require([r['id'] for r in results] == expected and taps['tests'] == len(expected), 'named test inventory mismatch')
            failed = [r for r in results if r['status'] == 'FAIL']
            if args.suite == 'negative':
                require(code == 1 and taps['fail'] == 2 and taps['pass'] == len(expected) - 2, 'negative exit or TAP totals mismatch')
                require([r['id'] for r in failed] == NEGATIVE_IDS[:2], 'unexpected baseline failure set')
                require(all(r['error'] == {'name': 'AssertionError', 'code': 'ERR_ASSERTION'} for r in failed), 'baseline setup error is not an intended failure')
                require(results[0]['detail']['actual'] == FLOOD, 'X-to-H must expose specific incorrect flood result')
                require(results[1]['detail'] == {'first': UNKNOWN, 'second': FLOOD}, 'baseline conflict permutations must specifically disagree')
                require(results[2]['detail']['actual'] == UNKNOWN, 'passing baseline unknown permutation missing')
                require(results[5]['detail'].get('exception', {}).get('name') == 'TypeError', 'null-row exception must be recorded separately')
                receipt['counts']['intended_negative_failures'] = 2
            else:
                require(code == 0 and not failed and taps['fail'] == 0 and taps['pass'] == len(expected), 'focused assertions failed')
        require(all(digest(REPO / p) == sha for p, sha in receipt['source_hashes'].items()), 'source changed during acceptance')
        code, text = command(['git', 'rev-parse', 'HEAD'])
        require(code == 0 and text.strip() == receipt['candidate_head'], 'HEAD changed during acceptance')
        code, text = command(['git', 'status', '--porcelain'])
        require(code == 0 and text == receipt['candidate_status'], 'candidate status changed during acceptance')
        receipt['verdict'] = 'PASS_REVIEW_REQUIRED'
        receipt['wrapper_exit'] = 0
    except Exception as error:
        receipt['counts']['unexpected_failures'] += 1
        receipt['error'] = {'type': type(error).__name__, 'message': str(error)}
    receipt['output_hashes'] = {p.name: digest(p) for p in run.iterdir() if p.is_file()}
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(run / 'receipt.json'), 'verdict': receipt['verdict'], 'counts': receipt['counts'], 'error': receipt.get('error')}))
    return receipt['wrapper_exit']


if __name__ == '__main__':
    sys.exit(main())
