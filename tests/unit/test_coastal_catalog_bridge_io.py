"""Catalog bridge: frozen JSON is fully written even under short writes."""
import hashlib
import json
import os

import pytest

from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.http import Allowlist
from tests import _coastal_catalog_fixture as fx

ALLOW = Allowlist([fx.HOST])


@pytest.fixture
def world(tmp_path):
    root = tmp_path / "queue"
    root.mkdir()
    source = fx.cache_file(root, "sources/H11952_MB_2m_MLLW_1of1.bag")
    rows = [fx.candidate("H11952_MB_2m_MLLW_1of1.bag", size=source["bytes"], source_hash=source["sha256"])]
    catalog = fx.frozen_catalog(rows)
    path = tmp_path / "catalog.json"
    sha = fx.write_catalog(path, catalog)
    sel = fx.selection(rows[0]["source_id"], source)
    return dict(root=root, tmp=tmp_path, path=path, plan=fx.plan(catalog, sha, [sel]))


def limit_writes(monkeypatch, sizes):
    """Real os.write limited to cycling positive chunk sizes; records (requested, actual)."""
    real = os.write
    calls = []

    def write(fd, data):
        n = real(fd, bytes(data)[:sizes[len(calls) % len(sizes)]])
        calls.append((len(data), n))
        return n
    monkeypatch.setattr(os, "write", write)
    return calls


def oracle(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


@pytest.mark.parametrize("sizes", [[1], [7], [17], [1, 7, 17, 3]])
def test_freeze_multiple_short_writes_preserves_exact_json(tmp_path, monkeypatch, sizes):
    value = dict(a=list(range(40)), b="text" * 20)
    calls = limit_writes(monkeypatch, sizes)
    raw = bridge._freeze(tmp_path / "f.json", value)
    assert raw == oracle(value)
    assert (tmp_path / "f.json").read_bytes() == raw
    assert not os.stat(tmp_path / "f.json").st_mode & 0o222
    assert len(calls) > 1 and calls[0][0] == len(raw)
    assert calls[1][0] == len(raw) - calls[0][1]  # the remaining suffix, not the prefix


def test_freeze_zero_progress_fails_without_spin(tmp_path, monkeypatch):
    calls, closed, synced = [], [], []
    monkeypatch.setattr(os, "write", lambda fd, data: calls.append(1) or 0)
    real_close = os.close
    monkeypatch.setattr(os, "close", lambda fd: closed.append(fd) or real_close(fd))
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd))
    with pytest.raises(OSError):
        bridge._freeze(tmp_path / "f.json", {"a": 1})
    assert calls == [1] and len(closed) == 1 and synced == []


@pytest.mark.parametrize("result", [0, -1])
def test_freeze_no_progress_after_prefix_preserves_evidence(tmp_path, monkeypatch, result):
    real, calls, synced = os.write, [], []

    def write(fd, data):
        calls.append(1)
        return real(fd, bytes(data)[:5]) if len(calls) == 1 else result
    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd))
    value = dict(a="x" * 30)
    with pytest.raises(OSError):
        bridge._freeze(tmp_path / "f.json", value)
    assert (tmp_path / "f.json").read_bytes() == oracle(value)[:5]
    assert len(calls) == 2 and synced == []


def test_freeze_error_after_prefix_propagates(tmp_path, monkeypatch):
    real, calls, closed = os.write, [], []
    boom = OSError(28, "disk full")

    def write(fd, data):
        calls.append(1)
        if len(calls) == 1:
            return real(fd, bytes(data)[:4])
        raise boom
    monkeypatch.setattr(os, "write", write)
    real_close = os.close
    monkeypatch.setattr(os, "close", lambda fd: closed.append(fd) or real_close(fd))
    with pytest.raises(OSError) as info:
        bridge._freeze(tmp_path / "f.json", {"a": "y" * 30})
    assert info.value is boom and len(closed) == 1
    assert len((tmp_path / "f.json").read_bytes()) == 4


def test_freeze_fsync_failure_is_failure(tmp_path, monkeypatch):
    boom = OSError(5, "io")

    def fsync(fd):
        raise boom
    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(OSError) as info:
        bridge._freeze(tmp_path / "f.json", {"a": 1})
    assert info.value is boom
    assert (tmp_path / "f.json").read_bytes() == oracle({"a": 1})


def test_run_partial_progress_returns_truthful_job_and_receipt_refs(world, monkeypatch):
    limit_writes(monkeypatch, [17])
    receipt = bridge.run(world["root"], world["path"], world["plan"], world["root"] / "bridge", allowlist=ALLOW)
    refs = [j["input_manifest"] for j in receipt["jobs"]] + [receipt["output"]]
    assert len(refs) == 2
    for ref in refs:
        data = (world["root"] / ref["path"]).read_bytes()
        json.loads(data)
        assert len(data) == ref["bytes"] and hashlib.sha256(data).hexdigest() == ref["sha256"]
        assert not os.stat(world["root"] / ref["path"]).st_mode & 0o222


def test_dry_run_partial_progress_keeps_single_complete_receipt(world, monkeypatch):
    limit_writes(monkeypatch, [13])
    receipt = bridge.dry_run(world["root"], world["path"], world["plan"], world["tmp"] / "dry", allowlist=ALLOW)
    files = sorted(p.name for p in (world["tmp"] / "dry").iterdir())
    assert files == ["bridge-dry-run-receipt.json"]
    data = (world["tmp"] / "dry" / files[0]).read_bytes()
    assert len(data) == receipt["output"]["bytes"]
    assert hashlib.sha256(data).hexdigest() == receipt["output"]["sha256"]
    stored = json.loads(data)
    assert stored == {k: v for k, v in receipt.items() if k != "output"}
    assert not os.stat(world["tmp"] / "dry" / files[0]).st_mode & 0o222


def test_run_write_failure_stops_before_success_receipt(world, monkeypatch):
    real, calls = os.write, []

    def write(fd, data):
        calls.append(1)
        return real(fd, bytes(data)[:6]) if len(calls) == 1 else 0
    monkeypatch.setattr(os, "write", write)
    out = world["root"] / "bridge"
    with pytest.raises(OSError):
        bridge.run(world["root"], world["path"], world["plan"], out, allowlist=ALLOW)
    assert [p.name for p in out.iterdir()] == ["native-job-00.json"]
    assert len((out / "native-job-00.json").read_bytes()) == 6
    monkeypatch.undo()
    with pytest.raises(ValueError, match="never reused"):
        bridge.run(world["root"], world["path"], world["plan"], out, allowlist=ALLOW)


def test_existing_target_and_normal_write_unchanged(world, tmp_path, monkeypatch):
    target = tmp_path / "keep.json"
    target.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        bridge._freeze(target, {"a": 1})
    assert target.read_bytes() == b"old"
    plain = bridge.dry_run(world["root"], world["path"], world["plan"], world["tmp"] / "d1", allowlist=ALLOW)
    limit_writes(monkeypatch, [11])
    short = bridge.dry_run(world["root"], world["path"], world["plan"], world["tmp"] / "d2", allowlist=ALLOW)
    assert plain == short
    assert ((world["tmp"] / "d1" / "bridge-dry-run-receipt.json").read_bytes()
            == (world["tmp"] / "d2" / "bridge-dry-run-receipt.json").read_bytes())
    assert not os.stat(world["tmp"] / "d1" / "bridge-dry-run-receipt.json").st_mode & 0o222
