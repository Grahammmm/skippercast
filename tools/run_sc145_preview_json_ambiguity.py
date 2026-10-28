#!/usr/bin/env python3
"""Run only SC145's offline direct-API tests; never invoke an operational CLI."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import unittest

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
BASE = '8a805820c30895f5f037e26af9079fd3dc015b0f'
BASE_PREVIEW_SHA256 = 'ae2503049c48bdcb1c85602e7bcf671f8277fb809b3fe3322714441ec2f9e255'
SUITES = {
    'preflight': ['test_preflight'],
    'regression': ['test_valid_shapes', 'test_finite_spellings', 'test_duplicates',
                   'test_named_nonfinite', 'test_overflow', 'test_malformed', 'test_byte_bound'],
    'compatibility': ['test_valid_shapes', 'test_finite_spellings', 'test_alignment_shape', 'test_completion_shapes'],
    'negative-control': ['test_negative_control'],
    'baseline': ['test_valid_shapes', 'test_duplicates', 'test_overflow'],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(*args):
    # The only pre-guard children are literal read-only git queries.
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


class RecordingResult(unittest.TextTestResult):
    def startTest(self, test):
        self.executed.append(test.id())
        super().startTest(test)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed = []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=SUITES, required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    candidate = REPO.parent
    prefix = args.out.resolve()
    require(prefix.is_relative_to(candidate / 'out'), 'out must be candidate-local out/')
    prefix.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=prefix))
    stdout, stderr = io.StringIO(), io.StringIO()
    receipt = {'schema': 'sc145.receipt/v1', 'suite': args.suite,
               'argv': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
               'cwd': str(Path.cwd()), 'run_root': str(run), 'exit': 1}
    start = time.monotonic()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            require(Path.cwd().resolve() == REPO, 'acceptance cwd')
            manifest_path = args.source_manifest.resolve()
            require(manifest_path == candidate / 'SOURCE-MANIFEST.json', 'manifest location')
            manifest = json.loads(manifest_path.read_text())
            initial = json.loads((candidate / 'INITIAL-STAGE.json').read_text())
            spec_path = candidate / 'ACCEPTANCE-SPEC.json'
            spec = json.loads(spec_path.read_text())
            require(manifest['schema'] == 'agentorange.source-manifest/v1', 'manifest schema')
            require(Path(manifest['repo']) == REPO and Path(manifest['write_root']) == candidate,
                    'candidate/repo identity')
            require(manifest['card'] in {candidate.name, 't_ad90a611'}, 'manifest card')
            require(manifest['head'] == spec['base'] == initial['head'] == BASE, 'base identity')
            require(manifest['tree'] == git('rev-parse', BASE + '^{tree}'), 'base tree')
            require(manifest['clean'] is True and initial['clean'] is True, 'initial clean attestation')
            require(sha(manifest_path) == initial['manifest_sha256'] == spec['manifest_sha256'], 'unchanged manifest')
            require(initial['preview_sha256'] == BASE_PREVIEW_SHA256, 'initial source pin')
            require((REPO / '.venv').resolve() == Path(manifest['runtime']['repo_venv']).resolve()
                    == Path(sys.prefix).resolve(), 'literal repo venv identity')
            require(Path(manifest['runtime']['credential_scan_python3']) ==
                    candidate.parents[1] / 'tools/venv-fullsuite/bin/python3', 'literal scan interpreter')
            require(SUITES == spec['suites'], 'frozen suite test IDs')
            head = git('rev-parse', 'HEAD')
            require(git('merge-base', BASE, head) == BASE, 'head must descend from admitted base')
            status = git('status', '--porcelain')
            if args.suite != 'baseline':
                require(not status, 'final acceptance requires clean signed-off head')
                require('Signed-off-by: ' in git('log', '-1', '--format=%B'), 'signed-off candidate')
            test_path = REPO / 'tests/unit/test_sc145_preview_json_ambiguity.py'
            receipt.update(head=head, base=BASE, initial_stage=initial,
                           manifest_sha256=sha(manifest_path), spec_sha256=sha(spec_path),
                           git_status=status, implementation_sha256=sha(REPO / 'src/skippercast/coastal/render/preview.py'))
            # sys.path[0] is tools/ here; the test module imports tests._support and the
            # product closure, so put the checkout and its src/ first (runner-only).
            sys.path[:0] = [str(REPO / 'src'), str(REPO)]
            module_spec = importlib.util.spec_from_file_location('sc145_private_tests', test_path)
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            module.RUN_ROOT = run
            selected = unittest.TestSuite(module.SC145PreviewJSON(name) for name in SUITES[args.suite])
            result = unittest.TextTestRunner(stream=stderr, verbosity=2, resultclass=RecordingResult).run(selected)
            receipt.update(tests_run=result.testsRun, executed_test_ids=result.executed,
                           failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                           controls=module.SC145PreviewJSON.controls,
                           preservation=module.SC145PreviewJSON.records)
            sources = []
            for name in module.CLOSURE:
                path = Path(sys.modules[name].__file__).resolve()
                require(path.is_relative_to(REPO / 'src'), 'foreign product code')
                sources.append({'module': name, 'source': str(path.relative_to(REPO)), 'sha256': sha(path)})
            receipt['closure'] = {'read_only_product_sources': sources,
                                  'runtime_code_roots': [str(Path(sys.base_prefix).resolve()), str(Path(sys.prefix).resolve())],
                                  'synthetic_data_root': str(module.SC145PreviewJSON.root),
                                  'platform_contracts_imported': 'skippercast.platform.contracts' in sys.modules,
                                  'bound_data_defaults': [],
                                  'render_network_model_children': 'forbidden by scoped pre-import guards; none invoked',
                                  'limits': 'Scoped import/API safety controls, not a hostile-code sandbox.'}
            receipt['authored_source_hashes'] = {
                str(path.relative_to(REPO)): sha(path) for path in [Path(__file__).resolve(), test_path]}
            fixture = REPO / 'tests/fixtures/sc145-preview-json-ambiguity'
            receipt['fixture_hashes'] = {str(path.relative_to(REPO)): sha(path)
                                         for path in fixture.rglob('*') if path.is_file()} if fixture.exists() else {}
            receipt['synthetic_files'] = {str(path.relative_to(run)): sha(path)
                                          for path in run.rglob('*') if path.is_file()}
            receipt['integration_owed'] = 'Full original repository integration suites remain owed to exact-head CI; no render run.'
            require(result.testsRun == len(SUITES[args.suite]) and not result.skipped, 'missing/skipped required tests')
            require(result.wasSuccessful(), 'required assertion failed')
            if args.suite == 'negative-control':
                require(receipt['controls'].get('mutant_detected') is True and
                        receipt['controls'].get('positive_passed') is True, 'negative-control deciding gate')
            receipt['exit'] = 0
        except Exception:
            traceback.print_exc(file=stderr)
    receipt['duration_seconds'] = time.monotonic() - start
    summary = {'suite': args.suite, 'head': receipt.get('head'), 'exit': receipt['exit'],
               'tests_run': receipt.get('tests_run', 0), 'receipt': str(run / 'receipt.json')}
    stdout.write(json.dumps(summary, sort_keys=True) + '\n')
    for name, stream in [('stdout.txt', stdout), ('stderr.txt', stderr)]:
        with (run / name).open('x') as file:
            file.write(stream.getvalue())
    receipt['raw_outputs'] = {name: sha(run / name) for name in ['stdout.txt', 'stderr.txt']}
    with (run / 'receipt.json').open('x') as file:
        json.dump(receipt, file, indent=2, sort_keys=True)
        file.write('\n')
    sys.stdout.write(stdout.getvalue())
    sys.stderr.write(stderr.getvalue())
    return receipt['exit']


if __name__ == '__main__':
    raise SystemExit(main())
