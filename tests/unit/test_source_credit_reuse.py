"""Synthetic saved pointer projections, exercised at the review CLI boundary."""
import json

import pytest

from scripts.relief.source_credit_reuse import main


def _save(tmp_path, filename, doc):
    path = tmp_path / filename
    path.write_text(json.dumps(doc), encoding='utf-8')
    return str(path)


def _source(ident, credit):
    return {'id': ident, 'name': 'Fixture Survey', 'rights': {'attribution': credit}}


def _pointer(tmp_path, region, *ids):
    return _save(tmp_path, f'{region}.json', {
        'schema': 'sc-relief-pointer/1', 'region': region,
        'sources': [{'id': ident, 'label': 'Fixture Survey', 'attribution': 'Pointer credit'} for ident in ids],
    })


def _use(region):
    return {'region': region, 'layer': 'Depth shading'}


def test_shared_source_has_one_registered_credit_and_distinct_region_layer_pairs(tmp_path, capsys):
    # Catches a per-pointer report, a last-region-wins join, or substituting pointer credit for the register's.
    register = _save(tmp_path, 'sources.json', {'sources': [_source('shared', 'Canonical  credit')]})
    north = _pointer(tmp_path, 'fixture-north', 'shared', 'shared')
    south = _pointer(tmp_path, 'fixture-south', 'shared')
    assert main(['--register', register, south, north, north]) == 0
    assert json.loads(capsys.readouterr().out) == [{
        'source_id': 'shared', 'status': 'registered', 'name': 'Fixture Survey',
        'attribution': 'Canonical  credit', 'uses': [_use('fixture-north'), _use('fixture-south')],
    }]


def test_registered_ids_with_same_name_do_not_merge(tmp_path, capsys):
    # A name-keyed join would combine two distinct entries or assign one source's credit to the other.
    register = _save(tmp_path, 'sources.json', {'sources': [_source('survey-a', 'Credit A'),
                                                           _source('survey-b', 'Credit B')]})
    north = _pointer(tmp_path, 'fixture-north', 'survey-b')
    south = _pointer(tmp_path, 'fixture-south', 'survey-a')
    assert main(['--register', register, north, south]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [(row['source_id'], row['attribution'], row['uses']) for row in rows] == [
        ('survey-a', 'Credit A', [_use('fixture-south')]),
        ('survey-b', 'Credit B', [_use('fixture-north')]),
    ]


def test_unmatched_id_remains_explicit_without_credit(tmp_path, capsys):
    # A case-folded or label-based lookup would mis-credit this ID; an inner join would silently drop it.
    register = _save(tmp_path, 'sources.json', {'sources': [_source('survey-a', 'Credit A')]})
    north = _pointer(tmp_path, 'fixture-north', 'Survey-a')
    assert main(['--register', register, north]) == 0
    assert json.loads(capsys.readouterr().out) == [{
        'source_id': 'Survey-a', 'status': 'unresolved', 'name': None,
        'attribution': None, 'uses': [_use('fixture-north')],
    }]


def test_duplicate_registered_id_refuses_ambiguous_credit(tmp_path, capsys):
    # A dict comprehension could silently choose the last credit for a contradictory register.
    register = _save(tmp_path, 'sources.json', {'sources': [_source('survey-a', 'Credit A'),
                                                           _source('survey-a', 'Credit B')]})
    north = _pointer(tmp_path, 'fixture-north', 'survey-a')
    with pytest.raises(SystemExit) as exc:
        main(['--register', register, north])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert "duplicate registered source ID 'survey-a'" in captured.err
