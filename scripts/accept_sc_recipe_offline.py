"""SC-RECIPE-OFFLINE acceptance runner: focused, contract or negative suite.

    python3 scripts/accept_sc_recipe_offline.py --suite focused --output OUT

OUT must not exist; it becomes the write-once run directory holding raw
stdout/stderr, the JUnit report, the child sentinel report and receipt.json
(argv, cwd, interpreters, git identity, input/code hashes and counts).

The parent process only checks pins and paths, then starts ONE child: this
same file, under the staged repository's own virtual environment interpreter
(repo/.venv/bin/python3 by default, because pytest and the pinned jsonschema
are installed there and not in the system interpreter). The child sets
bytecode suppression and its import path in code, installs DNS, socket, HTTP,
subprocess, process-spawn and model-SDK sentinels BEFORE importing pytest, the
validator or jsonschema, traces every imported module, then runs pytest
in-process. Nothing is installed, fetched or contacted.

Suites (docs/engineering/sc_recipe_offline.md):
  focused   tests/unit/test_sc_recipe_offline.py -k a1_          (A1)
  contract  tests/unit/test_coast_recipe.py unchanged, plus the whole new
            file under the child sentinels                        (A2)
  negative  tests/unit/test_sc_recipe_offline.py -k a3_, plus a direct
            mutation proof: the regression must FAIL on the in-memory
            retrieval counter when only the reference gate is disabled, and
            pass on the positive and restored controls            (A3)
Exit 0 only when every named assertion passed with zero failures, errors and
skips. Success is REVIEW REQUIRED, not full CI or semantic acceptance.
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import fnmatch  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import stat  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
BASE = '59fca09b2cc7f5c81a4796902504e263d7f06960'
PINNED = {
    'schemas/coast-recipe-v1.schema.json':
        'a659d136536a553043fac917473428ae0c6e51bdb179cc66bdd295e09ebf1593',
    'tests/unit/test_coast_recipe.py':
        '020dc5f5f736ac09cfefc50c7e8315079bb34e12d512a4bed054c84986413410',
}
BASE_VALIDATOR_SHA256 = '7f14c349497d647c540aa67f4a389da562908430b83e687098f493b15788dad3'
NEW_TEST = 'tests/unit/test_sc_recipe_offline.py'
COAST_TEST = 'tests/unit/test_coast_recipe.py'
FIXTURE_DIR = 'tests/fixtures/sc_recipe_offline'
SUITES = {
    'focused': {'files': [NEW_TEST], 'select': 'a1_'},
    'contract': {'files': [COAST_TEST, NEW_TEST], 'select': None},
    'negative': {'files': [NEW_TEST], 'select': 'a3_'},
}
CODE_INPUTS = [
    'validate_recipe.py', 'scripts/accept_sc_recipe_offline.py', NEW_TEST, COAST_TEST,
    'tests/__init__.py', 'tests/unit/__init__.py', 'tests/conftest.py', 'tests/_support.py',
    'pyproject.toml', 'schemas/coast-recipe-v1.schema.json', 'catalog/sources.json',
    'catalog/coastal-sectors.json', 'src/skippercast/coastal/prefetch.py',
    'research/scripts/build_coast_prefetch_plan.py',
]
SLUGS = ('morro-bay', 'cambria-san-simeon', 'south-big-sur-san-simeon', 'santa-cruz-monterey-bay')
for _slug in SLUGS:
    CODE_INPUTS += ['regions/' + _slug + '/region.json', 'regions/' + _slug + '/coast.json']
BLOCKED_IMPORTS = ('requests', 'urllib3', 'httpx', 'aiohttp', 'httplib2', 'pycurl',
                   'openai', 'anthropic', 'ollama', 'google.generativeai', 'boto3', 'botocore')
CHILD_TIMEOUT_SECONDS = 900
SCRUBBED_ENV = ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE',
                'PYTHONSAFEPATH', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'SKIPPERCAST_NETWORK',
                'SKIPPERCAST_REQUIRE_GIS')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 16), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    data = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n'
    with open(path, 'x', encoding='utf-8') as handle:
        handle.write(data)


def no_symlink_ancestry(path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise SystemExit('refused: symlink in output ancestry: ' + str(current))
        if not stat.S_ISDIR(mode):
            raise SystemExit('refused: non-directory in output ancestry: ' + str(current))


def new_run_dir(output):
    output = Path(output)
    if not output.is_absolute() or '..' in output.parts:
        raise SystemExit('refused: --output must be an absolute path without ..')
    if output == REPO or REPO in output.parents:
        raise SystemExit('refused: --output must be outside the staged repository')
    no_symlink_ancestry(output)
    if os.path.lexists(output):
        raise SystemExit('refused: --output already exists (run roots are write-once)')
    output.parent.mkdir(parents=True, exist_ok=True)
    no_symlink_ancestry(output)
    output.mkdir(exist_ok=False)
    return output


def git(*args):
    import subprocess
    done = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True,
                          timeout=60, check=False)
    return {'argv': ['git', '-C', str(REPO), *args], 'exit': done.returncode,
            'stdout': done.stdout.strip(), 'stderr': done.stderr.strip()}


def junit_counts(path):
    import xml.etree.ElementTree as ElementTree
    root = ElementTree.parse(path).getroot()
    totals = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    by_file = {}
    for case in root.iter('testcase'):
        name = case.get('classname', '')
        key = name.split('.')[-1] if name else '?'
        row = by_file.setdefault(key, dict.fromkeys(totals, 0))
        outcome = 'tests'
        for child in case:
            if child.tag == 'failure':
                outcome = 'failures'
            elif child.tag == 'error':
                outcome = 'errors'
            elif child.tag == 'skipped':
                outcome = 'skipped'
        for target in (totals, row):
            target['tests'] += 1
            if outcome != 'tests':
                target[outcome] += 1
    return totals, by_file


def collection_check():
    import tomllib
    config = tomllib.loads((REPO / 'pyproject.toml').read_text(encoding='utf-8'))
    options = config['tool']['pytest']['ini_options']
    testpaths, patterns = options['testpaths'], options['python_files']
    rows = {}
    for name in (NEW_TEST, COAST_TEST):
        relative = Path(name)
        rows[name] = {
            'under_testpaths': any(relative.parts[:len(Path(p).parts)] == Path(p).parts
                                   for p in testpaths),
            'matches_python_files': any(fnmatch.fnmatch(relative.name, p) for p in patterns),
        }
    return {'testpaths': testpaths, 'python_files': patterns, 'files': rows,
            'ok': all(all(row.values()) for row in rows.values()),
            'full_discovery': 'operator-run (not part of this scoped runner)'}


def parent(args):
    import platform
    import subprocess
    import time
    run_dir = new_run_dir(args.output)
    problems = []
    pins = {name: sha256_file(REPO / name) for name in PINNED}
    for name, expected in PINNED.items():
        if pins[name] != expected:
            problems.append('pinned unchanged input differs: ' + name)
    head = git('rev-parse', 'HEAD')
    ancestry = git('merge-base', '--is-ancestor', BASE, 'HEAD')
    if ancestry['exit'] != 0:
        problems.append('base ' + BASE + ' is not an ancestor of HEAD')
    status = git('status', '--porcelain', '--untracked-files=all')
    changed = git('diff', '--name-only', BASE, 'HEAD')
    inputs = {name: sha256_file(REPO / name) for name in CODE_INPUTS}
    fixtures = {str(p.relative_to(REPO)): sha256_file(p)
                for p in sorted((REPO / FIXTURE_DIR).iterdir()) if p.is_file()}
    python = Path(args.python) if args.python else REPO / '.venv' / 'bin' / 'python3'
    if not python.is_absolute() or not os.access(python, os.X_OK):
        problems.append('child interpreter is not an executable absolute path: ' + str(python))
    collection = collection_check()
    if not collection['ok']:
        problems.append('new or contract test file is outside pyproject discovery')
    env = {key: value for key, value in os.environ.items()
           if key not in SCRUBBED_ENV and not key.startswith('LD_')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONNOUSERSITE'] = '1'
    argv = [str(python), '-B', str(Path(__file__).resolve()), '--child', args.suite,
            '--run-dir', str(run_dir)]
    child = {'argv': argv, 'cwd': str(REPO), 'exit': None}
    if not problems:
        started = time.time()
        with open(run_dir / 'stdout.txt', 'xb') as out, open(run_dir / 'stderr.txt', 'xb') as err:
            try:
                done = subprocess.run(argv, cwd=REPO, env=env, stdout=out, stderr=err,
                                      timeout=CHILD_TIMEOUT_SECONDS, check=False)
                child['exit'] = done.returncode
            except subprocess.TimeoutExpired:
                problems.append('child timed out')
        child['seconds'] = round(time.time() - started, 3)
        child['stdout_sha256'] = sha256_file(run_dir / 'stdout.txt')
        child['stderr_sha256'] = sha256_file(run_dir / 'stderr.txt')
        if child['exit'] != 0:
            problems.append('child exited ' + str(child['exit']))
    report_path = run_dir / 'child-report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else None
    counts, by_file = ({}, {})
    if (run_dir / 'junit.xml').exists():
        counts, by_file = junit_counts(run_dir / 'junit.xml')
        child['junit_sha256'] = sha256_file(run_dir / 'junit.xml')
    if not problems:
        if report is None:
            problems.append('child wrote no report')
        if not counts.get('tests'):
            problems.append('no tests ran')
        for key in ('failures', 'errors', 'skipped'):
            if counts.get(key):
                problems.append(key + ': ' + str(counts[key]))
        expected_files = {Path(name).stem for name in SUITES[args.suite]['files']}
        if set(by_file) != expected_files or not all(by_file[f]['tests'] for f in expected_files):
            problems.append('per-file counts do not cover ' + ', '.join(sorted(expected_files)))
    receipt = {
        'card': 't_b73efb9a', 'suite': args.suite, 'status': 'PASS' if not problems else 'FAIL',
        'meaning': 'local scoped REVIEW REQUIRED evidence; not full CI or semantic acceptance',
        'argv': sys.argv, 'cwd': os.getcwd(),
        'parent_interpreter': {'executable': sys.executable, 'version': sys.version,
                               'platform': platform.platform()},
        'child': child, 'child_report': report, 'counts': counts, 'counts_by_file': by_file,
        'git': {'base': BASE, 'head': head, 'base_is_ancestor': ancestry['exit'] == 0,
                'status_porcelain': status['stdout'].splitlines(),
                'changed_since_base': changed['stdout'].splitlines()},
        'pinned_unchanged_inputs': pins, 'base_validator_sha256': BASE_VALIDATOR_SHA256,
        'input_sha256': inputs, 'fixture_sha256': fixtures, 'collection': collection,
        'problems': problems,
    }
    write_json(run_dir / 'receipt.json', receipt)
    summary = {'suite': args.suite, 'status': receipt['status'], 'counts': counts,
               'counts_by_file': by_file, 'head': head['stdout'], 'run_dir': str(run_dir),
               'receipt_sha256': sha256_file(run_dir / 'receipt.json'), 'problems': problems}
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0 if not problems else 1


# --- child -----------------------------------------------------------------

CALLS = []
IMPORTS = []


def install_sentinels():
    """Replace every transport/process entrypoint before any project import."""
    import http.client
    import socket
    import subprocess
    import urllib.request

    def refused(name):
        def call(*args, **kwargs):
            CALLS.append(name)
            raise RuntimeError('acceptance sentinel refused ' + name)
        return call

    targets = [
        (socket, ['socket', 'create_connection', 'create_server', 'socketpair', 'fromfd',
                  'getaddrinfo', 'gethostbyname', 'gethostbyname_ex', 'gethostbyaddr',
                  'getnameinfo', 'getfqdn']),
        (http.client.HTTPConnection, ['connect', 'request', 'send']),
        (http.client.HTTPSConnection, ['connect']),
        (urllib.request, ['urlopen', 'urlretrieve']),
        (urllib.request.OpenerDirector, ['open']),
        (subprocess, ['Popen', 'run', 'call', 'check_call', 'check_output', 'getoutput',
                      'getstatusoutput']),
        (os, ['system', 'popen', 'fork', 'forkpty', 'execv', 'execve', 'execvp', 'execvpe',
              'execl', 'execle', 'execlp', 'execlpe', 'spawnv', 'spawnve', 'spawnvp',
              'spawnvpe', 'spawnl', 'spawnle', 'posix_spawn', 'posix_spawnp']),
    ]
    for owner, names in targets:
        for name in names:
            if hasattr(owner, name):
                setattr(owner, name, refused(getattr(owner, '__name__', '?') + '.' + name))

    class Blocked:
        @staticmethod
        def find_spec(name, path=None, target=None):
            if any(name == b or name.startswith(b + '.') for b in BLOCKED_IMPORTS):
                CALLS.append('import ' + name)
                raise ImportError('acceptance sentinel blocked import ' + name)
            return None

    sys.meta_path.insert(0, Blocked)

    def audit(event, event_args):
        if event == 'import':
            IMPORTS.append(event_args[0])
        elif event in ('socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                       'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn',
                       'os.spawn', 'os.fork', 'urllib.Request'):
            CALLS.append('audit ' + event)

    sys.addaudithook(audit)


def module_trace():
    allowed = [REPO, Path(sys.base_prefix), Path(sys.base_exec_prefix)]
    outside, project = [], {}
    for name, module in sorted(sys.modules.items()):
        location = getattr(module, '__file__', None)
        if not location:
            continue
        path = Path(location).absolute()
        if not any(path == root or root in path.parents for root in allowed):
            outside.append([name, str(path)])
        if name in ('validate_recipe', 'jsonschema', 'referencing', 'pytest', 'skippercast'):
            project[name] = str(path)
    return outside, project


def mutation_proof(run_dir):
    """Reuse the test module's own regression on fresh synthetic roots."""
    import importlib.util
    path = REPO / NEW_TEST
    spec = importlib.util.spec_from_file_location('sc_recipe_offline_mutation_proof', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recipe = module.recipe
    original_gate = recipe._check_references
    original_hook = recipe._refuse_retrieval
    rows = []
    try:
        recipe._refuse_retrieval = module.counting_retrieval
        for index, case_id in enumerate(module.TRAVERSED):
            case = module.REJECTED[case_id]
            row = {'case': case_id}
            root = run_dir / 'mutation' / ('%02d' % index)
            metadata, workspace = module.stage(root, module.edited(case))
            module.RETRIEVALS.clear()
            module.check_refused(case, metadata, workspace)
            row['positive_control'] = 'passed'
            recipe._check_references = lambda schema: None
            try:
                module.check_refused(case, metadata, workspace)
                row['mutated_regression'] = 'NOT DETECTED'
            except AssertionError as error:
                text = str(error)
                row['mutated_regression'] = ('detected by retrieval counter'
                                             if text.startswith('retrieval counter moved')
                                             else 'failed for another reason: ' + text)
            row['retrieval_counter'] = len(module.RETRIEVALS)
            row['retrieved'] = list(module.RETRIEVALS)
            row['mutated_error'] = module.outcome(metadata, workspace)
            recipe._check_references = original_gate
            module.RETRIEVALS.clear()
            module.check_refused(case, metadata, workspace)
            row['restored_control'] = 'passed'
            row['ok'] = (row['mutated_regression'] == 'detected by retrieval counter'
                         and row['retrieval_counter'] >= 1
                         and str(row['mutated_error']).startswith(
                             'schema reference unresolvable offline'))
            rows.append(row)
    finally:
        recipe._check_references = original_gate
        recipe._refuse_retrieval = original_hook
    return {'rows': rows, 'ok': bool(rows) and all(row['ok'] for row in rows)}


def child(args):
    run_dir = Path(args.run_dir)
    sys.path[0] = str(REPO)
    install_sentinels()
    preloaded = sorted(name for name in sys.modules
                       if name.split('.')[0] in ('jsonschema', 'referencing', 'validate_recipe',
                                                 'pytest'))
    import pytest
    suite = SUITES[args.suite]
    options = [str(REPO / name) for name in suite['files']]
    if suite['select']:
        options += ['-k', suite['select']]
    options += ['-p', 'no:cacheprovider', '--rootdir', str(REPO), '-c', str(REPO / 'pyproject.toml'),
                '--basetemp', str(run_dir / 'tmp'), '--junitxml', str(run_dir / 'junit.xml'),
                '-rA', '-q']
    requested = list(options)
    exit_code = int(pytest.main(options))
    mutation = None
    if args.suite == 'negative' and exit_code == 0:
        mutation = mutation_proof(run_dir)
    outside, project = module_trace()
    import importlib.metadata
    report = {
        'pytest_argv': requested, 'pytest_exit': exit_code, 'interpreter': sys.executable,
        'interpreter_realpath': os.path.realpath(sys.executable), 'version': sys.version,
        'prefix': sys.prefix, 'prefix_realpath': os.path.realpath(sys.prefix),
        'dont_write_bytecode': sys.dont_write_bytecode,
        'versions': {name: importlib.metadata.version(name)
                     for name in ('jsonschema', 'referencing', 'pytest')},
        'preloaded_before_sentinels': preloaded, 'sentinel_calls': CALLS,
        'imported_module_count': len(set(IMPORTS)),
        'modules_outside_staged_roots': outside, 'project_modules': project,
        'mutation_proof': mutation,
    }
    ok = (exit_code == 0 and not CALLS and not outside and not preloaded
          and project.get('validate_recipe') == str(REPO / 'validate_recipe.py')
          and 'skippercast' not in project
          and (args.suite != 'negative' or (mutation is not None and mutation['ok'])))
    report['ok'] = ok
    write_json(run_dir / 'child-report.json', report)
    print('child report ok=' + str(ok))
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--suite', choices=sorted(SUITES))
    parser.add_argument('--output')
    parser.add_argument('--python', help='child interpreter (default: repo/.venv/bin/python3)')
    parser.add_argument('--child', choices=sorted(SUITES), help=argparse.SUPPRESS)
    parser.add_argument('--run-dir', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        args.suite = args.child
        return child(args)
    if not args.suite or not args.output:
        parser.error('--suite and --output are required')
    return parent(args)


if __name__ == '__main__':
    sys.exit(main())
