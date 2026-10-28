"""SC-RECIPE-OFFLINE acceptance runner: focused, contract or negative suite.

    python3 research/scripts/accept_sc_recipe_offline.py --suite focused --output OUT

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

Runner-only input/output contract (not a production budget): every file the
runner reads is lstat-checked from its allowed root to the leaf (no symlink,
no '..', ancestors directories, leaf a regular file) and size-checked BEFORE it
is opened (O_NOFOLLOW|O_NONBLOCK, same inode re-checked), then bound to an
expected identity before parse/use: committed HEAD blob ids for code, pinned
sha256 for the two unchanged inputs, and the chain stdout marker ->
child-report.json -> junit.xml for child outputs. Bounds: 2 MiB per file,
16 MiB aggregate input, 4096 rows, 8 MiB aggregate report output. The 8 MiB
is split BEFORE the child starts into fixed per-artifact reservations
(OUTPUT_RESERVATIONS: stdout 1 MiB, stderr 1 MiB, junit 2 MiB, child report
2 MiB, receipt 2 MiB - 64 KiB, fallback receipt 64 KiB) that sum to exactly
8 MiB; every write is refused before it happens if it exceeds its share.
stdout/stderr are pipes drained by the parent within their shares (the child
is killed on overflow); the child runs under RLIMIT_FSIZE = 2 MiB, equal to
the share of each artifact it writes, and a 900 s timeout. Reports are
deterministic, nonfinite-free and never overwrite.
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

REPO = Path(__file__).resolve().parents[2]
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
    'validate_recipe.py', 'research/scripts/accept_sc_recipe_offline.py', NEW_TEST, COAST_TEST,
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
# Runner-only diagnostic bounds (frozen card contract). They govern what THIS
# tool reads and writes; they do not change any production API or budget.
MIB = 1024 * 1024
MAX_FILE_BYTES = 2 * MIB           # per input file read by the runner
MAX_TOTAL_INPUT_BYTES = 16 * MIB   # aggregate runner reads (parent or child)
MAX_ROWS = 4096                    # listed fixtures, tree rows, JUnit cases, git lines
MAX_OUTPUT_BYTES = 8 * MIB         # aggregate report bytes in the run directory
REPORT_MARKER = 'child-report-sha256='


class Refused(Exception):
    """A diagnostic input or output violated the runner's safety contract."""


class InputBudget:
    def __init__(self, total=MAX_TOTAL_INPUT_BYTES):
        self.total, self.used = total, 0

    def take(self, size):
        if self.used + size > self.total:
            raise Refused('refused: aggregate input budget of %d bytes exceeded' % self.total)
        self.used += size


class OutputBudget:
    """A single aggregate output cap (kept for isolated writes)."""

    def __init__(self, total=MAX_OUTPUT_BYTES):
        self.total, self.used = total, 0

    def take(self, size, slot=None):
        if self.used + size > self.total:
            raise Refused('refused: output budget of %d bytes exceeded' % self.total)
        self.used += size


# Shared report-output reservation for one run directory. Every artifact has a
# fixed share decided BEFORE the child starts; the shares sum to exactly the
# 8 MiB aggregate, so no combination of artifacts (including the fallback
# receipt, which is only written when the primary receipt was refused) can
# exceed it. Child-written artifacts get exactly the child's kernel per-file
# cap, so a child that ignored the runner still could not exceed its share.
CHILD_FILE_LIMIT = 2 * MIB
OUTPUT_RESERVATIONS = {
    'stdout': 1 * MIB,                          # parent-written from a bounded pipe
    'stderr': 1 * MIB,                          # parent-written from a bounded pipe
    'junit': CHILD_FILE_LIMIT,                  # child-written, RLIMIT_FSIZE-capped
    'child_report': CHILD_FILE_LIMIT,           # child-written, pre-write checked too
    'receipt': 2 * MIB - 64 * 1024,             # parent-written receipt.json
    'fallback_receipt': 64 * 1024,              # receipt.json when the primary is refused
}
ARTIFACTS = {'stdout': 'stdout.txt', 'stderr': 'stderr.txt', 'junit': 'junit.xml',
             'child_report': 'child-report.json'}


class OutputLedger:
    """Pre-write enforcement of fixed per-artifact output reservations."""

    def __init__(self, reservations=None, total=MAX_OUTPUT_BYTES):
        self.reservations = dict(OUTPUT_RESERVATIONS if reservations is None else reservations)
        if sum(self.reservations.values()) > total:
            raise Refused('refused: output reservations exceed the %d byte aggregate' % total)
        self.total, self.used, self.taken = total, 0, {}

    def capacity(self, slot):
        if slot not in self.reservations:
            raise Refused('refused: unknown output reservation: ' + str(slot))
        return self.reservations[slot]

    def take(self, size, slot=None):
        capacity = self.capacity(slot)
        if slot in self.taken:
            raise Refused('refused: output reservation %s already used' % slot)
        if size > capacity:
            raise Refused('refused: output reservation %s of %d bytes exceeded (%d)'
                          % (slot, capacity, size))
        self.taken[slot] = size
        self.used += size


def _checked(path, root, leaf_directory=False):
    """lstat every component from `root` to the leaf before any open.

    The path must be absolute, without '..', inside `root`; no component may be
    a symlink; ancestors must be directories and the leaf a regular file (or a
    directory when listing). Nothing is opened here."""
    path, root = Path(path), Path(root)
    if not path.is_absolute() or '..' in path.parts:
        raise Refused('refused: parent traversal or relative path: ' + str(path))
    if not (path == root or root in path.parents):
        raise Refused('refused: outside allowed root: ' + str(path))
    current = root
    components = [root] + [current := current / part for part in path.parts[len(root.parts):]]
    for index, component in enumerate(components):
        try:
            info = component.lstat()
        except FileNotFoundError:
            raise Refused('refused: missing input: ' + str(component)) from None
        if stat.S_ISLNK(info.st_mode):
            raise Refused('refused: symlink: ' + str(component))
        last = index == len(components) - 1
        if not last or leaf_directory:
            if not stat.S_ISDIR(info.st_mode):
                raise Refused('refused: not a directory: ' + str(component))
        elif not stat.S_ISREG(info.st_mode):
            raise Refused('refused: not a regular file: ' + str(component))
    return info


def git_blob_id(data):
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def read_bounded(path, root, budget, expected_sha256=None, expected_blob=None,
                 limit=MAX_FILE_BYTES):
    """Read one regular file inside `root` with every check BEFORE any byte is
    read, then bind its identity before the caller may parse or use it."""
    info = _checked(path, root)
    limit = min(limit, MAX_FILE_BYTES)
    if info.st_size > limit:
        raise Refused('refused: input exceeds %d bytes: %s' % (limit, path))
    budget.take(info.st_size)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags | getattr(os, 'O_CLOEXEC', 0))
    try:
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino)
                != (info.st_dev, info.st_ino)):
            raise Refused('refused: input changed between check and open: ' + str(path))
        chunks, size = [], 0
        while True:
            chunk = os.read(descriptor, min(1 << 16, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise Refused('refused: input exceeds %d bytes: %s' % (limit, path))
    finally:
        os.close(descriptor)
    data = b''.join(chunks)
    if size != info.st_size:
        raise Refused('refused: input size changed while reading: ' + str(path))
    if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
        raise Refused('refused: sha256 mismatch: ' + str(path))
    if expected_blob is not None and git_blob_id(data) != expected_blob:
        raise Refused('refused: git blob mismatch: ' + str(path))
    return data


def sha256_file(path, root, budget, **expected):
    return hashlib.sha256(read_bounded(path, root, budget, **expected)).hexdigest()


def list_regular_files(directory, root, rows=MAX_ROWS):
    """Names of the regular files directly in `directory`; any symlink,
    special file or subdirectory is refused rather than followed or skipped."""
    _checked(directory, root, leaf_directory=True)
    names = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(names) >= rows:
                raise Refused('refused: more than %d rows: %s' % (rows, directory))
            if not entry.is_file(follow_symlinks=False):
                raise Refused('refused: fixture entry is not a regular file: ' + entry.path)
            names.append(entry.name)
    return sorted(names)


def _serialize(value):
    try:
        return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    except ValueError as error:
        raise Refused('refused: non-finite value in report: ' + str(error)) from error


def write_bounded(run_dir, name, value, budget, limit=MAX_OUTPUT_BYTES, slot=None):
    """Deterministic, nonfinite-free, size-bounded and never-overwriting write
    of one report into a validated run directory."""
    return write_bytes_bounded(run_dir, name, _serialize(value), budget, limit, slot)


def write_bytes_bounded(run_dir, name, data, budget, limit=MAX_OUTPUT_BYTES, slot=None):
    """Write `data` as a new file only after the path, the per-file limit and
    the budget (or the artifact's ledger reservation `slot`) admitted it."""
    run_dir = Path(run_dir)
    _checked(run_dir, Path(run_dir.anchor), leaf_directory=True)
    if '/' in name or name in ('', '.', '..'):
        raise Refused('refused: report name must be a plain file name')
    if len(data) > limit:
        raise Refused('refused: output budget of %d bytes exceeded by %s' % (limit, name))
    target = run_dir / name
    if os.path.lexists(target):
        raise Refused('refused: output exists (write-once): ' + str(target))
    budget.take(len(data), slot)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(target, flags, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(data)
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    """Child-side report write, refused before writing beyond the child
    report's reservation (the kernel per-file cap backs this up)."""
    path = Path(path)
    return write_bounded(path.parent, path.name, value, OutputBudget(),
                         limit=OUTPUT_RESERVATIONS['child_report'])


def bound_report_sha256(stdout):
    """The child prints exactly one marker line binding its report's sha256."""
    found = [line[len(REPORT_MARKER):] for line in stdout.decode('utf-8', 'replace').splitlines()
             if line.startswith(REPORT_MARKER)]
    if len(found) != 1 or len(found[0]) != 64 or any(c not in '0123456789abcdef' for c in found[0]):
        raise Refused('refused: child report identity marker missing, repeated or malformed')
    return found[0]


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
    """Run one read-only git query; output is capped at the per-file input
    budget and MAX_ROWS lines (anything larger is a problem, not truncated)."""
    import subprocess
    done = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True,
                          timeout=60, check=False)
    row = {'argv': ['git', '-C', str(REPO), *args], 'exit': done.returncode,
           'stdout': done.stdout.decode('utf-8', 'replace').strip(),
           'stderr': done.stderr.decode('utf-8', 'replace').strip()[:4096]}
    if len(done.stdout) > MAX_FILE_BYTES or len(row['stdout'].splitlines()) > MAX_ROWS:
        row.update(exit=-1, stdout='', stderr='refused: git output exceeds runner bounds')
    return row


def head_tree(paths):
    """{path: blob id} for the committed HEAD entries of `paths` (regular blobs only)."""
    listing = git('ls-tree', '-r', '--full-tree', 'HEAD', '--', *paths)
    if listing['exit'] != 0:
        raise Refused('refused: git ls-tree failed: ' + listing['stderr'])
    tree = {}
    for line in listing['stdout'].splitlines():
        meta, _, name = line.partition('\t')
        mode, kind, blob = meta.split()
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise Refused('refused: committed input is not a regular blob: ' + name)
        tree[name] = blob
    return tree


def junit_counts(data, rows=MAX_ROWS):
    """Counts from already identity-bound JUnit bytes (never a path)."""
    import xml.etree.ElementTree as ElementTree
    root = ElementTree.fromstring(data)
    totals = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    by_file = {}
    for case in root.iter('testcase'):
        if totals['tests'] >= rows:
            raise Refused('refused: more than %d rows in JUnit report' % rows)
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


def collection_check(pyproject):
    """Discovery check on identity-bound pyproject.toml bytes."""
    import tomllib
    config = tomllib.loads(pyproject.decode('utf-8'))
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


def _limit_child_output():
    """Child pre-exec: no single file the child writes (JUnit, report, test
    scratch) may exceed CHILD_FILE_LIMIT, which is exactly the reservation of
    each child-written artifact. stdout/stderr are pipes, bounded by the parent."""
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE, (CHILD_FILE_LIMIT, CHILD_FILE_LIMIT))


def capture_streams(fds, caps, timeout, stop):
    """Drain pipe read ends {name: fd} keeping at most caps[name] bytes each.

    The first time any stream exceeds its cap, or the deadline passes, `stop()`
    is called once (the parent kills the child); excess bytes are discarded,
    never written. Closes every fd. Returns {name: bytes, 'refused': [...],
    'timed_out': bool}."""
    import selectors
    import time
    deadline = time.monotonic() + timeout
    kept = {name: bytearray() for name in fds}
    over = {name: False for name in fds}
    stopped, timed_out = False, False
    selector = selectors.DefaultSelector()
    try:
        for name, fd in fds.items():
            selector.register(fd, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(min(remaining, 1.0)):
                name = key.data
                chunk = os.read(key.fd, 1 << 16)
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                room = caps[name] - len(kept[name])
                kept[name] += chunk[:max(room, 0)]
                if len(chunk) > room and not over[name]:
                    over[name] = True
                    if not stopped:
                        stopped = True
                        stop()
        if timed_out and not stopped:
            stopped = True
            stop()
    finally:
        selector.close()
        for fd in fds.values():
            os.close(fd)
    result = {name: bytes(data) for name, data in kept.items()}
    result['refused'] = ['refused: %s capture exceeds %d bytes' % (name, caps[name])
                         for name in fds if over[name]]
    result['timed_out'] = timed_out
    return result


def launch_child(argv, env, ledger, timeout=CHILD_TIMEOUT_SECONDS):
    """Start the child with piped stdout/stderr bounded by their reservations."""
    import subprocess
    process = subprocess.Popen(argv, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               preexec_fn=_limit_child_output)
    fds = {'stdout': os.dup(process.stdout.fileno()), 'stderr': os.dup(process.stderr.fileno())}
    process.stdout.close()
    process.stderr.close()
    captured = capture_streams(fds, {name: ledger.capacity(name) for name in fds}, timeout,
                               stop=process.kill)
    try:
        captured['exit'] = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        captured['exit'] = process.wait()
    if captured['timed_out']:
        captured['refused'].append('child timed out')
    return captured


def settle_child(run_dir, launched, reads, ledger, problems):
    """Write the bounded captures under their reservations, then accept the
    child-written report and JUnit only within their reservations and only
    through the identity chain stdout marker -> child-report.json -> junit.xml.
    Returns (child fields, report, counts, by_file); problems are appended."""
    child = {'exit': launched['exit']}
    problems.extend(launched.get('refused', []))
    report, counts, by_file = None, {}, {}
    try:
        for slot in ('stdout', 'stderr'):
            child[slot + '_sha256'] = write_bytes_bounded(run_dir, ARTIFACTS[slot],
                                                          launched[slot], ledger, slot=slot)
        if launched['exit'] is not None:
            report_sha256 = bound_report_sha256(launched['stdout'])
            raw_report = read_bounded(run_dir / ARTIFACTS['child_report'], run_dir, reads,
                                      expected_sha256=report_sha256,
                                      limit=ledger.capacity('child_report'))
            ledger.take(len(raw_report), 'child_report')
            report = json.loads(raw_report, parse_constant=_no_constant)
            child['child_report_sha256'] = report_sha256
            expected_junit = report.get('junit_sha256') if isinstance(report, dict) else None
            if not (isinstance(expected_junit, str) and len(expected_junit) == 64):
                raise Refused('refused: child report carries no JUnit identity')
            junit = read_bounded(run_dir / ARTIFACTS['junit'], run_dir, reads,
                                 expected_sha256=expected_junit, limit=ledger.capacity('junit'))
            ledger.take(len(junit), 'junit')
            child['junit_sha256'] = expected_junit
            counts, by_file = junit_counts(junit)
    except (Refused, ValueError) as error:
        problems.append(str(error))
        counts, by_file = {}, {}
    return child, report, counts, by_file


def write_receipt(run_dir, receipt, minimal, ledger, problems):
    """receipt.json within its reservation; if refused, a minimal FAIL receipt
    within the separate fallback reservation. Both shares are pre-reserved."""
    try:
        return write_bounded(run_dir, 'receipt.json', receipt, ledger, slot='receipt')
    except Refused as error:
        problems.append(str(error))
    fallback = dict(minimal, status='FAIL',
                    problems=[str(problem)[:512] for problem in problems[-16:]])
    return write_bounded(run_dir, 'receipt.json', fallback, ledger, slot='fallback_receipt')


def parent(args):
    import platform
    import time
    run_dir = new_run_dir(args.output)
    problems = []
    reads = InputBudget()
    ledger = OutputLedger()
    head = git('rev-parse', 'HEAD')
    ancestry = git('merge-base', '--is-ancestor', BASE, 'HEAD')
    if ancestry['exit'] != 0:
        problems.append('base ' + BASE + ' is not an ancestor of HEAD')
    status = git('status', '--porcelain', '--untracked-files=all')
    changed = git('diff', '--name-only', BASE, 'HEAD')
    pins, inputs, fixtures, collection = {}, {}, {}, None
    try:
        # Every input is bound to its committed HEAD blob before parse or use;
        # the two unchanged inputs are additionally bound to their frozen sha256.
        tree = head_tree(CODE_INPUTS + [FIXTURE_DIR])
        missing = [name for name in CODE_INPUTS if name not in tree]
        if missing:
            raise Refused('refused: input not committed at HEAD: ' + ', '.join(missing))
        for name in CODE_INPUTS:
            data = read_bounded(REPO / name, REPO, reads, expected_blob=tree[name],
                                expected_sha256=PINNED.get(name))
            inputs[name] = hashlib.sha256(data).hexdigest()
            if name in PINNED:
                pins[name] = inputs[name]
            if name == 'pyproject.toml':
                collection = collection_check(data)
        listed = list_regular_files(REPO / FIXTURE_DIR, REPO)
        committed = sorted(name.rsplit('/', 1)[1] for name in tree
                           if name.startswith(FIXTURE_DIR + '/'))
        if listed != committed:
            raise Refused('refused: fixture directory differs from HEAD tree')
        for name in listed:
            relative = FIXTURE_DIR + '/' + name
            fixtures[relative] = sha256_file(REPO / relative, REPO, reads,
                                             expected_blob=tree[relative])
    except Refused as error:
        problems.append(str(error))
    if collection is not None and not collection['ok']:
        problems.append('new or contract test file is outside pyproject discovery')
    python = Path(args.python) if args.python else REPO / '.venv' / 'bin' / 'python3'
    if not python.is_absolute() or not os.access(python, os.X_OK):
        problems.append('child interpreter is not an executable absolute path: ' + str(python))
    env = {key: value for key, value in os.environ.items()
           if key not in SCRUBBED_ENV and not key.startswith('LD_')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONNOUSERSITE'] = '1'
    argv = [str(python), '-B', str(Path(__file__).resolve()), '--child', args.suite,
            '--run-dir', str(run_dir)]
    child = {'argv': argv, 'cwd': str(REPO), 'exit': None,
             'file_size_limit_bytes': CHILD_FILE_LIMIT}
    report, counts, by_file = None, {}, {}
    if not problems:
        started = time.time()
        try:
            launched = launch_child(argv, env, ledger)
        except OSError as error:
            launched = None
            problems.append('child could not start: ' + type(error).__name__)
        child['seconds'] = round(time.time() - started, 3)
        if launched is not None:
            settled, report, counts, by_file = settle_child(run_dir, launched, reads, ledger,
                                                            problems)
            child.update(settled)
        if child['exit'] != 0:
            problems.append('child exited ' + str(child['exit']))
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
        'bounds': {'max_file_bytes': MAX_FILE_BYTES, 'max_total_input_bytes': MAX_TOTAL_INPUT_BYTES,
                   'max_rows': MAX_ROWS, 'max_output_bytes': MAX_OUTPUT_BYTES,
                   'child_file_limit_bytes': CHILD_FILE_LIMIT,
                   'output_reservations': ledger.reservations,
                   'input_bytes_read': reads.used,
                   'report_bytes_before_receipt': ledger.used},
        'problems': problems,
    }
    minimal = {'card': 't_b73efb9a', 'suite': args.suite, 'child_exit': child['exit']}
    receipt_sha256 = write_receipt(run_dir, receipt, minimal, ledger, problems)
    summary = {'suite': args.suite, 'status': 'PASS' if not problems else 'FAIL',
               'counts': counts, 'counts_by_file': by_file, 'head': head['stdout'],
               'run_dir': str(run_dir), 'receipt_sha256': receipt_sha256, 'problems': problems}
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0 if not problems else 1


def _no_constant(value):
    raise ValueError('refused: non-finite literal in child report: ' + value)


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
    try:
        junit_sha256 = sha256_file(run_dir / 'junit.xml', run_dir, InputBudget())
    except Refused as error:
        junit_sha256 = None
        CALLS.append(str(error))     # forces ok=False below
    report = {
        'pytest_argv': requested, 'pytest_exit': exit_code, 'interpreter': sys.executable,
        'interpreter_realpath': os.path.realpath(sys.executable), 'version': sys.version,
        'prefix': sys.prefix, 'prefix_realpath': os.path.realpath(sys.prefix),
        'dont_write_bytecode': sys.dont_write_bytecode,
        'versions': {name: importlib.metadata.version(name)
                     for name in ('jsonschema', 'referencing', 'pytest')},
        'preloaded_before_sentinels': preloaded, 'sentinel_calls': CALLS[:MAX_ROWS],
        'sentinel_call_count': len(CALLS),
        'imported_module_count': len(set(IMPORTS)),
        'modules_outside_staged_roots': outside[:MAX_ROWS],
        'modules_outside_count': len(outside), 'project_modules': project,
        'mutation_proof': mutation, 'junit_sha256': junit_sha256,
    }
    ok = (exit_code == 0 and not CALLS and not outside and not preloaded
          and project.get('validate_recipe') == str(REPO / 'validate_recipe.py')
          and 'skippercast' not in project
          and (args.suite != 'negative' or (mutation is not None and mutation['ok'])))
    report['ok'] = ok
    digest = write_json(run_dir / 'child-report.json', report)
    print(REPORT_MARKER + digest)
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
