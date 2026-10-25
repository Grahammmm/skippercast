"""Offline acceptance runner for SC-METADATA-OBJECT (nonobject cached metadata).

    python3 research/scripts/accept_sc_metadata_object.py --suite focused|contract|negative --output DIR

The repository is derived from this file. Bytecode writing is disabled and the
staged repository (and its src/) is put first on sys.path in code, before any
project import; the installed pytest API is then invoked in-process with literal
test-file arguments. Temporary files and pytest's --basetemp are redirected into
a new write-once run directory under DIR, and an audit-hook sentinel refuses
network, process creation, model-client imports and writes outside that run.

Suites:
  focused   tests/unit/test_sc_metadata_object.py (whole file)
  contract  tests/unit/test_coastal_cached_intake.py + tests/contract/test_research_boundary.py
  negative  the new file's test_a3_ mutation controls, plus each control re-run directly
            to confirm its specific tagged inner failure and its healthy positive control

Each run writes DIR/<utc>-<pid>-<token>/{receipt.json,stdout.txt,stderr.txt}.
Exit 0 only when pytest returned 0, every collected item passed, nothing was
skipped, collected counts equal the frozen expected counts, the production
module resolved inside this staged checkout, all hashed inputs are unchanged and
no sentinel fired. Exit 3 when pytest or jsonschema is not importable from this
interpreter (INPUT_UNAVAILABLE: never a skip). A pass is REVIEW REQUIRED: not
full CI, source qualification or semantic acceptance; full discovery = operator-run.
"""
import sys

sys.dont_write_bytecode = True  # before any project import

import argparse  # noqa: E402
import contextlib  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import importlib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import tempfile  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / 'src'
NEW_TESTS = 'tests/unit/test_sc_metadata_object.py'
SUITES = {
    'focused': dict(files=(NEW_TESTS,), select=None, expected={NEW_TESTS: 36}),
    'contract': dict(files=('tests/unit/test_coastal_cached_intake.py', 'tests/contract/test_research_boundary.py'),
                     select=None, expected={'tests/unit/test_coastal_cached_intake.py': 18,
                                            'tests/contract/test_research_boundary.py': 8}),
    'negative': dict(files=(NEW_TESTS,), select='test_a3_', expected={NEW_TESTS: 6}),
}
HASHED = ('research/scripts/accept_sc_metadata_object.py', 'src/skippercast/coastal/cached_inventory.py',
          NEW_TESTS, 'tests/fixtures/sc_metadata_object/nonobject-cases.json',
          'tests/unit/test_coastal_cached_intake.py', 'tests/contract/test_research_boundary.py',
          'tests/_support.py', 'tests/conftest.py', 'pyproject.toml',
          'docs/engineering/sc_metadata_object.md')
BLOCKED_EVENTS = {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
                  'socket.bind', 'socket.sendto', 'socket.sendmsg', 'urllib.Request', 'http.client.connect',
                  'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork',
                  'os.forkpty', 'pty.spawn', 'webbrowser.open'}
MODEL_IMPORTS = {'openai', 'anthropic', 'ollama', 'litellm', 'google.generativeai'}
WRITE_EVENTS = {'os.mkdir', 'os.symlink', 'os.link', 'os.rename', 'os.remove', 'os.rmdir', 'os.truncate',
                'os.chmod', 'os.chown', 'os.utime', 'shutil.rmtree', 'shutil.copyfile', 'shutil.move'}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
EXIT_INPUT_UNAVAILABLE = 3


class Tee(io.TextIOBase):
    def __init__(self, stream):
        self.stream, self.text = stream, io.StringIO()

    def write(self, text):
        self.text.write(text)
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return False


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def sha256_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def input_hashes():
    hashes = {rel: sha256_file(REPO / rel) for rel in HASHED}
    for path in sorted((REPO / 'tests/fixtures/sc_metadata_object').glob('*')):
        hashes[path.relative_to(REPO).as_posix()] = sha256_file(path)
    return hashes


def git_head():
    """Read HEAD from files (subprocess is sentinel-blocked)."""
    try:
        git = REPO / '.git'
        if git.is_file():
            git = (REPO / git.read_text().split(':', 1)[1].strip()).resolve()
        head = (git / 'HEAD').read_text().strip()
        if not head.startswith('ref: '):
            return head
        ref = head[5:]
        if (git / ref).is_file():
            return (git / ref).read_text().strip()
        for line in (git / 'packed-refs').read_text().splitlines():
            if line.endswith(' ' + ref):
                return line.split()[0]
    except (OSError, IndexError):
        pass
    return None


class RunRootRefused(Exception):
    pass


def open_output_root(output):
    """Open --output from / one component at a time with O_NOFOLLOW; create missing parts."""
    text = os.fspath(output)
    absolute = text if os.path.isabs(text) else os.path.join(os.getcwd(), text)
    if '\0' in text or absolute != os.path.normpath(absolute) or absolute.startswith('//'):
        raise RunRootRefused(f'--output must be a normalized path: {text!r}')
    parts = absolute.split('/')[1:]
    if not parts or not all(parts):
        raise RunRootRefused(f'--output must name a directory below /: {text!r}')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            try:
                new = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, 0o700, dir_fd=fd)
                try:
                    new = os.open(part, flags, dir_fd=fd)
                except OSError as error:
                    raise RunRootRefused(f'refused --output at {part!r}: {error.strerror}') from None
            except OSError as error:
                raise RunRootRefused(f'refused --output at {part!r}: symlink or non-directory ({error.strerror})') from None
            os.close(fd)
            fd = new
        return fd, absolute
    except BaseException:
        os.close(fd)
        raise


def prepare_run_dir(output, started):
    root_fd, absolute = open_output_root(output)
    name = f"{started.replace(':', '').replace('.', '-')}-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        try:
            os.mkdir(name, 0o700, dir_fd=root_fd)  # exclusive: never reuse a run directory
            run_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        except OSError as error:
            raise RunRootRefused(f'cannot create run directory {name}: {error.strerror}') from None
    finally:
        os.close(root_fd)
    for sub in ('tmp', 'basetemp', 'work'):
        os.mkdir(sub, 0o700, dir_fd=run_fd)
    run_dir = os.path.join(absolute, name)
    if os.path.realpath(run_dir) != run_dir:
        os.close(run_fd)
        raise RunRootRefused(f'run directory path is not canonical: {run_dir}')
    return Path(run_dir), run_fd


def write_once(dir_fd, name, data):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=dir_fd)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)


def install_sentinels(run_dir, violations):
    allowed = str(run_dir) + os.sep

    def under_run(path):
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if isinstance(path, int):
            return True  # an already-open descriptor
        if not isinstance(path, str) or not os.path.isabs(path):
            return True  # dir_fd-relative names below a checked descriptor
        if path == os.devnull:
            return True  # pytest's logging plugin opens os.devnull when no log_file is set
        return (os.path.normpath(path) + os.sep).startswith(allowed)

    def refuse(event, detail):
        violations.append(dict(event=event, detail=repr(detail)[:240]))
        raise RuntimeError('sentinel: blocked ' + event)

    def hook(event, args):
        if event in BLOCKED_EVENTS:
            refuse(event, args)
        if event == 'import' and args and (args[0] in MODEL_IMPORTS or args[0].split('.')[0] in MODEL_IMPORTS):
            refuse('model-import', args[0])
        if event == 'open' and len(args) >= 3:
            path, mode, flags = args[0], args[1], args[2]
            writes = (isinstance(flags, int) and flags & WRITE_FLAGS) or (isinstance(mode, str) and set(mode) & set('wax+'))
            if writes and not under_run(path):
                refuse('write-outside-run', path)
        if event in WRITE_EVENTS and args and not under_run(args[0]):
            refuse(event, args[0])
    sys.addaudithook(hook)


class Collector:
    """pytest plugin: record every collected node and its final outcome."""

    def __init__(self):
        self.collected, self.deselected, self.outcomes, self.longrepr = [], [], {}, {}

    def pytest_deselected(self, items):
        self.deselected.extend(item.nodeid for item in items)

    def pytest_collection_finish(self, session):
        # After -k deselection: exactly the items that will run.
        self.collected = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report):
        current = self.outcomes.get(report.nodeid)
        if report.failed:
            self.outcomes[report.nodeid] = 'failed'
            self.longrepr[report.nodeid] = str(report.longrepr)[:4000]
        elif report.skipped and current != 'failed':
            self.outcomes[report.nodeid] = 'skipped'
        elif report.when == 'call' and report.passed and current is None:
            self.outcomes[report.nodeid] = 'passed'


def dependency_versions():
    from importlib import metadata
    found = {}
    for name in ('pytest', 'jsonschema'):
        spec = importlib.util.find_spec(name)
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            version = None
        found[name] = dict(origin=spec.origin if spec else None, version=version)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--suite', required=True, choices=sorted(SUITES))
    parser.add_argument('--output', required=True, help='run root; every existing component must be a real directory')
    args = parser.parse_args(argv)
    suite = SUITES[args.suite]

    started = utc()
    try:
        run_dir, run_fd = prepare_run_dir(args.output, started)
    except RunRootRefused as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        return 2

    # Staged import path and temp redirection BEFORE any project or pytest import.
    script_dir = str(Path(__file__).resolve().parent)
    sys.path[:] = [str(SRC), str(REPO)] + [p for p in sys.path if p not in ('', script_dir, str(SRC), str(REPO))]
    tempfile.tempdir = str(run_dir / 'tmp')
    os.environ['TMPDIR'] = str(run_dir / 'tmp')
    hashes_before = input_hashes()
    receipt = dict(schema='sc-metadata-object-acceptance-v1', suite=args.suite, argv=[sys.executable, *sys.argv],
                   cwd=os.getcwd(), started_utc=started, run_dir=str(run_dir), repo=str(REPO),
                   git_head_file_read=git_head(), python=dict(executable=sys.executable, version=sys.version),
                   dependencies=dependency_versions(), input_hashes=hashes_before,
                   pytest_files=list(suite['files']), pytest_select=suite['select'],
                   expected_counts=suite['expected'], review_status='REVIEW REQUIRED',
                   scope='local scoped acceptance only; not full CI, source qualification or semantic '
                         'acceptance; full discovery = operator-run')
    out, err = Tee(sys.stdout), Tee(sys.stderr)
    violations, controls = [], None
    missing = [name for name, found in receipt['dependencies'].items() if not found['origin']]
    if missing:
        result, exit_code = 'INPUT_UNAVAILABLE', EXIT_INPUT_UNAVAILABLE
        print(f'[{utc()}] INPUT_UNAVAILABLE: {", ".join(missing)} not importable from {sys.executable}; '
              'no suite was run or skipped (operator-staged runtime required)', file=err)
        receipt.update(missing_dependencies=missing)
    else:
        install_sentinels(run_dir, violations)
        before_modules = set(sys.modules)
        pytest_args = [*(str(REPO / f) for f in suite['files']), '-c', str(REPO / 'pyproject.toml'),
                       '--rootdir', str(REPO), '-p', 'no:cacheprovider', '--basetemp', str(run_dir / 'basetemp'),
                       '-v', '--color=no']
        if suite['select']:
            pytest_args += ['-k', suite['select']]
        receipt['pytest_args'] = pytest_args
        collector = Collector()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            print(f'[{utc()}] suite={args.suite} run_dir={run_dir} python={sys.executable}')
            try:
                import pytest
                pytest_exit = int(pytest.main(pytest_args, plugins=[collector]))
            except Exception:
                pytest_exit = -1
                print(traceback.format_exc(), file=sys.stderr)
            if args.suite == 'negative' and pytest_exit == 0:
                controls = []
                try:
                    module = sys.modules['tests.unit.test_sc_metadata_object']
                    for index, (name, mutation, contract, tag) in enumerate(module.MUTATION_CONTROLS):
                        root = run_dir / 'work' / f'control-{index}'
                        root.mkdir()
                        detected, positive, message = module.run_mutation_control(root, mutation, contract, tag)
                        controls.append(dict(control=name, mutation=mutation, contract=contract, required_tag=tag,
                                             detected=detected, positive_passed=positive, message=message))
                        print(f'CONTROL {name}: detected={detected} positive_passed={positive} :: {message}')
                except Exception:
                    controls.append(dict(control='<error>', detected=False, positive_passed=False,
                                         message=traceback.format_exc()))
                    print(traceback.format_exc(), file=sys.stderr)
        ci_module = sys.modules.get('skippercast.coastal.cached_inventory')
        receipt['production_module'] = getattr(ci_module, '__file__', None)
        receipt['imported_skippercast'] = {name: getattr(mod, '__file__', None) for name, mod in sorted(sys.modules.items())
                                           if name.split('.')[0] in ('skippercast', 'tests') and name not in before_modules}
        foreign = [f'{n}: {p}' for n, p in receipt['imported_skippercast'].items()
                   if p and not str(Path(p).resolve()).startswith(str(REPO) + os.sep)]
        violations.extend(dict(event='foreign-checkout-import', detail=d) for d in foreign)

        counts = {}
        for rel in suite['files']:
            ids = [n for n in collector.collected if n.split('::')[0] == rel]
            outcome = [collector.outcomes.get(n, 'not-run') for n in ids]
            counts[rel] = dict(collected=len(ids), passed=outcome.count('passed'), failed=outcome.count('failed'),
                               skipped=outcome.count('skipped'), not_run=outcome.count('not-run'),
                               expected=suite['expected'][rel])
        hashes_after = input_hashes()
        checks = dict(
            pytest_exit_zero=pytest_exit == 0,
            counts_match=all(c['collected'] == c['expected'] == c['passed'] for c in counts.values()),
            no_failed_skipped_or_unrun=all(c['failed'] == c['skipped'] == c['not_run'] == 0 for c in counts.values()),
            all_collected_in_named_files=len(collector.collected) == sum(c['collected'] for c in counts.values()),
            selection_exact=suite['select'] is None and not collector.deselected
            or suite['select'] is not None and all(n.split('::')[-1].startswith(suite['select'])
                                                   for n in collector.collected)
            and not any(n.split('::')[-1].startswith(suite['select']) for n in collector.deselected),
            production_module_staged=receipt['production_module'] is not None
            and Path(receipt['production_module']).resolve() == (SRC / 'skippercast/coastal/cached_inventory.py'),
            inputs_unchanged=hashes_after == hashes_before,
            no_sentinel_violations=not violations,
        )
        if controls is not None or args.suite == 'negative':
            checks['mutation_controls_detected'] = bool(controls) and all(
                c['detected'] and c['positive_passed'] for c in controls)
        ok = all(checks.values())
        result, exit_code = ('PASS', 0) if ok else ('FAIL', 1)
        receipt.update(pytest_exit=pytest_exit, collected=collector.collected, deselected=collector.deselected,
                       outcomes=collector.outcomes,
                       failures=collector.longrepr, counts=counts, checks=checks, mutation_controls=controls,
                       input_hashes_after=hashes_after, sentinel_violations=violations, sys_path=list(sys.path))
        print(f'[{utc()}] RESULT {result} suite={args.suite} counts={json.dumps(counts, sort_keys=True)} '
              f'checks={json.dumps(checks, sort_keys=True)} (REVIEW REQUIRED)', file=out)
    receipt.update(finished_utc=utc(), result=result, exit_code=exit_code)
    write_once(run_fd, 'stdout.txt', out.text.getvalue().encode())
    write_once(run_fd, 'stderr.txt', err.text.getvalue().encode())
    write_once(run_fd, 'receipt.json', (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode())
    os.close(run_fd)
    print(f'receipt: {run_dir / "receipt.json"} sha256={sha256_file(run_dir / "receipt.json")}')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
