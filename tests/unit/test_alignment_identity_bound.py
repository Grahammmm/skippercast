"""Alignment identity enforces its byte ceiling while hashing (RF0440-8)."""
import hashlib
from pathlib import Path

import pytest

from skippercast.coastal.render import align, preview

REAL_OPEN = Path.open


class Spy:
    """Forward a real unbuffered stream, recording requests and returns."""

    def __init__(self, stream, on_read=None):
        self.stream, self.on_read = stream, on_read
        self.requests, self.returned, self.closed_after = [], 0, False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stream.close()

    def fileno(self):
        return self.stream.fileno()

    def read(self, n):
        self.requests.append(n)
        if self.on_read:
            self.on_read(len(self.requests))
        block = self.stream.read(n)
        self.returned += len(block)
        return block


def install(monkeypatch, before_open=None, on_read=None):
    spies = []

    def fake_open(self, mode="r", buffering=-1, *a, **k):
        if mode != "rb" or not getattr(self, "_probe", True):
            return REAL_OPEN(self, mode, buffering, *a, **k)
        if before_open:
            before_open(self)
        spy = Spy(REAL_OPEN(self, mode, buffering=0), on_read)
        spies.append(spy)
        return spy

    monkeypatch.setattr(Path, "open", fake_open)
    return spies


def append(path, data):
    with REAL_OPEN(path, "ab") as f:
        f.write(data)


def test_growth_after_admission_refuses_identity_and_verified_path(tmp_path, monkeypatch):
    monkeypatch.setattr(align, "MAX_FILE_BYTES", 8)
    target = tmp_path / "a.bin"
    target.write_bytes(b"abcd")
    grown = b"abcd" + b"x" * 10
    install(monkeypatch, before_open=lambda p: append(p, b"x" * 10))
    with pytest.raises(ValueError, match="artifact_byte_bound"):
        align.identity(target)
    target.write_bytes(b"abcd")
    ref = {"path": "a.bin", "sha256": hashlib.sha256(grown).hexdigest(), "bytes": len(grown)}
    with pytest.raises(ValueError, match="artifact_byte_bound"):
        preview.verified_path(tmp_path, ref)


def test_actual_consumption_stops_at_cap_plus_one(tmp_path, monkeypatch):
    monkeypatch.setattr(align, "MAX_FILE_BYTES", 8)
    target = tmp_path / "a.bin"
    target.write_bytes(b"12345")
    updates = []
    real_sha = hashlib.sha256

    class Digest:
        def __init__(self):
            self.d = real_sha()

        def update(self, b):
            updates.append(len(b))
            self.d.update(b)

    monkeypatch.setattr(align.hashlib, "sha256", Digest)
    spies = install(monkeypatch, on_read=lambda i: append(target, b"z" * 100) if i == 1 else None)
    with pytest.raises(ValueError, match="artifact_byte_bound"):
        align.identity(target)
    spy = spies[0]
    assert all(0 < n <= 9 for n in spy.requests)
    assert spy.requests[0] == 9
    assert spy.returned <= 9
    assert sum(updates) <= 8
    assert len(spy.requests) <= 2


@pytest.mark.parametrize("cap", [4, 1024 * 1024 + 3])
def test_empty_minus_one_exact_and_plus_one(tmp_path, monkeypatch, cap):
    monkeypatch.setattr(align, "MAX_FILE_BYTES", cap)
    for size in (0, cap - 1, cap):
        p = tmp_path / f"f{size}"
        data = bytes(i % 251 for i in range(size))
        p.write_bytes(data)
        assert align.identity(p) == {"sha256": hashlib.sha256(data).hexdigest(), "bytes": size}
    over = tmp_path / "over"
    over.write_bytes(b"\0" * (cap + 1))
    with pytest.raises(ValueError, match="artifact_byte_bound"):
        align.identity(over)


def test_short_reads_and_legal_growth_remain_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(align, "MAX_FILE_BYTES", 20)
    target = tmp_path / "a.bin"
    target.write_bytes(b"0123456789")
    spies = []

    def fake_open(self, mode="r", buffering=-1, *a, **k):
        if mode != "rb" or not getattr(self, "_probe", True):
            return REAL_OPEN(self, mode, buffering, *a, **k)
        real = REAL_OPEN(self, mode, buffering=0)

        class Short(Spy):
            def read(s, n):
                return super().read(min(n, 3))

        spy = Short(real, lambda i: append(target, b"AB") if i == 1 else None)
        spies.append(spy)
        return spy

    monkeypatch.setattr(Path, "open", fake_open)
    got = align.identity(target)
    data = rb(target)
    assert data == b"0123456789AB"
    assert got == {"sha256": hashlib.sha256(data).hexdigest(), "bytes": 12}


def test_path_replacement_after_read_does_not_mix_identity_fields(tmp_path, monkeypatch):
    target = tmp_path / "a.bin"
    target.write_bytes(b"original")
    replacement = tmp_path / "other.bin"
    replacement.write_bytes(b"x" * 50)
    state = {"n": 0}

    def swap(i):
        state["n"] = i
        if i == 2:  # EOF read: bytes already consumed
            replacement.replace(target)

    install(monkeypatch, on_read=swap)
    got = align.identity(target)
    assert got == {"sha256": hashlib.sha256(b"original").hexdigest(), "bytes": 8}
    assert rb(target) == b"x" * 50


def test_resources_and_existing_errors_preserved(tmp_path, monkeypatch):
    target = tmp_path / "a.bin"
    target.write_bytes(b"hello")
    ref = {"path": "a.bin", "sha256": hashlib.sha256(b"hello").hexdigest(), "bytes": 5}
    assert preview.verified_path(tmp_path, ref) == target.resolve()
    with pytest.raises(ValueError, match="artifact_identity_mismatch"):
        preview.verified_path(tmp_path, {**ref, "sha256": "0" * 64})
    with pytest.raises(ValueError, match="artifact_byte_bound"):
        align.identity(tmp_path)
    with pytest.raises(ValueError, match="artifact_byte_bound"):
        align.identity(tmp_path / "missing")

    spies = install(monkeypatch)
    align.identity(target)
    assert spies[0].stream.closed

    monkeypatch.setattr(align, "MAX_FILE_BYTES", 3)
    with pytest.raises(ValueError, match="artifact_byte_bound"):
        align.identity(target)
    assert spies[1].stream.closed and spies[1].requests == []

    monkeypatch.setattr(align, "MAX_FILE_BYTES", 8)
    grow = tmp_path / "g.bin"
    grow.write_bytes(b"ab")
    spies = install(monkeypatch, on_read=lambda i: append(grow, b"c" * 20))
    with pytest.raises(ValueError, match="artifact_byte_bound"):
        align.identity(grow)
    assert spies[0].stream.closed

    def boom(i):
        raise OSError("read failed")

    spies = install(monkeypatch, on_read=boom)
    with pytest.raises(OSError, match="read failed"):
        align.identity(target)
    assert spies[0].stream.closed


def rb(path):
    with REAL_OPEN(path, "rb") as f:
        return f.read()
