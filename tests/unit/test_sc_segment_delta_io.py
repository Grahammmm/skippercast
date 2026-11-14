"""SC-SEGMENT-DELTA report writer: non-progress writes are refused, not retried."""
import importlib.util
import os

import pytest

from tests._support import FIXTURES, ROOT

MODULE_PATH = ROOT / 'scripts' / 'coast_diagnostics' / 'segment_receipt_delta.py'
FIXTURE_DIR = FIXTURES / 'sc_segment_delta'
DATA = b'0123456789'
MAX_CALLS = 20  # a regression fails here instead of hanging


class Spin(Exception):
    pass


@pytest.fixture()
def delta():
    spec = importlib.util.spec_from_file_location('sc_segment_delta_io_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def traced(monkeypatch):
    """Intercept writes to descriptors created with O_EXCL (the report output only)."""
    state = dict(out_fds=set(), writes=[], fsyncs=0, plan=[])
    real_open, real_write, real_fsync = os.open, os.write, os.fsync

    def fake_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if flags & os.O_EXCL and kwargs.get('dir_fd') is not None:
            state['out_fds'].add(fd)
        return fd

    def fake_write(fd, data):
        if fd not in state['out_fds']:
            return real_write(fd, data)
        state['writes'].append(len(data))
        if len(state['writes']) > MAX_CALLS:
            raise Spin('write loop did not terminate')
        step = state['plan'].pop(0) if state['plan'] else None
        if step is None:
            return real_write(fd, data)
        if isinstance(step, Exception):
            raise step
        if step <= 0:
            return step
        return real_write(fd, data[:step])

    def fake_fsync(fd):
        if fd in state['out_fds']:
            state['fsyncs'] += 1
        return real_fsync(fd)

    monkeypatch.setattr(os, 'open', fake_open)
    monkeypatch.setattr(os, 'write', fake_write)
    monkeypatch.setattr(os, 'fsync', fake_fsync)
    return state


def open_fds():
    return set(os.listdir('/proc/self/fd'))


@pytest.mark.parametrize('plan,calls', [([0], 1), ([3, 0], 2), ([-1], 1), ([4, -1], 2)])
def test_nonprogress_refuses_cleans_and_does_not_retry(delta, traced, tmp_path, plan, calls):
    sibling = tmp_path / 'sibling.json'
    sibling.write_bytes(b'keep')
    traced['plan'] = list(plan)
    before = open_fds()
    with pytest.raises(OSError, match='no write progress'):
        delta.write_new(tmp_path / 'report.json', DATA)
    assert len(traced['writes']) == calls
    assert traced['fsyncs'] == 0
    assert not (tmp_path / 'report.json').exists()
    assert sibling.read_bytes() == b'keep'
    assert open_fds() == before


def test_positive_short_writes_finish_exact_bytes(delta, traced, tmp_path):
    traced['plan'] = [1, 3, 2]
    target = tmp_path / 'report.json'
    delta.write_new(target, DATA)
    assert target.read_bytes() == DATA
    assert traced['writes'] == [10, 9, 6, 4]
    assert traced['fsyncs'] == 1
    with pytest.raises(delta.InvalidReceipt, match='file exists'):
        delta.write_new(target, b'other')
    assert target.read_bytes() == DATA


def test_ordinary_write_error_after_prefix_cleans_up(delta, traced, tmp_path):
    traced['plan'] = [4, OSError(28, 'No space left')]
    before = open_fds()
    with pytest.raises(OSError, match='No space'):
        delta.write_new(tmp_path / 'report.json', DATA)
    assert traced['fsyncs'] == 0
    assert not (tmp_path / 'report.json').exists()
    assert open_fds() == before


@pytest.mark.parametrize('right', ['open-receipt.json', 'closed-receipt.json'])
def test_cli_nonprogress_is_invalid_not_success(delta, traced, tmp_path, capsys, right):
    left_path = tmp_path / 'left.json'
    right_path = tmp_path / 'right.json'
    left_path.write_bytes((FIXTURE_DIR / 'open-receipt.json').read_bytes())
    right_path.write_bytes((FIXTURE_DIR / right).read_bytes())
    sibling = tmp_path / 'sibling.json'
    sibling.write_bytes(b'keep')
    canaries = {p: p.read_bytes() for p in (left_path, right_path, sibling)}
    traced['plan'] = [0]
    code = delta.main(['--left', str(left_path), '--right', str(right_path), '--out', str(tmp_path / 'r.json')])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ''
    assert 'INVALID:' in captured.err and 'no write progress' in captured.err
    assert not (tmp_path / 'r.json').exists()
    assert {p: p.read_bytes() for p in canaries} == canaries
    assert len(traced['writes']) == 1


def test_cli_full_progress_control(delta, traced, tmp_path, capsys):
    left_path = tmp_path / 'left.json'
    left_path.write_bytes((FIXTURE_DIR / 'open-receipt.json').read_bytes())
    code = delta.main(['--left', str(left_path), '--right', str(left_path), '--out', str(tmp_path / 'r.json')])
    assert code == 0
    assert (tmp_path / 'r.json').read_bytes().endswith(b'\n')
    assert capsys.readouterr().out.startswith('{')
