"""Synthetic, source-free grid compatibility; no scientific/live admission."""
import copy

import numpy as np
import pytest

from skippercast.coastal.coordinator import ordered_trial, saved_area
from skippercast.coastal.authenticated_v1.profiles import PARTIAL_SUPPORT, PARTIAL_WINDOWS
from tests.gis.test_coastal_saved_area_native_grid import facts, WINDOW

FINAL = [3762, 3488, 128, 128]


@pytest.fixture
def contract():
    return dict(schema=saved_area.STRICT_FINAL_A_CONTRACT,
                scope=ordered_trial.LARGER_SCOPE, support_policy='strict',
                window_set=copy.deepcopy(ordered_trial.LARGER_WINDOWS),
                full_grid_transform=list(ordered_trial.LARGER_AFFINE))


@pytest.fixture
def final_facts():
    # Independent synthetic 128x128 support array; never an observed/live field.
    support = np.ones((128, 128), dtype=bool)
    doc = facts(window=list(FINAL), transform=[2, 0, 728615, 0, -2, 3819179])
    doc.update(valid_count=int(np.count_nonzero(support)), valid_fraction=float(support.mean()))
    return doc


@pytest.fixture
def no_io(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('grid compatibility must not access metadata, SQLite or native sources')
    for name in ('metadata_document', 'resolve', 'load', 'bounded_control_bytes'):
        monkeypatch.setattr(saved_area, name, forbidden)
    monkeypatch.setattr(saved_area.sqlite3, 'connect', forbidden)
    yield tmp_path
    assert list(tmp_path.iterdir()) == []


def test_original_default_and_explicit_final_are_distinct(contract, final_facts, no_io):
    assert saved_area.require_saved_area_a_native_grid(facts(), list(WINDOW)) is None
    assert saved_area.require_saved_area_a_native_grid(final_facts, FINAL, grid_contract=contract) is None
    with pytest.raises(ValueError, match='transform does not match'):
        saved_area.require_saved_area_a_native_grid(final_facts, FINAL)
    with pytest.raises(ValueError, match='window does not match'):
        saved_area.require_saved_area_a_native_grid(facts(), FINAL, grid_contract=contract)
    with pytest.raises(ValueError, match='transform does not match'):
        saved_area.require_saved_area_a_native_grid(facts(window=FINAL), FINAL, grid_contract=contract)


def test_final_pin_uses_a_row_not_whole_block_upper_left(contract, final_facts, no_io):
    from affine import Affine
    full = Affine(*ordered_trial.LARGER_AFFINE)
    assert tuple(full * Affine.translation(*FINAL[:2]))[:6] == saved_area.STRICT_FINAL_A['transform']
    assert tuple(full * Affine.translation(3762, 3360))[:6] != saved_area.STRICT_FINAL_A['transform']
    with pytest.raises(TypeError):
        saved_area.STRICT_FINAL_A['transform'] = ()
    final_facts['header']['transform'] = list(full * Affine.translation(3762, 3360))[:6]
    with pytest.raises(ValueError, match='transform does not match'):
        saved_area.require_saved_area_a_native_grid(final_facts, FINAL, grid_contract=contract)


@pytest.mark.parametrize('change', [
    {'schema': 'unknown'}, {'scope': 'unknown'}, {'support_policy': PARTIAL_SUPPORT},
    {'window_set': PARTIAL_WINDOWS}, {'window_set': [[3890, 3488, 128, 128]]},
    {'window_set': [FINAL] * 4}, {'full_grid_transform': [2, 0, 728615, 0, -2, 3819179]},
    {'full_grid_transform': [2, 0, 721091.5, 0, -2, 3826155]},
    {'reviewer_id': 'not-an-attestation'}, {'state': 'cancelled'}, {'state': 'stale'},
    {'state': 'expired'}, {'valid_until': 0},
])
def test_unknown_partial_duplicate_or_unchecked_contract_refuses_before_facts(contract, change, no_io):
    contract.update(change)
    with pytest.raises(ValueError, match='recognized reviewed strict final-A'):
        saved_area.require_saved_area_a_native_grid(None, FINAL, grid_contract=contract)


@pytest.mark.parametrize('bad', [{}, 'strict-final-A', False, []])
def test_absent_or_wrong_contract_does_not_select_final(bad, no_io):
    with pytest.raises(ValueError, match='recognized reviewed strict final-A'):
        saved_area.require_saved_area_a_native_grid(None, FINAL, grid_contract=bad)


@pytest.mark.parametrize('window', [list(WINDOW), [3762, 3360, 128, 128], [3762, 3488, 64, 64]])
def test_same_source_different_window_cannot_reuse_final_pin(contract, window, no_io):
    with pytest.raises(ValueError, match='window/full-grid affine pin differs'):
        saved_area.require_saved_area_a_native_grid(None, window, grid_contract=contract)


@pytest.mark.parametrize('field,value', [
    ('transform', [2, 0, 728617, 0, -2, 3819179]),
    ('transform', [2, 0, 728615.5, 0, -2, 3819179]),
    ('transform', [2, 0, 728615, 0, 2, 3819179]),
    ('horizontal_crs', 'EPSG:26911'), ('shape', [128, 128]), ('resolution_m', [1, 1]),
    ('window', list(WINDOW)),
])
def test_final_grid_refuses_bad_native_facts(contract, final_facts, field, value, no_io):
    final_facts['header'][field] = value
    with pytest.raises(ValueError, match=field + ' does not match'):
        saved_area.require_saved_area_a_native_grid(final_facts, FINAL, grid_contract=contract)


@pytest.mark.parametrize('field,value', [('valid_count', 16383), ('valid_fraction', 0.999)])
def test_final_requires_full_support(contract, final_facts, field, value, no_io):
    final_facts[field] = value
    with pytest.raises(ValueError, match=field + ' does not match'):
        saved_area.require_saved_area_a_native_grid(final_facts, FINAL, grid_contract=contract)


@pytest.mark.parametrize('pin', ['LARGER_WINDOWS', 'LARGER_AFFINE'])
def test_shared_pin_drift_cannot_silently_relocate_final_a(contract, pin, monkeypatch, no_io):
    changed = copy.deepcopy(getattr(ordered_trial, pin))
    if pin == 'LARGER_WINDOWS':
        changed[0][0] += 1
        contract['window_set'] = changed
    else:
        changed[2] += 0.5
        contract['full_grid_transform'] = changed
    monkeypatch.setattr(ordered_trial, pin, changed)
    with pytest.raises(ValueError, match='window/full-grid affine pin differs'):
        saved_area.require_saved_area_a_native_grid(None, FINAL, grid_contract=contract)


def test_contract_and_facts_are_not_mutated(contract, final_facts, no_io):
    before = copy.deepcopy((contract, final_facts))
    saved_area.require_saved_area_a_native_grid(final_facts, FINAL, grid_contract=contract)
    saved_area.require_saved_area_a_native_grid(final_facts, FINAL, grid_contract=contract)
    assert (contract, final_facts) == before
