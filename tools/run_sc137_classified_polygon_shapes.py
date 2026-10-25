#!/usr/bin/env python3
"""Standalone, guarded SC137 acceptance runner; runs only its named test file."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
import uuid

sys.dont_write_bytecode = True


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def file_manifest(root):
    if not root.is_dir():
        raise RuntimeError('required fixture directory is missing: ' + str(root))
    rows = []
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        rows.append({'path': path.relative_to(root).as_posix(), 'sha256': sha256(path)})
    return rows


def validate_admission(manifest, write_root, repo):
    if manifest.get('schema') != 'agentorange.source-manifest/v1':
        return False, 'manifest schema'
    if manifest.get('write_root') != str(write_root) or Path(manifest.get('repo', '')).resolve() != repo:
        return False, 'manifest root identity'
    if manifest.get('head') != '33734f90073a2150eac5a418564ea314c4a591ac':
        return False, 'exact admitted baseline head'
    runtime = manifest.get('runtime', {})
    expected_scanner = str(Path.home() / 'agent-work/tools/venv-fullsuite/bin/python3')
    if runtime.get('credential_scan_python3') != expected_scanner:
        return False, 'exact credential scanner interpreter'
    if manifest.get('clean') is not True or manifest.get('inputs') != []:
        return False, 'clean staged baseline and empty inputs'
    return True, 'admitted manifest'


def preserved_snapshot(source, test_path, spec_path, manifest_path, fixture_root):
    return {'source': sha256(source), 'test': sha256(test_path), 'spec': sha256(spec_path),
            'manifest': sha256(manifest_path), 'fixtures': file_manifest(fixture_root)}


def guard(event, args):
    blocked = ('subprocess.Popen', 'os.system', 'os.fork', 'os.forkpty',
               'os.posix_spawn', 'socket.__new__', 'socket.connect', 'socket.getaddrinfo')
    if event in blocked:
        raise RuntimeError('SC137 guard refused prohibited operation: ' + event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', required=True,
                        choices=('preflight', 'regression', 'compatibility', 'negative-control'))
    parser.add_argument('--source-manifest', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    manifest_path = Path(args.source_manifest).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    write_root = manifest_path.parent
    repo = Path(manifest['repo']).resolve(strict=True)
    tools_dir = Path(__file__).resolve().parent
    if tools_dir != repo / 'tools':
        raise SystemExit('runner must reside in the manifest repository tools directory')
    out_parent = Path(args.out).resolve()
    out_parent.mkdir(parents=True, exist_ok=True)
    run_root = out_parent / (args.suite + '-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
                             + '-' + uuid.uuid4().hex)
    run_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    source = repo / 'src/skippercast/seafloor/classified_geometry.py'
    test_path = repo / 'tests/gis/test_sc137_classified_polygon_shapes.py'
    spec_path = write_root / 'ACCEPTANCE-SPEC.json'
    base = manifest['head']
    head = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                          check=True, capture_output=True, text=True).stdout.strip()
    status = subprocess.run(['git', '-C', str(repo), 'status', '--porcelain=v1',
                             '--untracked-files=all'], check=True, capture_output=True,
                            text=True).stdout
    base_ancestor = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor',
                                    base, head], capture_output=True).returncode == 0
    baseline_source = subprocess.run(['git', '-C', str(repo), 'show',
                                      base + ':src/skippercast/seafloor/classified_geometry.py'],
                                     check=True, capture_output=True).stdout
    baseline_source_sha256 = hashlib.sha256(baseline_source).hexdigest()
    selected_closure = [
        'runner: tools/run_sc137_classified_polygon_shapes.py',
        'test: tests/gis/test_sc137_classified_polygon_shapes.py',
        'product: src/skippercast/seafloor/classified_geometry.py',
        'imports: pyproj, shapely.geometry, shapely.ops, skippercast.seafloor package',
        'fixture: synthetic polygon constructors embedded in the named test module; no external fixture bytes',
    ]
    rc = 0
    test_ids = []
    test_count = 0
    failures = []
    skips = []
    stdout_text = ''
    stderr_text = ''
    inner_failure = None
    checks = []
    fixture_root = repo / 'tests/fixtures/sc137-classified-polygon-shapes'
    before_snapshot = None
    sentinel_path = run_root / 'synthetic-sentinel.txt'
    sentinel_path.write_text('SC137 immutable test sentinel\\n', encoding='utf-8')
    sentinel_before = sha256(sentinel_path)
    run_root_confined = run_root.resolve().is_relative_to(out_parent.resolve())

    def check(condition, label):
        checks.append({'check': label, 'passed': bool(condition)})
        if not condition:
            raise RuntimeError('preflight failure: ' + label)

    if args.suite == 'preflight':
        try:
            valid_manifest, _ = validate_admission(manifest, write_root, repo)
            check(valid_manifest, 'exact operator manifest schema/root/base/scanner/runtime admission')
            negative_base = dict(manifest, head='0' * 40)
            negative_scanner = dict(manifest, runtime=dict(manifest['runtime'],
                                   credential_scan_python3='/tmp/not-the-approved-scanner'))
            check(not validate_admission(negative_base, write_root, repo)[0],
                  'synthetic wrong-base manifest rejected')
            check(not validate_admission(negative_scanner, write_root, repo)[0],
                  'synthetic wrong-scanner manifest rejected')
            check(manifest.get('write_root') == str(write_root), 'manifest write_root identity')
            check(Path(manifest.get('repo', '')).resolve() == repo, 'manifest repo identity')
            check(manifest.get('clean') is True and base_ancestor,
                  'operator staged clean baseline is ancestor of candidate HEAD')
            check(status == '', 'candidate worktree clean for frozen acceptance')
            check(base == '33734f90073a2150eac5a418564ea314c4a591ac',
                  'manifest head is exact admitted full base')
            check(baseline_source_sha256 == 'f43299dca9090ef70f68eff74fd7fb62a2610d292fdbdbfecce4418ae34fa103',
                  'source bytes at admitted base match pinned baseline hash')
            check(manifest.get('inputs') == [] and manifest.get('card') == write_root.name,
                  'operator manifest inputs/card identity')
            expected_venv = Path(manifest['runtime']['repo_venv']).resolve(strict=True)
            check((repo / '.venv').resolve(strict=True) == expected_venv,
                  'linked repo .venv matches manifest runtime')
            check((repo / '.venv/bin/python3').is_file(), 'repo venv interpreter exists')
            expected_scanner = str(Path.home() / 'agent-work/tools/venv-fullsuite/bin/python3')
            check(manifest['runtime']['credential_scan_python3'] == expected_scanner
                  and Path(manifest['runtime']['credential_scan_python3']).is_file(),
                  'credential scanner path exactly matches admitted interpreter')
            check(source.is_file() and test_path.is_file() and spec_path.is_file(),
                  'selected source/test/spec closure exists')
            check(run_root_confined and run_root.parent == out_parent,
                  'exclusive run root confined to selected output parent')
            fixture_before = file_manifest(fixture_root)
            check(bool(fixture_before), 'submitted synthetic fixture closure exists')
            before_snapshot = preserved_snapshot(source, test_path, spec_path, manifest_path, fixture_root)
            check(sha256(sentinel_path) == sentinel_before and sentinel_path.parent == run_root,
                  'synthetic sentinel begins unchanged inside run root')
            sys.addaudithook(guard)
            sys.path.insert(0, str(repo / 'src'))
            import skippercast.paths as paths
            paths.repo_root = lambda: run_root / 'synthetic-repo-root'
            module_spec = importlib.util.spec_from_file_location('sc137_preflight_tests', test_path)
            if module_spec is None or module_spec.loader is None:
                raise RuntimeError('could not load selected preflight test closure')
            test_module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(test_module)
            check(test_module.cg.polygon(test_module.valid_shell_hole()).is_valid,
                  'guarded selected product/test import closure executes valid fixture')
            after_snapshot = preserved_snapshot(source, test_path, spec_path, manifest_path, fixture_root)
            check(after_snapshot == before_snapshot, 'preflight preserves source/test/spec/manifest/fixture hashes')
            check(sha256(sentinel_path) == sentinel_before,
                  'preflight preserves synthetic sentinel hash')
            check(file_manifest(fixture_root) == fixture_before,
                  'guarded preflight preserves submitted fixture identities')
            stdout_text = json.dumps({'preflight': 'passed', 'base': base, 'candidate_head': head,
                                      'selected_import_fixture_closure': selected_closure,
                                      'imported_modules': ['skippercast.paths',
                                                           'skippercast.seafloor.classified_geometry',
                                                           'sc137_preflight_tests'],
                                      'checks': checks}, sort_keys=True, indent=2) + '\n'
        except Exception as exc:
            rc = 1
            stderr_text = str(exc) + '\n'
            stdout_text = json.dumps({'preflight': 'failed', 'base': base, 'candidate_head': head,
                                      'selected_import_fixture_closure': selected_closure,
                                      'checks': checks}, sort_keys=True, indent=2) + '\n'
    else:
        try:
            check(manifest.get('schema') == 'agentorange.source-manifest/v1', 'manifest schema')
            check(manifest.get('write_root') == str(write_root), 'manifest write_root identity')
            check(base == '33734f90073a2150eac5a418564ea314c4a591ac',
                  'operator manifest head is exact admitted base')
            expected_scanner = str(Path.home() / 'agent-work/tools/venv-fullsuite/bin/python3')
            check(manifest.get('runtime', {}).get('credential_scan_python3') == expected_scanner,
                  'credential scanner path exactly matches admitted interpreter')
            check(base_ancestor, 'admitted base is an ancestor of candidate HEAD')
            check(source.is_file() and test_path.is_file() and spec_path.is_file(),
                  'selected source/test/spec closure exists')
            check(run_root_confined and run_root.parent == out_parent,
                  'exclusive run root confined to selected output parent')
            before_snapshot = preserved_snapshot(source, test_path, spec_path, manifest_path, fixture_root)
            check(sha256(sentinel_path) == sentinel_before,
                  'synthetic sentinel begins unchanged inside run root')
            checks.append({'check': 'guards installed before product and test imports', 'passed': True})
            sys.addaudithook(guard)
            sys.path.insert(0, str(repo / 'src'))
            module_spec = importlib.util.spec_from_file_location('sc137_named_tests', test_path)
            if module_spec is None or module_spec.loader is None:
                raise RuntimeError('could not create named test module loader')
            test_module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(test_module)
            method_sets = {
                'regression': ('test_positive_polygon_and_multipolygon_object_identity_and_properties',
                               'test_geojson_polygon_and_multipolygon_mappings_decode_without_mutation',
                               'test_malformed_values_all_use_named_value_error',
                               'test_input_mapping_is_unchanged_on_refusal'),
                'compatibility': ('test_compatibility_shell_hole_and_point_contact_direct_api',),
                'negative-control': ('test_old_unchecked_attribute_boundary_is_decided_by_typed_assertion',),
            }
            test_ids = ['sc137_named_tests.ClassifiedPolygonShapeTests.' + name
                        for name in method_sets[args.suite]]
            suite = unittest.TestSuite(test_module.ClassifiedPolygonShapeTests(name)
                                       for name in method_sets[args.suite])
            stream = io.StringIO()
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
            test_count = result.testsRun
            failures = [{'test': test.id(), 'traceback': trace} for test, trace in result.failures + result.errors]
            skips = [{'test': test.id(), 'reason': reason} for test, reason in result.skipped]
            stdout_text = stream.getvalue()
            if test_count != len(method_sets[args.suite]):
                failures.append({'test': 'suite completeness',
                                'traceback': 'required named test count mismatch'})
            after_snapshot = preserved_snapshot(source, test_path, spec_path, manifest_path, fixture_root)
            check(after_snapshot == before_snapshot,
                  'suite preserves submitted source/test/spec/manifest/fixture identities')
            check(sha256(sentinel_path) == sentinel_before and sentinel_path.parent == run_root,
                  'suite preserves synthetic sentinel and run-root confinement')
            if args.suite == 'negative-control':
                observation = test_module.NEGATIVE_CONTROL_OBSERVATION
                inner_failure = {
                    'mutant_detected': observation.get('typed_refusal_failure', {}).get('type') == 'AttributeError',
                    'mutant_positive_passed': observation.get('mutant_positive_passed') is True,
                    'positive_passed': observation.get('restored_positive_passed') is True,
                    'observed_typed_refusal_failure': observation.get('typed_refusal_failure'),
                }
                check(inner_failure['mutant_detected'] and inner_failure['mutant_positive_passed']
                      and inner_failure['positive_passed'],
                      'negative control derives mutant and positives from observed execution')
            rc = 0 if (test_count > 0 and not failures and not skips) else 1
            if args.suite == 'negative-control' and not inner_failure['positive_passed']:
                rc = 1
        except Exception as exc:
            rc = 1
            stderr_text = type(exc).__name__ + ': ' + str(exc) + '\n'

    (run_root / 'stdout.txt').write_text(stdout_text, encoding='utf-8')
    (run_root / 'stderr.txt').write_text(stderr_text, encoding='utf-8')
    receipt = {
        'schema': 'sc137-acceptance-receipt/v1', 'suite': args.suite,
        'argv': sys.argv, 'cwd': str(Path.cwd()), 'interpreter': sys.executable,
        'exit_code': rc, 'test_ids': test_ids, 'test_count': test_count,
        'failures': failures, 'skips': skips, 'inner_failure': inner_failure,
        'preflight_checks': checks, 'selected_import_fixture_closure': selected_closure,
        'preservation_before': before_snapshot, 'preservation_after': locals().get('after_snapshot'),
        'synthetic_sentinel': {'path': str(sentinel_path), 'sha256_before': sentinel_before,
                               'sha256_after': sha256(sentinel_path),
                               'confined_to_run_root': sentinel_path.parent == run_root},
        'run_root_confined': run_root_confined and run_root.parent == out_parent,
        'base': base, 'candidate_head': head,
        'hashes': {'source': sha256(source), 'test': sha256(test_path),
                   'spec': sha256(spec_path), 'manifest': sha256(manifest_path),
                   'stdout': sha256(run_root / 'stdout.txt'), 'stderr': sha256(run_root / 'stderr.txt')},
        'fixture_hashes': file_manifest(repo / 'tests/fixtures/sc137-classified-polygon-shapes'),
        'run_root': str(run_root),
    }
    (run_root / 'receipt.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n',
                                           encoding='utf-8')
    print(json.dumps({'suite': args.suite, 'exit_code': rc, 'test_count': test_count,
                      'test_ids': test_ids, 'failures': failures, 'skips': skips,
                      'inner_failure': inner_failure, 'run_root': str(run_root),
                      'receipt': str(run_root / 'receipt.json')}, sort_keys=True))
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
