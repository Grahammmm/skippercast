"""SC-5b mask-topology pre-scan, end to end on a fake one-open dataset.

The fake stands in for the GDAL BAG dataset (numpy masked reads); the cached
H11952 BAG is never opened, hashed or stat'ed here.
"""
import json

import numpy as np
import pytest

from research.scripts import coastal_four128_mask_topology as topo
from tests.unit.test_coastal_four128_budget import V7_LIMITS
from tests.unit.test_coastal_four128_mask_topology import synthetic_amendment


class FakeDataset:
    driver = 'BAG'
    count = 2
    height, width = topo.GRID_SHAPE
    transform = [2.0, 0.0, 721091.0, 0.0, -2.0, 3826155.0, 0.0, 0.0, 1.0]
    nodatavals = (1000000.0, 1000000.0)

    def __init__(self, masked):
        self.masked = masked  # {(col,row): [(band, r, c), ...]}
        self.reads = []
        self.closed = False

    def read(self, band, *, window, masked):
        assert masked is True
        key = (int(window.col_off), int(window.row_off))
        self.reads.append((band, key, int(window.width), int(window.height)))
        values = np.full((128, 128), -30.0 if band == 1 else 0.3, dtype='float32')
        mask = np.zeros((128, 128), dtype=bool)
        for b, r, c in self.masked.get(key, []):
            if b == band:
                mask[r, c] = True
                values[r, c] = 1000000.0
        return np.ma.MaskedArray(values, mask=mask)

    def close(self):
        self.closed = True


A, B, C, D = [tuple(w[:2]) for w in topo.WINDOWS]
HOLES = {A: [(1, 60, 60), (2, 60, 61), (1, 61, 60), (1, 0, 5)],  # enclosed 3 + a border notch
         B: [(1, 0, 0), (2, 127, 127)],                         # border only
         C: [(1, 40, 40), (1, 41, 41)],                          # two 4-holes, one 8-hole
         D: [(2, 127, 3)]}                                        # border only


def run(tmp_path, monkeypatch, masked):
    monkeypatch.setattr(topo, 'OPENS', [])
    monkeypatch.setattr(topo, '_ledger_limits', lambda raw: dict(V7_LIMITS))
    dataset = FakeDataset(masked)
    opened = []

    def opener(path):
        opened.append(path)
        return dataset
    result = topo.scan(synthetic_amendment(tmp_path), 'c' * 40, project=tmp_path, opener=opener,
                       envelope=lambda: dict(cgroup='/test.service', readings={'memory.max': '1073741824', 'pids.max': '32'}),
                       git=lambda head: head)
    return result, dataset, opened


def test_one_open_exact_windows_and_a_verifiable_receipt(tmp_path, monkeypatch):
    result, dataset, opened = run(tmp_path, monkeypatch, HOLES)
    assert opened == [str(tmp_path / topo.SOURCE_RELATIVE)] and result['opens'] == 1
    assert dataset.closed is True
    assert sorted(dataset.reads) == sorted((band, key, 128, 128) for key in (A, B, C, D) for band in (1, 2))
    path = tmp_path / 'outputs/sc5-partial-20261020p1-prescan' / topo.RECEIPT_NAME
    assert result['receipt'] == str(path)
    raw = path.read_bytes()
    assert len(raw) <= topo.RECEIPT_MAX_BYTES and result['sha256'] == topo.digest(raw)
    doc = json.loads(raw)
    assert doc['status'] == 'TOPOLOGY_RECORDED_REVIEW_REQUIRED' and doc['scientific_acceptance'] is False
    assert doc['source']['sha256_recomputed'] is False and doc['source']['metadata_pass'] is False
    assert doc['budget']['sc5_geometry_prescan_charged_bytes'] == 36757568
    assert doc['budget']['remaining_run_allowance_bytes'] == 8 * 36757568
    assert (doc['network_requests'], doc['downloads'], doc['cash_usd'], doc['managed_mission_writes']) == (0, 0, 0, 0)
    a, b, c, d = doc['windows']
    assert (a['unsupported_cells'], b['unsupported_cells'], c['unsupported_cells'], d['unsupported_cells']) == (4, 2, 2, 1)
    assert a['elevation_mask_invalid'] == 3 and a['uncertainty_mask_invalid'] == 1
    assert a['topology_4']['enclosed_regions'] == 1 and a['topology_4']['border_regions'] == 1
    assert b['topology_4']['enclosed_regions'] == 0 and d['topology_4']['enclosed_regions'] == 0
    assert (c['topology_4']['enclosed_regions'], c['topology_8']['enclosed_regions']) == (2, 1)
    assert doc['require_holes']['met'] is True
    assert [x['equal'] for x in doc['count_only_comparison']] == [False] * 4  # synthetic counts differ
    assert topo.verify_receipt(doc)['met'] is True
    # No rerun: the preserved output root refuses before any second open.
    with pytest.raises(ValueError, match='preserve it'):
        run(tmp_path, monkeypatch, HOLES)
    assert path.read_bytes() == raw


def test_border_notches_only_are_recorded_and_fail_the_gate(tmp_path, monkeypatch):
    notches = {key: [(1, 0, 7)] for key in (A, B, C, D)}
    result, _, opened = run(tmp_path, monkeypatch, notches)
    assert len(opened) == 1
    assert result['require_holes']['met'] is False
    assert 'no enclosed' in result['require_holes']['reasons'][0]
    doc = json.loads((tmp_path / 'outputs/sc5-partial-20261020p1-prescan' / topo.RECEIPT_NAME).read_text())
    assert all(w['unsupported_cells'] == 1 for w in doc['windows'])  # counts alone would have passed


def test_wrong_grid_refuses_without_writing(tmp_path, monkeypatch):
    class Wrong(FakeDataset):
        height = 10000
    monkeypatch.setattr(topo, 'OPENS', [])
    monkeypatch.setattr(topo, '_ledger_limits', lambda raw: dict(V7_LIMITS))
    with pytest.raises(ValueError, match='grid'):
        topo.scan(synthetic_amendment(tmp_path), 'c' * 40, project=tmp_path, opener=lambda p: Wrong({}),
                  envelope=lambda: {}, git=lambda head: head)
    assert not (tmp_path / 'outputs').exists()
