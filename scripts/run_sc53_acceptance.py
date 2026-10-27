"""Offline SC53 acceptance; in-process pytest, unique durable evidence per run."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REGRESSION = 'tests/unit/test_sc53_regression.py'
COMPATIBILITY = 'tests/contract/test_seafloor_source_rights.py::SourceRightsTests::'
SELECTORS = (
    'test_reviewed_ventresca_original_can_qualify_with_same_producer_restrictions',
    'test_exact_macginitie_products_require_unchanged_producer_review',
    'test_unreviewed_or_lookalike_cruise_archives_remain_rejected',
    'test_checked_noncommercial_producer_contract_can_qualify_without_inventing_public_domain',
    'test_missing_conflicting_or_fabricated_permissions_do_not_qualify',
    'test_mixed_source_terms_and_unknown_contributors_cannot_disappear',
)
IGNORED = {'.git', '.venv', '__pycache__', '.pytest_cache', '.ruff_cache',
           'node_modules', '.wrangler', 'build'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root):
    """Preserve the complete regular input tree; never walk staging/runtime links."""
    result = {}
    for parent, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in IGNORED)
        for name in sorted(files):
            path = Path(parent) / name
            if name == '.git':
                continue
            require(not path.is_symlink(), f'Unexpected input symlink: {path}')
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def head_identity(root):
    dotgit = root / '.git'
    gitdir = dotgit
    if dotgit.is_file():
        text = dotgit.read_text().strip()
        require(text.startswith('gitdir: '), 'Invalid staged git metadata')
        gitdir = (root / text[8:]).resolve()
    head = (gitdir / 'HEAD').read_text().strip()
    if head.startswith('ref: '):
        ref = head[5:]
        common_file = gitdir / 'commondir'
        common = (gitdir / common_file.read_text().strip()).resolve() if common_file.exists() else gitdir
        loose = common / ref
        if loose.is_file():
            head = loose.read_text().strip()
        else:
            matches = [line.split()[0] for line in (common / 'packed-refs').read_text().splitlines()
                       if line and not line.startswith(('#', '^')) and line.split()[1] == ref]
            require(len(matches) == 1, 'Cannot resolve staged HEAD')
            head = matches[0]
    require(len(head) == 40 and all(c in '0123456789abcdef' for c in head), 'Invalid staged HEAD')
    return head


def install_guards(stack, events):
    def refuse(*args, **kwargs):
        events.append('offline network/DNS/process seam invoked')
        raise RuntimeError(events[-1])

    seams = ((socket.socket, ('connect', 'connect_ex', 'bind', 'listen', 'sendto')),
             (socket, ('create_connection', 'getaddrinfo', 'gethostbyname', 'gethostbyname_ex', 'gethostbyaddr')),
             (subprocess, ('Popen', 'run', 'call', 'check_call', 'check_output')),
             (os, ('system', 'popen', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp',
                   'execv', 'execve', 'execvp', 'execvpe', 'execl', 'execle', 'execlp', 'execlpe',
                   'spawnl', 'spawnle', 'spawnlp', 'spawnlpe', 'spawnv', 'spawnve', 'spawnvp', 'spawnvpe')))
    for owner, names in seams:
        for name in names:
            if hasattr(owner, name):
                stack.enter_context(patch.object(owner, name, refuse))


class Counts:
    def __init__(self):
        self.collected = []
        self.reports = []

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report):
        self.reports.append({'nodeid': report.nodeid, 'when': report.when,
                             'outcome': report.outcome, 'detail': str(report.longrepr) if report.longrepr else '',
                             'subtest': hasattr(report, 'context'),
                             'parameters': repr(report.context) if hasattr(report, 'context') else None,
                             'xfail': hasattr(report, 'wasxfail')})


def run_pytest(pytest, run, root, label, selectors, extra=()):
    counts = Counts()
    argv = ['-vv', '-p', 'no:cacheprovider', '--rootdir', str(root),
            '--basetemp', str(run / (label + '-temporary')), *extra, *selectors]
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = int(pytest.main(argv, plugins=[counts]))
    outpath, errpath = run / (label + '.stdout.txt'), run / (label + '.stderr.txt')
    outpath.write_text(stdout.getvalue())
    errpath.write_text(stderr.getvalue())
    calls = [r for r in counts.reports if r['when'] == 'call' and not r['subtest']]
    subtests = [r for r in counts.reports if r['when'] == 'call' and r['subtest']]
    result = {'label': label, 'pytest_argv': argv, 'exit': code,
              'collected': counts.collected, 'collected_count': len(counts.collected),
              'executed_count': len(calls),
              'passed': sum(r['outcome'] == 'passed' for r in calls),
              'failed': sum(r['outcome'] == 'failed' for r in calls),
              'subtest_count': len(subtests),
              'subtests_passed': sum(r['outcome'] == 'passed' for r in subtests),
              'subtests_by_node': {node: sum(r['nodeid'] == node for r in subtests)
                                   for node in counts.collected},
              'skipped': sum(r['outcome'] == 'skipped' or r['xfail'] for r in counts.reports),
              'reports': counts.reports,
              'stdout': str(outpath), 'stdout_sha256': digest(outpath),
              'stderr': str(errpath), 'stderr_sha256': digest(errpath)}
    print(f"{label}: exit={code} collected={result['collected_count']} "
          f"executed={result['executed_count']} passed={result['passed']} failed={result['failed']} "
          f"skipped={result['skipped']} subtests={result['subtest_count']}")
    return result


def passed(result, expected=None):
    require(result['exit'] == 0, f"{result['label']} pytest failed")
    require(result['executed_count'] > 0, 'No checks executed')
    require(result['collected_count'] == result['executed_count'] == result['passed'], 'Incomplete execution')
    require(result['skipped'] == 0, 'Unexpected skip or xfail')
    require(result['subtest_count'] == result['subtests_passed'], 'A subtest failed')
    if expected is not None:
        require(result['executed_count'] == expected, 'Wrong check count')


def origins(root):
    result = {}
    for name, module in sorted(sys.modules.items()):
        if name == 'skippercast' or name.startswith(('skippercast.', 'tests.', 'research.')):
            filename = getattr(module, '__file__', None)
            if filename:
                path = Path(filename).resolve()
                require(path.is_relative_to(root), f'Ambient candidate import refused: {name} {path}')
                result[name] = str(path)
    require('skippercast.seafloor.rights' in result, 'Full rights module was not imported')
    return result


def portable_tree(run):
    target = run / 'differently-named-local-project'
    target.mkdir()
    # Copy only the full regression dependency closure, not extracted algorithms.
    shutil.copytree(ROOT / 'src/skippercast', target / 'src/skippercast',
                    ignore=shutil.ignore_patterns('__pycache__'))
    for relative in (REGRESSION, 'conftest.py', 'tests/conftest.py', 'tests/_support.py',
                     'tests/__init__.py', 'pyproject.toml', 'catalog/surveys.json'):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    return target


def execute(args, run, receipt):
    before = snapshot(ROOT)
    receipt['head'] = head_identity(ROOT)
    receipt['inputs_before'] = before
    receipt['input_count'] = len(before)
    receipt['guard_events'] = []
    receipt['tests'] = []
    try:
        # These are ordinary process-local settings, not import-path overrides.
        # Install guards before dependency imports or candidate module execution.
        with ExitStack() as stack:
            install_guards(stack, receipt['guard_events'])
            home = run / 'synthetic-home'
            home.mkdir()
            stack.enter_context(patch.dict(os.environ, {'HOME': str(home), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}))
            root = portable_tree(run) if args.mode == 'portability' else ROOT
            stack.enter_context(patch.dict(os.environ, {'SKIPPERCAST_ROOT': str(root)}))
            receipt['test_root'] = str(root)
            receipt['home_before_imports'] = str(Path.home())
            local_before = snapshot(root)
            receipt['relocated_inputs'] = local_before if root != ROOT else None
            # Verify every relocated input byte against its original before imports.
            for relative, sha in local_before.items():
                require(before.get(relative) == sha, f'Relocated input drift: {relative}')
            sys.path[:0] = [str(root / 'src'), str(root)]
            import pytest
            import numpy
            import rasterio
            import jsonschema
            from skippercast.seafloor import rights
            receipt['runtime'] = {'python': sys.version, 'executable': sys.executable,
                                  'pytest': pytest.__version__, 'numpy': numpy.__version__,
                                  'rasterio': rasterio.__version__,
                                  'jsonschema_origin': jsonschema.__file__}
            receipt['module_origins'] = origins(root)
            if args.mode == 'mutation':
                original = rights._sc53_archive_locator
                try:
                    # The sole control: old predicate, in memory, full real module.
                    rights._sc53_archive_locator = lambda url: url.startswith(rights.CSUMB_ARCHIVES)
                    negative = run_pytest(pytest, run, root, 'old-predicate-traversal',
                                          [str(root / REGRESSION) + '::test_rejects_literal_parent_traversal'])
                    receipt['tests'].append(negative)
                    require(negative['exit'] == 1 and negative['executed_count'] == 2
                            and negative['failed'] == 2 and negative['skipped'] == 0,
                            'Controlled traversal did not fail exactly twice')
                    failures = [r for r in negative['reports'] if r['when'] == 'call' and r['outcome'] == 'failed']
                    require(all('DID NOT RAISE ValueError' in r['detail'] for r in failures),
                            'Mutation failed for an unrelated reason')
                    positive = run_pytest(pytest, run, root, 'old-predicate-positive',
                                         [str(root / REGRESSION) + '::test_ordinary_original_preserves_complete_restrictive_terms'])
                    receipt['tests'].append(positive)
                    passed(positive, expected=12)
                finally:
                    rights._sc53_archive_locator = original
                restored = run_pytest(pytest, run, root, 'restored-predicate-traversal',
                                      [str(root / REGRESSION) + '::test_rejects_literal_parent_traversal'])
                receipt['tests'].append(restored)
                passed(restored, expected=2)
                receipt['predicate_restored'] = rights._sc53_archive_locator is original
                require(receipt['predicate_restored'], 'Predicate restoration failed')
            else:
                selectors = ([str(root / COMPATIBILITY) + name for name in SELECTORS]
                             if args.mode == 'compatibility' else [str(root / REGRESSION)])
                result = run_pytest(pytest, run, root, args.mode, selectors)
                receipt['tests'].append(result)
                passed(result, expected=6 if args.mode == 'compatibility' else 176)
                if args.mode == 'compatibility':
                    # Frozen source has 4 + 20 + 4 + 0 + 13 + 0 unittest
                    # subtests in addition to the six top-level selectors.
                    expected_subtests = dict(zip(SELECTORS, (4, 20, 4, 0, 13, 0)))
                    actual_subtests = {node.rsplit('::', 1)[-1]: count
                                       for node, count in result['subtests_by_node'].items()}
                    require(actual_subtests == expected_subtests,
                            'A named compatibility parameterization was not executed')
            receipt['module_origins'] = origins(root)
            receipt['bound_candidate_roots'] = {}
            for name, attribute in (('skippercast.platform.contracts', 'REPO'),
                                    ('research.lib.paths', 'ROOT'), ('tests._support', 'ROOT')):
                if name in sys.modules:
                    bound = Path(getattr(sys.modules[name], attribute)).resolve()
                    receipt['bound_candidate_roots'][name] = str(bound)
                    require(bound == root, f'Ambient bound root refused: {name}')
            require(not receipt['guard_events'], 'An offline guard seam was invoked')
            require(Path.home() == home, 'Synthetic HOME was not retained')
            receipt['test_inputs_preserved'] = snapshot(root) == local_before
            require(receipt['test_inputs_preserved'], 'Test-local input bytes changed')
    finally:
        receipt['inputs_after'] = snapshot(ROOT)
        receipt['inputs_preserved'] = before == receipt['inputs_after']
        require(receipt['inputs_preserved'], 'Candidate inputs changed during acceptance')


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['regression', 'mutation', 'compatibility', 'portability'], required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_root.resolve()
    require(not output.is_relative_to(ROOT), 'Outputs must be outside committed inputs')
    output.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='sc53-' + args.mode + '-', dir=output))
    receipt = {'schema': 'sc53-acceptance-v1', 'argv': sys.argv, 'cwd': str(Path.cwd()),
               'mode': args.mode, 'run': str(run), 'repository': str(ROOT), 'exit': 1}
    captured_out, captured_err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(captured_out), redirect_stderr(captured_err):
            execute(args, run, receipt)
        receipt['exit'] = 0
    except Exception:
        captured_err.write(traceback.format_exc())
    (run / 'runner.stdout.txt').write_text(captured_out.getvalue())
    (run / 'runner.stderr.txt').write_text(captured_err.getvalue())
    receipt['raw_output_hashes'] = {name: digest(run / name) for name in ('runner.stdout.txt', 'runner.stderr.txt')}
    (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(captured_out.getvalue(), end='')
    print(captured_err.getvalue(), end='', file=sys.stderr)
    print(f"SC53 {args.mode}: exit={receipt['exit']} receipt={run / 'receipt.json'}")
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())
