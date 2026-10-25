"""SC162 bounded acceptance; no source/native lifecycle or live CLI execution."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
SPEC_SHA256 = 'c5d16873c4f38bdb0610e73c375f7ac9e776e75bfd2ec08124b459339037a50a'
PRODUCT = 'src/skippercast/coastal/authenticated_v1/source_reuse.py'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_logs(root, expected, required):
    if set(expected) != set(required) or not required:
        return False
    try:
        return all((root / name).is_file()
                   and (root / name).stat().st_size == item['bytes']
                   and sha(root / name) == item['sha256']
                   for name, item in expected.items())
    except (OSError, KeyError, TypeError):
        return False


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


def validate_manifest(path):
    manifest = json.loads(path.read_text())
    if (manifest.get('schema') != 'agentorange.source-manifest/v1'
            or Path(manifest['repo']) != REPO
            or Path(manifest['write_root']) != REPO.parent
            or manifest.get('head') != BASE
            or manifest.get('tree') != git('rev-parse', BASE + '^{tree}')
            or manifest.get('clean') is not True):
        raise ValueError('staged source manifest mismatch')
    runtime = manifest['runtime']
    if (Path(runtime['repo_venv']).resolve() != (REPO / '.venv').resolve()
            or Path(sys.executable).parent.parent.resolve() != Path(runtime['repo_venv']).resolve()
            or not Path(runtime['credential_scan_python3']).is_file()
            or not Path(runtime['system_python3']).is_file()):
        raise ValueError('staged runtime mismatch; existing staging owner required')
    return manifest


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []
        self.subcases = []

    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)

    def addSubTest(self, test, subtest, err):
        self.subcases.append(dict(method=test._testMethodName,
                                  case=subtest.params.get('case'), ok=err is None))
        super().addSubTest(test, subtest, err)


def peer_state():
    return (dict(os.environ), list(sys.path), list(sys.meta_path), sys.dont_write_bytecode,
            socket.socket.connect, socket.create_connection, subprocess.Popen, os.system,
            {name: id(value) for name, value in sys.modules.copy().items()
             if name == 'skippercast' or name.startswith('skippercast.')})


class HarmlessPeer(unittest.TestCase):
    def runTest(self):
        self.assertEqual(json.loads('{"ordinary": [1, true]}'), {'ordinary': [1, True]})
        self.assertTrue(callable(socket.socket.connect))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    manifest = validate_manifest(args.source_manifest)
    if not args.out.resolve().is_relative_to(REPO.parent / 'out'):
        raise ValueError('output must stay under candidate sibling out')
    args.out.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=args.out))
    previous_path = list(sys.path)
    try:
        sys.path.insert(0, str(REPO / 'tests/unit'))
        tests = importlib.import_module('test_sc162_batch_control_json')
    finally:
        sys.path[:] = previous_path
    cases = [tests.BatchControlJSONTests(name) for name in tests.REQUIRED_CASES]
    for case in cases:
        case.output_root = out
    identity_before = git('rev-parse', 'HEAD')
    hashes_before = {name: sha(REPO / name) for name in
                     (PRODUCT, 'tools/run_sc162_batch_control_json.py',
                      'tests/unit/test_sc162_batch_control_json.py',
                      'tests/fixtures/sc162-batch-control-json/control.json')}
    ambient = peer_state()
    stdout = out / 'stdout.log'
    stderr = out / 'stderr.log'
    with stdout.open('w') as so, stderr.open('w') as se:
        with redirect_stdout(so), redirect_stderr(se):
            peer_before = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([HarmlessPeer()]))
            result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(unittest.TestSuite(cases))
            peer_after = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([HarmlessPeer()]))
    restored = peer_state() == ambient
    observed = {name: set() for name in tests.REQUIRED_CASES}
    for subcase in result.subcases:
        if subcase['ok']:
            observed[subcase['method']].add(subcase['case'])
    complete = observed == tests.REQUIRED_CASES and len(result.subcases) == sum(map(len, observed.values()))
    unchanged = (identity_before == git('rev-parse', 'HEAD')
                 and hashes_before == {name: sha(REPO / name) for name in hashes_before})
    events = [event for case in cases for event in getattr(case, 'events', [])]
    negative = [event for event in events if event['case'] == 'legacy-detected']
    control = out / 'integrity-controls'
    control.mkdir()
    positive = control / 'positive.log'
    positive.write_bytes(b'complete log\n')
    known = dict(sha256=sha(positive), bytes=positive.stat().st_size)
    positive_ok = verify_logs(control, {'positive.log': known}, {'positive.log'})
    missing_refused = not verify_logs(control, {'missing.log': known}, {'missing.log'})
    mutation = control / 'mutated.log'
    mutation.write_bytes(b'complete log\nlate append\n')
    mutation_refused = not verify_logs(control, {'mutated.log': known}, {'mutated.log'})
    omission_refused = not verify_logs(control, {}, {'positive.log'})
    integrity_controls = dict(positive=positive_ok, missing_refused=missing_refused,
                              mutated_refused=mutation_refused, omitted_refused=omission_refused)
    # All event/raw writers are closed before sealing; never reseal an older run.
    required_logs = {'stdout.log', 'stderr.log', 'integrity-controls/positive.log',
                     'integrity-controls/mutated.log'} | {
                         str((case.root / 'events.json').relative_to(out)) for case in cases}
    logs = {name: dict(sha256=sha(out / name), bytes=(out / name).stat().st_size)
            for name in sorted(required_logs) if (out / name).is_file()}
    logs_verified = verify_logs(out, logs, required_logs)
    passed = (result.testsRun == 4 and result.wasSuccessful() and not result.skipped
              and complete and restored and unchanged and len(negative) == 1
              and peer_before.wasSuccessful() and peer_after.wasSuccessful()
              and all(integrity_controls.values()) and logs_verified)
    report = dict(schema='sc162-acceptance/v1', status='REVIEW_REQUIRED' if passed else 'FAIL',
                  argv=[sys.executable, *sys.argv], cwd=str(Path.cwd()), interpreter=sys.executable,
                  base=BASE, head=identity_before, staged_runtime=manifest['runtime'],
                  source_manifest_sha256=sha(args.source_manifest), frozen_spec_sha256=SPEC_SHA256,
                  frozen_spec_row='SC162-BATCH-CONTROL-JSON', hashes=hashes_before,
                  imported_origins={k: v for case in cases for k, v in getattr(case, 'origins', {}).items()},
                  test_ids=result.ids, method_count=result.testsRun, subcase_count=len(result.subcases),
                  subcases=result.subcases, required_subcases={k: sorted(v) for k, v in tests.REQUIRED_CASES.items()},
                  failures=[(test.id(), text) for test, text in result.failures],
                  errors=[(test.id(), text) for test, text in result.errors], skips=result.skipped,
                  negative_control=negative, peer_tests=2, peer_state_restored=restored,
                  exact_identity_unchanged=unchanged, original_selectors=[],
                  original_suites='NOT RUN: none admitted; full required CI remains OWED',
                  log_hashes=logs, logs_verified=logs_verified, integrity_controls=integrity_controls,
                  exit=0 if passed else 1)
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(out=str(out), status=report['status'], methods=result.testsRun,
                          subcases=len(result.subcases), skips=len(result.skipped),
                          result_sha256=sha(out / 'result.json')), indent=2))
    print(stderr.read_text())
    return report['exit']


if __name__ == '__main__':
    raise SystemExit(main())
