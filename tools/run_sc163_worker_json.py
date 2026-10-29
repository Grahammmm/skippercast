"""Run the four bounded SC163 direct-API methods; preserve unique sealed evidence."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
import unittest

REPO = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
METHODS = ['test_regression', 'test_compatibility', 'test_negative_control', 'test_preservation']
EXPECTED = {
    'test_regression': ['stage_conflict', 'stage_equal', 'lease_conflict', 'lease_equal', 'job_identity',
                        'nested_conflict', 'nested_equal', 'array_nested', 'escaped_key',
                        'positive_overflow', 'negative_overflow', 'nested_overflow'],
    'test_compatibility': ['unique_finite', 'finite_exponent', 'unicode', 'qualify_optional', 'NaN', 'Infinity', '-Infinity'],
    'test_negative_control': ['legacy_positive', 'same_assertion_detects_legacy_acceptance',
                              'restored_duplicate_rejected', 'restored_unique_positive'],
    'test_preservation': ['empty', 'oversize', 'list', 'null', 'scalar', 'malformed_json', 'malformed_utf8',
                          'fingerprint', 'truncate', 'grow', 'exact_byte_limit', 'wrong_namespace', 'hardlink',
                          'symlink_leaf', 'symlink_ancestor', 'nonregular_directory'],
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def head():
    git = REPO / '.git'
    if git.is_file():
        git = (REPO / git.read_text().strip().split(': ', 1)[1]).resolve()
    value = (git / 'HEAD').read_text().strip()
    if value.startswith('ref: '):
        ref = value[5:]
        if (git / ref).is_file():
            return (git / ref).read_text().strip()
        for line in (git / 'packed-refs').read_text().splitlines():
            if line.endswith(' ' + ref):
                return line.split()[0]
        raise ValueError('unresolved head')
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.source_manifest.read_text())
    if (manifest.get('schema') != 'agentorange.source-manifest/v1' or
            Path(manifest['repo']).resolve() != REPO or Path(manifest['write_root']).resolve() != REPO.parent or
            manifest['head'] != BASE or manifest['runtime']['repo_venv'] != str((REPO / '.venv').resolve()) or
            not Path(manifest['runtime']['credential_scan_python3']).is_file()):
        raise ValueError('staging manifest mismatch')
    output_base = args.out.resolve()
    if not output_base.is_relative_to(REPO.parent / 'out'):
        raise ValueError('output must be under candidate sibling out')
    output_base.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=output_base))
    sys.dont_write_bytecode = True
    test_file = REPO / 'tests/unit/test_sc163_worker_json.py'
    spec = importlib.util.spec_from_file_location('sc163_tests', test_file)
    module = importlib.util.module_from_spec(spec)
    record = dict(argv=sys.argv, cwd=str(Path.cwd()), interpreter=sys.executable,
                  base=BASE, head=head(), manifest_sha256=sha(args.source_manifest),
                  frozen_spec_source_sha256='c5d16873c4f38bdb0610e73c375f7ac9e776e75bfd2ec08124b459339037a50a',
                  fixture_hashes={'tests/fixtures/sc163-worker-json/producer.json': sha(REPO / 'tests/fixtures/sc163-worker-json/producer.json')},
                  spec_sha256=hashlib.sha256(json.dumps(EXPECTED, sort_keys=True).encode()).hexdigest(),
                  original_selectors=[], original_suites_executed=False,
                  source_hashes={str(p.relative_to(REPO)): sha(p) for p in
                                 (test_file, Path(__file__), REPO / 'src/skippercast/coastal/authenticated_v1/worker.py')},
                  expected=EXPECTED, output=str(out), status='FAIL')
    with (out / 'stdout.log').open('w') as stdout, (out / 'stderr.log').open('w') as stderr:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                # The test imports ROOT from tests._support (repo layout rule), so the
                # candidate root must be importable when this runner loads it by path.
                if str(REPO) not in sys.path:
                    sys.path.insert(0, str(REPO))
                spec.loader.exec_module(module)
                module.OUTPUT_ROOT = out
                suite = unittest.TestSuite(module.WorkerJSONTests(name) for name in METHODS)
                result = unittest.TextTestRunner(stream=stderr, verbosity=2).run(suite)
                actual = {name: [e['subcase'] for e in module.EVENTS if e['method'] == name] for name in METHODS}
                record.update(tests_run=result.testsRun, ids=[module.WorkerJSONTests(n).id() for n in METHODS],
                              events=module.EVENTS, actual=actual, origins=module.ORIGINS, control=module.CONTROL,
                              failures=len(result.failures), errors=len(result.errors), skips=len(result.skipped),
                              subcases=sum(len(v) for v in actual.values()))
                if (result.wasSuccessful() and result.testsRun == 4 and not result.skipped and actual == EXPECTED
                        and module.CONTROL.get('detected') and module.CONTROL.get('restored_positive')):
                    record['status'] = 'PASS_REVIEW_REQUIRED'
            except Exception:
                traceback.print_exc()
    # All log writers have exited before sealing. Never overwrite a previous run.
    record['logs'] = {name: {'sha256': sha(out / name), 'bytes': (out / name).stat().st_size}
                      for name in ('stdout.log', 'stderr.log')}
    record['exit'] = 0 if record['status'] == 'PASS_REVIEW_REQUIRED' else 1
    (out / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
    return record['exit']


if __name__ == '__main__':
    raise SystemExit(main())
