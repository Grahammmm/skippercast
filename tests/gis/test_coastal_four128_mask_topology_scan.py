"""SC-5b mask-topology pre-scan, end to end on a fake one-open dataset.

The fake stands in for the GDAL BAG dataset (numpy masked reads); the cached
H11952 BAG is never opened, hashed or stat'ed here.
"""
import json
import os
import signal
import subprocess
import sys

import numpy as np
import pytest

from research.scripts import coastal_four128_mask_topology as topo
from tests._support import ROOT
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
                       git=lambda head: head, guard=lambda: [])
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
    # The durable claim made before the open is bound into the receipt and kept.
    out = tmp_path / 'outputs/sc5-partial-20261020p1-prescan'
    claim = (out / topo.CLAIM_NAME).read_bytes()
    assert doc['attempt'] == dict(name=topo.CLAIM_NAME, sha256=topo.digest(claim), bytes=len(claim))
    assert json.loads(claim)['code_head'] == 'c' * 40
    assert sorted(p.name for p in out.iterdir()) == [topo.CLAIM_NAME, topo.RECEIPT_NAME]
    assert len(claim) + topo.FAILURE_MAX_BYTES + len(raw) <= topo.RECEIPT_MAX_BYTES
    # No rerun: the preserved output root refuses before any second open.
    with pytest.raises(ValueError, match='preserve it'):
        run(tmp_path, monkeypatch, HOLES)
    assert path.read_bytes() == raw and (out / topo.CLAIM_NAME).read_bytes() == claim


def test_border_notches_only_are_recorded_and_fail_the_gate(tmp_path, monkeypatch):
    notches = {key: [(1, 0, 7)] for key in (A, B, C, D)}
    result, _, opened = run(tmp_path, monkeypatch, notches)
    assert len(opened) == 1
    assert result['require_holes']['met'] is False
    assert 'no enclosed' in result['require_holes']['reasons'][0]
    doc = json.loads((tmp_path / 'outputs/sc5-partial-20261020p1-prescan' / topo.RECEIPT_NAME).read_text())
    assert all(w['unsupported_cells'] == 1 for w in doc['windows'])  # counts alone would have passed


def test_wrong_grid_consumes_the_claimed_attempt_without_a_receipt(tmp_path, monkeypatch):
    class Wrong(FakeDataset):
        height = 10000
    monkeypatch.setattr(topo, 'OPENS', [])
    monkeypatch.setattr(topo, '_ledger_limits', lambda raw: dict(V7_LIMITS))
    with pytest.raises(ValueError, match='grid'):
        topo.scan(synthetic_amendment(tmp_path), 'c' * 40, project=tmp_path, opener=lambda p: Wrong({}),
                  envelope=lambda: {}, git=lambda head: head, guard=lambda: [])
    out = tmp_path / 'outputs' / topo.OUTPUT_NAME
    assert sorted(p.name for p in out.iterdir()) == [topo.CLAIM_NAME, topo.FAILURE_NAME]
    assert json.loads((out / topo.FAILURE_NAME).read_text())['phase'] == 'read'
    monkeypatch.setattr(topo, 'OPENS', [])  # as a fresh process
    opened = []
    with pytest.raises(ValueError, match='preserve it'):
        topo.scan(synthetic_amendment(tmp_path), 'c' * 40, project=tmp_path, opener=opened.append,
                  envelope=lambda: {}, git=lambda head: head, guard=lambda: [])
    assert opened == []


def test_a_racer_past_the_absence_check_loses_at_the_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(topo, 'OPENS', [])
    monkeypatch.setattr(topo, '_ledger_limits', lambda raw: dict(V7_LIMITS))
    out = tmp_path / 'outputs' / topo.OUTPUT_NAME
    topo.claim_attempt(out, dict(winner=True))
    monkeypatch.setattr(topo, 'output_root', lambda project: out)  # both passed the check
    opened = []
    with pytest.raises(ValueError, match='already claimed'):
        topo.scan(synthetic_amendment(tmp_path), 'c' * 40, project=tmp_path, opener=opened.append,
                  envelope=lambda: {}, git=lambda head: head, guard=lambda: [])
    assert opened == [] and json.loads((out / topo.CLAIM_NAME).read_text())['winner'] is True
    assert not (out / topo.FAILURE_NAME).exists()


# ------------------------------------------------------- fresh processes / faults

DRIVER = r'''
import json, os, signal, sys, time
from pathlib import Path
from research.scripts import coastal_four128_mask_topology as topo
from tests.gis.test_coastal_four128_mask_topology_scan import FakeDataset, HOLES
from tests.unit.test_coastal_four128_budget import V7_LIMITS
mode, project, amendment, calls, gate = sys.argv[1:6]
topo._ledger_limits = lambda raw: dict(V7_LIMITS)

def note():
    fd = os.open(calls, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.write(fd, (mode + '\n').encode())
    os.close(fd)

class BrokenRead(FakeDataset):
    def read(self, *a, **k):
        raise OSError('synthetic read failure after the open')

def opener(path):
    note()
    if mode == 'open-fails':
        raise OSError('synthetic failure after the open attempt')
    if mode == 'killed':
        os.kill(os.getpid(), signal.SIGKILL)
    if mode == 'read-fails':
        return BrokenRead({})
    if mode == 'slow':
        time.sleep(0.5)
    return FakeDataset(HOLES)

def broken(*a, **k):
    raise OSError('synthetic failure before the receipt write')
if mode == 'verify-fails':
    topo.verify_receipt = broken
if mode == 'receipt-fails':
    topo.write_receipt = broken
while gate != '-' and not Path(gate).exists():
    time.sleep(0.01)
try:
    result = topo.scan(amendment, 'c' * 40, project=project, opener=opener, envelope=lambda: {},
                       git=lambda h: h, guard=lambda: [])
except Exception as exc:
    print(json.dumps(dict(ok=False, error=str(exc))))
    sys.exit(3)
print(json.dumps(dict(ok=True, status=result['status'])))
'''


def spawn(tmp_path, mode, gate='-'):
    # Driver and amendment are written once: rewriting them while an earlier racer
    # starts up would hand it a truncated file.
    script, amendment = tmp_path / 'driver.py', tmp_path / 'amendment.json'
    if not script.exists():
        script.write_text(DRIVER)
        synthetic_amendment(tmp_path)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT) + os.pathsep + str(ROOT / 'src'))
    argv = [sys.executable, '-B', str(script), mode, str(tmp_path), str(amendment),
            str(tmp_path / 'opener-calls'), gate]
    return subprocess.Popen(argv, env=env, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def finish(proc):
    out, err = proc.communicate(timeout=120)
    return proc.returncode, (json.loads(out.strip().splitlines()[-1]) if out.strip() else None), err


@pytest.mark.parametrize('mode, phase', [('open-fails', 'open'), ('read-fails', 'read'),
                                         ('verify-fails', 'receipt'), ('receipt-fails', 'receipt'),
                                         ('killed', None)])
def test_a_failed_or_killed_attempt_is_never_retried_by_a_fresh_process(tmp_path, mode, phase):
    code, result, err = finish(spawn(tmp_path, mode))
    out = tmp_path / 'outputs' / topo.OUTPUT_NAME
    claim = (out / topo.CLAIM_NAME).read_bytes()
    assert json.loads(claim)['status'] == 'ATTEMPT_CLAIMED_SOLE_OPEN_CONSUMED'
    assert not (out / topo.RECEIPT_NAME).exists()
    if phase is None:
        assert code == -signal.SIGKILL and not (out / topo.FAILURE_NAME).exists()
    else:
        assert code == 3 and result['ok'] is False, err
        failure = json.loads((out / topo.FAILURE_NAME).read_text())
        assert failure['phase'] == phase and failure['status'] == 'ATTEMPT_FAILED_CLAIM_RETAINED'
        assert failure['opens'] == 1 and failure['refund'] is False and failure['retry'] is False
    # A fresh process with a healthy dataset refuses before touching the source.
    code, result, err = finish(spawn(tmp_path, 'ok'))
    assert code == 3 and 'preserve it' in result['error'], err
    assert (tmp_path / 'opener-calls').read_text().splitlines() == [mode]
    assert (out / topo.CLAIM_NAME).read_bytes() == claim


def test_concurrent_invocations_open_the_source_once(tmp_path):
    gate = tmp_path / 'start'
    procs = [spawn(tmp_path, 'slow', str(gate)) for _ in range(4)]
    gate.write_text('go')
    results = [finish(p) for p in procs]
    assert all(r is not None for _, r, _ in results), results  # every racer reached scan()
    winners = [r for code, r, _ in results if code == 0 and r['ok']]
    losers = [r for code, r, _ in results if code == 3]
    assert len(winners) == 1 and len(losers) == 3, results
    assert all('preserve it' in r['error'] or 'already claimed' in r['error'] for r in losers)
    assert (tmp_path / 'opener-calls').read_text().splitlines() == ['slow']
    out = tmp_path / 'outputs' / topo.OUTPUT_NAME
    assert sorted(p.name for p in out.iterdir()) == [topo.CLAIM_NAME, topo.RECEIPT_NAME]
