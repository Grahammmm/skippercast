"""Exercise the inventory reader with saved custody metadata, never real tiles."""

import json
from pathlib import Path

import pytest

from scripts.relief import north_cusp_manifest_audit as auditor

_REGION = 'synthetic-north'
# At z12 the raw east edge crosses into column 686, but the water frame snaps
# it inward to column 685. The latitude span stays in row 1579.
_BOUNDS = [-119.96, 38.0, -119.7070301, 38.04]
_SERVED = '12/683/1579'
_UNAVAILABLE = '12/684/1579'
_UNLISTED = '12/685/1579'
_OUTSIDE = '12/686/1579'
_PIN = 'a7' * 32


def _served(tile, **overrides):
    return {'tile': tile, 'status': 'served', 'path': f'tiles/{tile}.pbf',
            'sha256': _PIN, **overrides}


def _unavailable(tile):
    return {'tile': tile, 'status': 'unavailable'}


def _save_inputs(root, rows, *, regions=None):
    config = root / 'region.json'
    manifest = root / 'manifest.json'
    if regions is None:
        regions = {_REGION: {'bounds': _BOUNDS}}
    config.write_text(json.dumps({'id': _REGION, 'bounds': _BOUNDS}), encoding='utf-8')
    manifest.write_text(json.dumps({'regions': regions, 'tiles': rows}), encoding='utf-8')
    return config, manifest


def test_counts_only_needed_tiles_and_distinguishes_all_three_states(tmp_path, capsys, monkeypatch):
    # Raw-bounds selection, whole-manifest counts, or merging both gap states
    # would change the inventory. A valid pin must not depend on local bytes.
    config, manifest = _save_inputs(tmp_path, [
        _served(_OUTSIDE), _unavailable('12/12/12'),
        _unavailable(_UNAVAILABLE), _served(_SERVED),
    ])
    real_open = Path.open

    def guard_open(path, *args, **kwargs):
        assert not path.is_relative_to(tmp_path / 'tiles'), 'inventory must not open tile bytes'
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guard_open)
    assert auditor.main(['--region-config', str(config), '--shoreline-manifest', str(manifest)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        'kind': 'custody_inventory_only',
        'region': _REGION,
        'frame_wgs84': [-119.96, 38.0, -119.70704, 38.04],
        'required_tile_count': 3,
        'outside_frame_row_count': 2,
        'counts': {'served': 1, 'unavailable': 1, 'not_listed': 1},
        'tiles': [
            {'tile': _SERVED, 'status': 'served', 'sha256': _PIN},
            {'tile': _UNAVAILABLE, 'status': 'unavailable'},
            {'tile': _UNLISTED, 'status': 'not_listed'},
        ],
    }


@pytest.mark.parametrize('second, issue', [
    pytest.param(_unavailable(_SERVED), 'conflicting', id='valid-served-unavailable-conflict'),
    pytest.param(_served(_SERVED), 'duplicate', id='identical-served-duplicate'),
])
def test_refuses_repeated_tiles_before_a_later_row_can_win(tmp_path, second, issue):
    # A dict comprehension would accept both ambiguous manifests and silently
    # choose the second row. Both competing rows are valid in isolation.
    inputs = _save_inputs(tmp_path, [_served(_SERVED), second])
    with pytest.raises(ValueError, match=rf'{issue} rows for tile {_SERVED}'):
        auditor.audit(*inputs)


@pytest.mark.parametrize('tile, pin', [
    pytest.param(_SERVED, 'g' * 64, id='non-hex-needed-pin'),
    pytest.param(_OUTSIDE, 'a' * 63, id='short-outside-frame-pin'),
    pytest.param(_SERVED, None, id='null-pin'),
])
def test_refuses_invalid_digest_syntax_even_outside_frame(tmp_path, tile, pin):
    # Checking length alone accepts non-hex values, and filtering first hides
    # malformed recorded digests in unrelated rows of the same saved manifest.
    inputs = _save_inputs(tmp_path, [_served(tile, sha256=pin)])
    with pytest.raises(ValueError, match=rf'tile {tile}: invalid SHA-256 pin'):
        auditor.audit(*inputs)


def test_foreign_only_manifest_cannot_lend_pins_to_selected_region(tmp_path):
    # Global rows alone cannot establish that this custody document covers the
    # requested region, even when one of its tile IDs happens to match.
    inputs = _save_inputs(tmp_path, [_served(_SERVED)], regions={'other': {'bounds': _BOUNDS}})
    with pytest.raises(ValueError, match=rf'region {_REGION}'):
        auditor.audit(*inputs)
