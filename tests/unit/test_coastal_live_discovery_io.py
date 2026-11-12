"""Frozen discovery metadata: complete writes before a size/hash reference is returned.

Offline only: the write seam is the module's `os`, filtered to the frozen file's
descriptor; run coverage uses the existing injected synthetic opener.
"""
import hashlib
import json
import os
import socket

import pytest

from skippercast.coastal import live_discovery as ld
from tests.unit.test_coastal_live_discovery import ARCGIS, BASE, LISTING, Opener, plan, runner_for


class OsShim:
    """Stand-in for `ld.os`: short/failed writes only on files whose name matches."""

    def __init__(self, target, counts=(), fsync_error=False):
        self.target, self.counts, self.fsync_error = target, list(counts), fsync_error
        self.fds, self.closed, self.writes, self.fsyncs = set(), [], [], 0

    def __getattr__(self, name):
        return getattr(os, name)

    def open(self, path, *args):
        fd = os.open(path, *args)
        if os.path.basename(path) == self.target:
            self.fds.add(fd)
        return fd

    def write(self, fd, data):
        if fd not in self.fds:
            return os.write(fd, data)
        want = self.counts.pop(0) if self.counts else len(data)
        self.writes.append(len(data))
        if isinstance(want, Exception):
            raise want
        return os.write(fd, bytes(data[:want])) if want > 0 else want

    def fsync(self, fd):
        if fd in self.fds:
            self.fsyncs += 1
            if self.fsync_error:
                raise OSError("fsync failed")
        return os.fsync(fd)

    def close(self, fd):
        if fd in self.fds:
            self.closed.append(fd)
        return os.close(fd)


def oracle(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


VALUE = dict(schema="x", items=[f"item-{n}" for n in range(30)], note="caf\u00e9")


def use(monkeypatch, name, **kw):
    shim = OsShim(name, **kw)
    monkeypatch.setattr(ld, "os", shim)
    return shim


def test_positive_short_writes_finish_exact_buffer(tmp_path, monkeypatch):
    shim = use(monkeypatch, "f.json", counts=[7, 1, 50])
    ref = ld._freeze(tmp_path / "f.json", VALUE)
    stored = (tmp_path / "f.json").read_bytes()
    assert stored == oracle(VALUE)
    assert ref == dict(path="f.json", sha256=hashlib.sha256(stored).hexdigest(), bytes=len(stored))
    assert shim.writes[:3] == [len(stored), len(stored) - 7, len(stored) - 8] and len(shim.writes) == 4
    assert shim.fsyncs == 1 and len(shim.closed) == 1
    assert not os.stat(tmp_path / "f.json").st_mode & 0o222


@pytest.mark.parametrize("counts,kept", [([0], 0), ([-1], 0), ([7, 0], 7)])
def test_zero_and_negative_progress_refuse_promptly(tmp_path, monkeypatch, counts, kept):
    shim = use(monkeypatch, "f.json", counts=counts)
    with pytest.raises(OSError, match="no progress"):
        ld._freeze(tmp_path / "f.json", VALUE)
    assert len(shim.writes) == len(counts) and shim.fsyncs == 0 and len(shim.closed) == 1
    assert (tmp_path / "f.json").read_bytes() == oracle(VALUE)[:kept]


def test_write_and_fsync_errors_do_not_claim_success(tmp_path, monkeypatch):
    shim = use(monkeypatch, "f.json", counts=[7, OSError("disk")])
    with pytest.raises(OSError, match="disk"):
        ld._freeze(tmp_path / "f.json", VALUE)
    assert shim.fsyncs == 0 and len(shim.closed) == 1
    shim = use(monkeypatch, "g.json", fsync_error=True)
    with pytest.raises(OSError, match="fsync"):
        ld._freeze(tmp_path / "g.json", VALUE)
    assert shim.fsyncs == 1 and len(shim.closed) == 1
    (tmp_path / "h.json").write_bytes(b"keep")
    shim = use(monkeypatch, "h.json")
    with pytest.raises(FileExistsError):
        ld._freeze(tmp_path / "h.json", VALUE)
    assert (tmp_path / "h.json").read_bytes() == b"keep" and shim.closed == [] and shim.writes == []


def test_dry_run_receipt_reference_matches_real_file(tmp_path, monkeypatch):
    shim = use(monkeypatch, "dry-run-receipt.json", counts=[5, 11, 3])
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("no network"))
    receipt = ld.dry_run(plan(), tmp_path / "dry")
    stored = (tmp_path / "dry" / "dry-run-receipt.json").read_bytes()
    out = receipt["output"]
    assert out == dict(path="dry-run-receipt.json", sha256=hashlib.sha256(stored).hexdigest(), bytes=len(stored))
    saved = json.loads(stored)
    assert saved["network_requests"] == 0 and "output" not in saved
    assert len(shim.writes) == 4 and not os.stat(tmp_path / "dry" / "dry-run-receipt.json").st_mode & 0o222
    with pytest.raises(ValueError, match="never reused"):
        ld.dry_run(plan(), tmp_path / "dry")


def test_offline_run_outputs_remain_consistent(tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("no network"))
    names = ("catalog.json", "catalog-diff.json", "receipt.json")
    shims = []
    real_open = os.open

    class Multi(OsShim):
        def open(self, path, *args):
            fd = real_open(path, *args)
            if os.path.basename(path) in names:
                self.fds.add(fd)
            return fd

    multi = Multi("", counts=[13] * 3 + [29] * 3)
    shims.append(multi)
    monkeypatch.setattr(ld, "os", multi)
    opener = Opener({BASE + "BAG/": LISTING, BASE + "footprints.json": ARCGIS})
    receipt = ld.run(plan(), tmp_path / "live", runner=runner_for(opener))
    assert {o["path"] for o in receipt["outputs"]} == set(names)
    for ref in receipt["outputs"]:
        if ref["path"] == "receipt.json":
            continue
        stored = (tmp_path / "live" / ref["path"]).read_bytes()
        assert ref["bytes"] == len(stored) and ref["sha256"] == hashlib.sha256(stored).hexdigest()
        json.loads(stored)
    stored_receipt = json.loads((tmp_path / "live" / "receipt.json").read_bytes())
    assert "receipt.json" not in {o["path"] for o in stored_receipt["outputs"]}


@pytest.mark.parametrize("stalled", ["catalog.json", "receipt.json"])
def test_incomplete_freeze_stops_attempt_without_reuse(tmp_path, monkeypatch, stalled):
    shim = use(monkeypatch, stalled, counts=[9, 0])
    opener = Opener({BASE + "BAG/": LISTING, BASE + "footprints.json": ARCGIS})
    with pytest.raises(OSError, match="no progress"):
        ld.run(plan(), tmp_path / "live", runner=runner_for(opener))
    out = tmp_path / "live"
    assert (out / stalled).stat().st_size == 9 and len(shim.closed) == 1
    if stalled == "catalog.json":
        assert not (out / "catalog-diff.json").exists() and not (out / "receipt.json").exists()
    else:
        assert (out / "catalog.json").exists() and (out / "catalog-diff.json").exists()
    with pytest.raises(ValueError, match="never reused"):
        ld.run(plan(), out, runner=runner_for(opener))


def test_normal_bytes_and_holds_unchanged(tmp_path):
    ref = ld._freeze(tmp_path / "n.json", VALUE)
    assert (tmp_path / "n.json").read_bytes() == oracle(VALUE) and ref["bytes"] == len(oracle(VALUE))
    opener = Opener({BASE + "BAG/": LISTING, BASE + "footprints.json": ARCGIS})
    ld.run(plan(), tmp_path / "live", runner=runner_for(opener))
    catalog = json.loads((tmp_path / "live" / "catalog.json").read_text())
    assert catalog["mapping_accepted"] is False and catalog["review_required"] is True
    assert all(c["terrain"]["accepted"] is False for c in catalog["candidates"])
