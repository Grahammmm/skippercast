"""SC178 manifest-preflighted offline API runner; evidence is never overwritten."""
import sys
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import ast  # noqa: E402
from contextlib import redirect_stderr, redirect_stdout  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import traceback  # noqa: E402
import unittest  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
BASE = '67ff9bcf34257698a41585bc2ad163171dc68259'
SOURCE = 'src/skippercast/seafloor/screen.py'
TEST = 'tests/gis/test_sc178_species_fit_types.py'
FIXTURE = 'tests/fixtures/sc178-species-fit-types/constructors.py'
ROOT_MODULE = 'skippercast.seafloor.screen'
# Producers the tests import explicitly in addition to the screen closure.
EXTRA_MODULES = ('skippercast.seafloor.habitat', 'skippercast.seafloor.classified_habitat',
                 'skippercast.seafloor.bedrock_habitat')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    completed = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, check=True)
    return completed.stdout


def module_file(name):
    base = REPO / 'src' / Path(*name.split('.'))
    if (base / '__init__.py').is_file():
        return base / '__init__.py'
    return base.with_suffix('.py') if base.with_suffix('.py').is_file() else None


def static_closure():
    """Every skippercast module reachable by any import statement (conservative)."""
    seen, queue = {}, [ROOT_MODULE, *EXTRA_MODULES]
    while queue:
        name = queue.pop()
        if name in seen or not name.startswith('skippercast'):
            continue
        path = module_file(name)
        if path is None:
            continue
        seen[name] = path
        parts = name.split('.')
        queue.extend('.'.join(parts[:i]) for i in range(1, len(parts)))
        package = name if path.name == '__init__.py' else name.rsplit('.', 1)[0]
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                queue.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    pkg = package.split('.')
                    module = '.'.join(pkg[:len(pkg) - node.level + 1]) + ('.' + node.module if node.module else '')
                else:
                    module = node.module
                queue.append(module)
                queue.extend(module + '.' + alias.name for alias in node.names)
    return seen


def preflight(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    if manifest['schema'] != 'agentorange.source-manifest/v1':
        raise ValueError('wrong manifest schema')
    root = Path(manifest['write_root']).resolve()
    if Path(manifest['repo']).resolve() != REPO or root / 'repo' != REPO:
        raise ValueError('staging identity mismatch')
    if manifest['head'] != BASE or git('rev-parse', BASE).decode().strip() != BASE:
        raise ValueError('moved staging base')
    if git('rev-parse', BASE + '^{tree}').decode().strip() != manifest['tree']:
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
    if hashlib.sha256(git('show', BASE + ':' + SOURCE)).hexdigest() != spec['source_sha256']:
        raise ValueError('frozen source pin mismatch')
    closure = {}
    for name, path in sorted(static_closure().items()):
        if not path.resolve().is_relative_to(REPO / 'src'):
            raise ValueError('escaped inspected closure')
        relative = str(path.relative_to(REPO))
        closure[relative] = digest(path)
        if relative != SOURCE and hashlib.sha256(git('show', BASE + ':' + relative)).hexdigest() != closure[relative]:
            raise ValueError('unadmitted import closure edit: ' + relative)
    return root, spec, {'base': BASE, 'head': git('rev-parse', 'HEAD').decode().strip(),
                        'tracked_status': git('status', '--porcelain', '--untracked-files=no').decode(),
                        'source_sha256': digest(REPO / SOURCE),
                        'test_sha256': digest(REPO / TEST), 'fixture_sha256': digest(REPO / FIXTURE),
                        'runner_sha256': digest(Path(__file__)),
                        'source_manifest_sha256': digest(manifest_path),
                        'spec_sha256': digest(spec_path), 'closure_hashes': closure,
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
                        help='Initial red assertions and unchanged integer positive only')
    args = parser.parse_args()
    root, frozen, identity = preflight(args.source_manifest.resolve())
    out = args.out.resolve()
    if not out.is_relative_to(root) or out.is_relative_to(REPO):
        raise ValueError('output must stay in candidate evidence, outside repo')
    out.mkdir(parents=True, exist_ok=True)
    invocation = Path(tempfile.mkdtemp(prefix='run-', dir=out))
    result = {'schema': 'sc178.result/v1', 'identity': identity, 'argv': sys.argv,
              'cwd': str(Path.cwd()), 'baseline': args.baseline, 'status': 'FAILED',
              'invocation': str(invocation)}
    stdout, stderr = invocation / 'stdout.txt', invocation / 'stderr.txt'
    exit_code = 1
    with stdout.open('w') as output, stderr.open('w') as errors:
        with redirect_stdout(output), redirect_stderr(errors):
            try:
                print(json.dumps(identity, indent=2))
                # The test module imports tests._support, so the repo root must be importable.
                if str(REPO) not in sys.path:
                    sys.path.insert(0, str(REPO))
                spec = importlib.util.spec_from_file_location('test_sc178_species_fit_types', REPO / TEST)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                cls = module.SpeciesFitTypeTests
                cls.output_prefix = invocation
                cls.records, cls.preservation, cls.fixture_hashes = [], [], []
                cls.negative_control, cls.origins = [], {}
                state = module.ambient_state()

                class Peer(unittest.TestCase):
                    def runTest(self):
                        self.assertEqual(module.ambient_state(), state)
                        paths = sys.modules.get('skippercast.paths')
                        if paths is not None:
                            self.assertEqual(paths.repo_root(), REPO)
                            for name in ('skippercast.platform.contracts', 'skippercast.seafloor.search_areas',
                                         'skippercast.seafloor.classified_habitat'):
                                self.assertEqual(sys.modules[name].REPO, REPO)
                            self.assertIs(sys.modules['skippercast.platform.contracts'].repo_root, paths.repo_root)
                            self.assertFalse(hasattr(sys.modules['skippercast.seafloor.screen'].screen_candidates,
                                                     '_mock_name'))

                peer_before = unittest.TextTestRunner(stream=errors, verbosity=2).run(unittest.TestSuite([Peer()]))
                if not peer_before.wasSuccessful():
                    raise ValueError('pre-suite peer failed')
                if args.baseline:
                    if identity['head'] != BASE or identity['source_sha256'] != frozen['source_sha256']:
                        raise ValueError('baseline requires unchanged pinned product')

                    class Baseline(cls):
                        def test_initial_bool_red(self):
                            self.assert_held_fit(self.fx.malformed('bool-true-rank'))

                        def test_initial_list_red(self):
                            self.assert_held_fit(self.fx.malformed('list-fit'))

                        def test_initial_positive(self):
                            passed, held, _ = self.run_screen([self.fx.candidate('positive', fit={'lingcod': 3})])
                            self.assertFalse(held['features'])
                            self.assert_passed_habitat(passed['features'][0])

                    suite = unittest.TestSuite([Baseline('test_initial_bool_red'), Baseline('test_initial_list_red'),
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
                               'dependency_env_effects_restored': module.DEPENDENCY_ENV,
                               'peer_tests': {'before': peer_before.wasSuccessful(),
                                              'after': peer_after.wasSuccessful()}})
                for key in ('failures', 'errors', 'skips'):
                    result[key] = [[test.id(), text] for test, text in result[key]]
                origins_ok = all(Path(origin).is_relative_to(REPO / 'src') for origin in cls.origins.values())
                result['origins_inside_candidate'] = origins_ok
                if args.baseline:
                    failures = {test.id().rsplit('.', 1)[1]: text for test, text in actual.failures}
                    errors_by = {test.id().rsplit('.', 1)[1]: text for test, text in actual.errors}
                    valid = (actual.testsRun == 3 and not actual.skipped and origins_ok
                             and set(failures) == {'test_initial_bool_red'}
                             and 'malformed fit passed: bad-bool-true-rank' in failures['test_initial_bool_red']
                             and set(errors_by) == {'test_initial_list_red'}
                             and "AttributeError: 'list' object has no attribute 'values'"
                             in errors_by['test_initial_list_red']
                             and peer_after.wasSuccessful())
                    result['status'] = 'BASELINE_REPRODUCED' if valid else 'BASELINE_INVALID'
                    # A deciding red is a real failing invocation, never a green receipt.
                else:
                    expected = {(method, case) for method, cases in frozen['requirements'].items() for case in cases}
                    seen = [(record['method'], record['case']) for record in cls.records]
                    valid = (actual.wasSuccessful() and actual.testsRun == 4 and not actual.skipped
                             and len(seen) == len(expected) and set(seen) == expected
                             and all(record['ok'] for record in cls.records) and origins_ok
                             and len(cls.negative_control) == 1 and cls.negative_control[0]['detected']
                             and peer_after.wasSuccessful())
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
    (invocation / 'result.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
    print(json.dumps({'status': result['status'], 'exit': exit_code, 'result': str(invocation / 'result.json'),
                      'tests': result.get('tests_run'), 'subcases': len(result.get('subcases', [])),
                      'failures': len(result.get('failures', [])), 'errors': len(result.get('errors', []))}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
