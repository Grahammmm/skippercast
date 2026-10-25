#!/usr/bin/env python3
"""BM1-RENDER-PRIVATE acceptance runner (stdlib only).

Usage: python3 scripts/accept_bm1_render_private.py --suite {focused,compatibility,negative,isolation}
           --output-root <absolute directory outside this repository>

The runner is the file-launched process. It first re-executes itself once with
the same argv under ``-I -B`` (isolated, no bytecode). It then refuses bad
arguments or output roots before writing, creates a fresh unique child of the
output root and records argv/cwd/interpreter, git HEAD and dirty state,
source/test hashes and the frozen brief hash. Only then does it install the
offline sentinels, redirect tempfile/TMPDIR/HOME into the run directory and put
the repository (``src`` first) on sys.path, BEFORE importing the test module
or any project module. The selected test classes run in this process with
their stdout/stderr captured raw; an isolation report (pre-import modules,
sentinels, closure, bytecode, path defaults) is written for every run.
The exit status comes from explicit checks, never from ``assert``.

The test module itself follows the repository layout contract (ROOT from
tests._support, no sys.path edits); the repository-relative bootstrap lives
only here, in the script surface.

Exit 0 means PASS_REVIEW_REQUIRED: machine-valid scoped evidence only. It is not
semantic, scientific, legal, source, full-suite or live acceptance and grants no
publication authority. Exit 1: a check failed (evidence kept). Exit 2: refused
arguments or output root (nothing written).
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import ast  # noqa: E402
import contextlib  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
import hashlib  # noqa: E402
import importlib  # noqa: E402
import inspect  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import platform  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import traceback  # noqa: E402
import unittest  # noqa: E402

SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[1]
TEST_MODULE = 'tests.unit.test_bm1_render_private'
TEST_FILE = REPO / 'tests' / 'unit' / 'test_bm1_render_private.py'
PYCACHE = REPO / 'src' / 'skippercast' / 'coastal' / 'handoff' / '__pycache__'
HASHED = ('src/skippercast/coastal/handoff/render.py', 'tests/unit/test_bm1_render_private.py',
          'scripts/accept_bm1_render_private.py')
BASE_PIN = '59fca09b2cc7f5c81a4796902504e263d7f06960'
RENDER = 'src/skippercast/coastal/handoff/render.py'
# Operator plan files live outside the repository; resolved from the launching
# user's home at import time (before the run redirects HOME) so no private
# path is committed.
PLANS = Path.home() / 'agent-work' / 'plans' / 'astra-refill-BM-1'
FROZEN = {
    'brief': PLANS / 'briefs' / 'skippercast-BM1-RENDER-PRIVATE.brief',
    'items': PLANS / 'ITEMS.json',
    'verification_blueprint': PLANS / 'verification' / 'skippercast-V-BM1-RENDER-PRIVATE.md',
}
SUITES = {
    'focused': ('PositiveA1', 'NegativeA2', 'BoundaryA3'),
    'compatibility': ('Compatibility',),
    'negative': ('GateControl',),
    'isolation': ('Isolation',),
}
AUTHOR_DECLARED = dict(profile='opus-coder-bopus', model='claude-opus-5-5', provider='anthropic',
                       note='declared label recorded by the runner; not runtime proof')
OFFLINE_MESSAGE = 'BM1 offline sentinel: network access refused'
LAUNCH_ENV = 'BM1_RUNNER_LAUNCH'
LINE = re.compile(r'^(test\w+) \(' + re.escape(TEST_MODULE) + r'\.(\w+)\.(test\w+)\) \.\.\. (.*)$')


class Refused(Exception):
    pass


def relaunch_isolated():
    """Re-execute once under -I -B with the same argv; record the outer launch."""
    if sys.flags.isolated:
        return
    os.environ[LAUNCH_ENV] = json.dumps(dict(argv=[sys.executable, *sys.argv], cwd=os.getcwd(),
                                             flags=dict(isolated=sys.flags.isolated,
                                                        dont_write_bytecode=sys.flags.dont_write_bytecode)))
    os.execv(sys.executable, [sys.executable, '-I', '-B', str(SCRIPT), *sys.argv[1:]])


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    done = subprocess.run(['git', *args], cwd=REPO, capture_output=True, text=True, timeout=60)
    return dict(argv=['git', *args], returncode=done.returncode, stdout=done.stdout, stderr=done.stderr)


def checked_output_root(raw):
    """Refuse relative, traversing, linked or repository-contained roots before any write."""
    path = Path(raw)
    if not path.is_absolute():
        raise Refused('output root must be absolute')
    if '..' in path.parts:
        raise Refused('output root must not contain ..')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise Refused(f'output root component is a symlink: {current}')
        if not current.exists():
            break
        if not current.is_dir():
            raise Refused(f'output root component is not a directory: {current}')
    resolved = path.resolve()
    repo = REPO.resolve()
    if resolved == repo or repo in resolved.parents:
        raise Refused('output root inside the repository refused')
    return path


def expected_tests(classes):
    tree = ast.parse(TEST_FILE.read_text())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in classes:
            found[node.name] = [n.name for n in node.body
                                if isinstance(n, ast.FunctionDef) and n.name.startswith('test')]
    return [(cls, name) for cls in classes for name in found.get(cls, [])]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def project_modules():
    return sorted(m for m in sys.modules if m == 'skippercast' or m.startswith('skippercast.'))


def pycache_listing():
    return sorted(p.name for p in PYCACHE.iterdir()) if PYCACHE.is_dir() else []


def install_bootstrap(tmp):
    """Offline sentinels, redirected filesystem globals and the repository-relative
    import path, installed BEFORE any project or test module is imported."""
    tmp = tmp.resolve()
    tempfile.tempdir = str(tmp)
    os.environ['TMPDIR'] = str(tmp)
    os.environ['HOME'] = str(tmp)
    import socket

    def refuse(*args, **kwargs):
        raise OSError(OFFLINE_MESSAGE)

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse
    for entry in (str(REPO), str(REPO / 'src')):
        while entry in sys.path:
            sys.path.remove(entry)
    sys.path[0:0] = [str(REPO / 'src'), str(REPO)]


def sentinel_probe():
    import socket
    observed = {}
    for label, attempt in (('create_connection', lambda: socket.create_connection(('192.0.2.1', 9), timeout=1)),
                           ('socket_connect', lambda: socket.socket().connect(('192.0.2.1', 9))),
                           ('getaddrinfo', lambda: socket.getaddrinfo('example.invalid', 80))):
        try:
            attempt()
            observed[label] = 'NOT_BLOCKED'
        except OSError as error:
            observed[label] = str(error)
    return observed


def path_defaults(names):
    found = []
    for name in names:
        for attr, obj in vars(sys.modules[name]).items():
            if inspect.isfunction(obj) and obj.__module__ == name:
                for value in list(obj.__defaults__ or ()) + list((obj.__kwdefaults__ or {}).values()):
                    if isinstance(value, os.PathLike) or (isinstance(value, str) and ('/' in value or '\\' in value)):
                        found.append(f'{name}.{attr}={value!r}')
    return found


def run_suite(classes, tmp):
    """Install the bootstrap, then import and run the selected classes in-process."""
    install_bootstrap(tmp)
    report = dict(pre_import_project_modules=project_modules(),
                  pre_import_test_module_loaded=TEST_MODULE in sys.modules,
                  sentinel=sentinel_probe(), pycache_before=pycache_listing(),
                  dont_write_bytecode=sys.dont_write_bytecode, isolated_flag=sys.flags.isolated,
                  sys_path_head=sys.path[:2])
    out, err = io.StringIO(), io.StringIO()
    successful = False
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            module = importlib.import_module(TEST_MODULE)
            loader = unittest.TestLoader()
            suite = unittest.TestSuite(loader.loadTestsFromName(name, module) for name in classes)
            successful = unittest.TextTestRunner(stream=err, verbosity=2).run(suite).wasSuccessful()
        except BaseException:  # recorded as evidence; the explicit checks decide the exit
            traceback.print_exc(file=err)
            successful = False
    closure = {name: getattr(sys.modules[name], '__file__', None) for name in project_modules()}
    report.update(closure=closure, path_defaults=path_defaults(closure),
                  render_file=getattr(sys.modules.get('skippercast.coastal.handoff.render'), '__file__', None),
                  test_module_file=getattr(sys.modules.get(TEST_MODULE), '__file__', None),
                  pycache_after=pycache_listing(), tempdir=tempfile.gettempdir(), home=os.environ.get('HOME'),
                  cwd=os.getcwd(), executable=sys.executable)
    return successful, out.getvalue().encode('utf-8'), err.getvalue().encode('utf-8'), report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--suite', required=True, choices=sorted(SUITES))
    parser.add_argument('--output-root', required=True)
    args = parser.parse_args(argv)
    try:
        root = checked_output_root(args.output_root)
    except Refused as refusal:
        print(f'accept_bm1_render_private: refused: {refusal}', file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    child = root / f'run-{args.suite}-{stamp}-{os.getpid()}-{secrets.token_hex(4)}'
    child.mkdir(exist_ok=False)
    if child.is_symlink() or child.resolve().parent != root.resolve():
        print('accept_bm1_render_private: refused: run directory identity changed', file=sys.stderr)
        return 2
    tmp = child / 'tmp'
    tmp.mkdir()

    classes = SUITES[args.suite]
    expected = expected_tests(classes)
    head = git('rev-parse', 'HEAD')
    porcelain = git('status', '--porcelain', '--untracked-files=all')
    tracked = git('status', '--porcelain', '--untracked-files=no')
    base_render = subprocess.run(['git', 'show', f'{BASE_PIN}:{RENDER}'], cwd=REPO, capture_output=True,
                                 timeout=60)
    launch = os.environ.get(LAUNCH_ENV)
    invocation = dict(
        schema='bm1-render-private-acceptance-invocation/v2', suite=args.suite,
        argv=[sys.executable, *sys.argv] if argv is None else [sys.executable, str(SCRIPT), *argv],
        launch=json.loads(launch) if launch else None,
        cwd=os.getcwd(), interpreter=dict(executable=sys.executable, version=sys.version,
                                          implementation=platform.python_implementation(),
                                          isolated=sys.flags.isolated,
                                          dont_write_bytecode=sys.dont_write_bytecode),
        repo=str(REPO), run_dir=str(child), started_utc=datetime.now(timezone.utc).isoformat(),
        git=dict(head=head['stdout'].strip(), head_rc=head['returncode'], porcelain_all=porcelain['stdout'],
                 tracked_dirty=bool(tracked['stdout'].strip()), base_pin=BASE_PIN,
                 base_pin_render_sha256=hashlib.sha256(base_render.stdout).hexdigest()
                 if base_render.returncode == 0 else None),
        hashes={rel: sha256_file(REPO / rel) for rel in HASHED},
        fixture=dict(path=str(TEST_FILE), sha256=sha256_file(TEST_FILE)),
        frozen={name: dict(path=str(p), sha256=sha256_file(p) if p.is_file() else None) for name, p in FROZEN.items()},
        author_declared=AUTHOR_DECLARED, test_module=TEST_MODULE, execution='in-process after bootstrap',
        bootstrap=dict(tempdir=str(tmp), home=str(tmp), sys_path_head=[str(REPO / 'src'), str(REPO)],
                       sentinels=['socket.socket.connect', 'socket.socket.connect_ex',
                                  'socket.create_connection', 'socket.getaddrinfo']),
        selectors=list(classes), expected_tests=[f'{c}.{n}' for c, n in expected],
        expected_counts={c: sum(1 for k, _ in expected if k == c) for c in classes},
        acceptance_note='PASS_REVIEW_REQUIRED only; not semantic, scientific, legal, source, full-suite or live acceptance',
    )
    write_json(child / 'invocation.json', invocation)

    successful, stdout, stderr, report = run_suite(classes, tmp)
    (child / 'suite.stdout.txt').write_bytes(stdout)
    (child / 'suite.stderr.txt').write_bytes(stderr)
    write_json(child / 'isolation-report.json', report)
    text = stderr.decode('utf-8', 'replace')
    statuses = {}
    duplicates = []
    for line in text.splitlines():
        match = LINE.match(line)
        if match and match.group(1) == match.group(3):
            key = f'{match.group(2)}.{match.group(1)}'
            if key in statuses:
                duplicates.append(key)
            statuses[key] = match.group(4)
    ran = re.findall(r'^Ran (\d+) tests? in ', text, re.M)
    final = [line for line in text.splitlines() if line.startswith(('OK', 'FAILED'))]
    skipped = sum(1 for s in statuses.values() if s.startswith('skipped'))
    want = invocation['expected_tests']
    src = (REPO / 'src').resolve()
    outside = sorted(name for name, file in report['closure'].items()
                     if not file or not Path(file).resolve().is_relative_to(src))
    checks = [
        ('suite_successful', successful is True, successful),
        ('expected_tests_nonzero', len(want) > 0, len(want)),
        ('every_selector_has_tests', all(invocation['expected_counts'][c] > 0 for c in classes),
         invocation['expected_counts']),
        ('ran_equals_expected', ran == [str(len(want))], ran),
        ('final_line_exact_ok', final == ['OK'], final),
        ('every_expected_test_ok', all(statuses.get(t) == 'ok' for t in want),
         {t: statuses.get(t) for t in want if statuses.get(t) != 'ok'}),
        ('no_unexpected_tests', set(statuses) == set(want), sorted(set(statuses) ^ set(want))),
        ('no_duplicates', not duplicates, duplicates),
        ('zero_skips', skipped == 0, skipped),
        ('git_head_known', head['returncode'] == 0, head['returncode']),
        ('isolated_interpreter', sys.flags.isolated == 1 and sys.dont_write_bytecode is True,
         [sys.flags.isolated, sys.dont_write_bytecode]),
        ('no_project_module_before_bootstrap', report['pre_import_project_modules'] == []
         and report['pre_import_test_module_loaded'] is False,
         [report['pre_import_project_modules'], report['pre_import_test_module_loaded']]),
        ('sentinels_refuse_network', set(report['sentinel'].values()) == {OFFLINE_MESSAGE}, report['sentinel']),
        ('closure_inside_repo_src', bool(report['closure']) and not outside, outside),
        ('render_is_candidate', report['render_file'] is not None
         and Path(report['render_file']).resolve() == (REPO / RENDER).resolve(), report['render_file']),
        ('no_path_like_bound_defaults', report['path_defaults'] == [], report['path_defaults']),
        ('no_bytecode_written', report['pycache_after'] == report['pycache_before'],
         [report['pycache_before'], report['pycache_after']]),
    ]
    passed = all(ok for _, ok, _ in checks)
    result = dict(
        schema='bm1-render-private-acceptance-result/v2', suite=args.suite,
        verdict='PASS_REVIEW_REQUIRED' if passed else 'FAIL', suite_successful=successful,
        tests_expected=len(want), tests_ran=int(ran[0]) if len(ran) == 1 else None, skipped=skipped,
        statuses=statuses, checks=[dict(name=n, ok=ok, observed=obs) for n, ok, obs in checks],
        suite_stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        suite_stderr_sha256=hashlib.sha256(stderr).hexdigest(),
        isolation_report_sha256=sha256_file(child / 'isolation-report.json'),
        invocation_sha256=sha256_file(child / 'invocation.json'),
        ended_utc=datetime.now(timezone.utc).isoformat(),
    )
    write_json(child / 'result.json', result)
    print(f'suite={args.suite} verdict={result["verdict"]} ran={result["tests_ran"]} '
          f'expected={len(want)} skipped={skipped} run_dir={child}')
    for name, ok, observed in checks:
        if not ok:
            print(f'FAILED CHECK {name}: {observed}')
    return 0 if passed else 1


if __name__ == '__main__':
    relaunch_isolated()
    sys.exit(main())
