"""Offline acceptance runner for SC-SEGMENT-DELTA (two-receipt metadata comparator).

    python3 scripts/accept_sc_segment_delta.py --suite focused|contract|negative --output DIR

Uses only the installed python3 standard library plus jsonschema; pytest is not
required. Bytecode writing is disabled and offline sentinels are installed
BEFORE any project import. The import path is set in code to this staged
checkout only, temporary files and the tests' WORK_ROOT are redirected into a
new write-once run directory under DIR, and every transitive import is traced.

Each run writes DIR/<utc>-<pid>-<token>/{receipt.json,stdout.txt,stderr.txt}.
Exit 0 only when every selected assertion passed, the collected count equals
the frozen expected count (no skips exist), no sentinel fired and, for the
negative suite, every mutation control was detected and its positive control
passed. A pass is REVIEW REQUIRED: not full CI, source qualification,
closure or semantic acceptance.
"""
import sys

sys.dont_write_bytecode = True  # before any project import

import argparse  # noqa: E402
import contextlib  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import importlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import tempfile  # noqa: E402
import traceback  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SUITES = {'focused': 'test_a1_', 'contract': 'test_a2_', 'negative': 'test_a3_'}
EXPECTED = {'focused': 6, 'contract': 4, 'negative': 11}
# Existing repository layout contracts the new test module must satisfy.
LAYOUT_CONTRACTS = ('tests.contract.test_test_layout', 'tests.contract.test_research_boundary')
HASHED = ('scripts/accept_sc_segment_delta.py', 'scripts/coast_diagnostics/segment_receipt_delta.py',
          'tests/unit/test_sc_segment_delta.py', 'tests/_support.py', 'tests/__init__.py', 'tests/unit/__init__.py',
          'scripts/validate_coast_receipt.py',
          'skills/coast-campaign-shared/schemas/coast-segment-receipt-v1.schema.json',
          'skills/coast-campaign-shared/scripts/coast_refs.py',
          'skills/coast-campaign-shared/scripts/validate_coast_receipt.py',
          'docs/engineering/sc_segment_delta.md')
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
        self.stream, self.buffer_text = stream, io.StringIO()

    def write(self, text):
        self.buffer_text.write(text)
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def sha256_file(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


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


def write_once(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)


def install_sentinels(run_dir, violations):
    allowed = str(run_dir) + os.sep

    def under_run(path):
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if not isinstance(path, str) or not os.path.isabs(path):
            return True  # dir_fd-relative names; the parent fd was opened under a checked root
        return (os.path.normpath(path) + os.sep).startswith(allowed)

    def hook(event, args):
        if event in BLOCKED_EVENTS:
            violations.append(dict(event=event, detail=repr(args)[:200]))
            raise RuntimeError('sentinel: blocked ' + event)
        if event == 'import' and args and args[0] in MODEL_IMPORTS:
            violations.append(dict(event='model-import', detail=args[0]))
            raise RuntimeError('sentinel: model client import ' + args[0])
        if event == 'open' and len(args) >= 3 and isinstance(args[2], int) and args[2] & WRITE_FLAGS:
            if not under_run(args[0]):
                violations.append(dict(event='write-outside-run', detail=repr(args[0])[:200]))
                raise RuntimeError('sentinel: write outside run root')
        if event == 'open' and len(args) >= 2 and isinstance(args[1], str) and set(args[1]) & set('wax+'):
            if not under_run(args[0]):
                violations.append(dict(event='write-outside-run', detail=repr(args[0])[:200]))
                raise RuntimeError('sentinel: write outside run root')
        if event in WRITE_EVENTS and args and not under_run(args[0]):
            violations.append(dict(event=event, detail=repr(args[0])[:200]))
            raise RuntimeError('sentinel: filesystem change outside run root ' + event)
    sys.addaudithook(hook)


def run_layout_contracts():
    results = []
    for name in LAYOUT_CONTRACTS:
        module = importlib.import_module(name)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        stream = io.StringIO()
        outcome = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        results.append(dict(module=name, tests=outcome.testsRun, failures=len(outcome.failures),
                            errors=len(outcome.errors), skipped=len(outcome.skipped),
                            ok=outcome.wasSuccessful() and not outcome.skipped, output=stream.getvalue()))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--suite', required=True, choices=sorted(SUITES))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)

    started = utc()
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=True)
    run_dir = output / f"{started.replace(':', '').replace('.', '-')}-{os.getpid()}-{secrets.token_hex(4)}"
    run_dir.mkdir(exist_ok=False)
    run_dir = Path(os.path.realpath(run_dir))
    (run_dir / 'tmp').mkdir()
    (run_dir / 'work').mkdir()

    out_tee, err_tee = Tee(sys.stdout), Tee(sys.stderr)
    violations = []
    receipt = dict(schema='sc-segment-delta-acceptance-v1', suite=args.suite, argv=list(sys.argv),
                   cwd=os.getcwd(), started_utc=started, run_dir=str(run_dir),
                   python=dict(executable=sys.executable, version=sys.version),
                   repo=str(REPO), git_head_file_read=git_head(),
                   code_hashes={rel: sha256_file(REPO / rel) for rel in HASHED},
                   fixture_hashes={p.name: sha256_file(p) for p in
                                   sorted((REPO / 'tests/fixtures/sc_segment_delta').glob('*'))},
                   review_status='REVIEW REQUIRED',
                   scope='local scoped acceptance only; not full CI, source qualification, closure or '
                         'semantic acceptance; full discovery = operator-run')

    # Redirect constants and process-wide temp defaults BEFORE project imports.
    tempfile.tempdir = str(run_dir / 'tmp')
    os.environ['TMPDIR'] = str(run_dir / 'tmp')
    script_dir = str(Path(__file__).resolve().parent)
    sys.path[:] = [str(REPO)] + [p for p in sys.path if p not in ('', script_dir, str(REPO))]
    install_sentinels(run_dir, violations)
    try:
        import jsonschema  # noqa: F401  (record the actual dependency identity)
        from importlib import metadata
        receipt['jsonschema_version'] = metadata.version('jsonschema')
    except Exception as error:  # capability gap is a FAIL, never a skip
        receipt['jsonschema_version'] = 'UNAVAILABLE: ' + repr(error)

    before = set(sys.modules)
    tests, controls, layout = [], None, None
    with contextlib.redirect_stdout(out_tee), contextlib.redirect_stderr(err_tee):
        print(f'[{utc()}] suite={args.suite} run_dir={run_dir}')
        try:
            module = importlib.import_module('tests.unit.test_sc_segment_delta')
            module.WORK_ROOT = run_dir / 'work'
            receipt['test_module'] = module.__file__
            selected = [(n, f) for n, f in vars(module).items() if n.startswith(SUITES[args.suite]) and callable(f)]
            for name, function in selected:
                captured_out, captured_err = io.StringIO(), io.StringIO()
                status, detail = 'passed', ''
                with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
                    try:
                        function()
                    except Exception:  # AssertionError or any error: recorded as a failure
                        status, detail = 'failed', traceback.format_exc()
                tests.append(dict(name=name, status=status, detail=detail, stdout=captured_out.getvalue(),
                                  stderr=captured_err.getvalue()))
                print(f'{status.upper():7} {name}')
                if detail:
                    print(detail, file=sys.stderr)
            if args.suite == 'negative':
                controls = module.run_mutation_controls()
                for control in controls:
                    print(f"CONTROL {control['control']}: detected={control['detected']} "
                          f"positive_passed={control['positive_passed']} :: {control['message']}")
            if args.suite == 'contract':
                layout = run_layout_contracts()
                for result in layout:
                    print(f"LAYOUT  {result['module']}: tests={result['tests']} failures={result['failures']} "
                          f"errors={result['errors']} skipped={result['skipped']}")
        except Exception:
            tests.append(dict(name='<collection>', status='failed', detail=traceback.format_exc(), stdout='', stderr=''))
            print('FAILED  <collection>\n' + traceback.format_exc(), file=sys.stderr)

    imported = {}
    for name in sorted(set(sys.modules) - before):
        path = getattr(sys.modules.get(name), '__file__', None)
        imported[name] = path
        if path and 'skippercast' in Path(path).parts and not path.startswith(str(REPO)):
            violations.append(dict(event='foreign-checkout-import', detail=f'{name}: {path}'))
    passed = sum(t['status'] == 'passed' for t in tests)
    failed = len(tests) - passed
    counts = dict(collected=len(tests), passed=passed, failed=failed, skipped=0, expected=EXPECTED[args.suite])
    ok = failed == 0 and len(tests) == EXPECTED[args.suite] and not violations
    if controls is not None:
        ok = ok and bool(controls) and all(c['detected'] and c['positive_passed'] for c in controls)
    if layout is not None:
        ok = ok and all(r['ok'] for r in layout)
    if not str(receipt.get('jsonschema_version', '')).replace('.', '').isdigit():
        ok = False
    summary = (f"[{utc()}] RESULT {'PASS' if ok else 'FAIL'} suite={args.suite} collected={counts['collected']} "
               f"passed={passed} failed={failed} skipped=0 expected={counts['expected']} "
               f"sentinel_violations={len(violations)} (REVIEW REQUIRED)")
    print(summary, file=out_tee)
    receipt.update(finished_utc=utc(), tests=tests, counts=counts, mutation_controls=controls,
                   layout_contracts=layout, sentinel_violations=violations, imported_modules=imported,
                   sys_path=list(sys.path), result='PASS' if ok else 'FAIL', exit_code=0 if ok else 1)
    write_once(run_dir / 'stdout.txt', out_tee.buffer_text.getvalue().encode())
    write_once(run_dir / 'stderr.txt', err_tee.buffer_text.getvalue().encode())
    write_once(run_dir / 'receipt.json', (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode())
    print(f'receipt: {run_dir / "receipt.json"} sha256={sha256_file(run_dir / "receipt.json")}')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
