"""F26-11: the feasibility CLI must not classify without a supported mainland."""

import json
import sys

import pytest

from research.scripts import assess_land_water_feasibility as probe


@pytest.mark.parametrize(
    ('paths', 'reason'),
    [
        ([], 'bounds-to-bounds paths 0'),
        ([[(1, 0), (1, -2)], [(2, 0), (2, -2)]], 'bounds-to-bounds paths 2'),
        ([[(0, -1), (3, -1)]], 'north-to-south mainland'),
        ([[(1, 0), (1, -2)]], None),
    ],
    ids=['empty', 'ambiguous', 'unsupported', 'supported'],
)
def test_feasibility_verdict(tmp_path, monkeypatch, capsys, paths, reason):
    # Synthetic geometry only. The empty case used to index mainland[0];
    # the positive control catches accidentally skipping parity for every input.
    dist = tmp_path / 'dist'
    shore_dir = dist / 'regions/synthetic'
    shore_dir.mkdir(parents=True)
    (dist / 'data').mkdir()
    tile = '12/2065/2059'
    (shore_dir / 'shoreline.geojson').write_text(json.dumps({
        'provenance': {
            'bounds': [0, -2, 3, 0],
            'tile_receipts': [{'tile': tile}],
            'requested_tiles': 1,
            'unavailable_tiles': [],
            'display_quantisation_m': 1,
        },
        'features': [{
            'geometry': {'coordinates': paths},
            'properties': {'HOR_ACC': 4, 'source_tile': tile},
        }] if paths else [],
    }))
    (dist / 'data/atlas.json').write_text(json.dumps({'targets': [
        {'id': 'synthetic-land', 'longitude': 1.5, 'latitude': -1},
    ]}))
    monkeypatch.setattr(probe, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['probe', '--region', 'synthetic'])

    probe.main()

    lines = capsys.readouterr().out.splitlines()
    if reason:
        assert lines[-1].startswith('PRODUCT UNAVAILABLE: ')
        assert reason in lines[-1]
        assert not any('waypoints' in line or 'opposite closure' in line for line in lines)
    else:
        assert lines[-1] == 'PRODUCT AVAILABLE'
        assert "{('atlas', 'land'): 1}" in '\n'.join(lines)
        assert 'parity changed by defect removal: 0' in '\n'.join(lines)
        assert 'with the opposite closure (SW,NW): on land 0 of 1' in '\n'.join(lines)
