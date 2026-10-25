#!/usr/bin/env python3
"""BM1-RENDER-PRIVATE acceptance runner (stdlib only).

Usage: python3 scripts/accept_bm1_render_private.py --suite {focused,compatibility,negative,isolation}
           --output-root <absolute directory outside this repository>

Each invocation creates a fresh unique child of the output root, launches the
test module as a file in a fresh interpreter (``-I -B``, explicit argv, no
shell), and records argv/cwd/interpreter, git HEAD and dirty state, source/test
hashes, the frozen brief hash, raw child stdout/stderr and per-test statuses.
The exit status comes from explicit checks, never from ``assert``.

Exit 0 means PASS_REVIEW_REQUIRED: machine-valid scoped evidence only. It is not
semantic, scientific, legal, source, full-suite or live acceptance and grants no
publication authority. Exit 1: a check failed (evidence kept). Exit 2: refused
arguments or output root (nothing written).
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
TEST_FILE = REPO / 'tests' / 'unit' / 'test_bm1_render_private.py'
HASHED = ('src/skippercast/coastal/handoff/render.py', 'tests/unit/test_bm1_render_private.py',
          'scripts/accept_bm1_render_private.py')
BASE_PIN = '59fca09b2cc7f5c81a4796902504e263d7f06960'
RENDER = 'src/skippercast/coastal/handoff/render.py'
FROZEN = {
    'brief': Path('/home/user/agent-work/plans/astra-refill-BM-1/briefs/skippercast-BM1-RENDER-PRIVATE.brief'),
    'items': Path('/home/user/agent-work/plans/astra-refill-BM-1/ITEMS.json'),
    'verification_blueprint': Path('/home/user/agent-work/plans/astra-refill-BM-1/verification/'
                                   'skippercast-V-BM1-RENDER-PRIVATE.md'),
}
SUITES = {
    'focused': ('PositiveA1', 'NegativeA2', 'BoundaryA3'),
    'compatibility': ('Compatibility',),
    'negative': ('GateControl',),
    'isolation': ('Isolation',),
}
AUTHOR_DECLARED = dict(profile='opus-coder-bopus', model='claude-opus-5-5', provider='anthropic',
                       note='declared label recorded by the runner; not runtime proof')
LINE = re.compile(r'^(test\w+) \(__main__\.(\w+)\.(test\w+)\) \.\.\. (.*)$')


class Refused(Exception):
    pass


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
    child_argv = [sys.executable, '-I', '-B', str(TEST_FILE), '-v', *classes]
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    env.update(TMPDIR=str(tmp), BM1_EVIDENCE_TMP=str(tmp))
    head = git('rev-parse', 'HEAD')
    porcelain = git('status', '--porcelain', '--untracked-files=all')
    tracked = git('status', '--porcelain', '--untracked-files=no')
    base_render = subprocess.run(['git', 'show', f'{BASE_PIN}:{RENDER}'], cwd=REPO, capture_output=True,
                                 timeout=60)
    invocation = dict(
        schema='bm1-render-private-acceptance-invocation/v1', suite=args.suite,
        argv=[sys.executable, *sys.argv] if argv is None else [sys.executable, __file__, *argv],
        cwd=os.getcwd(), interpreter=dict(executable=sys.executable, version=sys.version,
                                          implementation=platform.python_implementation()),
        repo=str(REPO), run_dir=str(child), started_utc=datetime.now(timezone.utc).isoformat(),
        git=dict(head=head['stdout'].strip(), head_rc=head['returncode'], porcelain_all=porcelain['stdout'],
                 tracked_dirty=bool(tracked['stdout'].strip()), base_pin=BASE_PIN,
                 base_pin_render_sha256=hashlib.sha256(base_render.stdout).hexdigest()
                 if base_render.returncode == 0 else None),
        hashes={rel: sha256_file(REPO / rel) for rel in HASHED},
        fixture=dict(path=str(TEST_FILE), sha256=sha256_file(TEST_FILE)),
        frozen={name: dict(path=str(p), sha256=sha256_file(p) if p.is_file() else None) for name, p in FROZEN.items()},
        author_declared=AUTHOR_DECLARED, child_argv=child_argv, child_cwd=str(REPO),
        child_env_overrides=dict(TMPDIR=str(tmp), BM1_EVIDENCE_TMP=str(tmp)), removed_env='PYTHON*',
        selectors=list(classes), expected_tests=[f'{c}.{n}' for c, n in expected],
        expected_counts={c: sum(1 for k, _ in expected if k == c) for c in classes},
        acceptance_note='PASS_REVIEW_REQUIRED only; not semantic, scientific, legal, source, full-suite or live acceptance',
    )
    write_json(child / 'invocation.json', invocation)

    done = subprocess.run(child_argv, cwd=REPO, env=env, capture_output=True, timeout=1500)
    (child / 'child.stdout.txt').write_bytes(done.stdout)
    (child / 'child.stderr.txt').write_bytes(done.stderr)
    text = done.stderr.decode('utf-8', 'replace')
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
    checks = [
        ('child_exit_zero', done.returncode == 0, done.returncode),
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
    ]
    passed = all(ok for _, ok, _ in checks)
    result = dict(
        schema='bm1-render-private-acceptance-result/v1', suite=args.suite,
        verdict='PASS_REVIEW_REQUIRED' if passed else 'FAIL', child_returncode=done.returncode,
        tests_expected=len(want), tests_ran=int(ran[0]) if len(ran) == 1 else None, skipped=skipped,
        statuses=statuses, checks=[dict(name=n, ok=ok, observed=obs) for n, ok, obs in checks],
        child_stdout_sha256=hashlib.sha256(done.stdout).hexdigest(),
        child_stderr_sha256=hashlib.sha256(done.stderr).hexdigest(),
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
    sys.exit(main())
