"""Sample-report writer refuses writes that make no progress (offline, synthetic)."""
import contextlib
import json
import os

import pytest

from tests.unit.test_sc_sample_audit import audit, cli_main, focused_document, real_tmpdir

REAL_WRITE = os.write
DATA = b'{"synthetic":true}\n'


class _Sentinel(Exception):
    pass


@contextlib.contextmanager
def fake_write(returns, calls):
    """Replace os.write in the audit module only; a callable result is delegated."""
    class Double:
        def __getattr__(self, name):
            return getattr(os, name)

        def write(self, fd, view):
            calls.append(len(view))
            if len(calls) > len(returns):
                raise _Sentinel('unexpected extra write attempt')
            item = returns[len(calls) - 1]
            return item(fd, view) if callable(item) else item

    original = audit.os
    audit.os = Double()
    try:
        yield
    finally:
        audit.os = original


def _short(fd, view):
    return REAL_WRITE(fd, view[:3])


def test_zero_write_refuses_without_second_attempt():
    calls = []
    with real_tmpdir() as tmp:
        out = tmp / 'r.json'
        with fake_write([0], calls), pytest.raises(OSError, match='report write made no progress'):
            audit.write_new(str(out), DATA)
        assert calls == [19]
        assert not out.exists()


@pytest.mark.parametrize('bad', [0, -1])
def test_zero_after_partial_write_rolls_back(bad):
    calls = []
    with real_tmpdir() as tmp:
        out = tmp / 'r.json'
        with fake_write([_short, bad], calls), pytest.raises(OSError, match='no progress'):
            audit.write_new(str(out), DATA)
        assert calls == [19, 16]
        assert not out.exists()


def test_cli_zero_write_returns_refused(capsys):
    fixture, document = focused_document()
    with real_tmpdir() as tmp:
        sample = tmp / 'sample.json'
        sample.write_text(json.dumps(document), encoding='utf-8')
        before = sample.read_bytes()
        out = tmp / 'report.json'
        argv = ['--sample', str(sample), '--plan-sha256', fixture['plan_sha256'],
                '--bridge-sha256', fixture['bridge_sha256'], '--out', str(out)]
        with fake_write([0], []):
            assert cli_main(argv) == audit.EXIT_REFUSED
        captured = capsys.readouterr()
        assert 'REFUSED report write made no progress' in captured.err
        assert 'REPORTED' not in captured.out
        assert not out.exists() and sample.read_bytes() == before
        assert cli_main(argv) == 0 and out.exists()


def test_positive_short_writes_and_empty_control():
    with real_tmpdir() as tmp:
        out = tmp / 'r.json'
        calls = []
        with fake_write([_short] * 7, calls):
            assert audit.write_new(str(out), DATA) == out
        assert out.read_bytes() == DATA
        assert calls == [19, 16, 13, 10, 7, 4, 1]
        empty = tmp / 'e.json'
        calls = []
        with fake_write([], calls):
            audit.write_new(str(empty), b'')
        assert calls == [] and empty.read_bytes() == b''
