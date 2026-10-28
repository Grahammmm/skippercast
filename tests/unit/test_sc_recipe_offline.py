"""SC-RECIPE-OFFLINE: recipe schema references never reach another resource.

A1 (test_a1_*): the four committed recipes, admitted same-document fragments,
local refusal of external references (also inside branches no instance
traverses), fail-closed missing jsonschema and the CLI INVALID result.
A2 (test_a2_*): zero transport calls and zero reads outside the staged
metadata/workspace roots, on the success and the error-reporting paths.
A3 (test_a3_*): negatives (nested, file, traversal, duplicate keys, malformed
fragments, invalid schema shape, non-finite values) and the isolated mutation
control whose regression fails on an in-memory retrieval counter.

All schema edits are synthetic, in memory or under tmp_path. Every external
address uses the reserved .invalid domain or is a relative name; none is ever
contacted: transport entrypoints are replaced by refusing doubles and the
retrieval callback is a counting double that performs no I/O.
See docs/engineering/sc_recipe_offline.md.
"""
from copy import deepcopy
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import urllib.request

import pytest

from tests._support import FIXTURES, ROOT
import validate_recipe as recipe

FIXTURE = FIXTURES / 'sc_recipe_offline'
SCHEMA = 'schemas/coast-recipe-v1.schema.json'
SCHEMA_SHA256 = 'a659d136536a553043fac917473428ae0c6e51bdb179cc66bdd295e09ebf1593'
SLUGS = ('morro-bay', 'cambria-san-simeon', 'south-big-sur-san-simeon',
         'santa-cruz-monterey-bay')
METADATA = [SCHEMA, 'catalog/sources.json', 'catalog/coastal-sectors.json']
METADATA += ['regions/' + slug + '/region.json' for slug in SLUGS]
CASES = json.loads((FIXTURE / 'reference-cases.json').read_text(encoding='utf-8'))
REJECTED = {case['id']: case for case in CASES['rejected']}
ADMITTED = {case['id']: case for case in CASES['admitted']}
TRAVERSED = [key for key, case in REJECTED.items() if case.get('traversed')]
NOT_ADMITTED = 'schema reference not admitted: '
VALID = {'status': 'REVIEW REQUIRED', 'valid': True, 'semantic_approval': False,
         'execution_allowed': False, 'not_for_navigation': True}
INVALID_FIELDS = {'path', 'status', 'valid', 'error', 'semantic_approval', 'execution_allowed'}

TRANSPORT = []    # refused transport calls (must stay empty)
RETRIEVALS = []   # calls to the counting retrieval double (must stay empty)
AUDIT = {'opened': None}


def _audit(event, args):
    opened = AUDIT['opened']
    if opened is not None and event in ('open', 'os.listdir', 'os.scandir'):
        if args and isinstance(args[0], (str, bytes, os.PathLike)):
            opened.append(os.fsdecode(args[0]))


sys.addaudithook(_audit)


def counting_retrieval(uri):
    """Synthetic retrieval double: count in memory and raise; never any I/O."""
    RETRIEVALS.append(uri)
    raise LookupError('synthetic retrieval double refused ' + str(uri))


@pytest.fixture(autouse=True)
def offline_sentinels(monkeypatch):
    """Refuse DNS, sockets, HTTP and subprocesses; count any schema retrieval."""
    TRANSPORT.clear()
    RETRIEVALS.clear()

    def refused(name):
        def call(*args, **kwargs):
            TRANSPORT.append(name)
            raise AssertionError('transport refused during offline acceptance: ' + name)
        return call

    targets = [
        (socket, ['socket', 'create_connection', 'getaddrinfo', 'gethostbyname',
                  'gethostbyname_ex', 'gethostbyaddr', 'getnameinfo']),
        (http.client.HTTPConnection, ['connect', 'request']),
        (http.client.HTTPSConnection, ['connect']),
        (urllib.request, ['urlopen']),
        (urllib.request.OpenerDirector, ['open']),
        (subprocess, ['Popen', 'run', 'call', 'check_call', 'check_output']),
        (os, ['system']),
    ]
    for owner, names in targets:
        for name in names:
            monkeypatch.setattr(owner, name, refused(getattr(owner, '__name__', '?') + '.' + name))
    # The production hook is replaced by the counting double for every test, so
    # any regression that reaches retrieval moves the counter. raising=False only
    # lets the initial red run import the pre-hardening module.
    monkeypatch.setattr(recipe, '_refuse_retrieval', counting_retrieval, raising=False)
    yield
    assert TRANSPORT == [], TRANSPORT


def load(slug='morro-bay'):
    return json.loads((ROOT / 'regions' / slug / 'coast.json').read_text(encoding='utf-8'))


def pristine_schema():
    return json.loads((ROOT / SCHEMA).read_text(encoding='utf-8'))


def edited(case):
    schema = pristine_schema()
    for path, value in case['inserts']:
        target = schema
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = deepcopy(value)
    return schema


def stage(root, schema=None, raw=None):
    """Independent regular-file metadata snapshot plus an empty workspace."""
    metadata = root / 'metadata'
    for name in METADATA:
        target = metadata / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    if schema is not None:
        (metadata / SCHEMA).write_text(json.dumps(schema), encoding='utf-8')
    if raw is not None:
        (metadata / SCHEMA).write_bytes(raw)
    workspace = root / 'workspace'
    workspace.mkdir()
    return metadata, workspace


def outcome(metadata, workspace, document=None):
    try:
        recipe.validate_recipe(load() if document is None else document,
                               metadata_root=metadata, workspace_root=workspace)
    except recipe.RecipeError as error:
        return str(error)
    return None


def check_refused(case, metadata, workspace):
    """The regression: no retrieval at all, then the exact local refusal reason."""
    before = len(RETRIEVALS)
    message = outcome(metadata, workspace)
    assert len(RETRIEVALS) == before, 'retrieval counter moved: ' + repr(RETRIEVALS[before:])
    assert message is not None and message.startswith(NOT_ADMITTED + case['reason'] + ' at /'), message
    return message


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob('*')) if path.is_file()}


# A1 focused acceptance ------------------------------------------------------

@pytest.mark.parametrize('slug', SLUGS)
def test_a1_committed_recipes_still_review_required(slug, tmp_path):
    assert recipe.validate_recipe(load(slug), metadata_root=ROOT,
                                  workspace_root=tmp_path) == dict(VALID, slug=slug)
    assert not list(tmp_path.iterdir())
    assert RETRIEVALS == []


@pytest.mark.parametrize('case_id', ADMITTED)
def test_a1_admitted_same_document_fragment(case_id, tmp_path):
    metadata, workspace = stage(tmp_path, edited(ADMITTED[case_id]))
    for slug in SLUGS:
        assert recipe.validate_recipe(load(slug), metadata_root=metadata,
                                      workspace_root=workspace) == dict(VALID, slug=slug)
    assert RETRIEVALS == []
    assert not list(workspace.iterdir())


@pytest.mark.parametrize('case_id', ['pointer-alias-chain', 'pointer-escaped-key',
                                     'pointer-percent-encoded', 'plain-anchor'])
def test_a1_local_fragment_is_resolved_and_enforced(case_id, tmp_path):
    metadata, workspace = stage(tmp_path, edited(ADMITTED[case_id]))
    document = load()
    document['slug'] = 'Morro-Bay'
    message = outcome(metadata, workspace, document)
    assert message is not None and message.startswith('schema slug: '), message
    assert RETRIEVALS == []


def test_a1_pinned_schema_semantics_unchanged(tmp_path):
    assert hashlib.sha256((ROOT / SCHEMA).read_bytes()).hexdigest() == SCHEMA_SHA256
    document = load()
    document['slug'] = 'Morro-Bay'
    assert outcome(ROOT, tmp_path, document).startswith('schema slug: ')
    document = load()
    document['cache_budget_bytes'] = 25_000_000_001
    assert outcome(ROOT, tmp_path, document).startswith('schema cache_budget_bytes: ')


@pytest.mark.parametrize('case_id', [key for key, case in REJECTED.items()
                                     if case['reason'] == 'external resource'])
def test_a1_external_reference_refused_locally(case_id, tmp_path):
    metadata, workspace = stage(tmp_path, edited(REJECTED[case_id]))
    check_refused(REJECTED[case_id], metadata, workspace)
    assert not list(workspace.iterdir())


def test_a1_refusal_names_stable_location(tmp_path):
    metadata, workspace = stage(tmp_path, edited(REJECTED['nested-deep-unused']))
    assert outcome(metadata, workspace) == (
        NOT_ADMITTED + 'external resource at /$defs/deep/properties/a/items/not/allOf/0/$ref')
    metadata, workspace = stage(tmp_path / 'b', edited(REJECTED['branch-untraversed-anyof']))
    assert outcome(metadata, workspace) == (
        NOT_ADMITTED + 'external resource at /properties/depth_target_ft/anyOf/1/$ref')


def test_a1_refusal_precedes_instance_evaluation(tmp_path):
    metadata, workspace = stage(tmp_path, edited(REJECTED['property-http']))
    # An empty instance would fail 'required' if evaluation started first.
    assert outcome(metadata, workspace, {}) == NOT_ADMITTED + 'external resource at /properties/slug/$ref'
    assert RETRIEVALS == []


def test_a1_missing_jsonschema_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'jsonschema', None)
    with pytest.raises(recipe.RecipeError, match='^jsonschema is required for recipe validation$'):
        recipe.validate_recipe(load(), metadata_root=ROOT, workspace_root=tmp_path)


def test_a1_cli_external_reference_one_invalid_exit_1(tmp_path, capsys):
    metadata, workspace = stage(tmp_path, edited(REJECTED['defs-unused-http']))
    path = tmp_path / 'synthetic-recipe.json'
    path.write_text(json.dumps(load()), encoding='utf-8')
    code = recipe.main([str(path), '--workspace-root', str(workspace),
                        '--metadata-root', str(metadata)])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == ''
    results = json.loads(captured.out)
    assert len(results) == 1 and set(results[0]) == INVALID_FIELDS
    assert results[0]['status'] == 'INVALID' and results[0]['valid'] is False
    assert results[0]['error'] == NOT_ADMITTED + 'external resource at /$defs/unused/$ref'
    assert results[0]['semantic_approval'] is False and results[0]['execution_allowed'] is False
    assert RETRIEVALS == []


def test_a1_cli_positive_behavior_unchanged(tmp_path, capsys):
    paths = [str(ROOT / 'regions' / slug / 'coast.json') for slug in SLUGS]
    assert recipe.main(paths + ['--workspace-root', str(tmp_path),
                                '--metadata-root', str(ROOT)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ''
    assert json.loads(captured.out) == [dict(VALID, slug=slug) for slug in SLUGS]


# A2 producer contract: transport and read boundary ----------------------------

def test_a2_sentinels_armed():
    assert socket.getaddrinfo.__qualname__.endswith('refused.<locals>.call')
    assert urllib.request.urlopen.__qualname__.endswith('refused.<locals>.call')
    assert subprocess.Popen.__qualname__.endswith('refused.<locals>.call')
    assert recipe._refuse_retrieval is counting_retrieval


@pytest.mark.parametrize('case_id', ['property-http', 'defs-unused-http', 'file-url',
                                     'relative-traversal', 'pointer-missing'])
def test_a2_reads_stay_inside_staged_roots(case_id, tmp_path, capsys):
    case = REJECTED[case_id]
    # Warm up imports and lazy library state outside the measured window.
    warm_metadata, warm_workspace = stage(tmp_path / 'warm', edited(case))
    outcome(warm_metadata, warm_workspace)
    assert outcome(*stage(tmp_path / 'warm-ok')) is None
    measured = tmp_path / 'measured'
    metadata, workspace = stage(measured, edited(case))
    good_metadata, good_workspace = stage(measured / 'positive')
    path = measured / 'synthetic-recipe.json'
    path.write_text(json.dumps(load()), encoding='utf-8')
    document, good_document = load(), load()
    AUDIT['opened'] = opened = []
    try:
        message = outcome(metadata, workspace, document)
        code = recipe.main([str(path), '--workspace-root', str(workspace),
                            '--metadata-root', str(metadata)])
        positive = outcome(good_metadata, good_workspace, good_document)
    finally:
        AUDIT['opened'] = None
    capsys.readouterr()
    assert message.startswith(NOT_ADMITTED + case['reason'])
    assert code == 1 and positive is None
    assert opened, 'audit hook recorded no reads at all'
    outside = [name for name in opened if not Path(name).absolute().is_relative_to(measured)]
    assert outside == []
    assert RETRIEVALS == [] and TRANSPORT == []


# A3 negatives, preservation and the isolated mutation control -----------------

@pytest.mark.parametrize('case_id', [key for key, case in REJECTED.items()
                                     if case['reason'] != 'external resource'])
def test_a3_malformed_traversal_and_embedded_refused(case_id, tmp_path):
    metadata, workspace = stage(tmp_path, edited(REJECTED[case_id]))
    check_refused(REJECTED[case_id], metadata, workspace)


@pytest.mark.parametrize('name,reason', [
    ('duplicate-key.schema.json', 'JSON duplicate key: type'),
    ('nonfinite-literal.schema.txt', 'JSON non-finite number: NaN'),
    ('nonfinite-overflow.schema.json', 'schema document non-finite numeric value'),
    ('invalid-shape.schema.json', 'schema document invalid at /type'),
    ('malformed-reference.schema.json', 'schema document invalid at /$defs/bad/$ref'),
])
def test_a3_raw_schema_negatives(name, reason, tmp_path):
    raw = (FIXTURE / name).read_bytes()
    metadata, workspace = stage(tmp_path, raw=raw)
    before = snapshot(tmp_path)
    message = outcome(metadata, workspace)
    assert message is not None and message.startswith(reason), message
    assert RETRIEVALS == []
    assert snapshot(tmp_path) == before
    assert (FIXTURE / name).read_bytes() == raw


TARGET_CASES = [key for key, case in REJECTED.items() if key.startswith('target-')
                or key == 'anchor-in-data-position']


@pytest.mark.parametrize('case_id', TARGET_CASES)
def test_a3_malformed_local_target_is_recipe_error_before_evaluation(case_id, tmp_path):
    """A pointer that merely exists (string, array, number, null) or an object
    the metaschema rejects is refused during admission, also when unused, and
    always as RecipeError; an empty instance proves evaluation never started."""
    case = REJECTED[case_id]
    metadata, workspace = stage(tmp_path, edited(case))
    before = snapshot(tmp_path)
    for document in (load(), {}):
        try:
            recipe.validate_recipe(document, metadata_root=metadata, workspace_root=workspace)
        except recipe.RecipeError as error:
            message = str(error)
        else:
            raise AssertionError('admitted ' + case_id)
        assert message.startswith(NOT_ADMITTED + case['reason'] + ' at /'), message
    assert RETRIEVALS == [] and TRANSPORT == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('case_id', ['target-title-string', 'target-required-array',
                                     'target-example-number', 'target-invalid-object',
                                     'target-title-unused', 'target-nested-unused-branch'])
def test_a3_cli_malformed_local_target_one_invalid_exit_1(case_id, tmp_path, capsys):
    case = REJECTED[case_id]
    metadata, workspace = stage(tmp_path, edited(case))
    path = tmp_path / 'synthetic-recipe.json'
    path.write_text(json.dumps(load()), encoding='utf-8')
    code = recipe.main([str(path), '--workspace-root', str(workspace),
                        '--metadata-root', str(metadata)])
    captured = capsys.readouterr()
    assert code == 1 and captured.err == ''
    results = json.loads(captured.out)
    assert len(results) == 1 and set(results[0]) == INVALID_FIELDS
    assert results[0]['status'] == 'INVALID' and results[0]['valid'] is False
    assert results[0]['error'].startswith(NOT_ADMITTED + case['reason'] + ' at /')
    assert RETRIEVALS == []


def test_a3_malformed_target_reason_names_stable_location(tmp_path):
    metadata, workspace = stage(tmp_path, edited(REJECTED['target-title-string']))
    assert outcome(metadata, workspace) == (
        NOT_ADMITTED + 'local target is not a schema at /properties/slug/$ref')
    metadata, workspace = stage(tmp_path / 'b', edited(REJECTED['target-nested-unused-branch']))
    assert outcome(metadata, workspace) == (
        NOT_ADMITTED + 'local target is not a schema at /properties/depth_target_ft/anyOf/1/$ref')
    metadata, workspace = stage(tmp_path / 'c', edited(REJECTED['target-dynamic-scalar']))
    assert outcome(metadata, workspace) == (
        NOT_ADMITTED + 'local target is not a schema at /$defs/d1/$dynamicRef')


def test_a3_boolean_and_object_targets_keep_local_semantics(tmp_path):
    case = {'inserts': [[['$defs', 'never'], False],
                        [['properties', 'notes'], {'$ref': '#/$defs/never'}]]}
    metadata, workspace = stage(tmp_path, edited(case))
    assert outcome(metadata, workspace) is None                 # unused boolean target
    document = load()
    document['notes'] = 'x'
    message = outcome(metadata, workspace, document)            # false target enforced
    assert message is not None and message.startswith('schema notes: '), message
    assert RETRIEVALS == []


def test_a3_traversed_reference_cycle_is_recipe_error(tmp_path):
    case = {'inserts': [[['$defs', 'loop'], {'$ref': '#/$defs/loop'}],
                        [['properties', 'slug'], {'$ref': '#/$defs/loop'}]]}
    metadata, workspace = stage(tmp_path, edited(case))
    message = outcome(metadata, workspace)
    assert message == 'schema reference cycle does not terminate', message
    assert RETRIEVALS == []


OVERLONG_INDEX = '9' * 5000       # far beyond sys.get_int_max_str_digits()
INDEX_CASES = {
    # id: (inserts, location of the refused keyword)
    'index-overlong-used': (
        [[['examples'], [True]],
         [['properties', 'slug'], {'$ref': '#/examples/' + OVERLONG_INDEX}]],
        '/properties/slug/$ref'),
    'index-overlong-unused': (
        [[['examples'], [True]],
         [['$defs', 'unused'], {'$ref': '#/examples/' + OVERLONG_INDEX}]],
        '/$defs/unused/$ref'),
    'index-overlong-dynamic-unused': (
        [[['examples'], [True]],
         [['$defs', 'unusedDyn'], {'$dynamicRef': '#/examples/' + OVERLONG_INDEX}]],
        '/$defs/unusedDyn/$dynamicRef'),
    'index-twenty-digits-unused': (
        [[['examples'], [True]],
         [['$defs', 'unused'], {'$ref': '#/examples/' + '1' * 20}]],
        '/$defs/unused/$ref'),
    'index-leading-zero-unused': (
        [[['examples'], [True]],
         [['$defs', 'unused'], {'$ref': '#/examples/00'}]],
        '/$defs/unused/$ref'),
}


@pytest.mark.parametrize('case_id', sorted(INDEX_CASES))
def test_a3_impossible_array_index_is_recipe_error_before_conversion(case_id, tmp_path):
    """An array-index segment that cannot index any list is refused during
    admission as the stable local-fragment reason, used or unused, without
    ever reaching the interpreter's integer-conversion limit."""
    inserts, where = INDEX_CASES[case_id]
    metadata, workspace = stage(tmp_path, edited({'inserts': inserts}))
    before = snapshot(tmp_path)
    for document in (load(), {}):
        try:
            recipe.validate_recipe(document, metadata_root=metadata, workspace_root=workspace)
        except recipe.RecipeError as error:
            assert type(error) is recipe.RecipeError
            message = str(error)
        else:
            raise AssertionError('admitted ' + case_id)
        assert message == NOT_ADMITTED + 'unresolved local fragment at ' + where, message
    assert RETRIEVALS == [] and TRANSPORT == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('case_id', ['index-overlong-used', 'index-overlong-unused'])
def test_a3_cli_impossible_array_index_one_invalid_exit_1(case_id, tmp_path, capsys):
    inserts, where = INDEX_CASES[case_id]
    metadata, workspace = stage(tmp_path, edited({'inserts': inserts}))
    path = tmp_path / 'synthetic-recipe.json'
    path.write_text(json.dumps(load()), encoding='utf-8')
    code = recipe.main([str(path), '--workspace-root', str(workspace),
                        '--metadata-root', str(metadata)])
    captured = capsys.readouterr()
    assert code == 1 and captured.err == ''
    results = json.loads(captured.out)
    assert len(results) == 1 and set(results[0]) == INVALID_FIELDS
    assert results[0]['status'] == 'INVALID' and results[0]['valid'] is False
    assert results[0]['error'] == NOT_ADMITTED + 'unresolved local fragment at ' + where
    assert 'digits' not in results[0]['error']                # no interpreter message
    assert RETRIEVALS == []


def test_a3_pointer_index_rule_is_exact():
    """Unit rule: canonical decimal index, at most len(str(sys.maxsize))
    digits, below the list length; never an exception for any length."""
    schema = {'a': [True, {'type': 'string'}]}
    assert recipe._pointer_target(schema, '/a/0') and recipe._pointer_target(schema, '/a/1')
    for fragment in ('/a/2', '/a/00', '/a/01', '/a/-1', '/a/+1', '/a/ 1', '/a/1.0',
                     '/a/' + '0' * 19, '/a/' + '9' * 20, '/a/' + OVERLONG_INDEX,
                     '/a/' + '9' * 100_000):
        assert recipe._pointer_target(schema, fragment) is False, fragment[:24]
    assert recipe.MAX_INDEX_DIGITS == len(str(sys.maxsize))
    assert recipe._pointer_target({'a': [True] * 12}, '/a/11')


def test_a3_valid_array_index_targets_keep_local_semantics(tmp_path):
    case = {'inserts': [[['examples'], [True, {'type': 'string', 'maxLength': 1}]],
                        [['$defs', 'unused'], {'$ref': '#/examples/0'}],
                        [['properties', 'notes'], {'$ref': '#/examples/1'}]]}
    metadata, workspace = stage(tmp_path, edited(case))
    assert outcome(metadata, workspace) is None                 # valid indices admitted
    document = load()
    document['notes'] = 'xy'
    message = outcome(metadata, workspace, document)            # indexed target enforced
    assert message is not None and message.startswith('schema notes: '), message
    assert RETRIEVALS == []


def test_a3_nonfinite_recipe_value_still_refused(tmp_path):
    document = load()
    document['depth_target_ft'] = float('inf')
    assert outcome(ROOT, tmp_path, document) == 'non-finite numeric value'


# A3 runner input/output contract (synthetic trees only) ----------------------

def load_runner():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'sc_recipe_offline_runner_under_test', ROOT / 'scripts' / 'accept_sc_recipe_offline.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_runner()
MIB = 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_window(callable_, *args, **kwargs):
    """Run a runner call while the audit hook records every open/listdir."""
    AUDIT['opened'] = opened = []
    try:
        try:
            return callable_(*args, **kwargs), None, opened
        except runner.Refused as error:
            return None, str(error), opened
    finally:
        AUDIT['opened'] = None


def test_a3_runner_frozen_bounds():
    assert runner.MAX_FILE_BYTES == 2 * MIB
    assert runner.MAX_TOTAL_INPUT_BYTES == 16 * MIB
    assert runner.MAX_ROWS == 4096
    assert runner.MAX_OUTPUT_BYTES == 8 * MIB


def test_a3_runner_reads_exact_boundary_and_refuses_one_more(tmp_path):
    exact = tmp_path / 'exact.bin'
    exact.write_bytes(b'a' * runner.MAX_FILE_BYTES)
    budget = runner.InputBudget()
    data = runner.read_bounded(exact, tmp_path, budget, expected_sha256=sha(exact.read_bytes()))
    assert len(data) == runner.MAX_FILE_BYTES and budget.used == runner.MAX_FILE_BYTES
    small = tmp_path / 'small.bin'
    small.write_bytes(b'0123456789')
    assert runner.read_bounded(small, tmp_path, runner.InputBudget(), limit=10) == b'0123456789'
    small.write_bytes(b'0123456789A')
    result, error, opened = read_window(runner.read_bounded, small, tmp_path,
                                        runner.InputBudget(), limit=10)
    assert result is None and error.startswith('refused: input exceeds 10 bytes'), error
    assert opened == []                                          # refused from metadata


def test_a3_runner_aggregate_input_budget(tmp_path):
    for name in ('a', 'b'):
        (tmp_path / name).write_bytes(b'x' * 6)
    budget = runner.InputBudget(total=10)
    runner.read_bounded(tmp_path / 'a', tmp_path, budget)
    result, error, opened = read_window(runner.read_bounded, tmp_path / 'b', tmp_path, budget)
    assert result is None and error.startswith('refused: aggregate input budget'), error
    assert opened == [] and budget.used == 6


def test_a3_runner_refuses_symlink_leaf_without_reading_target(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = outside / 'secret.txt'
    target.write_bytes(b'tiny')
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'link.txt').symlink_to(target)
    result, error, opened = read_window(runner.read_bounded, root / 'link.txt', root,
                                        runner.InputBudget())
    assert result is None and error.startswith('refused: symlink'), error
    assert opened == []
    with pytest.raises(runner.Refused, match='^refused: symlink'):
        runner.sha256_file(root / 'link.txt', root, runner.InputBudget())


def test_a3_runner_refuses_symlink_ancestry_and_outside_root(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    (real / 'f.txt').write_bytes(b'x')
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'dir').symlink_to(real, target_is_directory=True)
    for path, reason in ((root / 'dir' / 'f.txt', 'refused: symlink'),
                         (real / 'f.txt', 'refused: outside allowed root'),
                         (root / '..' / 'real' / 'f.txt', 'refused: parent traversal')):
        result, error, opened = read_window(runner.read_bounded, path, root, runner.InputBudget())
        assert result is None and error.startswith(reason), (path, error)
        assert opened == []


def test_a3_runner_refuses_fifo_and_directory_without_hang(tmp_path):
    fifo = tmp_path / 'pipe'
    os.mkfifo(fifo)
    (tmp_path / 'sub').mkdir()
    for path in (fifo, tmp_path / 'sub'):
        result, error, opened = read_window(runner.read_bounded, path, tmp_path,
                                            runner.InputBudget())
        assert result is None and error.startswith('refused: not a regular file'), error
        assert opened == []


def test_a3_runner_binds_expected_identity_before_use(tmp_path):
    path = tmp_path / 'pinned.json'
    path.write_bytes(b'{"a": 1}\n')
    before = path.read_bytes()
    with pytest.raises(runner.Refused, match='^refused: sha256 mismatch'):
        runner.read_bounded(path, tmp_path, runner.InputBudget(), expected_sha256='0' * 64)
    with pytest.raises(runner.Refused, match='^refused: git blob mismatch'):
        runner.read_bounded(path, tmp_path, runner.InputBudget(), expected_blob='0' * 40)
    blob = runner.git_blob_id(before)
    assert runner.read_bounded(path, tmp_path, runner.InputBudget(), expected_blob=blob) == before
    # Same object id as git hash-object would give for these bytes.
    assert runner.git_blob_id(b'') == 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391'
    assert path.read_bytes() == before


def test_a3_runner_fixture_listing_refuses_links_special_and_row_overflow(tmp_path):
    fixtures = tmp_path / 'fixtures'
    fixtures.mkdir()
    for index in range(3):
        (fixtures / ('f%d.json' % index)).write_bytes(b'{}')
    assert runner.list_regular_files(fixtures, tmp_path) == ['f0.json', 'f1.json', 'f2.json']
    with pytest.raises(runner.Refused, match='^refused: more than 2 rows'):
        runner.list_regular_files(fixtures, tmp_path, rows=2)
    (fixtures / 'zlink.json').symlink_to(fixtures / 'f0.json')
    with pytest.raises(runner.Refused, match='^refused: fixture entry is not a regular file'):
        runner.list_regular_files(fixtures, tmp_path)
    special = tmp_path / 'special'
    special.mkdir()
    (special / 'f0.json').write_bytes(b'{}')
    os.mkfifo(special / 'zpipe')
    with pytest.raises(runner.Refused, match='^refused: fixture entry is not a regular file'):
        runner.list_regular_files(special, tmp_path)


def test_a3_runner_writes_are_bounded_and_never_overwrite(tmp_path):
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    budget = runner.OutputBudget(total=64)
    digest = runner.write_bounded(run_dir, 'ok.json', {'b': 1, 'a': [1, 2]}, budget)
    data = (run_dir / 'ok.json').read_bytes()
    assert data == b'{\n  "a": [\n    1,\n    2\n  ],\n  "b": 1\n}\n' and digest == sha(data)
    with pytest.raises(runner.Refused, match='^refused: output exists'):
        runner.write_bounded(run_dir, 'ok.json', {'c': 3}, budget)
    assert (run_dir / 'ok.json').read_bytes() == data
    with pytest.raises(runner.Refused, match='^refused: output budget'):
        runner.write_bounded(run_dir, 'big.json', {'x': 'y' * 64}, budget)
    assert not (run_dir / 'big.json').exists()
    with pytest.raises(runner.Refused, match='^refused: non-finite'):
        runner.write_bounded(run_dir, 'nan.json', {'x': float('nan')}, budget)
    assert not (run_dir / 'nan.json').exists()
    linked = tmp_path / 'linked'
    linked.symlink_to(run_dir, target_is_directory=True)
    with pytest.raises(runner.Refused, match='^refused: symlink'):
        runner.write_bounded(linked, 'via-link.json', {}, runner.OutputBudget())
    assert not (run_dir / 'via-link.json').exists()
    assert sorted(path.name for path in run_dir.iterdir()) == ['ok.json']


def test_a3_runner_junit_rows_and_report_binding(tmp_path):
    case = b'<testcase classname="tests.unit.test_x" name="t"/>'
    junit = b'<testsuites><testsuite>' + case * 3 + b'</testsuite></testsuites>'
    totals, by_file = runner.junit_counts(junit)
    assert totals == {'tests': 3, 'failures': 0, 'errors': 0, 'skipped': 0}
    assert by_file == {'test_x': totals}
    with pytest.raises(runner.Refused, match='^refused: more than 2 rows'):
        runner.junit_counts(junit, rows=2)
    digest = 'a' * 64
    assert runner.bound_report_sha256(b'noise\n' + runner.REPORT_MARKER.encode() + digest.encode()
                                      + b'\nchild report ok=True\n') == digest
    for stdout in (b'no marker\n',
                   (runner.REPORT_MARKER + digest + '\n') .encode() * 2,
                   (runner.REPORT_MARKER + 'xyz\n').encode()):
        with pytest.raises(runner.Refused, match='^refused: child report identity'):
            runner.bound_report_sha256(stdout)


def test_a3_runner_refusals_leave_inputs_unchanged(tmp_path):
    frozen = tmp_path / 'frozen'
    frozen.mkdir()
    (frozen / 'input.json').write_bytes(b'{"keep": true}\n')
    (frozen / 'link.json').symlink_to(frozen / 'input.json')
    before = {path.name: (path.is_symlink(), path.read_bytes()) for path in frozen.iterdir()}
    for call in (lambda: runner.read_bounded(frozen / 'link.json', frozen, runner.InputBudget()),
                 lambda: runner.read_bounded(frozen / 'input.json', frozen, runner.InputBudget(),
                                             expected_sha256='1' * 64),
                 lambda: runner.write_bounded(frozen, 'input.json', {}, runner.OutputBudget())):
        with pytest.raises(runner.Refused):
            call()
    after = {path.name: (path.is_symlink(), path.read_bytes()) for path in frozen.iterdir()}
    assert after == before


def test_a3_runner_new_output_root_is_write_once(tmp_path):
    existing = tmp_path / 'existing'
    existing.mkdir()
    with pytest.raises(SystemExit, match='already exists'):
        runner.new_run_dir(str(existing))
    linked = tmp_path / 'linked'
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(SystemExit, match='symlink'):
        runner.new_run_dir(str(linked / 'run'))
    assert not (tmp_path / 'run').exists()


# A3 runner shared output reservation (composed, inert: os.pipe + synthetic files)

TINY = {'stdout': 256, 'stderr': 64, 'junit': 512, 'child_report': 512,
        'receipt': 8192, 'fallback_receipt': 1024}


def disk_bytes(root):
    return sum(path.stat().st_size for path in root.rglob('*') if path.is_file())


def pipe_with(data, close=True):
    """A read end preloaded with `data` (small, fits the pipe buffer)."""
    read_end, write_end = os.pipe()
    os.write(write_end, data)
    if close:
        os.close(write_end)
        return read_end
    return read_end, write_end


def padded_junit(size, cases=1):
    body = (b'<testsuites><testsuite>'
            + b'<testcase classname="tests.unit.test_x" name="t"/>' * cases
            + b'</testsuite></testsuites>')
    pad = size - len(body) - len(b'<!---->')
    assert pad >= 0
    return b'<!--' + b'p' * pad + b'-->' + body


def padded_report(size, junit_sha256):
    value = {'junit_sha256': junit_sha256, 'pad': ''}
    value['pad'] = 'p' * (size - len(runner._serialize(value)))
    data = runner._serialize(value)
    assert len(data) == size
    return data


def fake_child(run_dir, *, junit_size=TINY['junit'], report_size=TINY['child_report'],
               stdout_size=TINY['stdout'], stderr_size=TINY['stderr']):
    """What a well-behaved child leaves behind: junit.xml and child-report.json
    on disk, plus stdout carrying the report-identity marker."""
    junit = padded_junit(junit_size)
    (run_dir / 'junit.xml').write_bytes(junit)
    report = padded_report(report_size, sha(junit))
    (run_dir / 'child-report.json').write_bytes(report)
    line = (runner.REPORT_MARKER + sha(report) + '\n').encode()
    stdout = line + b'x' * (stdout_size - len(line))
    return pipe_with(stdout), pipe_with(b'e' * stderr_size)


def settle(run_dir, stdout_fd, stderr_fd, ledger, exit_code=0):
    stopped = []
    captured = runner.capture_streams({'stdout': stdout_fd, 'stderr': stderr_fd},
                                      {'stdout': ledger.capacity('stdout'),
                                       'stderr': ledger.capacity('stderr')},
                                      timeout=10, stop=lambda: stopped.append('stop'))
    launched = dict(captured, exit=exit_code)
    problems = []
    child, report, counts, by_file = runner.settle_child(run_dir, launched, runner.InputBudget(),
                                                         ledger, problems)
    return problems, child, report, counts, stopped


def test_a3_runner_production_reservations_cover_every_artifact():
    reserved = runner.OUTPUT_RESERVATIONS
    assert set(reserved) == {'stdout', 'stderr', 'junit', 'child_report', 'receipt',
                             'fallback_receipt'}
    assert sum(reserved.values()) <= runner.MAX_OUTPUT_BYTES == 8 * MIB
    # Every child-written artifact's reservation covers the kernel per-file cap,
    # so the child cannot exceed its share even if it ignores the runner.
    assert runner.CHILD_FILE_LIMIT == reserved['junit'] == reserved['child_report']
    assert runner.CHILD_FILE_LIMIT <= runner.MAX_FILE_BYTES
    recorded = []
    import resource
    original = resource.setrlimit
    resource.setrlimit = lambda kind, limits: recorded.append((kind, limits))
    try:
        runner._limit_child_output()
    finally:
        resource.setrlimit = original
    assert recorded == [(resource.RLIMIT_FSIZE, (runner.CHILD_FILE_LIMIT,) * 2)]
    with pytest.raises(runner.Refused, match='^refused: output reservations'):
        runner.OutputLedger(dict(reserved, stdout=reserved['stdout'] + 1))


def test_a3_runner_ledger_refuses_before_any_write(tmp_path):
    ledger = runner.OutputLedger({'a': 10, 'b': 5}, total=15)
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    runner.write_bytes_bounded(run_dir, 'a.txt', b'x' * 10, ledger, slot='a')
    with pytest.raises(runner.Refused, match='^refused: output reservation b of 5 bytes'):
        runner.write_bytes_bounded(run_dir, 'b.txt', b'x' * 6, ledger, slot='b')
    with pytest.raises(runner.Refused, match='^refused: output reservation a already used'):
        runner.write_bytes_bounded(run_dir, 'a2.txt', b'', ledger, slot='a')
    with pytest.raises(runner.Refused, match='^refused: unknown output reservation'):
        runner.write_bytes_bounded(run_dir, 'c.txt', b'', ledger, slot='c')
    assert sorted(path.name for path in run_dir.iterdir()) == ['a.txt']
    assert ledger.used == 10


def test_a3_runner_composed_artifacts_exact_fit(tmp_path):
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    ledger = runner.OutputLedger(TINY, total=sum(TINY.values()))
    stdout_fd, stderr_fd = fake_child(run_dir)
    problems, child, report, counts, stopped = settle(run_dir, stdout_fd, stderr_fd, ledger)
    assert problems == [] and stopped == [], problems
    assert counts == {'tests': 1, 'failures': 0, 'errors': 0, 'skipped': 0}
    receipt = {'status': 'PASS', 'child': child, 'pad': ''}
    runner.write_receipt(run_dir, receipt, {'status': 'FAIL'}, ledger, problems)
    assert problems == []
    sizes = {path.name: path.stat().st_size for path in run_dir.iterdir()}
    assert sizes['stdout.txt'] == TINY['stdout'] and sizes['stderr.txt'] == TINY['stderr']
    assert sizes['junit.xml'] == TINY['junit'] and sizes['child-report.json'] == TINY['child_report']
    assert json.loads((run_dir / 'receipt.json').read_bytes())['status'] == 'PASS'
    assert disk_bytes(run_dir) <= sum(TINY.values())


def test_a3_runner_composed_capture_overflow_is_refused_and_bounded(tmp_path):
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    ledger = runner.OutputLedger(TINY, total=sum(TINY.values()))
    stdout_fd, stderr_fd = fake_child(run_dir, stdout_size=TINY['stdout'] + 1,
                                      stderr_size=TINY['stderr'] + 1)
    problems, child, report, counts, stopped = settle(run_dir, stdout_fd, stderr_fd, ledger)
    assert stopped == ['stop']                                   # child stopped once
    assert 'refused: stdout capture exceeds 256 bytes' in problems, problems
    assert 'refused: stderr capture exceeds 64 bytes' in problems, problems
    assert (run_dir / 'stdout.txt').stat().st_size == TINY['stdout']   # never beyond share
    assert (run_dir / 'stderr.txt').stat().st_size == TINY['stderr']
    runner.write_receipt(run_dir, {'status': 'FAIL', 'problems': problems}, {'status': 'FAIL'},
                         ledger, problems)
    assert json.loads((run_dir / 'receipt.json').read_bytes())['status'] == 'FAIL'
    assert disk_bytes(run_dir) <= sum(TINY.values())


def test_a3_runner_composed_child_artifact_overflow_refused_unread(tmp_path):
    for junit_size, report_size, reason in (
            (TINY['junit'], TINY['child_report'] + 1, 'refused: input exceeds 512 bytes'),
            (TINY['junit'] + 1, TINY['child_report'], 'refused: input exceeds 512 bytes')):
        run_dir = tmp_path / ('run-%d-%d' % (junit_size, report_size))
        run_dir.mkdir()
        ledger = runner.OutputLedger(TINY, total=sum(TINY.values()))
        stdout_fd, stderr_fd = fake_child(run_dir, junit_size=junit_size, report_size=report_size)
        before = {name: (run_dir / name).read_bytes() for name in ('junit.xml', 'child-report.json')}
        AUDIT['opened'] = opened = []
        try:
            problems, child, report, counts, stopped = settle(run_dir, stdout_fd, stderr_fd, ledger)
        finally:
            AUDIT['opened'] = None
        assert any(problem.startswith(reason) for problem in problems), problems
        oversize = 'child-report.json' if report_size > TINY['child_report'] else 'junit.xml'
        assert str(run_dir / oversize) not in opened              # refused from metadata
        assert counts == {} and (report is None or oversize == 'junit.xml')
        assert {name: (run_dir / name).read_bytes() for name in before} == before


def test_a3_runner_composed_receipt_overflow_uses_fallback_reservation(tmp_path):
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    ledger = runner.OutputLedger(TINY, total=sum(TINY.values()))
    stdout_fd, stderr_fd = fake_child(run_dir)
    problems, child, report, counts, stopped = settle(run_dir, stdout_fd, stderr_fd, ledger)
    assert problems == []
    receipt = {'status': 'PASS', 'pad': 'p' * TINY['receipt']}    # cannot fit its share
    digest = runner.write_receipt(run_dir, receipt, {'card': 't', 'status': 'FAIL'},
                                  ledger, problems)
    data = (run_dir / 'receipt.json').read_bytes()
    assert digest == sha(data) and len(data) <= TINY['fallback_receipt']
    fallback = json.loads(data)
    assert fallback['status'] == 'FAIL'
    assert problems and problems[0].startswith('refused: output reservation receipt'), problems
    assert fallback['problems'] == problems
    assert disk_bytes(run_dir) <= sum(TINY.values())


def test_a3_runner_capture_timeout_stops_without_hang(tmp_path):
    read_end, write_end = pipe_with(b'partial', close=False)
    stopped = []
    try:
        captured = runner.capture_streams({'stdout': read_end}, {'stdout': 64}, timeout=0.2,
                                          stop=lambda: stopped.append('stop'))
    finally:
        os.close(write_end)
    assert captured['stdout'] == b'partial' and captured['timed_out'] is True
    assert stopped == ['stop'] and captured['refused'] == []


def disable_reference_gate(monkeypatch):
    """Isolated synthetic mutation: only the pre-evaluation reference gate is
    removed, so the counting retrieval callback is reachable again."""
    monkeypatch.setattr(recipe, '_check_references', lambda schema: None)


@pytest.mark.parametrize('case_id', TRAVERSED)
def test_a3_mutation_control_fails_on_retrieval_counter(case_id, tmp_path, monkeypatch):
    case = REJECTED[case_id]
    metadata, workspace = stage(tmp_path, edited(case))
    before = snapshot(tmp_path)
    check_refused(case, metadata, workspace)                    # positive control
    with monkeypatch.context() as mutated:
        disable_reference_gate(mutated)
        with pytest.raises(AssertionError, match='^retrieval counter moved'):
            check_refused(case, metadata, workspace)            # regression detects
        assert len(RETRIEVALS) >= 1
        message = outcome(metadata, workspace)                  # still no traceback
        assert message.startswith('schema reference unresolvable offline'), message
    RETRIEVALS.clear()
    check_refused(case, metadata, workspace)                    # restored control
    assert snapshot(tmp_path) == before


def test_a3_untraversed_branch_needs_the_gate(tmp_path, monkeypatch):
    """Why the static gate exists: lazy resolution alone never sees this branch."""
    case = REJECTED['branch-untraversed-anyof']
    metadata, workspace = stage(tmp_path, edited(case))
    check_refused(case, metadata, workspace)
    with monkeypatch.context() as mutated:
        disable_reference_gate(mutated)
        assert outcome(metadata, workspace) is None
    assert RETRIEVALS == []


def test_a3_legacy_resolver_is_offline(tmp_path, monkeypatch):
    """jsonschema releases without the referencing registry use RefResolver;
    its remote hook is the same refusing callback (exercised here through the
    deprecated RefResolver of the installed release, instance validator only)."""
    import warnings
    from jsonschema import Draft202012Validator
    monkeypatch.setattr(recipe, '_registry_api', lambda: None)
    schema = edited(REJECTED['property-http'])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        validator = recipe._offline_validator(Draft202012Validator, schema)
        with pytest.raises(recipe._resolution_errors()):
            list(validator.iter_errors(load()))
        assert RETRIEVALS == ['https://sc-recipe-offline.invalid/slug.schema.json']
        RETRIEVALS.clear()
        assert list(recipe._offline_validator(Draft202012Validator, pristine_schema())
                    .iter_errors(load())) == []
    assert RETRIEVALS == []
