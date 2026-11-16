"""Unreadable retention directories refuse audit/settlement instead of counting zero bytes."""
import os
from pathlib import Path

import pytest

from skippercast.coastal.retention import Retention, LIMITS

REAL_SCANDIR = os.scandir


def make(tmp_path):
    retention = Retention.create(tmp_path, 'plan')
    retention.reserve('mapping', 'intent', 'outputs/mapping', role='mapping')
    target = tmp_path / 'outputs' / 'mapping'
    target.mkdir(parents=True)
    (target / 'a.bin').write_bytes(b'x' * 123)
    return retention, target


def fail_on(monkeypatch, failing):
    reached = []

    def scandir(path='.'):
        if Path(path) == failing:
            reached.append(path)
            raise PermissionError(13, 'denied', str(path))
        return REAL_SCANDIR(path)
    monkeypatch.setattr(os, 'scandir', scandir)
    return reached


def test_unreadable_reserved_subtree_is_not_zero_byte_success(tmp_path, monkeypatch):
    retention, target = make(tmp_path)
    assert retention.audit()['slots']['mapping'] == 123
    reached = fail_on(monkeypatch, target)
    with pytest.raises(ValueError, match='incomplete retention directory scan') as info:
        retention.audit()
    assert reached
    assert isinstance(info.value.__cause__, PermissionError)


@pytest.mark.parametrize('completed', [True, False])
@pytest.mark.parametrize('prior', ['reserved', 'uncertain'])
def test_failed_scan_never_persists_settlement(tmp_path, monkeypatch, completed, prior):
    retention, target = make(tmp_path)
    if prior == 'uncertain':
        retention.settle('mapping', completed=False)
    before_bytes = retention.path.read_bytes()
    before_entry = retention.read()['reservations']['mapping']
    reached = fail_on(monkeypatch, target)
    with pytest.raises(ValueError, match='incomplete retention directory scan'):
        retention.settle('mapping', completed=completed)
    assert reached
    assert retention.path.read_bytes() == before_bytes
    after = retention.read()['reservations']['mapping']
    assert after == before_entry
    assert after['state'] == prior
    assert ('observed_bytes' in after) == (prior == 'uncertain')


def test_unreadable_control_or_intermediate_directory_refuses(tmp_path, monkeypatch):
    retention, _ = make(tmp_path)
    (tmp_path / 'ctl').mkdir()
    (tmp_path / 'ctl' / 'c.bin').write_bytes(b'c' * 5)
    reached = fail_on(monkeypatch, tmp_path / 'ctl')
    with pytest.raises(ValueError, match='incomplete retention directory scan'):
        retention.audit()
    assert reached
    monkeypatch.undo()
    reached = fail_on(monkeypatch, tmp_path / 'outputs')
    with pytest.raises(ValueError, match='incomplete retention directory scan'):
        retention.audit()
    assert reached


def test_root_scan_failure_refuses(tmp_path, monkeypatch):
    retention, _ = make(tmp_path)
    reached = fail_on(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match='incomplete retention directory scan'):
        retention.audit()
    assert reached


def test_healthy_scan_and_retry_preserve_accounting(tmp_path, monkeypatch):
    retention, target = make(tmp_path)
    base = retention.audit()['control_bytes']  # ledger + lock files count as control
    (tmp_path / 'ctl.bin').write_bytes(b'c' * 7)
    audit = retention.audit()
    assert (audit['slots']['mapping'], audit['control_bytes'] - base, audit['observed_bytes']) == (
        123, 7, 130 + base)
    reached = fail_on(monkeypatch, target)
    with pytest.raises(ValueError):
        retention.settle('mapping', completed=True)
    assert reached
    monkeypatch.undo()
    retention.settle('mapping', completed=True)
    state = retention.read()
    entry = state['reservations']['mapping']
    assert (entry['state'], entry['observed_bytes'], entry['bytes']) == ('complete', 123, LIMITS['mapping'])
    assert list(state['reservations']) == ['mapping']


def test_existing_unsafe_leaf_and_cap_refusals_remain(tmp_path):
    retention, target = make(tmp_path)
    (target / 'link').symlink_to(target / 'a.bin')
    with pytest.raises(ValueError, match='single-link regular'):
        retention.audit()
    (target / 'link').unlink()
    os.link(target / 'a.bin', target / 'b.bin')
    with pytest.raises(ValueError, match='single-link regular'):
        retention.audit()
    (target / 'b.bin').unlink()
    (target / 'big.bin').write_bytes(b'x' * (LIMITS['mapping'] + 1))
    with pytest.raises(ValueError, match='ceiling exceeded'):
        retention.audit()
