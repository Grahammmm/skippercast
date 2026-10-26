"""Offline SC15A acceptance. Execute file, never extracted source or child code."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
import uuid

REPO = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
BRIEF_SHA = '9596ebcf4517952ee8c58914fd1c812da77554869e3c334b405e45e6bb591ce7'
SPEC_SHA = 'ff85452097c430cecd301754a4fecfd20282651b8be62071922d74201415b715'
REQUIRED = {
    'regression': ['test_positive_contract', 'test_rejects_malformed'],
    'compatibility': ['test_baseline_compatibility', 'test_isolation_and_discovery'],
    'negative-control': ['test_deciding_negative_control'],
}

REQUIRED_CASES = {
    'test_positive_contract': ['packet-to-grant-path', 'packet-to-grant-sha256', 'grant-to-packet-path', 'grant-to-packet-sha256'],
    'test_rejects_malformed': ['missing-saved_area_adoption', 'missing-source_volume_cap_bytes', 'missing-prior_effective_bytes', 'missing-cumulative_limit_bytes',
                               'execution-True', 'execution-None', 'execution-absent', "continuation-'wrong-contract'", "continuation-''", 'template-schema', 'template-stage'],
    'test_baseline_compatibility': ['complete-held-baseline-bytes-and-digest', 'no-continuation-removes-inherited-absent', 'no-continuation-removes-inherited-null',
                                    'inherited-larger-authority-retains-refusal-32', 'inherited-larger-authority-retains-refusal-64'],
    'test_isolation_and_discovery': ['peer-before', 'synthetic-import-and-real-predicates', 'teardown-restored-modules-paths-environment-guards', 'peer-after', 'five-required-methods-registered'],
    'test_deciding_negative_control': ['mutant-packet-to-grant-path', 'restored-packet-to-grant-path', 'mutant-packet-to-grant-sha256', 'restored-packet-to-grant-sha256',
                                      'mutant-grant-to-packet-path', 'restored-grant-to-packet-path', 'mutant-grant-to-packet-sha256', 'restored-grant-to-packet-sha256'],
}

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError('file loader unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def current_head(repo=REPO):
    dotgit = repo / '.git'
    if dotgit.is_file():
        dotgit = (repo / dotgit.read_text().strip().removeprefix('gitdir: ')).resolve()
    value = (dotgit / 'HEAD').read_text().strip()
    if value.startswith('ref: '):
        name = value[5:]
        ref = dotgit / name
        if ref.is_file():
            value = ref.read_text().strip()
        else:
            packed = (dotgit / 'packed-refs').read_text().splitlines()
            value = next(line.split()[0] for line in packed if line.endswith(' ' + name))
    if len(value) != 40 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('full exact HEAD unavailable')
    return value

def input_hashes():
    paths = [REPO / 'src/skippercast/coastal/coordinator/packet_release.py',
             REPO / 'tests/unit/test_sc15a_packet_copy.py', Path(__file__).resolve(),
             *sorted((REPO / 'tests/fixtures/sc15a-packet-copy').glob('*.json')),
             REPO / 'tests/fixtures/sc15a-packet-copy/support.py']
    return {str(p.relative_to(REPO)): file_hash(p) for p in paths}

def log_identity(root):
    result = {}
    for name in ('stdout.log', 'stderr.log'):
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('required raw log missing or unsafe: ' + name)
        data = path.read_bytes()
        result[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'lines': len(data.splitlines())}
    return result

def verify_logs(root, expected):
    if log_identity(root) != expected:
        raise ValueError('sealed raw log changed')
    return True

def finalization_controls(root):
    results = {}
    for case in ('complete-positive', 'missing-log', 'mutated-log', 'late-append'):
        target = root / case
        target.mkdir(parents=True, exist_ok=False)
        (target / 'stdout.log').write_bytes(b'complete\n')
        if case != 'missing-log':
            (target / 'stderr.log').write_bytes(b'')
        if case == 'missing-log':
            try:
                log_identity(target)
            except ValueError as exc:
                results[case] = {'detected': True, 'reason': str(exc)}
            else:
                raise RuntimeError('missing-log negative was not detected')
            continue
        sealed = log_identity(target)
        if case == 'mutated-log':
            (target / 'stdout.log').write_bytes(b'mutated!\n')
        elif case == 'late-append':
            with (target / 'stdout.log').open('ab') as stream:
                stream.write(b'late writer\n')
        try:
            verify_logs(target, sealed)
        except ValueError as exc:
            if case == 'complete-positive':
                raise
            results[case] = {'detected': True, 'reason': str(exc), 'original_seal': sealed}
        else:
            if case != 'complete-positive':
                raise RuntimeError(case + ' negative was not detected')
            results[case] = {'passed': True}
    return results

class Results(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed = []
        self.subtests = []
    def startTest(self, test):
        self.executed.append(test.id())
        super().startTest(test)
    def addSubTest(self, test, subtest, err):
        self.subtests.append({'id': subtest.id(), 'passed': err is None})
        super().addSubTest(test, subtest, err)

def validate_manifest(path):
    manifest = json.loads(path.read_text())
    checks = [manifest.get('schema') == 'agentorange.source-manifest/v1',
              manifest.get('head') == BASE, Path(manifest['repo']) == REPO,
              Path(manifest['write_root']) == REPO.parent,
              (REPO / '.venv').resolve() == Path(manifest['runtime']['repo_venv']).resolve()]
    if not all(checks):
        raise ValueError('staged source manifest mismatch; staging owner required')
    return manifest

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=REQUIRED, required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    validate_manifest(args.source_manifest)
    if Path.cwd() != REPO:
        raise ValueError('acceptance cwd differs from staged repo')
    root = args.out / ('run-' + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=False)
    before_hashes = input_hashes()
    head = current_head()
    # Setting bytecode policy precedes loading tests and every product module.
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(REPO / 'src'), str(REPO)]
    helper = load_file('sc15a_runner_support', REPO / 'tests/fixtures/sc15a-packet-copy/support.py')
    result = None
    module = None
    exit_code = 1
    with (root / 'stdout.log').open('w') as stdout, (root / 'stderr.log').open('w') as stderr:
        with redirect_stdout(stdout), redirect_stderr(stderr), helper.offline_guards():
            module = load_file('sc15a_acceptance_tests', REPO / 'tests/unit/test_sc15a_packet_copy.py')
            module.S.OUTPUT_BASE = root / 'state'
            suite = unittest.TestSuite(module.PacketCopyTest(name) for name in REQUIRED[args.suite])
            result = unittest.TextTestRunner(stream=stderr, verbosity=2, resultclass=Results).run(suite)
            expected_ids = ['sc15a_acceptance_tests.PacketCopyTest.' + name for name in REQUIRED[args.suite]]
            expected_cases = [name + ':' + case for name in REQUIRED[args.suite] for case in REQUIRED_CASES[name]]
            complete = (result.executed == expected_ids and result.testsRun == len(expected_ids)
                        and module.CASES == expected_cases and len(result.subtests) == len(expected_cases))
            all_subtests = all(row['passed'] for row in result.subtests)
            exit_code = 0 if result.wasSuccessful() and not result.skipped and complete and all_subtests else 1
    # All scoped writers/contexts finished; never seal logs while tests still write.
    controls = finalization_controls(root / 'finalization-controls')
    logs = log_identity(root)
    verify_logs(root, logs)
    unchanged = before_hashes == input_hashes() and head == current_head()
    if not unchanged:
        exit_code = 1
    receipt = {
        'schema': 'sc15a-acceptance-receipt/v1', 'suite': args.suite,
        'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()), 'interpreter': sys.executable,
        'base': BASE, 'head': head, 'brief_sha256': BRIEF_SHA, 'frozen_specs_sha256': SPEC_SHA,
        'source_manifest_sha256': file_hash(args.source_manifest), 'input_hashes': before_hashes,
        'inputs_unchanged': unchanged, 'executed_ids': result.executed,
        'testsRun': result.testsRun, 'subtest_count': len(result.subtests), 'subtests': result.subtests,
        'case_ids': module.CASES, 'skips': result.skipped,
        'failures': [(t.id(), text) for t,text in result.failures],
        'errors': [(t.id(), text) for t,text in result.errors],
        'loaded_modules': module.S.OBSERVATIONS, 'raw_logs': logs,
        'finalization_controls': controls, 'exit': exit_code,
        'limits': 'REVIEW REQUIRED only; synthetic metadata, no source/adoption validation, runtime, native execution or publication. No original selector named by SC15A; compatibility is new direct-API coverage plus unchanged harmless peer.'}
    (root / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    verify_logs(root, logs)
    print(json.dumps({'receipt': str(root / 'receipt.json'), 'suite': args.suite,
                      'testsRun': result.testsRun, 'subtests': len(result.subtests), 'exit': exit_code}))
    return exit_code

if __name__ == '__main__':
    raise SystemExit(main())
