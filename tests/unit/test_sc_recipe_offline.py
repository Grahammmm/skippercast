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


def test_a3_nonfinite_recipe_value_still_refused(tmp_path):
    document = load()
    document['depth_target_ft'] = float('inf')
    assert outcome(ROOT, tmp_path, document) == 'non-finite numeric value'


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
