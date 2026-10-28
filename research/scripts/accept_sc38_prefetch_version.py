"""Offline acceptance runner for SC38-PREFETCH-VERSION (integer coast plan schema_version).

    python3 research/scripts/accept_sc38_prefetch_version.py --suite focused|contract|negative --output DIR

Runs literal pytest selectors through the installed pytest API, in this staged
checkout only. Bytecode writing is disabled first. The runner uses only the
interpreter that invoked it; it never re-executes itself or selects another
runtime. If that interpreter cannot import pytest it writes an
INPUT_UNAVAILABLE receipt and exits 3 (the staging owner supplies the runtime).

Before any product import or test collection it creates a new write-once run
directory under DIR, points HOME and TMPDIR into it (prefetch derives MIRROR,
RETRY_STATE and STATUS from Path.home() at import), drops SKIPPERCAST_ROOT,
SKIPPERCAST_HTTP_CACHE and SKIPPERCAST_NETWORK, puts this checkout's src/ first
on sys.path (dropping any other skippercast source path) and installs
audit-hook sentinels for network, subprocess/exec, model-client imports and
writes outside the run directory.

prefetch hard-codes ``MOUNT = Path('/mnt/agentorange-backup')`` and binds MOUNT,
RAW, MIRROR and STATUS into ``Prefetch.__init__`` keyword defaults when the
module executes. So, still before collection, the runner executes the genuine
prefetch.py itself with one documented test-only path substitution: that single
MOUNT line points at <run_dir>/mount. No other byte changes (the receipt records
both source hashes and the one changed line); the code object keeps the real
file name, so inspect/linecache still read the genuine file. It then verifies
that every module path constant, every bound path default, Path.home() (the
lock_dir default) and the temp directory are inside the run directory, and
installs operational guards that record a violation and raise: constructing
Prefetch, constructing TransferSession without an injected resolver and
connection factory, and prefetch's default_allowlist. Tests that need their
own refusals still install them; the runner's guards apply to every suite.

Each run writes DIR/<utc>-<pid>-<token>/{receipt.json,stdout.txt,stderr.txt}.
Exit 0 only when pytest exits 0, the collected node IDs equal the frozen list
exactly, every one passed (no skip, xfail or collection error), no sentinel
fired, the import boundary held and every skippercast module came from this
checkout. A pass is REVIEW REQUIRED: not full CI, source/live qualification or
semantic acceptance; full discovery = operator-run.
"""
import sys

sys.dont_write_bytecode = True  # before any other import

import argparse  # noqa: E402
import contextlib  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
SCHEMA = 'sc38-prefetch-version-acceptance-v2'
PREFETCH_MODULE = 'skippercast.coastal.prefetch'
PREFETCH_REL = 'src/skippercast/coastal/prefetch.py'
# The only line the test-only staging substitutes (path plumbing, not logic).
MOUNT_LINE = "MOUNT = Path('/mnt/agentorange-backup')"
PATH_CONSTANTS = ('MOUNT', 'RAW', 'MIRROR', 'RETRY_STATE', 'STATUS')
BOUND_PATH_DEFAULTS = ('root', 'mirror', 'status', 'mount')
SCRUBBED_ENV = ('SKIPPERCAST_ROOT', 'SKIPPERCAST_HTTP_CACHE', 'SKIPPERCAST_NETWORK')

NEW = 'tests/unit/test_sc38_prefetch_version.py'
OLD = 'tests/unit/test_coast_prefetch.py'
BOUNDARY = 'tests/contract/test_research_boundary.py'
LAYOUT = 'tests/contract/test_test_layout.py'
REJECTED = ('true', 'false', 'float-1.0', 'exponent-1e0', 'string-1', 'null', 'object', 'object-1',
            'list', 'list-1', 'zero', 'two', 'negative-1')
MUTATION = ('true', 'float-1.0', 'exponent-1e0', 'healthy-integer-1')
NEGATIVE_IDS = [f'{NEW}::test_mutation_controls[{case}]' for case in MUTATION]
FOCUSED_IDS = [
    f'{NEW}::test_isolation_redirects_paths_and_blocks_transfer',
    f'{NEW}::test_a1_integer_version_plan_loads_and_dry_run_totals_are_preserved',
    f'{NEW}::test_a1_conflicting_duplicate_still_refused_with_integer_version',
    *[f'{NEW}::test_a2_non_integer_or_wrong_version_is_held_before_io[{case}]' for case in REJECTED],
    f'{NEW}::test_a2_absent_version_is_held_before_io',
    f'{NEW}::test_a2_decoded_bool_and_float_versions_are_the_cases_baseline_missed',
    f'{NEW}::test_a2_files_array_check_is_independent_of_a_valid_version',
    f'{NEW}::test_a2_empty_plan_hold_is_independent_of_a_valid_version',
    *NEGATIVE_IDS,
]
CONTRACT_IDS = [
    f'{OLD}::test_dry_run_deduplicates_shared_sources_in_campaign_order',
    *[f'{OLD}::test_bad_inventory_is_refused_before_io[update{n}]' for n in range(10)],
    f'{OLD}::test_duplicate_conflicting_hash_refused',
    f'{OLD}::test_empty_plan_cannot_report_complete',
    *[f'{BOUNDARY}::ResearchBoundaryTest::{name}' for name in (
        'test_app_and_worker_do_not_load_receipts', 'test_new_research_scripts_do_not_land_in_scripts',
        'test_product_python_never_imports_research', 'test_product_scripts_never_run_research',
        'test_product_workflows_run_no_research', 'test_research_scripts_compile',
        'test_research_workflows_publish_nothing', 'test_web_and_worker_never_import_research')],
    *[f'{LAYOUT}::LayoutTest::{name}' for name in (
        'test_every_layer_is_a_package', 'test_every_module_is_in_a_layer',
        'test_gis_imports_only_in_gis_directories', 'test_gis_package_list_matches_the_survey_requirements',
        'test_no_path_hacks_or_file_relative_roots', 'test_node_test_modules_match_the_standard_suite_glob',
        'test_product_tests_never_read_the_real_clock',
        'test_shared_survey_packages_are_pinned_the_same_in_the_test_extra')],
]
# Literal pytest selectors per suite (paths relative to the repository).
SELECTORS = {
    'focused': [NEW],
    'contract': [f'{OLD}::test_dry_run_deduplicates_shared_sources_in_campaign_order',
                 f'{OLD}::test_bad_inventory_is_refused_before_io',
                 f'{OLD}::test_duplicate_conflicting_hash_refused',
                 f'{OLD}::test_empty_plan_cannot_report_complete',
                 BOUNDARY, LAYOUT],
    'negative': [f'{NEW}::test_mutation_controls'],
}
EXPECTED = {'focused': FOCUSED_IDS, 'contract': CONTRACT_IDS, 'negative': NEGATIVE_IDS}
HASHED = ('src/skippercast/coastal/prefetch.py', 'src/skippercast/http.py', NEW, OLD, BOUNDARY, LAYOUT,
          'tests/conftest.py', 'tests/_support.py', 'pyproject.toml',
          'research/scripts/accept_sc38_prefetch_version.py', 'docs/engineering/sc38_prefetch_version.md')
FIXTURE_DIR = 'tests/fixtures/sc38_prefetch_version'
PACKAGES = ('pytest', 'pluggy', 'iniconfig', 'packaging')

BLOCKED_EVENTS = {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
                  'socket.bind', 'socket.sendto', 'socket.sendmsg', 'urllib.Request', 'http.client.connect',
                  'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork',
                  'os.forkpty', 'pty.spawn', 'webbrowser.open'}
MODEL_IMPORTS = {'openai', 'anthropic', 'ollama', 'google.generativeai', 'litellm'}
WRITE_EVENTS = {'os.mkdir', 'os.symlink', 'os.link', 'os.rename', 'os.remove', 'os.rmdir', 'os.truncate',
                'os.chmod', 'os.chown', 'os.utime', 'shutil.rmtree', 'shutil.copyfile', 'shutil.move'}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


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


class RunRootRefused(Exception):
    """--output is unsafe (symlink, non-directory, not normalized); nothing was written."""


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def sha256_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def git_head():
    """(HEAD commit, ref) read from files; subprocess is sentinel-blocked."""
    try:
        git = REPO / '.git'
        if git.is_file():
            git = (REPO / git.read_text().split(':', 1)[1].strip()).resolve()
        head = (git / 'HEAD').read_text().strip()
        if not head.startswith('ref: '):
            return head, None
        ref = head[5:]
        common = git
        if (git / 'commondir').is_file():
            common = (git / (git / 'commondir').read_text().strip()).resolve()
        for base in (git, common):
            if (base / ref).is_file():
                return (base / ref).read_text().strip(), ref
        for line in (common / 'packed-refs').read_text().splitlines():
            if line.endswith(' ' + ref):
                return line.split()[0], ref
        return None, ref
    except (OSError, IndexError):
        return None, None


def open_output_root(output):
    """Open --output from / one component at a time with O_NOFOLLOW, creating missing parts."""
    text = os.fspath(output)
    absolute = text if os.path.isabs(text) else os.path.join(os.getcwd(), text)
    if '\0' in text or absolute != os.path.normpath(absolute) or absolute.startswith('//'):
        raise RunRootRefused(f'--output must be a normalized path (no ., .., // or trailing /): {text}')
    parts = absolute.split('/')[1:]
    if not parts or not all(parts):
        raise RunRootRefused(f'--output must name a directory below /: {text}')
    no_follow = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            try:
                new = os.open(part, no_follow, dir_fd=fd)
            except FileNotFoundError:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, 0o700, dir_fd=fd)
                try:
                    new = os.open(part, no_follow, dir_fd=fd)
                except OSError as error:
                    raise RunRootRefused(f'refused --output {absolute} at {part!r}: {error.strerror}') from None
            except OSError as error:
                raise RunRootRefused(f'refused --output {absolute} at {part!r}: symlink or non-directory '
                                     f'({error.strerror})') from None
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
            os.mkdir(name, 0o700, dir_fd=root_fd)  # exclusive; an existing name is refused
            run_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        except OSError as error:
            raise RunRootRefused(f'cannot create run directory {name} in {absolute}: {error.strerror}') from None
    finally:
        os.close(root_fd)
    for sub in ('tmp', 'home'):
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
        if not isinstance(path, str) or not os.path.isabs(path):
            return True  # descriptor-relative names below an already checked directory
        if path == os.devnull:
            return True  # pytest's logging plugin opens its default log_file, os.devnull
        return (os.path.normpath(path) + os.sep).startswith(allowed)

    def refuse(kind, detail):
        violations.append(dict(event=kind, detail=repr(detail)[:200]))
        raise RuntimeError('sentinel: ' + kind)

    def hook(event, args):
        if event in BLOCKED_EVENTS:
            refuse(event, args)
        if event == 'import' and args and args[0] in MODEL_IMPORTS:
            refuse('model-import', args[0])
        if event == 'open' and len(args) >= 3:
            mode, flags = args[1], args[2]
            writes = (isinstance(flags, int) and flags & WRITE_FLAGS) or \
                (isinstance(mode, str) and set(mode) & set('wax+'))
            if writes and not under_run(args[0]):
                refuse('write-outside-run', args[0])
        if event in WRITE_EVENTS and args and not under_run(args[0]):
            refuse(event, args[0])
    sys.addaudithook(hook)


def isolate_import_path():
    """This checkout's src/ and root first; drop other skippercast sources and the script dir."""
    src, removed = str(REPO / 'src'), []
    keep = []
    for entry in sys.path:
        resolved = os.path.realpath(entry or os.getcwd())
        if entry in ('', str(SCRIPT.parent)) or resolved in (src, str(REPO)):
            continue
        if os.path.isdir(os.path.join(resolved, 'skippercast')):
            removed.append(entry)
            continue
        keep.append(entry)
    sys.path[:] = [src, str(REPO), *keep]
    return removed


class Recorder:
    """pytest plugin: collected node IDs, per-phase outcomes and collection errors."""

    def __init__(self):
        self.collected, self.reports, self.collect_errors = [], {}, []

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.collect_errors.append(dict(nodeid=report.nodeid, longrepr=str(report.longrepr)))

    def pytest_runtest_logreport(self, report):
        entry = self.reports.setdefault(report.nodeid, {})
        entry[report.when] = dict(outcome=report.outcome, xfail=hasattr(report, 'wasxfail'),
                                  longrepr=str(report.longrepr) if report.failed else '')


class StagingRefused(Exception):
    """The genuine prefetch source could not be staged safely; nothing was imported."""


def stage_prefetch(run_dir):
    """Execute the genuine prefetch.py with only its MOUNT line pointed into the run directory.

    Must run before anything imports prefetch. Returns (module, evidence).
    """
    import importlib
    import importlib.util
    if PREFETCH_MODULE in sys.modules:
        raise StagingRefused(f'{PREFETCH_MODULE} was imported before staging')
    path = REPO / PREFETCH_REL
    data = path.read_bytes()
    source = data.decode('utf-8')
    lines = source.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if line.rstrip('\n') == MOUNT_LINE]
    if len(hits) != 1:
        raise StagingRefused(f'expected exactly one {MOUNT_LINE!r} line, found {len(hits)}')
    mount = run_dir / 'mount'
    replacement = f'MOUNT = Path({str(mount)!r})\n'
    staged_lines = list(lines)
    staged_lines[hits[0]] = replacement
    staged = ''.join(staged_lines)
    changed = [dict(line=i + 1, genuine=a.rstrip('\n'), staged=b.rstrip('\n'))
               for i, (a, b) in enumerate(zip(lines, staged_lines)) if a != b]
    if len(changed) != 1 or len(staged_lines) != len(lines):
        raise StagingRefused('staging changed more than the MOUNT line')
    importlib.import_module('skippercast.coastal')  # package __init__ only (docstring)
    spec = importlib.util.spec_from_file_location(PREFETCH_MODULE, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[PREFETCH_MODULE] = module
    try:
        # dont_inherit: only the file's own future imports apply, as in a normal import.
        exec(compile(staged, str(path), 'exec', dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(PREFETCH_MODULE, None)
        raise
    setattr(sys.modules['skippercast.coastal'], 'prefetch', module)
    evidence = dict(kind='test-only path substitution before module execution (path plumbing only)',
                    module=module.__file__, genuine_sha256=hashlib.sha256(data).hexdigest(),
                    staged_sha256=hashlib.sha256(staged.encode('utf-8')).hexdigest(),
                    changed_lines=changed, line_count=len(lines))
    return module, evidence


def inside(path, run_dir):
    return (os.path.normpath(os.path.abspath(os.fspath(path))) + os.sep).startswith(str(run_dir) + os.sep)


def install_operational_guards(prefetch, violations):
    """Record and refuse operational constructors before collection, in every suite."""
    def refused(kind):
        violations.append(dict(event=kind, detail='operational path reached'))
        raise RuntimeError('sentinel: ' + kind)

    prefetch_init = prefetch.Prefetch.__init__

    def prefetch_guard(self, *args, **kwargs):
        refused('Prefetch-constructor')
    # Keep the (already redirected) bound defaults visible to tests that inspect them.
    prefetch_guard.__kwdefaults__ = dict(prefetch_init.__kwdefaults__)
    prefetch.Prefetch.__init__ = prefetch_guard

    transfer_init = prefetch.TransferSession.__init__

    def transfer_guard(self, *args, **kwargs):
        # Only inert test helpers: an injected resolver and connection factory.
        if not (callable(kwargs.get('resolver')) and callable(kwargs.get('connection_factory'))):
            refused('TransferSession-without-injected-transport')
        return transfer_init(self, *args, **kwargs)
    prefetch.TransferSession.__init__ = transfer_guard

    def allowlist_guard(*args, **kwargs):
        refused('prefetch-default_allowlist')
    prefetch.default_allowlist = allowlist_guard
    return dict(Prefetch_init=prefetch.Prefetch.__init__ is prefetch_guard,
                TransferSession_init=prefetch.TransferSession.__init__ is transfer_guard,
                default_allowlist=prefetch.default_allowlist is allowlist_guard)


def import_boundary(run_dir, violations):
    """Fresh-process, pre-collection boundary: stage prefetch, verify every path, install guards."""
    import pathlib
    prefetch, staging = stage_prefetch(run_dir)
    constants = {name: str(getattr(prefetch, name)) for name in PATH_CONSTANTS}
    kwdefaults = prefetch.Prefetch.__init__.__kwdefaults__ or {}
    bound = {name: str(kwdefaults.get(name)) for name in BOUND_PATH_DEFAULTS}
    runtime = dict(path_home=str(pathlib.Path.home()), tempdir=tempfile.gettempdir(),
                   lock_dir_default=str(pathlib.Path.home() / '.cache/skippercast/coast-prefetch'))
    env = {name: os.environ.get(name) for name in SCRUBBED_ENV}
    guards = install_operational_guards(prefetch, violations)
    # Probe each guard once: it must raise and record. Probe records are moved to the receipt.
    probes, mark = {}, len(violations)
    for name, call in (('Prefetch', lambda: prefetch.Prefetch({}, None)),
                       ('TransferSession', lambda: prefetch.TransferSession()),
                       ('default_allowlist', lambda: prefetch.default_allowlist())):
        try:
            call()
            probes[name] = 'NOT REFUSED'
        except RuntimeError as error:
            probes[name] = str(error)
    probe_records = violations[mark:]
    del violations[mark:]
    checks = dict(
        module_is_this_checkout=prefetch.__file__ == str(REPO / PREFETCH_REL),
        single_mount_line_substituted=len(staging['changed_lines']) == 1,
        genuine_source_matches_receipt_hash=staging['genuine_sha256'] == sha256_file(REPO / PREFETCH_REL),
        constants_inside_run_dir=all(inside(v, run_dir) for v in constants.values()),
        bound_defaults_inside_run_dir=bool(kwdefaults) and all(inside(v, run_dir) for v in bound.values()),
        runtime_defaults_inside_run_dir=all(inside(v, run_dir) for v in runtime.values()),
        scrubbed_environment=all(v is None for v in env.values()),
        guards_installed_before_collection=all(guards.values()),
        guards_refuse_and_record=(all(v.startswith('sentinel: ') for v in probes.values())
                                  and len(probe_records) == 3),
    )
    return dict(ok=all(checks.values()), checks=checks, run_dir=str(run_dir), staging=staging,
                path_constants=constants, bound_path_defaults=bound, runtime_defaults=runtime,
                scrubbed_environment=env, guards=guards, guard_probes=probes, guard_probe_records=probe_records)


def package_versions():
    from importlib import metadata
    found = {}
    for name in PACKAGES:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = None
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--suite', required=True, choices=sorted(SELECTORS))
    parser.add_argument('--output', required=True, help='run root; every component must be a real directory')
    args = parser.parse_args(argv)

    try:
        import pytest  # noqa: F401
        have_pytest = True
    except ImportError:
        have_pytest = False

    started = utc()
    try:
        run_dir, run_fd = prepare_run_dir(args.output, started)
    except RunRootRefused as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        return 2
    head, ref = git_head()
    receipt = dict(schema=SCHEMA, suite=args.suite, argv=list(sys.argv), cwd=os.getcwd(), started_utc=started,
                   run_dir=str(run_dir), repo=str(REPO), git_head_file_read=head, git_ref=ref,
                   python=dict(executable=sys.executable, version=sys.version, prefix=sys.prefix,
                               runtime_selection='invoking interpreter only; no re-exec or fallback'),
                   code_hashes={rel: sha256_file(REPO / rel) for rel in HASHED},
                   fixture_hashes={f.name: sha256_file(f) for f in sorted((REPO / FIXTURE_DIR).glob('*'))},
                   selectors=SELECTORS[args.suite], expected_ids=EXPECTED[args.suite],
                   review_status='REVIEW REQUIRED',
                   scope='local scoped acceptance only; not full CI, source/live qualification or semantic '
                         'acceptance; full discovery = operator-run')
    if not have_pytest:
        receipt.update(result='INPUT_UNAVAILABLE', exit_code=3, finished_utc=utc(),
                       detail='pytest is not importable by the invoking interpreter; the runner does not '
                              'select another runtime. The staging owner must supply a qualified runtime.')
        write_once(run_fd, 'receipt.json', (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode())
        os.close(run_fd)
        print(f'INPUT_UNAVAILABLE: pytest not importable by {sys.executable}; receipt '
              + str(run_dir / 'receipt.json'), file=sys.stderr)
        return 3

    # Redirect HOME/TMPDIR, scrub path/cache env and fix the import path BEFORE any product import.
    os.environ['HOME'] = str(run_dir / 'home')
    os.environ['TMPDIR'] = str(run_dir / 'tmp')
    tempfile.tempdir = str(run_dir / 'tmp')
    for name in SCRUBBED_ENV:
        os.environ.pop(name, None)
    receipt['sys_path_removed'] = isolate_import_path()
    violations = []
    install_sentinels(run_dir, violations)
    receipt['package_versions'] = package_versions()

    out_tee, err_tee = Tee(sys.stdout), Tee(sys.stderr)
    recorder, boundary, exit_code = Recorder(), None, None
    import pytest
    before = set(sys.modules)
    with contextlib.redirect_stdout(out_tee), contextlib.redirect_stderr(err_tee):
        print(f'[{utc()}] suite={args.suite} run_dir={run_dir} python={sys.executable}')
        try:
            boundary = import_boundary(run_dir, violations)
            print(f"BOUNDARY ok={boundary['ok']} checks={boundary['checks']}")
            print(f"BOUNDARY path_constants={boundary['path_constants']}")
            print(f"BOUNDARY bound_path_defaults={boundary['bound_path_defaults']}")
            print(f"BOUNDARY staging_changed_lines={boundary['staging']['changed_lines']}")
            if not boundary['ok']:
                raise StagingRefused('pre-collection boundary failed; pytest not started')
            pytest_args = ['-c', str(REPO / 'pyproject.toml'), '--rootdir', str(REPO), '-p', 'no:cacheprovider',
                           '--basetemp', str(run_dir / 'pytest-tmp'), '--capture=sys', '-v', '-rA',
                           *[str(REPO / s.split('::', 1)[0]) + ('::' + s.split('::', 1)[1] if '::' in s else '')
                             for s in SELECTORS[args.suite]]]
            receipt['pytest_args'] = pytest_args
            exit_code = int(pytest.main(pytest_args, plugins=[recorder]))
        except Exception as error:  # recorded as a failure, never a pass
            recorder.collect_errors.append(dict(nodeid='<runner>', longrepr=repr(error)))
            print('RUNNER ERROR ' + repr(error), file=sys.stderr)

    imported, foreign = {}, []
    for name in sorted(set(sys.modules) | before):
        if name == 'skippercast' or name.startswith('skippercast.'):
            path = getattr(sys.modules.get(name), '__file__', None)
            imported[name] = path
            if path and not path.startswith(str(REPO / 'src') + os.sep):
                foreign.append(f'{name}: {path}')
    expected = EXPECTED[args.suite]
    outcomes = {}
    for nodeid in recorder.collected:
        phases = recorder.reports.get(nodeid, {})
        passed = (all(phases.get(w, {}).get('outcome') == 'passed' for w in ('setup', 'call', 'teardown'))
                  and not any(v.get('xfail') for v in phases.values()))
        outcomes[nodeid] = 'passed' if passed else next(
            (f"{w}:{phases[w]['outcome']}" for w in ('setup', 'call', 'teardown')
             if w in phases and phases[w]['outcome'] != 'passed'), 'incomplete')
    checks = dict(
        pytest_exit_zero=exit_code == 0,
        collected_equals_expected=recorder.collected == expected,
        no_duplicate_ids=len(set(recorder.collected)) == len(recorder.collected),
        all_passed=bool(outcomes) and all(v == 'passed' for v in outcomes.values()),
        no_collection_errors=not recorder.collect_errors,
        no_sentinel_violations=not violations,
        import_boundary=bool(boundary and boundary['ok']),
        only_this_checkout_imported=not foreign and bool(imported),
        pytest_available=receipt['package_versions'].get('pytest') is not None,
    )
    if args.suite == 'negative':
        checks['mutation_detected_and_healthy_control_passed'] = all(
            outcomes.get(nodeid) == 'passed' for nodeid in NEGATIVE_IDS)
    ok = all(checks.values())
    counts = dict(collected=len(recorder.collected), expected=len(expected),
                  passed=sum(v == 'passed' for v in outcomes.values()),
                  failed=sum(v != 'passed' for v in outcomes.values()),
                  missing=sorted(set(expected) - set(recorder.collected)),
                  unexpected=sorted(set(recorder.collected) - set(expected)))
    summary = (f"[{utc()}] RESULT {'PASS' if ok else 'FAIL'} suite={args.suite} collected={counts['collected']} "
               f"expected={counts['expected']} passed={counts['passed']} failed={counts['failed']} "
               f"pytest_exit={exit_code} sentinel_violations={len(violations)} (REVIEW REQUIRED)")
    print(summary, file=out_tee)
    for name, value in checks.items():
        print(f'CHECK {name}={value}', file=out_tee)
    receipt.update(finished_utc=utc(), pytest_exit_code=exit_code, collected_ids=recorder.collected,
                   outcomes=outcomes, phase_reports=recorder.reports, collect_errors=recorder.collect_errors,
                   counts=counts, checks=checks, import_boundary=boundary, sentinel_violations=violations,
                   imported_skippercast=imported, foreign_imports=foreign, sys_path=list(sys.path),
                   result='PASS' if ok else 'FAIL', exit_code=0 if ok else 1)
    stdout_bytes, stderr_bytes = out_tee.text.getvalue().encode(), err_tee.text.getvalue().encode()
    receipt['stdout_sha256'] = hashlib.sha256(stdout_bytes).hexdigest()
    receipt['stderr_sha256'] = hashlib.sha256(stderr_bytes).hexdigest()
    write_once(run_fd, 'stdout.txt', stdout_bytes)
    write_once(run_fd, 'stderr.txt', stderr_bytes)
    write_once(run_fd, 'receipt.json', (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode())
    os.close(run_fd)
    print(f'receipt: {run_dir / "receipt.json"} sha256={sha256_file(run_dir / "receipt.json")}')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
