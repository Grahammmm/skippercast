import json
import subprocess
import sys

import pytest

from scripts.relief import central_stage_handoff
from skippercast.relief import receipts
from tests._support import ROOT


BIG_SUR = 'big-sur-coast'
CAMBRIA = 'cambria-san-simeon'
SOUTH_BIG_SUR = 'south-big-sur-san-simeon'
MONTEREY = 'monterey-point-sur'
ARGUELLO = 'point-arguello-conception'
SANTA_CRUZ = 'santa-cruz-monterey-bay'
SCRIPT = ROOT / 'scripts/relief/central_stage_handoff.py'


def _saved(out, region, step, *upstream, status='ok', **metadata):
    stage, _, scope = step.partition('.')
    code = dict(repo_sha='1' * 40, stage_digest='2' * 64)
    params = dict(fixture=step, region=region)
    doc = dict(schema='sc-stage-receipt/1', region=region, stage=stage, scope=scope or None,
               inputs=[], outputs=[dict(path='not-built.bin', sha256='3' * 64, bytes=1)] if status == 'ok' else [],
               code=code, params=params, upstream=list(upstream), status=status, attempt=1, **metadata)
    doc['generation'] = receipts.generation([], upstream, code['stage_digest'], params)
    _write(out, region, step, json.dumps(doc))
    ref = dict(stage=stage, generation=doc['generation'])
    if scope:
        ref['scope'] = scope
    return ref


def _write(out, region, step, text):
    path = out / region / 'stages' / f'{step}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def _triage(out, capsys):
    assert central_stage_handoff.main(['--out', str(out)]) == 0
    return {row['region']: row for row in json.loads(capsys.readouterr().out)['regions']}


def _last(region, step, ref):
    return dict(step=step, receipt=f'{region}/stages/{step}.json', generation=ref['generation'])


def test_cli_complete_through_envelope_and_reports_every_central_release(tmp_path):
    # Invariant: the whole public chain can verify without opening any outputs.
    # Regressions: wrong public paths, using the done rule, or stopping before envelope.
    def save(step, *upstream):
        return _saved(tmp_path, BIG_SUR, step, *upstream)

    select = save('select', save('census'))
    mosaic = save('mosaic.public', select)
    tiles = save('tiles.public', mosaic, select)  # link order is not identity
    zone = save('zone.public', select, mosaic)
    digests = save('digests', tiles)
    inventory = save('inventory', select, tiles, digests, zone)
    contours = save('contours', select, mosaic)
    nearshore = save('nearshore_vectors.public', select, mosaic)
    package = save('package', tiles, digests, zone, inventory, contours)
    save('shots', package)
    qa = save('qa', package, mosaic, nearshore, contours)
    envelope = save('envelope', package, qa)

    proc = subprocess.run([sys.executable, SCRIPT, '--out', str(tmp_path)],
                          cwd=ROOT, capture_output=True, text=True, check=True)
    payload = json.loads(proc.stdout)
    assert payload['mode'] == 'receipt-only, not R8-ready'
    rows = payload['regions']
    assert [row['region'] for row in rows] == [BIG_SUR, CAMBRIA, SOUTH_BIG_SUR, MONTEREY, ARGUELLO, SANTA_CRUZ]
    assert rows[0]['last_verified'] == _last(BIG_SUR, 'envelope', envelope)
    assert rows[0]['first_unresolved'] is rows[0]['reason'] is None
    assert all(row['first_unresolved'] == 'select' and row['reason'] == 'missing'
               and row['last_verified'] is None for row in rows[1:])


def test_matching_stale_held_and_failed_neighbors_stay_separate(tmp_path, capsys, monkeypatch):
    # Invariant: first unresolved stops the cursor per region, with no lock probe.
    # Regressions: trusting older history, skipping a held step for a later ok,
    # or using receipts.check, which checks locks for an interrupted receipt.
    select = _saved(tmp_path, BIG_SUR, 'select')
    mosaic = _saved(tmp_path, BIG_SUR, 'mosaic.public', select)

    old = _saved(tmp_path, CAMBRIA, 'select')
    select_path = tmp_path / CAMBRIA / 'stages/select.json'
    old_doc = json.loads(select_path.read_text(encoding='utf-8'))
    new_doc = dict(old_doc, params={'fixture': 'new'}, generation_history={old['generation']: old_doc})
    new_doc['generation'] = receipts.generation([], [], new_doc['code']['stage_digest'], new_doc['params'])
    select_path.write_text(json.dumps(new_doc), encoding='utf-8')
    _saved(tmp_path, CAMBRIA, 'mosaic.public', old)  # valid generation, but not the current upstream

    select = _saved(tmp_path, SOUTH_BIG_SUR, 'select')
    held = _saved(tmp_path, SOUTH_BIG_SUR, 'mosaic.public', select, status='held')
    _saved(tmp_path, SOUTH_BIG_SUR, 'tiles.public', select, held)
    _saved(tmp_path, MONTEREY, 'select', status='failed', error=receipts.INTERRUPTED)
    lock = tmp_path / MONTEREY / 'stages/select.lock'
    lock.touch()  # receipts.check would probe it

    def forbidden(*_args):
        pytest.fail('receipt-only reader tried to take a lock')

    monkeypatch.setattr(receipts.fcntl, 'flock', forbidden)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    rows = _triage(tmp_path, capsys)
    assert [(rows[r]['first_unresolved'], rows[r]['reason']) for r in (BIG_SUR, CAMBRIA, SOUTH_BIG_SUR, MONTEREY)] == [
        ('tiles.public', 'missing'), ('mosaic.public', 'stale'), ('mosaic.public', 'held'), ('select', 'failed'),
    ]
    assert rows[BIG_SUR]['last_verified'] == _last(BIG_SUR, 'mosaic.public', mosaic)
    assert rows[CAMBRIA]['last_verified']['generation'] == new_doc['generation']
    assert rows[SOUTH_BIG_SUR]['last_verified']['step'] == 'select'
    assert rows[MONTEREY]['last_verified'] is None
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('defect', ['malformed-json', 'wrong-schema', 'wrong-region', 'wrong-scope',
                                     'bad-generation', 'omitted-link', 'wrong-upstream-stage', 'duplicate-link'])
def test_invalid_receipt_cannot_advance_cursor(tmp_path, capsys, defect):
    # Invariant: JSON shape, identity, canonical generation and required direct
    # links must all agree; a status-only reader or generation-only join can lie.
    select = _saved(tmp_path, BIG_SUR, 'select')
    _saved(tmp_path, BIG_SUR, 'mosaic.public', select)
    path = tmp_path / BIG_SUR / 'stages/mosaic.public.json'
    doc = json.loads(path.read_text(encoding='utf-8'))
    if defect == 'malformed-json':
        path.write_text('{', encoding='utf-8')
    else:
        if defect == 'wrong-schema':
            doc['schema'] = 'sc-stage-receipt/0'
        elif defect == 'wrong-region':
            doc['region'] = CAMBRIA
        elif defect == 'wrong-scope':
            doc['scope'] = 'private'
        elif defect == 'bad-generation':
            doc['params']['edited'] = True  # the saved digest is still valid hex
        else:
            if defect == 'omitted-link':
                doc['upstream'] = []
            elif defect == 'wrong-upstream-stage':
                doc['upstream'] = [dict(select, stage='tiles', scope='public')]
            else:
                doc['upstream'].append(select)
            doc['generation'] = receipts.generation([], doc['upstream'], doc['code']['stage_digest'], doc['params'])
        path.write_text(json.dumps(doc), encoding='utf-8')
    row = _triage(tmp_path, capsys)[BIG_SUR]
    assert (row['first_unresolved'], row['reason']) == ('mosaic.public', 'stale')
    assert row['last_verified'] == _last(BIG_SUR, 'select', select)


def test_out_must_be_explicit_even_with_environment_default(tmp_path, capsys, monkeypatch):
    # Invariant: no inherited operational root. Reusing region.py's OUT default
    # would allow an omitted flag to read a root the caller did not choose.
    monkeypatch.setenv('SC_RELIEF_OUT', str(tmp_path))
    with pytest.raises(SystemExit) as exc:
        central_stage_handoff.main([])
    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert '--out' in captured.err and captured.out == ''
