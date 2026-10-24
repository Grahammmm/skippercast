"""S-019 metadata acceptance, derived from committed producer-shaped fixtures.

Synthetic files only. Closure adapter doubles test sequencing/bindings, not real
archive qualification. The operator-owned full suite retains real graph tests.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import validate_coast_receipt as segment
from tests._support import FIXTURES

ROOT_ID = 'queue:synthetic'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(root, path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dict(root_id=ROOT_ID, path=path, sha256=digest(raw), bytes=len(raw))


def seal(value):
    value['determinism_digest'] = segment.determinism_digest(value)
    return value


@pytest.fixture
def producer(tmp_path):
    root = tmp_path / 'admitted'
    root.mkdir()
    # Exact existing schemas/vocabulary, not newly invented stand-in run formats.
    original = FIXTURES / 'coast/queue'
    run = json.loads((original / 'valid/run-summary.json').read_text())
    admission = json.loads((original / run['admission']['path']).read_text())
    source_id = admission['sources'][0]['source_id']
    evidence = save(root, 'metadata/evidence.json', {'synthetic': True})
    cache = save(root, 'cache/source.json', {'synthetic': 'cached source metadata only'})
    admission['sources'][0]['hot_cache'] = [cache]
    run['admission'] = save(root, 'metadata/admission.json', admission)
    run_ref = save(root, 'metadata/run.json', run)
    recipe = save(root, 'metadata/recipe.json', {'synthetic': True, 'slug': 'synthetic-segment'})
    artifact = save(root, 'outputs/synthetic.json', {'synthetic': 'not a raster or real measurement'})
    qa = dict(report=evidence, hole_numerator=10, coverage_denominator=100,
              units='synthetic cells', spatial_support=evidence, flags=[], threshold_config=evidence)
    value = dict(schema='coast-segment-receipt-v1', schema_version=1,
                 **{key: run[key] for key in ('created_utc', 'author_profile', 'author_model', 'card_id',
                     'code_commit', 'skill_commit', 'campaign_segment_id', 'coordinator_segment_id')},
                 segment_slug='synthetic-segment', recipe_sha256=recipe['sha256'], recipe=recipe, run=run_ref,
                 inputs=[dict(source_id=source_id, source_sha256=cache['sha256'], cache=cache,
                              rights=evidence, datum=evidence, resolution=evidence)],
                 outputs=[dict(artifact=artifact, contributing_sources=[dict(source_id=source_id,
                     source_sha256=cache['sha256'])], tool=dict(name='synthetic-tool', version='v1',
                     code_commit=run['code_commit']), parameters={'cell': 1}, measured_format=evidence)],
                 qa=qa, tier1=dict(mode='unavailable', text_result='unavailable', vision_result='unavailable',
                                  reason='offline synthetic fixture; no model check performed'),
                 closed=False)
    resolver = segment.Resolver({ROOT_ID: str(root)}, allowed_root_ids={ROOT_ID})
    return root, resolver, seal(value)


def validate(producer, **kwargs):
    _, resolver, value = producer
    return segment.validate_receipt(value, resolver, root_id=ROOT_ID, **kwargs)


def test_producer_shaped_open_is_review_required_and_read_only(producer):
    root, _, value = producer
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = validate(producer)
    assert result == dict(status='REVIEW REQUIRED', structurally_valid=True, closed_verified=False,
                          semantic_approval=False, publication_allowed=False)
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
    assert value['qa']['hole_numerator'] / value['qa']['coverage_denominator'] == 0.1


@pytest.mark.parametrize('field', ['recipe_sha256', 'determinism_digest', 'segment_slug', 'inputs', 'outputs', 'qa',
                                  'tier1', 'closed', 'code_commit', 'skill_commit', 'run'])
def test_missing_required_fields_fail(producer, field):
    del producer[2][field]
    with pytest.raises(ValueError, match='schema'):
        validate(producer)


@pytest.mark.parametrize('bad', ['', None, 'a' * 63, 'A' * 64, 'g' * 64, 'a' * 65, 'a' * 64 + '\n'])
def test_malformed_hashes_fail(producer, bad):
    producer[2]['outputs'][0]['artifact']['sha256'] = bad
    with pytest.raises(ValueError):
        validate(producer)


@pytest.mark.parametrize('path', ['/absolute', '../escape', 'a/../escape', './relative', 'a//b', 'a/',
                                  'a\\b', 'a/./b', 'nul\x00', 'line\nbreak'])
def test_unsafe_paths_fail_before_any_payload_read(producer, path, monkeypatch):
    _, resolver, value = producer
    value['outputs'][0]['artifact']['path'] = path
    def forbidden(*args, **kwargs):
        pytest.fail('malformed receipt reached a file read')
    monkeypatch.setattr(resolver, 'read', forbidden)
    with pytest.raises(ValueError):
        validate(producer)


def test_duplicate_output_path_rejected_even_with_different_metadata(producer):
    value = producer[2]
    duplicate = copy.deepcopy(value['outputs'][0])
    duplicate['parameters']['cell'] = 2
    value['outputs'].append(duplicate)
    seal(value)
    with pytest.raises(ValueError, match='duplicate output path'):
        validate(producer)


@pytest.mark.parametrize('change', ['unknown_id', 'wrong_hash'])
def test_unbound_contributing_source(producer, change):
    value = producer[2]
    source = value['outputs'][0]['contributing_sources'][0]
    source['source_id' if change == 'unknown_id' else 'source_sha256'] = 'other' if change == 'unknown_id' else 'f' * 64
    seal(value)
    with pytest.raises(ValueError, match='unbound contributing source'):
        validate(producer)


def test_input_must_bind_to_actual_admission(producer):
    value = producer[2]
    value['inputs'][0]['source_id'] = 'unadmitted'
    value['outputs'][0]['contributing_sources'][0]['source_id'] = 'unadmitted'
    seal(value)
    with pytest.raises(ValueError, match='source is not bound to run admission'):
        validate(producer)


def test_input_cache_hash_must_match_source(producer):
    value = producer[2]
    value['inputs'][0]['source_sha256'] = 'f' * 64
    seal(value)
    with pytest.raises(ValueError, match='source/cache hash mismatch'):
        validate(producer)


def test_duplicate_input_ids(producer):
    value = producer[2]
    value['inputs'].append(copy.deepcopy(value['inputs'][0]))
    seal(value)
    with pytest.raises(ValueError, match='duplicate input source'):
        validate(producer)


@pytest.mark.parametrize('target', ['cache', 'artifact', 'qa'])
def test_changed_reference_bytes_are_rejected(producer, target):
    root, _, value = producer
    ref = value['inputs'][0]['cache'] if target == 'cache' else (
        value['outputs'][0]['artifact'] if target == 'artifact' else value['qa']['report'])
    raw = (root / ref['path']).read_bytes()
    (root / ref['path']).write_bytes(b'X' + raw[1:])
    with pytest.raises(ValueError, match='SHA256/bytes mismatch'):
        validate(producer)


@pytest.mark.parametrize('location', ['leaf', 'ancestor', 'root'])
def test_symlink_components_refused(producer, tmp_path, location):
    root, resolver, value = producer
    if location == 'root':
        alias = tmp_path / 'alias'
        alias.symlink_to(root, target_is_directory=True)
        with pytest.raises(OSError):
            segment.Resolver({ROOT_ID: str(alias)}, allowed_root_ids={ROOT_ID})
        return
    if location == 'ancestor':
        (root / 'alias').symlink_to(root / 'outputs', target_is_directory=True)
        value['outputs'][0]['artifact']['path'] = 'alias/synthetic.json'
    else:
        (root / 'alias.json').symlink_to(root / 'outputs/synthetic.json')
        value['outputs'][0]['artifact']['path'] = 'alias.json'
    seal(value)
    with pytest.raises(OSError):
        segment.validate_receipt(value, resolver, root_id=ROOT_ID)


def test_fifo_is_refused_without_blocking(producer):
    root, _, value = producer
    os.mkfifo(root / 'pipe')
    value['outputs'][0]['artifact']['path'] = 'pipe'
    seal(value)
    with pytest.raises(ValueError, match='not a regular file'):
        validate(producer)


@pytest.mark.parametrize('field', ['recipe_sha256', 'code_commit', 'campaign_segment_id'])
def test_existing_exact_identities_cannot_be_relabelled(producer, field):
    value = producer[2]
    value[field] = ('f' * (40 if field == 'code_commit' else 64)) if field != 'campaign_segment_id' else 'other'
    seal(value)
    with pytest.raises(ValueError, match='hash mismatch|identity mismatch|namespace differs'):
        validate(producer)


def test_digest_stable_across_physical_roots_and_top_level_clock(producer, tmp_path):
    root, _, value = producer
    second = tmp_path / 'second'
    second.mkdir()
    for path in root.rglob('*'):
        if path.is_file():
            dest = second / path.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())
    other = copy.deepcopy(value)
    other['created_utc'] = '2026-10-24T20:00:00Z'
    assert segment.determinism_digest(other) == value['determinism_digest']
    resolver = segment.Resolver({ROOT_ID: str(second)}, allowed_root_ids={ROOT_ID})
    assert segment.validate_receipt(other, resolver, root_id=ROOT_ID)['status'] == 'REVIEW REQUIRED'
    # Independent golden projection, not a second call to the production digest.
    fields = ['schema', 'schema_version', 'campaign_segment_id', 'coordinator_segment_id', 'segment_slug',
              'recipe_sha256', 'recipe', 'code_commit', 'skill_commit', 'inputs', 'outputs', 'qa', 'tier1']
    golden = json.dumps({k: value[k] for k in fields}, sort_keys=True, separators=(',', ':')).encode()
    assert value['determinism_digest'] == digest(golden)


@pytest.mark.parametrize('mutation', ['source', 'tool_version', 'parameters', 'output_hash', 'recipe'])
def test_content_changes_invalidate_digest(producer, mutation):
    value = copy.deepcopy(producer[2])
    if mutation == 'source':
        value['inputs'][0]['source_sha256'] = 'f' * 64
    elif mutation == 'tool_version':
        value['outputs'][0]['tool']['version'] = 'v2'
    elif mutation == 'parameters':
        value['outputs'][0]['parameters']['cell'] = 2
    elif mutation == 'output_hash':
        value['outputs'][0]['artifact']['sha256'] = 'f' * 64
    else:
        value['recipe_sha256'] = 'f' * 64
    assert segment.determinism_digest(value) != producer[2]['determinism_digest']


def test_stale_digest_rejected_after_otherwise_valid_change(producer):
    producer[2]['outputs'][0]['parameters']['cell'] = 2
    with pytest.raises(ValueError, match='determinism digest mismatch'):
        validate(producer)


@pytest.mark.parametrize(('numerator', 'denominator'), [(101, 100), (0, 0), (-1, 100), (1, -1), (True, 100)])
def test_qa_denominator_and_units_are_not_optional(producer, numerator, denominator):
    value = producer[2]
    value['qa'].update(hole_numerator=numerator, coverage_denominator=denominator)
    seal(value)
    with pytest.raises(ValueError):
        validate(producer)


@pytest.mark.parametrize('vision', ['pass', 'flag', 'held'])
def test_unavailable_vision_is_not_success(producer, vision):
    value = producer[2]
    value['tier1']['vision_result'] = vision
    seal(value)
    with pytest.raises(ValueError):
        validate(producer)


@pytest.mark.parametrize(('mode', 'text', 'vision'), [('text_only', 'pass', 'unavailable'),
    ('text_and_vision', 'flag', 'pass'), ('text_and_vision', 'held', 'flag')])
def test_actual_tier_modes_preserve_their_results(producer, mode, text, vision):
    value = producer[2]
    value['tier1'] = dict(mode=mode, text_result=text, vision_result=vision,
                        reason='synthetic reported result only', report=value['qa']['report'])
    seal(value)
    assert validate(producer)['semantic_approval'] is False


def test_closed_requires_refs_and_independently_bound_verdict(producer):
    value = producer[2]
    value['closed'] = True
    with pytest.raises(ValueError, match='schema'):
        validate(producer)
    # Otherwise valid shape/hashes, but caller has not supplied any trusted verdict.
    value['signoff'] = dict(verdict=value['qa']['report'], artifact=value['qa']['report'],
                            reviewed_digest=value['determinism_digest'])
    value['archive'] = dict(manifest=value['qa']['report'])
    segment.workflow.validate_schema(value)
    with pytest.raises(ValueError, match='independently bound approved verdict'):
        validate(producer)


def test_null_or_empty_signoff_never_stands_in_for_evidence(producer):
    producer[2]['signoff'] = None
    with pytest.raises(ValueError, match='schema'):
        validate(producer)


def test_closed_does_not_accept_self_declared_reviewed_digest(producer):
    root, _, value = producer
    identity = save(root, 'metadata/reviewed.json', segment.content_identity(value))
    value['signoff'] = dict(verdict=value['qa']['report'], artifact=identity, reviewed_digest='f' * 64)
    value['archive'] = dict(manifest=value['qa']['report'])
    value['closed'] = True
    with pytest.raises(ValueError, match='reviewed digest mismatch'):
        validate(producer, trusted_signoff=value['qa']['report'])


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}'])
def test_strict_json_parser_preserved(raw):
    with pytest.raises(ValueError):
        segment.loads(raw)


def test_cli_open_and_closed_preserve_no_approval(producer, capsys):
    root, _, value = producer
    roots_file = root / 'roots.json'
    roots_file.write_text(json.dumps({ROOT_ID: str(root)}))
    receipt_ref = save(root, 'segment.json', value)
    ref_file = root / 'receipt-ref.json'
    ref_file.write_text(json.dumps(receipt_ref))
    argv = [str(ref_file), '--roots', str(roots_file), '--allowed-root-id', ROOT_ID, '--root-id', ROOT_ID]
    assert segment.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'REVIEW REQUIRED' and result['semantic_approval'] is False
    value['closed'] = True
    ref_file.write_text(json.dumps(save(root, 'closed.json', value)))
    assert segment.main(argv) == 3
    assert 'REFUSED:' in capsys.readouterr().err


def closed_adapter(producer, monkeypatch):
    """Inert existing-API doubles: no archive creation or qualification claim."""
    root, resolver, value = producer
    identity = save(root, 'metadata/reviewed.json', segment.content_identity(value))
    original = FIXTURES / 'coast/queue/valid'
    verdict = json.loads((original / 'review-verdict.json').read_text())
    report = json.loads((original / 'open-report.json').read_text())
    report['evidence_snapshots'] = [identity]
    verdict['open_report'] = save(root, 'metadata/report.json', report)
    verdict['verdict'] = 'accept'
    trusted = save(root, 'metadata/verdict.json', verdict)
    routing = save(root, 'metadata/routing.json', dict(qualified_reviewers=[dict(
        actual_model=verdict['reviewer_model'], provenance=verdict['reviewer_provenance'])]))
    context = dict(run=value['run'], run_author_model=value['author_model'], routing=routing)
    manifest_ref = dict(value['qa']['report'], root_id='archive:synthetic:close01')
    value['closed'] = True
    value['signoff'] = dict(verdict=trusted, artifact=identity, reviewed_digest=value['determinism_digest'])
    value['archive'] = dict(manifest=manifest_ref)
    content_refs = list(segment._refs(segment.content_identity(value))) + [value['run'], identity]
    manifest = dict(campaign_segment_id=value['campaign_segment_id'], selected_verdicts=[trusted],
                    files=[dict(source_ref=ref) for ref in content_refs])
    result = dict(manifest_ref=manifest_ref, manifest=manifest)
    calls = []
    def trusted_context(res, ref):
        assert res is resolver and ref == verdict['context']
        calls.append('context')
        return context
    def reviewer(res, ctx, model, provenance):
        assert res is resolver and ctx == context
        assert model == verdict['reviewer_model'] and provenance == verdict['reviewer_provenance']
        calls.append('reviewer')
    archive_reader = object()
    def verify_closed(reader, **kwargs):
        assert reader is archive_reader
        assert kwargs == dict(archive_id='archive:synthetic:close01', original_queue_roots={ROOT_ID: str(root)},
                              original_raw_roots={})
        calls.append('archive_only')
        return result
    def load(name, path):
        if name == 'segment_review_common':
            return SimpleNamespace(trusted_context=trusted_context, reviewer=reviewer)
        assert name == 'segment_close_common'
        return SimpleNamespace(verify_closed=verify_closed)
    monkeypatch.setattr(segment, '_load', load)
    kwargs = dict(trusted_signoff=trusted, archive_resolver=archive_reader,
                  original_queue_roots={ROOT_ID: str(root)}, original_raw_roots={})
    return value, resolver, kwargs, result, calls


def test_closed_adapter_requires_existing_review_and_archive_apis(producer, monkeypatch):
    value, resolver, kwargs, _, calls = closed_adapter(producer, monkeypatch)
    segment._closed(value, resolver, **kwargs)
    assert calls == ['context', 'reviewer', 'archive_only']


@pytest.mark.parametrize('gate', ['missing_archive', 'wrong_manifest', 'wrong_verdict', 'missing_output',
                                  'wrong_reviewed_artifact', 'missing_snapshot', 'hold_verdict', 'unknown_trust'])
def test_isolated_closed_gate_controls(producer, monkeypatch, gate):
    value, resolver, kwargs, result, calls = closed_adapter(producer, monkeypatch)
    root = producer[0]
    expected = ''
    if gate == 'missing_archive':
        kwargs['archive_resolver'] = None
        expected = 'existing archive-only verification'
    elif gate == 'wrong_manifest':
        result['manifest_ref'] = dict(result['manifest_ref'], sha256='f' * 64)
        expected = 'archive manifest mismatch'
    elif gate == 'wrong_verdict':
        result['manifest']['selected_verdicts'] = []
        expected = 'archive/verdict segment mismatch'
    elif gate == 'missing_output':
        output = value['outputs'][0]['artifact']
        result['manifest']['files'] = [r for r in result['manifest']['files'] if r['source_ref'] != output]
        expected = 'content evidence missing'
    elif gate == 'wrong_reviewed_artifact':
        altered = segment.content_identity(value)
        altered['segment_slug'] = 'different-segment'
        value['signoff']['artifact'] = save(root, 'metadata/altered.json', altered)
        expected = 'reviewed artifact identity mismatch'
    elif gate == 'unknown_trust':
        kwargs['trusted_signoff'] = None
        expected = 'independently bound approved verdict'
    else:
        verdict = segment.document(resolver, kwargs['trusted_signoff'])
        if gate == 'missing_snapshot':
            report = segment.document(resolver, verdict['open_report'])
            report['evidence_snapshots'] = []
            verdict['open_report'] = save(root, 'metadata/altered-report.json', report)
            expected = 'does not review exact artifact identity'
        else:
            verdict['verdict'] = 'hold'
            expected = 'valid full-graph accept verdict'
        trusted = save(root, 'metadata/altered-verdict.json', verdict)
        value['signoff']['verdict'] = kwargs['trusted_signoff'] = trusted
    with pytest.raises(ValueError, match=expected):
        segment._closed(value, resolver, **kwargs)
    if gate in ('unknown_trust', 'wrong_reviewed_artifact', 'hold_verdict'):
        assert calls == []


def authenticated_signoff(producer, *, same_family=False, admitted_pair=True):
    """Synthetic runtime envelopes through the REAL existing review APIs."""
    root, resolver, value = producer
    original = FIXTURES / 'coast/queue/valid'
    context = json.loads((original / 'review-context.json').read_text())
    context.update(run=value['run'], root_ids=[ROOT_ID])
    author_model = value['author_model']
    reviewer_model = 'synthetic-reviewer'
    def provenance(model, family, session):
        return dict(actual_model=model, family=family, profile='synthetic-test', card_id=value['card_id'],
                    code_commit=value['code_commit'], skill_commit=value['skill_commit'],
                    created_utc=value['created_utc'], session_id=session, provider='synthetic-test-only')
    author = save(root, 'metadata/author.txt', provenance(author_model, 'synthetic-sol', 'author-session'))
    reviewer = save(root, 'metadata/reviewer.txt', provenance(reviewer_model,
        'synthetic-sol' if same_family else 'synthetic-opus', 'reviewer-session'))
    context['run_author_provenance'] = author
    identity_keys = ['campaign_segment_id', 'coordinator_segment_id', 'plan_id', 'plan_sha256',
                     'run_author_model', 'run_card_id']
    context['identity_provenance'] = save(root, 'metadata/identity.txt', {k: context[k] for k in identity_keys})
    context['posted_hashes'] = save(root, 'metadata/posted.txt', {k: context[k] for k in ('admission', 'run', 'bridge', 'enqueue')})
    leaf = save(root, 'metadata/opaque.txt', {'synthetic': True})
    context.update(thresholds=leaf, prompts=[leaf])
    routing = json.loads((original / 'review-routing.json').read_text())
    routing['allowed_pairs'] = [dict(author_model=author_model, reviewer_model=reviewer_model)] if admitted_pair else []
    routing['qualified_reviewers'] = [dict(actual_model=reviewer_model,
        family='synthetic-sol' if same_family else 'synthetic-opus', provenance=reviewer)]
    context['routing'] = save(root, 'metadata/routing.json', routing)
    context_ref = save(root, 'metadata/context.json', context)
    artifact = save(root, 'metadata/reviewed.json', segment.content_identity(value))
    report = json.loads((original / 'open-report.json').read_text())
    report.update(context=context_ref, evidence_snapshots=[artifact], reviewer_provenance=reviewer)
    verdict = json.loads((original / 'review-verdict.json').read_text())
    verdict.update(context=context_ref, open_report=save(root, 'metadata/report.json', report),
                   verdict='accept', reviewer_provenance=reviewer)
    trusted = save(root, 'metadata/verdict.json', verdict)
    value['closed'] = True
    value['signoff'] = dict(verdict=trusted, artifact=artifact, reviewed_digest=value['determinism_digest'])
    value['archive'] = dict(manifest=dict(value['qa']['report'], root_id='archive:synthetic:close01'))
    return trusted


@pytest.mark.parametrize(('same_family', 'admitted_pair', 'reason'), [
    (True, True, 'same actual author/reviewer model family'),
    (False, False, 'actual author/reviewer pair is not admitted'),
    (False, True, 'existing archive-only verification')])
def test_real_authentication_gates_precede_any_archive_access(producer, same_family, admitted_pair, reason):
    trusted = authenticated_signoff(producer, same_family=same_family, admitted_pair=admitted_pair)
    with pytest.raises(ValueError, match=reason):
        segment._closed(producer[2], producer[1], trusted_signoff=trusted, archive_resolver=None,
                        original_queue_roots=None, original_raw_roots=None)


def test_missing_output_hash_rejected_before_reads(producer, monkeypatch):
    del producer[2]['outputs'][0]['artifact']['sha256']
    def forbidden(*args, **kwargs):
        pytest.fail('missing hash reached a read')
    monkeypatch.setattr(producer[1], 'read', forbidden)
    with pytest.raises(ValueError, match='schema'):
        validate(producer)


def test_required_gate_negative_control_detects_disabled_gate(producer, monkeypatch):
    value = producer[2]
    value['outputs'].append(copy.deepcopy(value['outputs'][0]))
    seal(value)
    with pytest.raises(ValueError, match='duplicate output path'):
        validate(producer)
    original = segment.require
    def deliberately_broken(condition, message):
        if message != 'duplicate output path':
            original(condition, message)
    monkeypatch.setattr(segment, 'require', deliberately_broken)
    assert validate(producer)['structurally_valid'] is True
