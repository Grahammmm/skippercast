"""Exercise the offline plan via real region JSON, water frames and CUSP tile math."""

import json

import pytest

from scripts.relief.north_cusp_tile_plan import main


def _region(root, region, bounds):
    config = root / 'regions' / region / 'region.json'
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({'id': region, 'bounds': bounds}), encoding='utf-8')
    return config


@pytest.fixture
def configs(tmp_path):
    # The first two frames share z12 column 2047. All frames sit inside row
    # 2047, just north of the equator; the others each add one distinct tile.
    _region(tmp_path, 'point-reyes-pigeon', [-0.14, 0.01, -0.06, 0.02])
    _region(tmp_path, 'bodega-point-reyes', [-0.07, 0.01, 0.04, 0.02])
    for offset, region in enumerate((
        'point-arena-bodega', 'fort-bragg-point-arena', 'shelter-cove-north-mendocino',
        'humboldt-bay-cape-mendocino', 'trinidad-klamath', 'crescent-city',
    ), start=2):
        # A z12 column is 360 / 4096 degrees wide.
        west = (offset + 0.25) * (360 / 4096)
        _region(tmp_path, region, [west, 0.01, west + 0.01, 0.02])
    return tmp_path


def test_adjacent_frames_count_shared_tile_once(configs, capsys):
    """Concatenating per-region lists doubles 2047; omitting any region drops a tile."""
    assert main([str(configs)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['expected_tile_ids'] == [f'12/{x}/2047' for x in (
        2046, 2047, 2048, 2050, 2051, 2052, 2053, 2054, 2055,
    )]
    assert report['tile_count'] == 9
    assert report['zoom'] == 12
    assert report['max_tile_bytes'] == 4_194_304
    assert report['worst_case_bytes'] == 37_748_736
    assert report['budget_bytes'] is None
    assert report['budget_status'] == 'not_supplied'


def test_expanded_frame_keeps_tile_at_inclusive_edge(configs, capsys):
    """An exclusive east endpoint drops a tile the water stage requires."""
    # Shift Bodega away from column 2048, then extend Point Reyes east just
    # past zero. The water snap places its edge exactly on the tile boundary.
    _region(configs, 'bodega-point-reyes', [-0.08, 0.01, -0.04, 0.02])
    assert main([str(configs)]) == 0
    before = json.loads(capsys.readouterr().out)
    _region(configs, 'point-reyes-pigeon', [-0.14, 0.01, 0.000004, 0.02])
    assert main([str(configs)]) == 0
    after = json.loads(capsys.readouterr().out)
    assert after['frames_wgs84']['point-reyes-pigeon'][2] == 0
    assert set(after['expected_tile_ids']) - set(before['expected_tile_ids']) == {'12/2048/2047'}
    assert after['tile_count'] == before['tile_count'] + 1


@pytest.mark.parametrize(('budget', 'status', 'exit_code'), [
    (50_000_000, 'within_budget', 0),
    (37_748_736, 'within_budget', 0),
    (37_748_735, 'exceeded', 1),
], ids=['below-ceiling', 'equal-to-ceiling', 'over-ceiling'])
def test_explicit_budget_classifies_worst_case(configs, capsys, budget, status, exit_code):
    """A byte below the bound must fail; equality must not fail or erase the plan."""
    assert main([str(configs), '--budget-bytes', str(budget)]) == exit_code
    report = json.loads(capsys.readouterr().out)
    assert report['budget_status'] == status
    assert report['budget_bytes'] == budget
    assert report['worst_case_bytes'] == 37_748_736


def test_missing_config_refuses_partial_plan(configs, capsys):
    """Silently skipping a missing region would advertise an incomplete tile budget."""
    (configs / 'regions/crescent-city/region.json').unlink()
    with pytest.raises(SystemExit) as exc:
        main([str(configs)])
    assert exc.value.code == 2
    result = capsys.readouterr()
    assert not result.out
    assert 'crescent-city: region.json unreadable' in result.err
