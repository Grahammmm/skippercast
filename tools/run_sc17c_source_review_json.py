"""SC17C manifest-preflighted offline API runner; evidence is never overwritten."""
import sys
sys.dont_write_bytecode = True

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import traceback
import unittest

REPO = Path(__file__).resolve().parents[1]
BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
SOURCE = 'src/skippercast/seafloor/source_review.py'
TEST = 'tests/unit/test_sc17c_source_review_json.py'
CONSTRUCTORS = 'tests/fixtures/sc17c-source-review-json/constructors.py'
CLOSURE = ('__init__.py', 'paths.py', 'platform/__init__.py', 'platform/contracts.py',
           'seafloor/__init__.py', 'seafloor/io.py', 'seafloor/source_review.py', 'http.py',
           'util/__init__.py', 'util/time.py', 'util/hashing.py')
OVERFLOW = ('overflow-positive', 'overflow-negative', 'overflow-exponent', 'overflow-top-level')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    completed = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, check=True)
    return completed.stdout.decode().strip()


def base_blob(relative):
    return subprocess.run(['git', '-C', str(REPO), 'show', BASE + ':' + relative],
                          capture_output=True, check=True).stdout


def preflight(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    if manifest['schema'] != 'agentorange.source-manifest/v1':
        raise ValueError('wrong manifest schema')
    root = Path(manifest['write_root']).resolve()
    if Path(manifest['repo']).resolve() != REPO or root / 'repo' != REPO:
        raise ValueError('staging identity mismatch')
    if manifest['head'] != BASE or git('rev-parse', BASE) != BASE:
        raise ValueError('moved staging base')
    if git('rev-parse', BASE + '^{tree}') != manifest['tree']:
        raise ValueError('staging tree mismatch')
    if (REPO / '.venv').resolve() != Path(manifest['runtime']['repo_venv']).resolve():
        raise ValueError('staged venv mismatch')
    if Path(sys.prefix).resolve() != Path(manifest['runtime']['repo_venv']).resolve():
        raise ValueError('runner interpreter mismatch')
    if not Path(manifest['runtime']['credential_scan_python3']).is_file():
        raise ValueError('scan interpreter unavailable')
    spec_path = root / 'ACCEPTANCE-SPEC.json'
    spec = json.loads(spec_path.read_text())
    if spec['base'] != BASE or spec['source'] != SOURCE:
        raise ValueError('frozen spec pin mismatch')
    if hashlib.sha256(base_blob(SOURCE)).hexdigest() != spec['source_sha256']:
        raise ValueError('pinned source bytes differ from frozen spec')
    closure = {}
    for relative in CLOSURE:
        path = REPO / 'src/skippercast' / relative
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(REPO):
            raise ValueError('missing/escaped inspected closure')
        name = str(path.relative_to(REPO))
        closure[name] = digest(path)
        if name != SOURCE and hashlib.sha256(base_blob(name)).hexdigest() != closure[name]:
            raise ValueError('unadmitted import closure edit')
    return root, spec, {'base': BASE, 'head': git('rev-parse', 'HEAD'),
                        'tracked_status': git('status', '--porcelain', '--untracked-files=no'),
                        'source_manifest_sha256': digest(manifest_path),
                        'spec_sha256': digest(spec_path), 'closure_hashes': closure,
                        'source_sha256': digest(REPO / SOURCE),
                        'test_sha256': digest(REPO / TEST),
                        'constructors_sha256': digest(REPO / CONSTRUCTORS),
                        'runner_sha256': digest(Path(__file__)),
                        'runtime': {'executable': sys.executable, 'prefix': sys.prefix,
                                    'version': sys.version, 'manifest': manifest['runtime']}}


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = []

    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--baseline', action='store_true',
                        help='Initial red overflow assertion, premise check and valid positive only')
    args = parser.parse_args()
    root, frozen, identity = preflight(args.source_manifest.resolve())
    out = args.out.resolve()
    if not out.is_relative_to(root) or out.is_relative_to(REPO):
        raise ValueError('output must stay in candidate evidence, outside repo')
    out.mkdir(parents=True, exist_ok=True)
    invocation = Path(tempfile.mkdtemp(prefix='run-', dir=out))
    result = {'schema': 'sc17c.result/v1', 'identity': identity, 'argv': sys.argv,
              'cwd': str(Path.cwd()), 'baseline': args.baseline, 'status': 'FAILED',
              'invocation': str(invocation)}
    stdout, stderr = invocation / 'stdout.txt', invocation / 'stderr.txt'
    exit_code = 1
    with stdout.open('w') as output, stderr.open('w') as errors:
        with redirect_stdout(output), redirect_stderr(errors):
            try:
                print(json.dumps(identity, indent=2))
                spec = importlib.util.spec_from_file_location('test_sc17c_source_review_json', REPO / TEST)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                cls = module.SourceReviewJsonTests
                cls.output_prefix = invocation
                cls.records, cls.preservation, cls.fixture_hashes = [], [], []
                cls.negative_control, cls.origins = [], {}
                state = module.ambient_state()

                class Peer(unittest.TestCase):
                    def runTest(self):
                        self.assertEqual(module.ambient_state(), state)
                        contracts = sys.modules.get('skippercast.platform.contracts')
                        if contracts:
                            paths = sys.modules['skippercast.paths']
                            self.assertEqual(contracts.REPO, paths.repo_root())
                            self.assertEqual(contracts.load_region.__defaults__, (paths.repo_root(),))
                            self.assertIs(sys.modules['skippercast.http'].Session.__init__.__kwdefaults__['resolver'],
                                          module.socket.getaddrinfo)
                        review = sys.modules.get('skippercast.seafloor.source_review')
                        if review is not None and hasattr(review, '_decode_checkpoint'):
                            self.assertIsNot(review._decode_checkpoint, module.ordinary_json_loads)

                peer_before = unittest.TextTestRunner(stream=errors, verbosity=2).run(unittest.TestSuite([Peer()]))
                if not peer_before.wasSuccessful():
                    raise ValueError('pre-suite peer failed')
                if args.baseline:
                    if identity['head'] != BASE or identity['source_sha256'] != frozen['source_sha256']:
                        raise ValueError('baseline requires unchanged pinned product')

                    class Baseline(cls):
                        def test_initial_overflow(self):
                            for name in OVERFLOW:
                                with self.case(f'initial-red:{name}'):
                                    root_, _ = self.malformed(name)
                                    self.assert_refused(root_)

                        def test_initial_impact(self):
                            # Unchanged product: an overflow checkpoint really suppresses its lead.
                            for name in OVERFLOW:
                                with self.case(f'initial-impact-deferred:{name}'):
                                    root_, _ = self.malformed(name)
                                    self.assert_valid_defers_own_lead(root_)

                        def test_initial_premise(self):
                            for name in self.fixtures.MALFORMED:
                                if name not in OVERFLOW:
                                    with self.case(f'premise-already-refused:{name}'):
                                        root_, _ = self.malformed(name)
                                        self.assert_refused(root_)

                        def test_initial_positive(self):
                            with self.case('initial-positive'):
                                valid, _, _ = self.tree('initial-positive')
                                self.assert_valid_defers_own_lead(valid)

                    suite = unittest.TestSuite([Baseline('test_initial_overflow'),
                                                Baseline('test_initial_impact'),
                                                Baseline('test_initial_premise'),
                                                Baseline('test_initial_positive')])
                else:
                    if set(frozen['requirements']) != set(module.METHODS):
                        raise ValueError('empty or changed method collection')
                    suite = unittest.TestSuite(cls(name) for name in module.METHODS)
                actual = unittest.TextTestRunner(stream=errors, verbosity=2, resultclass=RecordingResult).run(suite)
                peer_after = unittest.TextTestRunner(stream=errors, verbosity=2).run(unittest.TestSuite([Peer()]))
                result.update({'tests_run': actual.testsRun, 'ids': actual.ids,
                               'failures': actual.failures, 'errors': actual.errors, 'skips': actual.skipped,
                               'subcases': cls.records, 'preservation': cls.preservation,
                               'negative_control': cls.negative_control, 'module_origins': cls.origins,
                               'fixture_hashes': cls.fixture_hashes,
                               'peer_tests': {'before': peer_before.wasSuccessful(), 'after': peer_after.wasSuccessful()}})
                # unittest failures hold TestCase objects; retain their real IDs instead.
                for key in ('failures', 'errors', 'skips'):
                    result[key] = [[test.id(), text] for test, text in result[key]]
                origins_ok = all(path.startswith(str(REPO / 'src') + '/') for path in cls.origins.values())
                result['origins_inside_candidate'] = origins_ok
                if args.baseline:
                    red = {r['case'] for r in cls.records if not r['ok']}
                    green = {r['case'] for r in cls.records if r['ok']}
                    valid = (actual.testsRun == 4 and not actual.errors and not actual.skipped
                             and len(actual.failures) == len(OVERFLOW)
                             and all('test_initial_overflow' in test.id() and 'ValueError not raised' in text
                                     for test, text in actual.failures)
                             and red == {f'initial-red:{n}' for n in OVERFLOW}
                             and 'initial-positive' in green and origins_ok
                             and {f'initial-impact-deferred:{n}' for n in OVERFLOW} <= green
                             and peer_after.wasSuccessful())
                    result['premise_already_refused'] = sorted(c for c in green if c.startswith('premise-'))
                    result['status'] = 'BASELINE_REPRODUCED' if valid else 'BASELINE_INVALID'
                    # A deciding red is a real failing invocation, not a green receipt.
                else:
                    expected = {(method, case) for method, cases in frozen['requirements'].items() for case in cases}
                    seen = [(record['method'], record['case']) for record in cls.records]
                    valid = (actual.wasSuccessful() and actual.testsRun == 4 and not actual.skipped
                             and len(seen) == len(expected) and set(seen) == expected
                             and all(record['ok'] for record in cls.records)
                             and len(cls.negative_control) == 1 and cls.negative_control[0]['detected']
                             and all(cls.negative_control[0].get('sweep', {}).values())
                             and len(cls.negative_control[0].get('sweep', {})) == 20
                             and origins_ok and peer_after.wasSuccessful())
                    result['required_subcases'] = len(expected)
                    result['status'] = 'REVIEW_REQUIRED' if valid else 'FAILED'
                    exit_code = 0 if valid else 1
                if digest(args.source_manifest) != identity['source_manifest_sha256']:
                    raise ValueError('staging manifest changed during run')
                print(json.dumps({'status': result['status'], 'tests': actual.testsRun,
                                  'subcases': len(cls.records), 'failures': len(actual.failures),
                                  'errors': len(actual.errors), 'skips': len(actual.skipped)}))
            except BaseException:
                result['status'] = 'FAILED'
                exit_code = 1
                traceback.print_exc()
    result['exit_code'] = exit_code
    result['raw_logs'] = {p.name: digest(p) for p in (stdout, stderr)}
    (invocation / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'exit': exit_code, 'result': str(invocation / 'result.json'),
                      'tests': result.get('tests_run'), 'subcases': len(result.get('subcases', [])),
                      'failures': len(result.get('failures', [])), 'errors': len(result.get('errors', []))}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
