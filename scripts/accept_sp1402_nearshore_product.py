"""Portable offline SP-14-v1 acceptance launcher; scoped green is review-required."""
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
import uuid

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO.parent
BASE = '33734f90073a2150eac5a418564ea314c4a591ac'
PRIMARY = 'web/map/nearshore.ts'
PRIMARY_BASE_HASH = '80b41d79423d9780827c5874785534db34dac8e1a07e28262a2ace9e93500753'
TEST = 'tests/test_sp1402_nearshore_product.mjs'
FIXTURE = 'tests/fixtures/sp1402_nearshore_product'
ORIGINAL = 'tests/test_nearshore_layer.mjs'
SPEC = FIXTURE + '/acceptance-spec.json'
EXPECTED = ['primary regression', 'healthy control']
FOCUSED = EXPECTED + [
    'A1 attribution is per clicked site regardless of site and source ordering',
    'A2 single and same-product CDIP preserve complete card and summary wording',
    'A3 missing or unusable source labels fall back to the exact clicked source ID',
    'A3 geometry scale hit area ordering and per-site run age are unchanged',
    'A3 freshness span sampling and binding admission remain intact',
]

def require(condition, message):
    if not condition:
        raise ValueError(message)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()

def no_links(path):
    """Check every existing component before opening/creating fixture/output paths."""
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        require(not part.is_symlink(), 'symlink not allowed in checked path: ' + str(part))
    return path

def paths_and_manifest(output):
    no_links(REPO)
    fixture = no_links(REPO / FIXTURE)
    require(fixture.is_dir(), 'missing fixture directory')
    for item in fixture.rglob('*'):
        no_links(item)
        require(item.is_dir() or item.is_file(), 'non-regular fixture entry')
    out = no_links(output)
    require(out.is_relative_to(CANDIDATE / 'out'), 'output must be under candidate/out')
    require(out != CANDIDATE / 'out', 'supply a named output root')
    require(not out.exists() or out.is_dir(), 'output root is not a directory')
    manifest = json.loads((CANDIDATE / 'SOURCE-MANIFEST.json').read_text())
    require(manifest.get('schema') == 'agentorange.source-manifest/v1', 'staging schema')
    require(manifest.get('head') == BASE, 'staged base mismatch')
    require(Path(manifest.get('repo', '')) == REPO, 'staged repo mismatch')
    require(Path(manifest.get('write_root', '')) == CANDIDATE, 'candidate mismatch')
    require((REPO / '.venv').is_symlink(), 'preserve staged venv linkage')
    require((REPO / '.venv').resolve() == Path(manifest['runtime']['repo_venv']), 'venv target drift')
    require(git('merge-base', BASE, 'HEAD') == BASE, 'HEAD must descend from staged base')
    return out, manifest

def snapshot():
    # Hash complete tracked input closure (not just an extracted function), plus new inputs.
    names = set(git('ls-files').splitlines())
    names.update([TEST, str(Path(__file__).relative_to(REPO)), 'docs/engineering/sp1402_nearshore_product.md'])
    names.update(str(p.relative_to(REPO)) for p in (REPO / FIXTURE).rglob('*') if p.is_file())
    hashes = {}
    for name in sorted(names):
        path = REPO / name
        require(path.is_file() and not path.is_symlink(), 'missing/nonregular source input: ' + name)
        hashes[name] = digest(path)
    return hashes

def tap_summary(text):
    names = re.findall(r'^# Subtest: (.+)$', text, re.M)
    results = re.findall(r'^(not ok|ok) \d+ - (.+?)(?: #.*)?$', text, re.M)
    counts = {}
    for key in ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo']:
        found = re.findall(r'^# ' + key + r' (\d+)$', text, re.M)
        counts[key] = int(found[-1]) if found else None
    return {'names': names, 'results': results, **counts}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, choices=['baseline', 'focused', 'regression', 'repository', 'typecheck', 'build'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out, staged = paths_and_manifest(args.output)
    out.mkdir(parents=True, exist_ok=True)
    run = out / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex)
    run.mkdir(exist_ok=False)
    (run / 'tmp').mkdir()
    receipt = {
        'schema': 'agentorange.sp1402-acceptance/v1', 'spec_version': 'SP-14-v1',
        'card': 'SP1402-NEARSHORE-PRODUCT', 'phase': args.suite, 'staged_base': BASE,
        'actual_head': git('rev-parse', 'HEAD'), 'status_before': git('status', '--porcelain'),
        'launcher_argv': sys.argv, 'launcher_cwd': str(Path.cwd()), 'launcher_python': sys.executable,
        'launcher_python_resolved': str(Path(sys.executable).resolve()), 'launcher_python_version': sys.version,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'author_runtime': {'model': 'gpt-6.1-sol', 'provider': 'openai-codex', 'profile': 'sol-reviewer',
                           'task': 't_70c9b868', 'run': 1815, 'basis': 'admitted actual builder runtime'},
        'material_commits': git('log', '--format=%H%n%B%n---', BASE + '..HEAD'),
        'source_manifest_sha256': digest(CANDIDATE / 'SOURCE-MANIFEST.json'),
        'inputs_before': snapshot(), 'children': [],
    }
    receipt['spec_sha256'] = receipt['inputs_before'][SPEC]
    success = False
    try:
        node = shutil.which('node')
        pnpm = shutil.which('pnpm')
        if node is None or pnpm is None:
            raise ValueError('installed Node or pnpm unavailable; no install/fallback permitted')
        receipt['node_runtime'] = {'executable': node, 'resolved': str(Path(node).resolve()),
                                  'version': subprocess.check_output([node, '--version'], text=True).strip()}
        receipt['pnpm_runtime'] = {'executable': pnpm, 'resolved': str(Path(pnpm).resolve())}
        if args.suite == 'baseline':
            require(receipt['actual_head'] == BASE, 'baseline must run at unchanged base HEAD')
            require(digest(REPO / PRIMARY) == PRIMARY_BASE_HASH, 'baseline product drift')
        if args.suite in ['baseline', 'focused', 'regression']:
            test_file = ORIGINAL if args.suite == 'regression' else TEST
            commands = [[node, '--experimental-strip-types', '--import', './' + FIXTURE + '/bootstrap.mjs',
                         '--test', '--test-reporter=tap', test_file]]
        elif args.suite == 'repository':
            interpreter = staged['runtime']['credential_scan_python3']
            require(Path(interpreter).is_absolute() and os.access(interpreter, os.X_OK), 'missing staged credential scan interpreter')
            receipt['credential_scan_python3'] = {'literal': interpreter, 'resolved': str(Path(interpreter).resolve())}
            commands = [[interpreter, 'scripts/check_repository.py']]
        elif args.suite == 'typecheck':
            commands = [[pnpm, 'exec', 'tsc', '--noEmit', '-p', p] for p in ['tsconfig.json', 'web/tsconfig.json', 'packages/coast/tsconfig.json']]
        else:
            commands = [[pnpm, 'build']]
        env = dict(os.environ)
        env['TMPDIR'] = str(run / 'tmp')
        env['SP1402_TEST_SUITE'] = args.suite
        for index, argv in enumerate(commands):
            child = {'argv': argv, 'cwd': str(REPO), 'environment_delta': {'TMPDIR': env['TMPDIR'], 'SP1402_TEST_SUITE': args.suite}}
            stdout = run / f'{index}.stdout.txt'
            stderr = run / f'{index}.stderr.txt'
            with stdout.open('xb') as so, stderr.open('xb') as se:
                result = subprocess.run(argv, cwd=REPO, env=env, stdout=so, stderr=se, check=False)
            child.update({'exit': result.returncode, 'stdout': str(stdout), 'stderr': str(stderr),
                          'stdout_sha256': digest(stdout), 'stderr_sha256': digest(stderr)})
            text = stdout.read_text(errors='replace')
            if args.suite in ['baseline', 'focused', 'regression']:
                child['tests'] = tap_summary(text)
            if args.suite == 'repository':
                match = re.search(r'Checked (\d+) text files:', text)
                child['checked_text_files'] = int(match.group(1)) if match else None
            receipt['children'].append(child)
            print(json.dumps(child, indent=2))
            if args.suite == 'baseline':
                counts = child['tests']
                require(result.returncode == 1, 'baseline child must exit exactly 1')
                require(counts['names'] == EXPECTED, 'baseline must register exactly the A4 pair')
                require(counts['results'] == [('not ok', EXPECTED[0]), ('ok', EXPECTED[1])], 'unexpected baseline failing test')
                require([counts[k] for k in ['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo']] == [2, 1, 1, 0, 0, 0], 'baseline counts drift')
                require(re.search(r'^  error: \|-\n    SP1402_A1_SECOND_KIND\n', text, re.M) is not None, 'expected semantic assertion absent')
                require("code: 'ERR_ASSERTION'" in text and "operator: 'strictEqual'" in text, 'not the expected assertion class')
                require("expected: 'Synthetic Other model site'" in text and "actual: 'CDIP MOP model site'" in text, 'semantic expected/actual mismatch')
                require('"observedException":null' in text, 'unexpected product exception')
                require(stderr.stat().st_size == 0, 'baseline setup/runtime stderr')
            else:
                require(result.returncode == 0, 'child failed: ' + str(argv))
                if args.suite in ['focused', 'regression']:
                    counts = child['tests']
                    expected = FOCUSED if args.suite == 'focused' else re.findall(r"^test\('((?:\\.|[^'])*)'", (REPO / ORIGINAL).read_text(), re.M)
                    if args.suite == 'regression':
                        expected = [s.replace("\\'", "'") for s in expected]
                    require(counts['names'] == expected, 'selected test names differ from complete required list')
                    require(counts['tests'] == counts['pass'] == len(expected), 'not all selected tests passed')
                    require(all(counts[k] == 0 for k in ['fail', 'cancelled', 'skipped', 'todo']), 'failure/cancellation/skip/todo')
                if args.suite == 'repository':
                    require(child['checked_text_files'] is not None, 'missing repository check count')
        receipt['inputs_after'] = snapshot()
        require(receipt['inputs_before'] == receipt['inputs_after'], 'input bytes changed during acceptance')
        require(receipt['actual_head'] == git('rev-parse', 'HEAD'), 'HEAD changed during acceptance')
        success = True
    except Exception as error:
        receipt['error'] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        receipt['status_after'] = git('status', '--porcelain')
        receipt['result'] = ('BASELINE_GAP_REPRODUCED' if args.suite == 'baseline' else 'SCOPED_GREEN_REVIEW_REQUIRED') if success else 'FAIL'
        receipt['exit'] = 0 if success else 1
        target = run / 'receipt.json'
        target.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'receipt': str(target), 'receipt_sha256': digest(target), 'result': receipt['result'], 'exit': receipt['exit']}, indent=2))
    return receipt['exit']

if __name__ == '__main__':
    raise SystemExit(main())
