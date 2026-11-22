"""Offline joins against saved selector-format metadata and North B recipes."""

import json

import pytest

from scripts.relief.north_b_camera_tiers import main
from skippercast.relief import receipts

FORT_BRAGG = 'fort-bragg-point-arena'
SHELTER_COVE = 'shelter-cove-north-mendocino'
HUMBOLDT = 'humboldt-bay-cape-mendocino'


def _save_native(root, region, rows, *, receipt_region=None):
    base = root / region
    table = base / 'select/native.json'
    table.parent.mkdir(parents=True)
    data = receipts.canonical(rows)
    table.write_bytes(data)
    receipt = base / 'stages/select.json'
    receipt.parent.mkdir()
    receipt.write_bytes(receipts.canonical({
        'schema': receipts.SCHEMA, 'region': receipt_region or region,
        'stage': 'select', 'scope': None, 'status': 'ok', 'attempt': 1,
        'generation': '1' * 64, 'upstream': [],
        'outputs': [{'path': 'select/native.json', 'bytes': len(data),
                     'sha256': receipts.sha256_bytes(data)}],
    }))
    return table, receipt


def _public(zoom):
    return {'rights_class': 'public', 'max_zoom': zoom, 'label': 'estimated',
            'path': 'nonexistent-grid.tif', 'support_path': None}


def _report(root, capsys):
    assert main(['--selection-root', str(root)]) == 0
    return json.loads(capsys.readouterr().out)


def test_same_cameras_follow_each_saved_regions_greatest_ceiling(tmp_path, capsys):
    # Regional and snapshot isolation: pooling, hardcoding, using the last row,
    # or treating equality as above would misclassify the same z15 camera.
    first, second = tmp_path / 'first', tmp_path / 'second'
    _save_native(first, FORT_BRAGG, [_public(13), _public(12)])
    _save_native(first, SHELTER_COVE, [_public(17)])
    _save_native(second, FORT_BRAGG, [_public(15)])
    report = _report(first, capsys)
    fort, shelter, humboldt = report['regions']
    assert report['basis'] == (
        'Saved public candidate metadata only; camera support and raster tiles were not assessed.'
    )
    assert fort == {
        'region': FORT_BRAGG, 'selection_status': 'recorded',
        'usable_candidate_ceilings_present': True, 'greatest_recorded_candidate_ceiling': 13,
        'cameras': [
            {'id': 'noyo-harbor-z13', 'zoom': 13, 'review_only_candidate': False},
            {'id': 'noyo-outer-z15', 'zoom': 15, 'review_only_candidate': True},
        ],
    }
    assert shelter['region'] == SHELTER_COVE
    assert shelter['greatest_recorded_candidate_ceiling'] == 17
    assert [(c['id'], c['zoom'], c['review_only_candidate']) for c in shelter['cameras']] == [
        ('shelter-cove-open-ocean-boat-launch-z13', 13, False), ('shelter-cove-outer-z15', 15, False),
    ]
    assert humboldt['region'] == HUMBOLDT
    assert [(c['id'], c['zoom'], c['review_only_candidate']) for c in humboldt['cameras']] == [
        ('woodley-island-marina-humboldt-bay-z13', 13, None), ('humboldt-outer-z15', 15, None),
    ]
    fort_again = _report(second, capsys)['regions'][0]
    assert fort_again['greatest_recorded_candidate_ceiling'] == 15
    assert fort_again['cameras'][1] == {'id': 'noyo-outer-z15', 'zoom': 15, 'review_only_candidate': False}


@pytest.mark.parametrize(('case', 'status'), [
    ('missing_receipt', 'missing_receipt'),
    ('foreign_receipt', 'unusable_receipt'),
    ('changed_metadata', 'unusable_metadata'),
    ('nonpublic_metadata', 'unusable_metadata'),
    ('invalid_ceilings', 'no_usable_ceilings'),
])
def test_unusable_selection_leaves_camera_comparison_unknown(tmp_path, capsys, case, status):
    # A plausible leftover, foreign, changed or nonpublic table cannot supply
    # evidence; neither can coercing bools/strings into zooms or defaulting null.
    rows = [_public(17)]
    if case == 'nonpublic_metadata':
        rows.append(dict(_public(17), rights_class='private'))
    elif case == 'invalid_ceilings':
        rows = [_public(z) for z in (None, True, '17', 16.5, -1, 100)]
    table, receipt = _save_native(tmp_path, FORT_BRAGG, rows,
                                  receipt_region=SHELTER_COVE if case == 'foreign_receipt' else None)
    if case == 'missing_receipt':
        receipt.unlink()
    elif case == 'changed_metadata':
        table.write_bytes(table.read_bytes().replace(b'17', b'15'))  # same size, different bytes
    fort = _report(tmp_path, capsys)['regions'][0]
    assert fort['selection_status'] == status
    assert fort['usable_candidate_ceilings_present'] is False
    assert fort['greatest_recorded_candidate_ceiling'] is None
    assert [(c['zoom'], c['review_only_candidate']) for c in fort['cameras']] == [(13, None), (15, None)]
