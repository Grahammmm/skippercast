"""Fixture-only checks of the public rollout diagnostic's CLI contract."""
import json
import subprocess
import sys

import pytest

from scripts.coast_diagnostics import relief_rollout_status as rollout
from scripts.relief.run_region import SCOPED_STAGES, STAGES, SURVEY_STAGES
from skippercast.relief import receipts
from tests._support import ROOT


def record(region, stage, *, scope=None, upstream=(), status='ok', **extra):
    path = region.receipt_path(stage, scope)
    payload = region.dir / f'{path.stem}.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(b'fixture')
    doc = dict(schema=receipts.SCHEMA, region=region.id, stage=stage, scope=scope,
               status=status, attempt=1, upstream=list(upstream), outputs=[
                   dict(path=payload.name, bytes=7, sha256=receipts.sha256_bytes(b'fixture'))],
               **extra)
    doc['generation'] = receipts.generation([], upstream, 'a' * 64, {'stage': stage, 'scope': scope})
    path.write_text(json.dumps(doc), encoding='utf-8')
    return doc


def dependency(doc):
    return {key: doc[key] for key in ('stage', 'scope', 'generation')}


def populate(region, *, contour_fails=False, survey=SURVEY_STAGES):
    # A linear chain; inventory also takes the survey stages the run chose (run_region.py --survey).
    upstream = ()
    doc = {}
    surveyed = []
    for stage in STAGES:
        if stage in SURVEY_STAGES and stage not in survey:
            continue
        fields = {}
        if stage == 'mosaic':
            fields['params'] = {'review_required': True}
        if contour_fails and stage == 'contours':
            fields.update(status='failed', error="KeyError: 'survey_year'")
        if stage == 'inventory':
            upstream = (*upstream, *(dependency(survey_doc) for survey_doc in surveyed))
        doc = record(region, stage, scope='public' if stage in SCOPED_STAGES else None,
                     upstream=upstream, **fields)
        if stage in SURVEY_STAGES:
            surveyed.append(doc)
        if doc['status'] == 'failed':
            break
        upstream = (dependency(doc),)
    return doc


def invoke(out, ids, *options):
    return subprocess.run([sys.executable, str(ROOT / 'scripts/coast_diagnostics/relief_rollout_status.py'),
                           '--out', str(out), '--regions', ids, *options],
                          cwd=out, capture_output=True, text=True, check=True).stdout


def test_cli_reports_cohort_in_requested_order(tmp_path):
    # A single-region or sorted report loses cohort order; receipt-only status misses never-started regions.
    morro = populate(receipts.Region(tmp_path, 'morro-fixture'), contour_fails=True)
    complete = populate(receipts.Region(tmp_path, 'complete-fixture'))
    ids = 'morro-fixture, never-started,complete-fixture'
    assert json.loads(invoke(tmp_path, ids, '--json')) == [
        dict(region='morro-fixture', stage='contours', state='failed',
             reason="attempt 1: KeyError: 'survey_year'", generation=morro['generation']),
        dict(region='never-started', stage='select', state='missing', reason='no receipt', generation=None),
        dict(region='complete-fixture', stage=None, state='complete',
             reason='complete through envelope (ready for review, not live)', generation=complete['generation']),
    ]
    text = invoke(tmp_path, ids).splitlines()
    assert len(text) == 3
    assert text[0].startswith('morro-fixture: contours failed;') and 'survey_year' in text[0]
    assert text[1].startswith('never-started: select missing;')
    assert text[2].startswith('complete-fixture: complete through envelope (ready for review, not live)')
    assert not (tmp_path / 'never-started').exists()


@pytest.mark.parametrize('stage', STAGES)
def test_first_missing_stage_ignores_later_receipts_and_other_scopes(tmp_path, stage):
    # The rollout order is not alphabetical or inferred from which receipts happen to exist.
    region = receipts.Region(tmp_path, 'gap')
    scope = 'public' if stage in SCOPED_STAGES else None
    # when the missing stage is a survey stage, inventory takes it, so its receipt is a required one
    takes = [dict(stage=name, scope='public', generation='0' * 64) for name in SURVEY_STAGES]
    for candidate in reversed(STAGES):
        if candidate != stage:
            record(region, candidate, scope='public' if candidate in SCOPED_STAGES else None,
                   upstream=takes if candidate == 'inventory' and stage in SURVEY_STAGES else ())
    if scope:
        record(region, stage, scope='private')
    row = rollout.region_status(region)
    assert row['stage'] == (stage if scope is None else f'{stage}.public')
    assert row['state'] == 'missing' and row['generation'] is None


@pytest.mark.parametrize(('damage', 'state', 'reason'), [
    ('json', 'invalid', 'not JSON'),
    ('encoding', 'invalid', 'cannot read receipt'),
    ('array', 'invalid', 'not a JSON object'),
    ('schema', 'invalid', 'schema is'),
    ('region', 'invalid', 'region is'),
    ('stage', 'invalid', 'stage is'),
    ('scope', 'invalid', 'scope is'),
    ('status', 'invalid', 'status'),
    ('generation', 'invalid', 'not 64 hex'),
    ('outputs', 'invalid', 'outputs malformed'),
    ('upstream', 'invalid', 'upstream malformed'),
    ('attempt', 'invalid', 'attempt malformed'),
    ('directory', 'invalid', 'not a regular file'),
    ('escape', 'invalid', 'leaves the region directory'),
    ('hash', 'unproved', 'output changed'),
    ('lost', 'unproved', 'output missing'),
    ('held', 'held', 'fixture hold'),
])
def test_unverified_receipt_blocks_later_progress(tmp_path, damage, state, reason):
    # Trusting status=ok or merely the filename could promote malformed or changed evidence.
    region = receipts.Region(tmp_path, 'invalid-case')
    record(region, 'select')
    doc = record(region, 'mosaic', scope='public')
    record(region, 'tiles', scope='public')
    path = region.receipt_path('mosaic', 'public')
    outputs = doc['outputs']
    assert isinstance(outputs, list)
    output, = outputs
    payload = region.dir / output['path']
    if damage in ('json', 'encoding', 'array'):
        path.write_bytes({'json': b'{', 'encoding': b'\xff', 'array': b'[]'}[damage])
    elif damage == 'directory':
        path.unlink()
        path.mkdir()
    elif damage == 'hash':
        payload.write_bytes(b'changed')  # same size: the digest must actually be checked
    elif damage == 'lost':
        payload.unlink()
    else:
        if damage == 'escape':
            output['path'] = '../elsewhere'
        elif damage == 'held':
            doc.update(status='held', held_reason='fixture hold')
        else:
            doc[damage] = {'malformed': True}
        path.write_text(json.dumps(doc), encoding='utf-8')
    row = rollout.region_status(region)
    assert row['stage'] == 'mosaic.public' and row['state'] == state
    assert reason in row['reason']
    if damage in ('escape', 'hash', 'lost', 'held'):
        assert row['generation'] == doc['generation']
    else:
        assert row['generation'] is None


@pytest.mark.parametrize(('kind', 'reason'), [
    ('changed', 'generation changed'), ('missing', 'no receipt'),
    ('bad-name', 'invalid stage name'), ('cycle', 'upstream cycle'),
])
def test_upstream_must_be_current_and_done(tmp_path, kind, reason):
    # A byte-valid receipt still cannot advance the rollout if its dependency is stale or invalid.
    region = receipts.Region(tmp_path, 'stale-case')
    ref = dependency(record(region, 'select'))
    if kind == 'changed':
        ref['generation'] = 'b' * 64
    elif kind == 'missing':
        ref['stage'] = 'not_present'
    elif kind == 'bad-name':
        ref['stage'] = '../select'
    else:
        ref.update(stage='mosaic', scope='public')
    doc = record(region, 'mosaic', scope='public', upstream=[ref])
    row = rollout.region_status(region)
    assert (row['stage'], row['state'], row['generation']) == ('mosaic.public', 'stale', doc['generation'])
    assert reason in row['reason']


def test_interrupted_receipt_never_probes_lock_or_changes_tree(tmp_path, monkeypatch):
    # Even a preexisting lock file must not turn the diagnostic into a competing writer.
    region = receipts.Region(tmp_path, 'interrupted-case')
    doc = record(region, 'select', status='failed', error=receipts.INTERRUPTED)
    region.lock_path('select').touch()
    before = {p: p.read_bytes() for p in region.dir.rglob('*') if p.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail('diagnostic tried to lock or write a receipt')

    monkeypatch.setattr(receipts.fcntl, 'flock', forbidden)
    monkeypatch.setattr(receipts, 'write_json_atomic', forbidden)
    row = rollout.region_status(region)
    assert (row['stage'], row['state'], row['generation']) == ('select', 'failed', doc['generation'])
    assert 'activity not checked' in row['reason']
    assert {p: p.read_bytes() for p in region.dir.rglob('*') if p.is_file()} == before


def test_stages_report_lists_every_stage_of_every_region(tmp_path):
    # The status page (#3819 slice B): the first-incomplete view hides what is done or stale after the gap.
    morro = receipts.Region(tmp_path, 'morro-fixture')
    populate(morro, contour_fails=True)
    populate(receipts.Region(tmp_path, 'complete-fixture'))
    mixed = receipts.Region(tmp_path, 'mixed-fixture')
    select = record(mixed, 'select')
    mosaic = record(mixed, 'mosaic', scope='public', upstream=[dependency(select)], status='held',
                    held_reason='fixture hold')
    record(mixed, 'tiles', scope='public', upstream=[dependency(mosaic)])
    keys = [f'{s}.public' if s in SCOPED_STAGES else s for s in STAGES]
    ids = 'morro-fixture,never-started,complete-fixture,mixed-fixture'
    matrix = json.loads(invoke(tmp_path, ids, '--stages', '--json'))
    assert [entry['region'] for entry in matrix] == ids.split(',')
    states = {entry['region']: [(row['stage'], row['state']) for row in entry['stages']] for entry in matrix}
    failed_at = STAGES.index('contours')
    assert states['morro-fixture'] == [
        (key, 'done' if i < failed_at else 'failed' if i == failed_at else 'missing') for i, key in enumerate(keys)]
    assert states['never-started'] == [(key, 'missing') for key in keys]
    assert states['complete-fixture'] == [(key, 'done') for key in keys]
    assert states['mixed-fixture'][:4] == [('select', 'done'), ('mosaic.public', 'held'), ('tiles.public', 'stale'),
                                           ('zone.public', 'missing')]
    contours = matrix[0]['stages'][failed_at]
    assert 'survey_year' in contours['reason'] and len(contours['generation']) == 64
    assert matrix[1]['stages'][0] == {'stage': 'select', 'state': 'missing', 'reason': 'no receipt', 'generation': None}
    assert not (tmp_path / 'never-started').exists()


def test_stages_text_is_a_region_by_stage_table(tmp_path):
    populate(receipts.Region(tmp_path, 'morro-fixture'), contour_fails=True)
    lines = invoke(tmp_path, 'morro-fixture,never-started', '--stages').splitlines()
    keys = [f'{s}.public' if s in SCOPED_STAGES else s for s in STAGES]
    failed_at = STAGES.index('contours')
    assert len(lines) == 3
    assert lines[0].split() == ['region', *keys]
    assert lines[1].split() == ['morro-fixture', *['done'] * failed_at, 'failed',
                                *['missing'] * (len(STAGES) - failed_at - 1)]
    assert lines[2].split() == ['never-started', *['missing'] * len(STAGES)]
    assert lines[1].index('failed') == lines[0].index('contours')  # each state sits under its stage name


@pytest.mark.parametrize('survey', [('survey_detail',), ()], ids=['detail', 'none'])
def test_survey_stages_a_run_skipped_do_not_block_completion(tmp_path, survey):
    # Bug caught (#3832 RETURN 2): a run through envelope with --survey detail or none reported
    # survey_gap / survey_detail 'missing' and never 'complete'.
    region = receipts.Region(tmp_path, 'gapless-fixture')
    envelope = populate(region, survey=survey)
    row = rollout.region_status(region)
    assert (row['stage'], row['state'], row['generation']) == (None, 'complete', envelope['generation'])
    [entry] = json.loads(invoke(tmp_path, 'gapless-fixture', '--stages', '--json'))
    states = {row['stage']: row['state'] for row in entry['stages']}
    for stage in SURVEY_STAGES:
        assert states[f'{stage}.public'] == ('done' if stage in survey else 'skipped')
    assert {state for key, state in states.items() if key.split('.')[0] not in SURVEY_STAGES} == {'done'}
    table = invoke(tmp_path, 'gapless-fixture', '--stages').splitlines()
    assert table[1].split().count('skipped') == len(SURVEY_STAGES) - len(survey)


def test_a_survey_stage_the_inventory_takes_is_still_required(tmp_path):
    # Skipping must not hide a required survey receipt: inventory took survey_gap, its receipt is gone.
    region = receipts.Region(tmp_path, 'lost-gap')
    populate(region)
    region.receipt_path('survey_gap', 'public').unlink()
    row = rollout.region_status(region)
    assert (row['stage'], row['state']) == ('survey_gap.public', 'missing')


def test_survey_stages_before_an_inventory_receipt_are_judged_by_their_own_receipts(tmp_path):
    # Until inventory records the choice, a survey stage that never ran cannot be called skipped.
    region = receipts.Region(tmp_path, 'mid-run')
    upstream = ()
    for stage in ('select', 'mosaic', 'tiles', 'zone'):
        upstream = (dependency(record(region, stage, scope='public' if stage in SCOPED_STAGES else None,
                                      upstream=upstream)),)
    states = [(row['stage'], row['state']) for row in rollout.stage_states(region)][4:6]
    assert states == [('survey_detail.public', 'missing'), ('survey_gap.public', 'missing')]


def test_a_leftover_survey_receipt_the_inventory_does_not_take_is_skipped(tmp_path):
    # An older detail-and-gap run left a now-stale survey_gap receipt; the current release dropped it.
    region = receipts.Region(tmp_path, 'dropped-gap')
    populate(region, survey=('survey_detail',))
    record(region, 'survey_gap', scope='public', upstream=[dict(stage='zone', scope='public', generation='0' * 64)])
    assert rollout.region_status(region)['state'] == 'complete'
