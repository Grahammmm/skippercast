"""SC-RIGHTS-DELTA write/fsync failure rollback: a report this call created is removed again.

Only the write, fsync, close, open and unlink syscalls of the report path are fault-injected;
inputs are the frozen synthetic fixture pair and every path lives under tmp_path.
"""
import errno
import json
import os
import stat

import pytest

from scripts.coast_diagnostics import rights_delta as rd
from tests._support import ROOT

FIXTURES = ROOT / "tests" / "fixtures" / "sc_rights_delta"
LEFT = FIXTURES / "observation_left.json"
RIGHT = FIXTURES / "observation_right.json"
EXPECTED = (FIXTURES / "expected_delta.json").read_bytes()
CLEANUP_FAILED = "output cleanup failed; incomplete report may remain"
REPLACEMENT_KEPT = "output changed during cleanup; replacement preserved"


class Faults:
    """Wrap the os syscalls for the one report path; every other descriptor passes through."""

    def __init__(self, monkeypatch, target):
        self.target = str(target)
        self.fd = None
        self.closes = 0
        self.unlinks = []
        self.on_write = None  # called with (fd, view) in place of the real write
        self.on_fsync = None
        self.on_close = None  # called after the real close
        self.on_open = None   # called before the real open
        self.on_unlink = None
        real = {name: getattr(os, name) for name in ("open", "write", "fsync", "close", "unlink")}
        self.real = real

        def open_(path, *args, **kwargs):
            if str(path) == self.target and self.on_open:
                self.on_open()
            fd = real["open"](path, *args, **kwargs)
            if str(path) == self.target:
                self.fd = fd
            return fd

        def write(fd, view):
            if fd == self.fd and self.on_write:
                return self.on_write(fd, view)
            return real["write"](fd, view)

        def fsync(fd):
            if fd == self.fd and self.on_fsync:
                return self.on_fsync(fd)
            return real["fsync"](fd)

        def close(fd):
            if fd != self.fd:
                return real["close"](fd)
            self.closes += 1
            self.fd = None  # the number may be reused by later opens
            real["close"](fd)
            if self.on_close:
                self.on_close()

        def unlink(path, *args, **kwargs):
            if str(path) == self.target:
                self.unlinks.append(str(path))
                if self.on_unlink:
                    return self.on_unlink(path)
            return real["unlink"](path, *args, **kwargs)

        for name, fn in (("open", open_), ("write", write), ("fsync", fsync), ("close", close), ("unlink", unlink)):
            monkeypatch.setattr(os, name, fn)


def _cli(out):
    return rd.main(["--left", str(LEFT), "--right", str(RIGHT), "--out", str(out)])


def _fail(code):
    def raiser(*_args):
        raise OSError(code, os.strerror(code))
    return raiser


def _short_write_then_enospc(faults):
    calls = []

    def write(fd, view):
        calls.append(len(view))
        if len(calls) == 1:
            return faults.real["write"](fd, bytes(view[:11]))
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
    return write


def _inputs():
    return LEFT.read_bytes(), RIGHT.read_bytes()


def test_write_failure_removes_partial_new_output_and_allows_retry(tmp_path, monkeypatch, capsys):
    out = tmp_path / "delta.json"
    before = _inputs()
    faults = Faults(monkeypatch, out)
    faults.on_write = _short_write_then_enospc(faults)
    assert _cli(out) == 4
    assert json.loads(capsys.readouterr().err)["detail"] == "OSError"
    assert not out.exists() and faults.closes == 1
    monkeypatch.undo()
    assert _cli(out) == 0
    assert out.read_bytes() == EXPECTED
    assert _inputs() == before


def test_fsync_failure_removes_complete_looking_new_output(tmp_path, monkeypatch):
    out = tmp_path / "delta.json"
    faults = Faults(monkeypatch, out)
    seen = []

    def fsync(fd):
        seen.append(os.fstat(fd).st_size)
        raise OSError(errno.EIO, os.strerror(errno.EIO))
    faults.on_fsync = fsync
    assert _cli(out) == 4
    assert seen == [len(EXPECTED)] and not out.exists() and faults.closes == 1
    monkeypatch.undo()
    assert _cli(out) == 0
    assert out.read_bytes() == EXPECTED


def test_failure_before_first_write_closes_and_rolls_back(tmp_path, monkeypatch):
    out = tmp_path / "delta.json"
    faults = Faults(monkeypatch, out)
    faults.on_write = _fail(errno.EIO)
    with pytest.raises(OSError) as raised:
        rd.write_new(out, EXPECTED)
    assert raised.value.errno == errno.EIO
    assert faults.closes == 1 and faults.unlinks == [str(out)] and not out.exists()
    assert _cli(out) == 4 and not out.exists()
    # a close failure after a complete write and fsync also rolls the new output back
    faults.on_write = None
    faults.on_close = _fail(errno.EIO)
    with pytest.raises(OSError):
        rd.write_new(out, EXPECTED)
    assert not out.exists() and faults.closes == 3
    assert _cli(out) == 4 and not out.exists()


def test_interruption_closes_and_rolls_back(tmp_path, monkeypatch):
    out = tmp_path / "delta.json"
    faults = Faults(monkeypatch, out)

    def interrupt(*_args):
        raise KeyboardInterrupt
    faults.on_write = interrupt
    with pytest.raises(KeyboardInterrupt):
        rd.write_new(out, EXPECTED)
    assert faults.closes == 1 and not out.exists()


def test_preexisting_and_racing_created_outputs_are_never_removed(tmp_path, monkeypatch):
    existing = tmp_path / "existing.json"
    existing.write_bytes(b"sentinel")
    faults = Faults(monkeypatch, existing)
    assert _cli(existing) == 4
    with pytest.raises(rd.Refused, match="output already exists"):
        rd.write_new(existing, EXPECTED)
    assert existing.read_bytes() == b"sentinel" and faults.unlinks == []

    racing = tmp_path / "racing.json"
    faults = Faults(monkeypatch, racing)
    faults.on_open = lambda: racing.write_bytes(b"arrived first")
    with pytest.raises(FileExistsError):
        rd.write_new(racing, EXPECTED)
    assert racing.read_bytes() == b"arrived first" and faults.unlinks == [] and faults.closes == 0


def test_cleanup_preserves_replaced_or_missing_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "delta.json"
    victim = tmp_path / "victim.json"
    victim.write_bytes(b"victim bytes")
    faults = Faults(monkeypatch, out)

    def replace_with_file(*_args):
        os.unlink(out)
        out.write_bytes(b"replacement")
        raise OSError(errno.ENOSPC, "no space")
    faults.on_write = replace_with_file
    with pytest.raises(rd.Refused, match=REPLACEMENT_KEPT) as raised:
        rd.write_new(out, EXPECTED)
    assert isinstance(raised.value.__cause__, OSError) and raised.value.__cause__.errno == errno.ENOSPC
    assert out.read_bytes() == b"replacement"
    out.unlink()

    def replace_with_symlink(*_args):
        os.unlink(out)
        out.symlink_to(victim)
        raise OSError(errno.ENOSPC, "no space")
    faults.on_write = replace_with_symlink
    assert _cli(out) == 4
    assert json.loads(capsys.readouterr().err)["detail"] == REPLACEMENT_KEPT
    assert out.is_symlink() and victim.read_bytes() == b"victim bytes"
    out.unlink()

    def vanish(*_args):
        os.unlink(out)
        raise OSError(errno.ENOSPC, "no space")
    faults.on_write = vanish
    with pytest.raises(OSError) as raised:
        rd.write_new(out, EXPECTED)
    assert not isinstance(raised.value, rd.Refused) and raised.value.errno == errno.ENOSPC
    assert not out.exists()


def test_cleanup_failure_is_explicit_refused_not_success(tmp_path, monkeypatch, capsys):
    out = tmp_path / "delta.json"
    faults = Faults(monkeypatch, out)
    faults.on_write = _short_write_then_enospc(faults)
    faults.on_unlink = _fail(errno.EPERM)
    with pytest.raises(rd.Refused, match=CLEANUP_FAILED) as raised:
        rd.write_new(out, EXPECTED)
    assert isinstance(raised.value.__cause__, OSError) and raised.value.__cause__.errno == errno.ENOSPC
    assert out.exists()
    faults.on_unlink = None
    out.unlink()
    faults.on_unlink = _fail(errno.EPERM)
    faults.on_write = _short_write_then_enospc(faults)
    assert _cli(out) == 4
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"detail": CLEANUP_FAILED, "schema": rd.DELTA_SCHEMA, "status": "REFUSED"}
    assert "Traceback" not in captured.err and out.exists()


def test_success_bytes_and_permissions_unchanged(tmp_path, monkeypatch):
    out = tmp_path / "delta.json"
    faults = Faults(monkeypatch, out)

    def seven_bytes_at_a_time(fd, view):
        return faults.real["write"](fd, bytes(view[:7]))
    faults.on_write = seven_bytes_at_a_time
    old_umask = os.umask(0o022)
    try:
        assert _cli(out) == 0
    finally:
        os.umask(old_umask)
    assert out.read_bytes() == EXPECTED
    assert stat.S_IMODE(out.stat().st_mode) == 0o644
    assert faults.closes == 1 and faults.unlinks == []
    assert _cli(out) == 4
    assert out.read_bytes() == EXPECTED and faults.unlinks == []
