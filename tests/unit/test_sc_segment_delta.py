"""SC-SEGMENT-DELTA: two-receipt metadata comparator acceptance (A1-A3).

Synthetic fixtures only (tests/fixtures/sc_segment_delta). Every Ref in them is
inert text: no file, archive or raw source is bound, and the comparator must
never stat or open one. The comparator explains DECLARED metadata only; a clean
report is REVIEW REQUIRED, never semantic, closure or scientific acceptance.

Functions take no arguments so they run unchanged under pytest collection and
under scripts/accept_sc_segment_delta.py (stdlib-only, offline sentinels). Test
groups: test_a1_* focused, test_a2_* producer contract, test_a3_* negative.
"""
import builtins
import contextlib
import copy
import hashlib
import importlib.util
import io
import itertools
import json
import os
import sys
import tempfile
from pathlib import Path

from tests._support import FIXTURES, ROOT

FIXTURE_DIR = FIXTURES / 'sc_segment_delta'
MODULE_PATH = ROOT / 'scripts' / 'coast_diagnostics' / 'segment_receipt_delta.py'
PRODUCER_PATH = ROOT / 'scripts' / 'validate_coast_receipt.py'
SCHEMA_PATH = ROOT / 'skills' / 'coast-campaign-shared' / 'schemas' / 'coast-segment-receipt-v1.schema.json'
# Pins measured by the planner at Grahammmm/skippercast main 59fca09b.
PRODUCER_SHA256 = 'c6dd85090739032205723c47378757a0da1cbb904ca28a9fc939d64530ea98a7'
SCHEMA_SHA256 = '73dc8b02224d7c8e958bd9a9534f06cc66a7c2fea64cd562313520f784506550'

# Independent frozen copy of the S-019 v1 projection (validate_coast_receipt.py
# lines 53-55). Never derived from the code under test.
FROZEN_CONTENT_FIELDS = ('schema', 'schema_version', 'campaign_segment_id', 'coordinator_segment_id',
                         'segment_slug', 'recipe_sha256', 'recipe', 'code_commit', 'skill_commit',
                         'inputs', 'outputs', 'qa', 'tier1')
FROZEN_BOOKKEEPING_FIELDS = ('created_utc', 'author_profile', 'author_model', 'card_id', 'run',
                             'closed', 'signoff', 'archive')
FLAGS = dict(evidence_scope='declared_metadata_only', referenced_bytes_verified=False,
             semantic_approval=False, closure_verified=False, semantic_comparability='UNVERIFIED')

# Redirected by the acceptance runner to its write-once synthetic output tree.
WORK_ROOT = None
_COUNTER = itertools.count()
_MODULE = None


# ---------------------------------------------------------------- helpers ---

def delta():
    """The module under test, loaded by explicit file path from this checkout."""
    global _MODULE
    if _MODULE is None:
        spec = importlib.util.spec_from_file_location('sc_segment_delta_under_test', MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE = module
    return _MODULE


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_bytes())


def fixture_bytes(name):
    return (FIXTURE_DIR / name).read_bytes()


def golden_projection(receipt):
    return {key: receipt[key] for key in FROZEN_CONTENT_FIELDS}


def golden_digest(receipt):
    raw = json.dumps(golden_projection(receipt), sort_keys=True, separators=(',', ':'),
                     allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def variant(name, mutate, reseal=True):
    value = copy.deepcopy(fixture(name))
    mutate(value)
    if reseal:
        value['determinism_digest'] = golden_digest(value)
    return value


def fake(label):
    return hashlib.sha256(('synthetic:' + label).encode()).hexdigest()


def workdir(label):
    base = WORK_ROOT if WORK_ROOT is not None else tempfile.mkdtemp(prefix='sc-segment-delta-')
    path = Path(os.path.realpath(base)) / f'{label}-{next(_COUNTER)}'
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_json(path, value):
    path.write_bytes((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
    return path


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = delta().main([str(a) for a in argv])
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


def expect_invalid(call, fragment):
    try:
        call()
    except delta().InvalidReceipt as error:
        assert fragment in str(error), f'expected {fragment!r} in {error!r}'
        return error
    raise AssertionError(f'expected InvalidReceipt containing {fragment!r}')


def row(pointer, before, after, before_present=True, after_present=True):
    return dict(pointer=pointer, before_present=before_present, before=before,
                after_present=after_present, after=after)


def snapshot(*roots):
    files = {}
    for root in roots:
        for path in sorted(Path(root).rglob('*')):
            if path.is_file() and not path.is_symlink():
                files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def refs(value):
    if isinstance(value, dict):
        if set(value) == {'root_id', 'path', 'sha256', 'bytes'}:
            yield value
        else:
            for child in value.values():
                yield from refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs(child)


@contextlib.contextmanager
def patched(module, **values):
    """In-memory callable/constant double; always restored."""
    saved = {name: getattr(module, name) for name in values}
    try:
        for name, value in values.items():
            setattr(module, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(module, name, value)


@contextlib.contextmanager
def offline_guard():
    """Regression sentinels (not a sandbox): any network/subprocess use fails."""
    import socket
    import subprocess

    def refuse(*args, **kwargs):
        raise AssertionError('sentinel: network/subprocess use attempted')
    targets = [(socket, 'create_connection'), (socket, 'getaddrinfo'), (socket.socket, 'connect'),
               (subprocess, 'Popen'), (os, 'system')]
    saved = [(owner, name, getattr(owner, name)) for owner, name in targets]
    try:
        for owner, name in targets:
            setattr(owner, name, refuse)
        yield
    finally:
        for owner, name, value in saved:
            setattr(owner, name, value)


@contextlib.contextmanager
def access_trace():
    """Record every path handed to open/stat/listdir-style calls."""
    seen = []
    targets = [(os, 'open'), (os, 'stat'), (os, 'lstat'), (os, 'listdir'), (os, 'scandir'),
               (builtins, 'open'), (io, 'open')]
    saved = [(owner, name, getattr(owner, name)) for owner, name in targets]

    def wrap(original):
        def traced(path, *args, **kwargs):
            seen.append(os.fsdecode(path) if isinstance(path, (str, bytes, os.PathLike)) else repr(path))
            return original(path, *args, **kwargs)
        return traced
    try:
        for owner, name, original in saved:
            setattr(owner, name, wrap(original))
        yield seen
    finally:
        for owner, name, original in saved:
            setattr(owner, name, original)


def load_producer():
    """Guarded, source-closed import of the existing S-019 identity helpers.

    Verifies the pinned bytes before execution, runs the import under the
    offline sentinels and returns (module, newly imported module files). Only
    content_identity/determinism_digest are used; validate_receipt and the
    Resolver are replaced with failing doubles so no graph/closure check or
    source read can run from this suite.
    """
    raw = PRODUCER_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PRODUCER_SHA256, 'producer validator differs from pin'
    before = set(sys.modules)
    with offline_guard():
        spec = importlib.util.spec_from_file_location('sc_delta_producer_contract', PRODUCER_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # registered so the import trace lists it
        spec.loader.exec_module(module)
    new = {name: getattr(sys.modules[name], '__file__', None) for name in set(sys.modules) - before}

    def forbidden(*args, **kwargs):
        raise AssertionError('contract suite must not call the graph validator or read sources')
    module.validate_receipt = forbidden
    module.document = forbidden
    module.Resolver = forbidden
    return module, new


# ------------------------------------------------------- A1 focused suite ---

def test_a1_identical_receipts_have_no_changes():
    for name in ('open-receipt.json', 'closed-receipt.json'):
        report = delta().compare_receipts(fixture_bytes(name), fixture_bytes(name))
        assert report['status'] == 'DIAGNOSTIC'
        assert report['content_changes'] == [] and report['bookkeeping_changes'] == []
        assert report['determinism_digest']['changed'] is False
        assert all(rows == [] for rows in report['facets'].values())
        for key, value in FLAGS.items():
            assert report[key] == value, key


def test_a1_bookkeeping_changes_never_touch_content():
    cases = [
        (lambda v: v.update(created_utc='2026-10-22T00:00:00Z'),
         [row('/created_utc', '2026-10-21T00:00:00Z', '2026-10-22T00:00:00Z')]),
        (lambda v: v.update(card_id='t_00000000'), [row('/card_id', 't_366d24e2', 't_00000000')]),
        (lambda v: v.update(author_model='synthetic-other', author_profile='fixture-2'),
         [row('/author_model', 'synthetic-author', 'synthetic-other'),
          row('/author_profile', 'fixture', 'fixture-2')]),
        (lambda v: v['run'].update(sha256=fake('run-2')),
         [row('/run/sha256', fake('run'), fake('run-2'))]),
    ]
    for mutate, expected in cases:
        left = fixture('open-receipt.json')
        right = variant('open-receipt.json', mutate, reseal=False)
        assert right['determinism_digest'] == left['determinism_digest'] == golden_digest(right)
        report = delta().compare_receipts(left, right)
        assert report['content_changes'] == [], report['content_changes']
        assert report['bookkeeping_changes'] == expected, report['bookkeeping_changes']
        assert report['determinism_digest']['changed'] is False
    # Closure references: declared values only, still bookkeeping.
    left = fixture('closed-receipt.json')
    right = variant('closed-receipt.json', lambda v: (v['signoff']['verdict'].update(sha256=fake('verdict-2')),
                                                    v['archive']['manifest'].update(path='manifest-2.json')),
                    reseal=False)
    report = delta().compare_receipts(left, right)
    assert report['content_changes'] == []
    assert report['bookkeeping_changes'] == [
        row('/archive/manifest/path', 'manifest.json', 'manifest-2.json'),
        row('/signoff/verdict/sha256', fake('verdict'), fake('verdict-2'))]
    assert report['closure_verified'] is False and report['declared_closed'] == dict(before=True, after=True)


CONTENT_CASES = {
    'source_hash': (
        lambda v: (v['inputs'][0].update(source_sha256=fake('source-a-2')),
                   v['inputs'][0]['cache'].update(sha256=fake('source-a-2')),
                   v['outputs'][0]['contributing_sources'][0].update(source_sha256=fake('source-a-2'))),
        [row('/inputs/0/cache/sha256', fake('source-a'), fake('source-a-2')),
         row('/inputs/0/source_sha256', fake('source-a'), fake('source-a-2')),
         row('/outputs/0/contributing_sources/0/source_sha256', fake('source-a'), fake('source-a-2'))],
        {'source', 'reference'}),
    'tool_code_version': (
        lambda v: v['outputs'][0]['tool'].update(version='v2', code_commit='3' * 40),
        [row('/outputs/0/tool/code_commit', '1' * 40, '3' * 40), row('/outputs/0/tool/version', 'v1', 'v2')],
        {'tool', 'code'}),
    'parameters': (
        lambda v: v['outputs'][0]['parameters'].update(cell=2),
        [row('/outputs/0/parameters/cell', 1, 2)], {'parameters'}),
    'qa_threshold_ref': (
        lambda v: v['qa']['threshold_config'].update(sha256=fake('qa-threshold-2')),
        [row('/qa/threshold_config/sha256', fake('qa-threshold'), fake('qa-threshold-2'))], {'qa', 'reference'}),
    'output_artifact_hash': (
        lambda v: v['outputs'][0]['artifact'].update(sha256=fake('artifact-2')),
        [row('/outputs/0/artifact/sha256', fake('artifact'), fake('artifact-2'))], {'output', 'reference'}),
    'recipe': (
        lambda v: (v['recipe'].update(sha256=fake('recipe-2')), v.update(recipe_sha256=fake('recipe-2'))),
        [row('/recipe/sha256', fake('recipe'), fake('recipe-2')),
         row('/recipe_sha256', fake('recipe'), fake('recipe-2'))], {'recipe', 'reference'}),
    'tier': (
        lambda v: v.update(tier1=dict(mode='text_only', text_result='pass', vision_result='unavailable',
                                      reason='synthetic reported result only', report=v['qa']['report'])),
        None, {'tier'}),
}


def test_a1_content_changes_have_exact_pointer_and_digest():
    left = fixture('open-receipt.json')
    for name, (mutate, expected, facets) in CONTENT_CASES.items():
        right = variant('open-receipt.json', mutate)
        report = delta().compare_receipts(left, right)
        assert report['status'] == 'DIAGNOSTIC', name
        if expected is not None:
            assert report['content_changes'] == expected, (name, report['content_changes'])
        else:
            assert report['content_changes'] and all(r['pointer'].startswith('/tier1/')
                                                      for r in report['content_changes'])
        assert report['bookkeeping_changes'] == [], name
        digest = report['determinism_digest']
        assert digest['left']['declared'] == digest['left']['recomputed'] == golden_digest(left)
        assert digest['right']['declared'] == digest['right']['recomputed'] == golden_digest(right)
        assert digest['changed'] is True and golden_digest(left) != golden_digest(right)
        listed = {facet for facet, rows in report['facets'].items() if rows}
        assert facets <= listed, (name, listed)
        for facet in facets:
            assert all(r['section'] == 'content' for r in report['facets'][facet])
        assert report['semantic_comparability'] == 'UNVERIFIED'


def test_a1_different_segment_identity_is_not_comparable():
    left = fixture('open-receipt.json')
    for field, value in (('segment_slug', 'other-segment'), ('campaign_segment_id', 'synthetic2'),
                         ('coordinator_segment_id', 'seg:3310:-50000:-400000:5000')):
        right = variant('open-receipt.json', lambda v: v.update({field: value}))
        report = delta().compare_receipts(left, right)
        assert report['status'] == 'NOT_COMPARABLE', field
        assert report['comparable'] is False
        assert report['identity_changes'] == [row('/' + field, left[field], value)]
        assert 'content_changes' not in report and 'bookkeeping_changes' not in report
        for key, flag in FLAGS.items():
            assert report[key] == flag


def test_a1_bad_determinism_digest_is_invalid():
    bad = variant('open-receipt.json', lambda v: v.update(determinism_digest=fake('tampered')), reseal=False)
    expect_invalid(lambda: delta().compare_receipts(fixture('open-receipt.json'), bad), 'determinism digest mismatch')
    expect_invalid(lambda: delta().compare_receipts(bad, fixture('open-receipt.json')), 'determinism digest mismatch')


def test_a1_cli_exit_codes_and_write_once_report():
    work = workdir('cli')
    left = FIXTURE_DIR / 'open-receipt.json'
    right = write_json(work / 'right.json', variant('open-receipt.json', CONTENT_CASES['parameters'][0]))
    out = work / 'report.json'
    code, stdout, stderr = run_cli(['--left', left, '--right', right, '--out', out])
    assert code == 0, stderr
    report = json.loads(out.read_bytes())
    assert report['schema'] == 'sc-segment-delta-v1' and report['status'] == 'DIAGNOSTIC'
    assert report['content_changes'] == CONTENT_CASES['parameters'][1]
    assert report['input_files']['left'] == dict(supplied=True, raw_sha256=hashlib.sha256(left.read_bytes()).hexdigest(),
                                                 raw_bytes=len(left.read_bytes()))
    # Raw-file hash and the no-newline canonical digest are distinct identities.
    assert report['input_files']['left']['raw_sha256'] != report['determinism_digest']['left']['declared']
    raw = out.read_bytes()
    assert raw == (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    code, _, stderr = run_cli(['--left', left, '--right', right, '--out', out])
    assert code == 2 and out.read_bytes() == raw, 'existing report must never be overwritten'
    other = workdir('cli-mismatch')
    mismatch = write_json(other / 'right.json', variant('open-receipt.json', lambda v: v.update(segment_slug='other')))
    code, _, _ = run_cli(['--left', left, '--right', mismatch, '--out', other / 'report.json'])
    assert code == 1 and json.loads((other / 'report.json').read_bytes())['status'] == 'NOT_COMPARABLE'
    tampered = write_json(other / 'bad.json',
                          variant('open-receipt.json', lambda v: v.update(determinism_digest='0' * 64), reseal=False))
    code, _, stderr = run_cli(['--left', left, '--right', tampered, '--out', other / 'bad-report.json'])
    assert code == 2 and 'determinism digest mismatch' in stderr
    assert not (other / 'bad-report.json').exists()


# ---------------------------------------------- A2 producer contract suite ---

def test_a2_pinned_sources_and_field_partition_cover_schema():
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == SCHEMA_SHA256
    assert hashlib.sha256(PRODUCER_PATH.read_bytes()).hexdigest() == PRODUCER_SHA256
    module = delta()
    assert module.SCHEMA_SHA256 == SCHEMA_SHA256
    assert Path(module.SCHEMA_PATH).resolve() == SCHEMA_PATH.resolve()
    assert tuple(module.CONTENT_FIELDS) == FROZEN_CONTENT_FIELDS
    assert tuple(module.BOOKKEEPING_FIELDS) == FROZEN_BOOKKEEPING_FIELDS
    schema = json.loads(SCHEMA_PATH.read_bytes())
    partition = set(FROZEN_CONTENT_FIELDS) | set(FROZEN_BOOKKEEPING_FIELDS) | {'determinism_digest'}
    assert set(schema['properties']) == partition
    assert not set(FROZEN_CONTENT_FIELDS) & set(FROZEN_BOOKKEEPING_FIELDS)
    assert set(module.IDENTITY_FIELDS) == {'segment_slug', 'campaign_segment_id', 'coordinator_segment_id'}


def test_a2_projection_and_digest_match_existing_producer_helpers():
    producer, imported = load_producer()
    samples = [fixture('open-receipt.json'), fixture('closed-receipt.json')]
    samples += [variant('open-receipt.json', mutate) for mutate, _, _ in CONTENT_CASES.values()]
    for receipt in samples:
        assert delta().content_identity(receipt) == producer.content_identity(receipt) == golden_projection(receipt)
        assert delta().determinism_digest(receipt) == producer.determinism_digest(receipt) == golden_digest(receipt)
    for name in ('open-receipt.json', 'closed-receipt.json'):
        value = fixture(name)
        assert value['determinism_digest'] == producer.determinism_digest(value)
    # Source-closed: every newly imported project module comes from this checkout.
    root = str(ROOT.resolve())
    for name, path in imported.items():
        if path and 'skippercast' in path.replace('\\', '/').split('/') and not path.startswith(root):
            raise AssertionError(f'{name} imported from outside the staged checkout: {path}')
    project = [p for p in imported.values() if p and p.startswith(root)]
    assert str(PRODUCER_PATH) in project


def test_a2_closed_true_and_false_are_declared_shapes_only():
    open_receipt, closed_receipt = fixture('open-receipt.json'), fixture('closed-receipt.json')
    report = delta().compare_receipts(open_receipt, closed_receipt)
    assert report['status'] == 'DIAGNOSTIC' and report['content_changes'] == []
    pointers = [r['pointer'] for r in report['bookkeeping_changes']]
    assert pointers == ['/archive/manifest/bytes', '/archive/manifest/path', '/archive/manifest/root_id',
                        '/archive/manifest/sha256', '/closed', '/signoff/artifact/bytes', '/signoff/artifact/path',
                        '/signoff/artifact/root_id', '/signoff/artifact/sha256', '/signoff/reviewed_digest',
                        '/signoff/verdict/bytes', '/signoff/verdict/path', '/signoff/verdict/root_id',
                        '/signoff/verdict/sha256']
    assert all(r['before_present'] is False for r in report['bookkeeping_changes'] if r['pointer'] != '/closed')
    assert report['declared_closed'] == dict(before=False, after=True)
    assert report['closure_verified'] is False and report['semantic_approval'] is False
    assert 'closure_verdict' not in report and 'verdict' not in report
    back = delta().compare_receipts(closed_receipt, open_receipt)
    assert back['declared_closed'] == dict(before=True, after=False) and back['closure_verified'] is False
    assert [r['pointer'] for r in back['bookkeeping_changes']] == pointers


def test_a2_schema_validation_denies_remote_retrieval():
    module = delta()
    with offline_guard():
        expect_invalid(lambda: module.build_validator({'$ref': 'https://example.invalid/schema.json'}),
                       'schema references are refused')
        expect_invalid(lambda: module.deny_retrieval('https://example.invalid/schema.json'),
                       'remote schema retrieval denied')
        report = module.compare_receipts(fixture_bytes('open-receipt.json'), fixture_bytes('closed-receipt.json'))
    assert report['status'] == 'DIAGNOSTIC'


# ------------------------------------------------ A3 negative/preservation ---

REQUIRED = ('schema', 'schema_version', 'created_utc', 'author_profile', 'author_model', 'card_id',
            'code_commit', 'skill_commit', 'campaign_segment_id', 'coordinator_segment_id', 'segment_slug',
            'recipe_sha256', 'recipe', 'run', 'inputs', 'outputs', 'qa', 'tier1', 'determinism_digest', 'closed')


def test_a3_absent_required_fields_are_invalid():
    schema = json.loads(SCHEMA_PATH.read_bytes())
    assert set(schema['required']) == set(REQUIRED)
    for field in REQUIRED:
        broken = variant('open-receipt.json', lambda v: v.pop(field), reseal=False)
        expect_invalid(lambda: delta().compare_receipts(fixture('open-receipt.json'), broken), 'schema')
    for name, path in (('signoff', 'signoff'), ('archive', 'archive')):
        broken = variant('closed-receipt.json', lambda v: v.pop(path), reseal=False)
        expect_invalid(lambda: delta().compare_receipts(fixture('closed-receipt.json'), broken), 'schema')


def test_a3_duplicate_keys_and_nonfinite_values_are_invalid():
    raw = fixture_bytes('open-receipt.json')
    duplicate = raw.replace(b'"card_id": "t_366d24e2",', b'"card_id": "t_366d24e2",\n  "card_id": "t_00000000",', 1)
    assert duplicate != raw
    expect_invalid(lambda: delta().compare_receipts(raw, duplicate), 'duplicate JSON key')
    for token in (b'NaN', b'Infinity', b'-Infinity', b'1e999'):
        broken = raw.replace(b'"hole_numerator": 10', b'"hole_numerator": ' + token, 1)
        assert broken != raw
        expect_invalid(lambda: delta().compare_receipts(raw, broken), 'nonfinite')
    in_memory = variant('open-receipt.json', lambda v: v['qa'].update(hole_numerator=float('nan')), reseal=False)
    expect_invalid(lambda: delta().compare_receipts(fixture('open-receipt.json'), in_memory), 'nonfinite')
    expect_invalid(lambda: delta().compare_receipts(raw, b'[]'), 'schema')
    expect_invalid(lambda: delta().compare_receipts(raw, b'{"truncated": '), 'malformed JSON')


def test_a3_malformed_refs_are_invalid():
    mutations = [lambda v: v['qa']['threshold_config'].update(path='../escape.json'),
                 lambda v: v['qa']['threshold_config'].update(path='/absolute.json'),
                 lambda v: v['qa']['threshold_config'].update(sha256='A' * 64),
                 lambda v: v['qa']['threshold_config'].pop('bytes'),
                 lambda v: v['qa']['threshold_config'].update(extra='x'),
                 lambda v: v['run'].update(root_id='file:/etc'),
                 lambda v: v['outputs'][0]['artifact'].update(bytes=-1)]
    for mutate in mutations:
        broken = variant('open-receipt.json', mutate)
        expect_invalid(lambda: delta().compare_receipts(fixture('open-receipt.json'), broken), 'schema')


def test_a3_tampered_digest_is_invalid_both_ways():
    content_only = variant('open-receipt.json', lambda v: v['outputs'][0]['parameters'].update(cell=2), reseal=False)
    expect_invalid(lambda: delta().compare_receipts(fixture('open-receipt.json'), content_only),
                   'determinism digest mismatch')
    stale = variant('open-receipt.json', lambda v: v.update(determinism_digest=golden_digest(content_only)),
                    reseal=False)
    expect_invalid(lambda: delta().compare_receipts(stale, fixture('open-receipt.json')),
                   'determinism digest mismatch')


def test_a3_same_output_bytes_with_changed_declared_producer_is_shown():
    left = fixture('open-receipt.json')
    right = variant('open-receipt.json', lambda v: (v.update(code_commit='3' * 40),
                                                    v['outputs'][0]['tool'].update(code_commit='3' * 40)))
    report = delta().compare_receipts(left, right)
    assert report['content_changes'] == [row('/code_commit', '1' * 40, '3' * 40),
                                         row('/outputs/0/tool/code_commit', '1' * 40, '3' * 40)]
    assert left['outputs'][0]['artifact'] == right['outputs'][0]['artifact']
    assert report['producer']['changed'] is True
    assert report['producer']['pointers'] == ['/code_commit', '/outputs/0/tool/code_commit']
    assert report['semantic_comparability'] == 'UNVERIFIED'
    same = delta().compare_receipts(left, left)
    assert same['producer']['changed'] is False and same['semantic_comparability'] == 'UNVERIFIED'
    assert same['semantic_approval'] is False


def test_a3_missing_producer_identity_is_invalid():
    for mutate in (lambda v: v.pop('code_commit'), lambda v: v.pop('skill_commit'),
                   lambda v: v['outputs'][0]['tool'].pop('code_commit'),
                   lambda v: v['outputs'][0]['tool'].update(version=''),
                   lambda v: v.update(code_commit='1' * 39)):
        broken = variant('open-receipt.json', mutate, reseal=False)
        expect_invalid(lambda: delta().compare_receipts(fixture('open-receipt.json'), broken), 'schema')


def test_a3_mismatched_segment_is_not_comparable_after_validation():
    other = variant('open-receipt.json', lambda v: v.update(campaign_segment_id='synthetic2'))
    report = delta().compare_receipts(fixture('closed-receipt.json'), other)
    assert report['status'] == 'NOT_COMPARABLE' and report['identity_changes'] == [
        row('/campaign_segment_id', 'synthetic', 'synthetic2')]
    # Invalid input still wins over NOT_COMPARABLE: nothing is explained from a bad receipt.
    bad = variant('open-receipt.json', lambda v: v.update(campaign_segment_id='synthetic2'), reseal=False)
    expect_invalid(lambda: delta().compare_receipts(fixture('open-receipt.json'), bad), 'determinism digest mismatch')


def test_a3_array_order_and_missing_versus_null_are_preserved():
    left = fixture('open-receipt.json')
    swapped = variant('open-receipt.json', lambda v: v['qa'].update(flags=list(reversed(v['qa']['flags']))))
    report = delta().compare_receipts(left, swapped)
    assert report['content_changes'] == [row('/qa/flags/0', 'synthetic-flag-a', 'synthetic-flag-b'),
                                         row('/qa/flags/1', 'synthetic-flag-b', 'synthetic-flag-a')]
    reordered = variant('open-receipt.json', lambda v: v.update(inputs=list(reversed(v['inputs']))))
    pointers = [r['pointer'] for r in delta().compare_receipts(left, reordered)['content_changes']]
    assert '/inputs/0/source_id' in pointers and '/inputs/1/source_id' in pointers
    removed = variant('open-receipt.json', lambda v: v['outputs'][0]['parameters'].pop('nodata'))
    assert delta().compare_receipts(left, removed)['content_changes'] == [
        row('/outputs/0/parameters/nodata', None, None, before_present=True, after_present=False)]
    nulled = variant('open-receipt.json', lambda v: v['outputs'][0]['parameters'].update(cell=None, extra=None))
    assert delta().compare_receipts(left, nulled)['content_changes'] == [
        row('/outputs/0/parameters/cell', 1, None),
        row('/outputs/0/parameters/extra', None, None, before_present=False, after_present=True)]
    shorter = variant('open-receipt.json', lambda v: v['outputs'][0]['parameters']['bands'].pop())
    assert delta().compare_receipts(left, shorter)['content_changes'] == [
        row('/outputs/0/parameters/bands/1', 2, None, after_present=False)]
    typed = variant('open-receipt.json', lambda v: v['outputs'][0]['parameters'].update(cell=1.0))
    assert delta().compare_receipts(left, typed)['content_changes'] == [row('/outputs/0/parameters/cell', 1, 1.0)]
    escaped = variant('open-receipt.json', lambda v: v['outputs'][0]['parameters'].update({'a/b~c': 1}))
    assert delta().compare_receipts(left, escaped)['content_changes'] == [
        row('/outputs/0/parameters/a~1b~0c', None, 1, before_present=False)]


def test_a3_referenced_files_are_never_statted_or_opened():
    work = workdir('refs')
    left_value, right_value = fixture('open-receipt.json'), fixture('closed-receipt.json')
    names = set()
    for value in (left_value, right_value):
        for ref in refs(value):
            names.update({ref['path'], Path(ref['path']).name, ref['path'].split('/')[0]})
            # Canary files at every declared Ref path next to the inputs.
            canary = work / ref['path']
            canary.parent.mkdir(parents=True, exist_ok=True)
            canary.write_bytes(b'canary: must never be read')
    left = write_json(work / 'left.json', left_value)
    right = write_json(work / 'right.json', right_value)
    tampered = write_json(work / 'tampered.json', variant('closed-receipt.json',
                          lambda v: v.update(determinism_digest='0' * 64), reseal=False))
    other = write_json(work / 'other.json', variant('open-receipt.json', lambda v: v.update(segment_slug='other')))
    broken = work / 'broken.json'
    broken.write_bytes(b'{"run": {"root_id": "queue:synthetic", "path": "metadata/run.json"')
    before = snapshot(work)
    runs = [([left, right, 'ok.json'], 0), ([left, tampered, 'tampered-report.json'], 2),
            ([left, other, 'other-report.json'], 1), ([left, broken, 'broken-report.json'], 2)]
    for (a, b, out), expected in runs:
        with access_trace() as seen:
            code, _, _ = run_cli(['--left', a, '--right', b, '--out', work / out])
        assert code == expected, (out, code)
        touched = {p for p in seen for n in names if p == n or p.endswith('/' + n)}
        assert not touched, f'Ref-named paths were accessed: {sorted(touched)}'
    after = snapshot(work)
    created = set(after) - set(before)
    assert {Path(p).name for p in created} == {'ok.json', 'other-report.json'}
    assert all(after[p] == digest for p, digest in before.items()), 'inputs/canaries changed'


def test_a3_unsafe_paths_and_bounds_are_refused_without_side_effects():
    module = delta()
    work = workdir('unsafe')
    good = write_json(work / 'good.json', fixture('open-receipt.json'))
    (work / 'link.json').symlink_to(good)
    (work / 'dir').mkdir()
    (work / 'real').mkdir()
    write_json(work / 'real' / 'inside.json', fixture('open-receipt.json'))
    (work / 'alias').symlink_to(work / 'real', target_is_directory=True)
    os.mkfifo(work / 'pipe.json')
    big = work / 'big.json'
    big.write_bytes(b' ' * (module.MAX_INPUT_BYTES + 1))
    existing = work / 'existing.json'
    existing.write_bytes(b'keep')
    before = snapshot(work)
    cases = [(work / 'link.json', good, work / 'o1.json', 'symlink'),
             (work / 'alias' / 'inside.json', good, work / 'o2.json', 'symlink'),
             (work / 'pipe.json', good, work / 'o3.json', 'regular file'),
             (work / 'dir', good, work / 'o4.json', 'regular file'),
             (big, good, work / 'o5.json', 'input cap'),
             (work / 'missing.json', good, work / 'o6.json', 'cannot open'),
             (good, good, existing, 'exists'),
             (good, good, work / 'alias' / 'o7.json', 'symlink'),
             (good, good, work / 'nodir' / 'o8.json', 'cannot open'),
             (str(work / 'real' / '..' / 'good.json'), good, work / 'o9.json', 'normalized')]
    for left, right, out, fragment in cases:
        code, _, stderr = run_cli(['--left', left, '--right', right, '--out', out])
        assert code == 2, (left, out, code, stderr)
        assert fragment in stderr, (fragment, stderr)
    assert snapshot(work) == before, 'refusals must leave inputs and outputs unchanged'
    assert not any((work / f'o{i}.json').exists() for i in range(1, 10))
    # Tool-local denial-of-service bounds (rows, output, aggregate input).
    wide = variant('open-receipt.json', lambda v: v['outputs'][0]['parameters'].update(
        {f'k{i:05d}': i for i in range(module.MAX_ROWS + 1)}))
    expect_invalid(lambda: module.compare_receipts(fixture('open-receipt.json'), wide), 'row cap')
    with patched(module, MAX_OUTPUT_BYTES=256):
        code, _, stderr = run_cli(['--left', good, '--right', good, '--out', work / 'o10.json'])
        assert code == 2 and 'output cap' in stderr and not (work / 'o10.json').exists()
    with patched(module, MAX_AGGREGATE_BYTES=len(good.read_bytes()) + 10):
        code, _, stderr = run_cli(['--left', good, '--right', good, '--out', work / 'o11.json'])
        assert code == 2 and 'aggregate' in stderr and not (work / 'o11.json').exists()
    code, _, _ = run_cli(['--left', good, '--right', good])
    assert code == 2, 'all three explicit files are required'


# ------------------------------------------------------ mutation controls ---
# Each control pairs a regression check with an in-memory callable double that
# breaks exactly the behaviour it guards. The negative suite requires the check
# to FAIL under the double and PASS once the double is removed.

def check_projection_includes_content():
    """Exact projection assertion; runs before any receipt validation."""
    module = delta()
    value = fixture('open-receipt.json')
    assert module.content_identity(value) == golden_projection(value), 'projection differs from frozen v1 fields'
    left = value
    mutate, expected, _ = CONTENT_CASES['source_hash']
    right = variant('open-receipt.json', mutate)
    report = module.compare_receipts(left, right)
    assert report['content_changes'] == expected, 'projection lost a changed source SHA'
    assert report['bookkeeping_changes'] == [], 'projection moved content to bookkeeping'


def check_digest_gate():
    bad = variant('open-receipt.json', lambda v: v.update(determinism_digest=fake('tampered')), reseal=False)
    expect_invalid(lambda: delta().compare_receipts(fixture('open-receipt.json'), bad), 'determinism digest mismatch')


def check_identity_gate():
    other = variant('open-receipt.json', lambda v: v.update(segment_slug='other-segment'))
    report = delta().compare_receipts(fixture('open-receipt.json'), other)
    assert report['status'] == 'NOT_COMPARABLE', 'different segment was explained instead of refused'


def check_missing_vs_null():
    removed = variant('open-receipt.json', lambda v: v['outputs'][0]['parameters'].pop('nodata'))
    rows = delta().compare_receipts(fixture('open-receipt.json'), removed)['content_changes']
    assert rows == [row('/outputs/0/parameters/nodata', None, None, after_present=False)], 'missing/null normalized'


def _drop_source_sha(original):
    def broken(receipt):
        projection = copy.deepcopy(original(receipt))
        for item in projection['inputs']:
            item.pop('source_sha256', None)
            item['cache'] = dict(item['cache'], sha256=None)
        for item in projection['outputs']:
            for source in item['contributing_sources']:
                source.pop('source_sha256', None)
        return projection
    return broken


def _double_projection_drops_source_sha(module):
    return patched(module, content_identity=_drop_source_sha(module.content_identity))


def _double_field_moved_to_bookkeeping(module):
    content = tuple(f for f in module.CONTENT_FIELDS if f != 'inputs')
    return patched(module, CONTENT_FIELDS=content, BOOKKEEPING_FIELDS=module.BOOKKEEPING_FIELDS + ('inputs',))


def _double_digest_gate_disabled(module):
    return patched(module, check_digest=lambda receipt, side: module.determinism_digest(receipt))


def _double_identity_gate_disabled(module):
    return patched(module, IDENTITY_FIELDS=())


def _double_missing_as_null(module):
    original = module.make_row

    def normalized(pointer, before_present, before, after_present, after):
        return original(pointer, True, before, True, after)
    return patched(module, make_row=normalized)


def _double_stats_declared_refs(module):
    original = module.compare_receipts

    def peeking(left, right, **kwargs):
        for side in (left, right):
            try:
                value = json.loads(side) if isinstance(side, (bytes, bytearray)) else side
            except ValueError:
                continue
            for ref in refs(value):
                try:
                    os.stat(ref['path'])
                except OSError:
                    pass
        return original(left, right, **kwargs)
    return patched(module, compare_receipts=peeking)


def check_refs_never_accessed():
    test_a3_referenced_files_are_never_statted_or_opened()


MUTATION_CONTROLS = (
    ('projection_drops_changed_source_sha', check_projection_includes_content, _double_projection_drops_source_sha,
     'projection differs'),
    ('content_field_moved_to_bookkeeping', check_projection_includes_content, _double_field_moved_to_bookkeeping,
     'projection differs'),
    ('digest_gate_disabled', check_digest_gate, _double_digest_gate_disabled, 'expected InvalidReceipt'),
    ('identity_gate_disabled', check_identity_gate, _double_identity_gate_disabled, 'refused'),
    ('missing_normalized_to_null', check_missing_vs_null, _double_missing_as_null, 'missing/null'),
    ('declared_refs_statted', check_refs_never_accessed, _double_stats_declared_refs, 'Ref-named paths'),
)


def run_mutation_controls():
    """Return one result per control; never raises for an expected detection."""
    module = delta()
    results = []
    for name, check, double, fragment in MUTATION_CONTROLS:
        detected, message = False, ''
        with double(module):
            try:
                check()
            except AssertionError as error:
                message = str(error)
                detected = fragment in message
        positive = True
        try:
            check()
        except AssertionError as error:
            positive, message = False, message + ' | positive control failed: ' + str(error)
        results.append(dict(control=name, detected=detected, positive_passed=positive, message=message))
    return results


def test_a3_mutation_controls_detect_isolated_broken_doubles():
    results = run_mutation_controls()
    assert len(results) == len(MUTATION_CONTROLS)
    for result in results:
        assert result['detected'] and result['positive_passed'], result
