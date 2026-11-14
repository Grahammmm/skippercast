"""Catalog bridge: metadata reads are bounded by the bytes actually read, not by an earlier lstat."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.http import Allowlist
from tests import _coastal_catalog_fixture as fx

ALLOW = Allowlist([fx.HOST])
CAP = bridge.MAX_DOCUMENT_BYTES
BOUND = "exceeds the metadata read bound"


def pad(raw, size):
    """Valid JSON stays valid: trailing whitespace only."""
    assert len(raw) <= size
    return raw + b" " * (size - len(raw))


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
    return dict(root=root, tmp=tmp_path, catalog=catalog, path=path, sha=sha, source=source, sel=sel)


def grow_after_lstat(monkeypatch, target, new_bytes):
    """Real lstat of `target` is captured, then the real file changes to `new_bytes` before it is returned."""
    real, seen = os.lstat, []
    target = Path(target)

    def lstat(p, *args, **kwargs):
        info = real(p, *args, **kwargs)
        if Path(p) == target and not seen:
            seen.append(info.st_size)
            target.write_bytes(new_bytes)
        return info
    monkeypatch.setattr(os, "lstat", lstat)
    return seen


class Spy:
    """Binary read seam over the real file: records requested sizes and closure."""

    def __init__(self, path, mode):
        assert mode == "rb"
        self.stream = open(path, mode)
        self.reads, self.closed = [], False

    def read(self, *args):
        self.reads.append(args)
        return self.stream.read(*args)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.closed = True
        self.stream.close()


def spy_open(monkeypatch):
    opened = []

    def opener(path, mode="r", *args, **kwargs):
        spy = Spy(path, mode)
        opened.append((Path(path), spy))
        return spy
    monkeypatch.setattr(bridge, "open", opener, raising=False)
    return opened


def grown_catalog_plan(world):
    raw = pad(world["path"].read_bytes(), CAP + 1)
    return raw, fx.plan(world["catalog"], hashlib.sha256(raw).hexdigest(), [world["sel"]])


def test_ordinary_catalog_control_selects_source(world):
    plan = fx.plan(world["catalog"], world["sha"], [world["sel"]])
    receipt = bridge.dry_run(world["root"], world["path"], plan, world["tmp"] / "ok", allowlist=ALLOW)
    assert receipt["selected_source_ids"] and receipt["source_opens"] == 0


@pytest.mark.parametrize("action", ["dry_run", "run"])
def test_catalog_growth_after_real_lstat_refuses_before_output(world, monkeypatch, action):
    grown, plan = grown_catalog_plan(world)
    seen = grow_after_lstat(monkeypatch, world["path"], grown)
    opened = spy_open(monkeypatch)
    out = world["root"] / "out" if action == "run" else world["tmp"] / "out"
    with pytest.raises(ValueError, match=BOUND) as info:
        getattr(bridge, action)(world["root"], world["path"], plan, out, allowlist=ALLOW)
    assert str(info.value) == f"catalog {BOUND}"
    assert seen and seen[0] < CAP and len(world["path"].read_bytes()) == CAP + 1
    assert not out.exists()
    assert [p for p, _ in opened] == [world["path"]]  # the cached native source is never opened
    assert opened[0][1].reads == [(CAP + 1,)] and opened[0][1].closed


def test_plan_growth_refuses_before_dispatch(world, monkeypatch, capsys):
    plan_path = world["tmp"] / "plan.json"
    plan = fx.plan(world["catalog"], world["sha"], [world["sel"]])
    plan_path.write_bytes(json.dumps(plan).encode())
    seen = grow_after_lstat(monkeypatch, plan_path, pad(plan_path.read_bytes(), CAP + 1))
    called = []
    for name in ("dry_run", "run"):
        monkeypatch.setattr(bridge, name, lambda *a, **k: called.append(a))
    out = world["tmp"] / "out"
    with pytest.raises(ValueError, match=BOUND) as info:
        bridge.main(["dry-run", "--root", str(world["root"]), "--catalog", str(world["path"]),
                     "--plan", str(plan_path), "--out", str(out)])
    assert str(info.value) == f"plan {BOUND}"
    assert seen and called == [] and not out.exists() and capsys.readouterr().out == ""


def test_ordinary_plan_still_dispatches_through_main(world, capsys):
    plan_path = world["tmp"] / "plan.json"
    plan_path.write_bytes(json.dumps(fx.plan(world["catalog"], world["sha"], [world["sel"]])).encode())
    bridge.main(["dry-run", "--root", str(world["root"]), "--catalog", str(world["path"]),
                 "--plan", str(plan_path), "--out", str(world["tmp"] / "out")])
    assert json.loads(capsys.readouterr().out)["selected_source_ids"]


def test_receipt_growth_refuses_before_store_access(world, monkeypatch):
    receipt_path = world["root"] / "receipt.json"
    receipt_path.write_bytes(b"{}")
    seen = grow_after_lstat(monkeypatch, receipt_path, pad(b"{}", CAP + 1))
    monkeypatch.setattr(bridge, "verify_ref", lambda root, ref: receipt_path)

    class Store:
        root = world["root"]

        @property
        def db(self):
            raise AssertionError("Store database must not be touched")

        def enqueue(self, *args, **kwargs):
            raise AssertionError("nothing may be enqueued")
    with pytest.raises(ValueError, match=BOUND) as info:
        bridge.enqueue(Store(), {}, code_sha="a" * 64, deps_sha="b" * 64)
    assert str(info.value) == f"bridge receipt {BOUND}" and seen


def test_bounded_request_and_parser_order(tmp_path, monkeypatch):
    path = tmp_path / "doc.json"
    path.write_bytes(b"{}")
    seen = grow_after_lstat(monkeypatch, path, pad(b"{}", CAP + 1))
    opened = spy_open(monkeypatch)
    parsed = []
    monkeypatch.setattr(bridge.json, "loads", lambda raw: parsed.append(raw))
    with pytest.raises(ValueError, match=BOUND):
        bridge._read(path, "catalog")
    assert seen and opened[0][1].reads == [(CAP + 1,)] and opened[0][1].closed and parsed == []


def test_descriptor_closes_when_read_or_parser_raises(tmp_path, monkeypatch):
    path = tmp_path / "doc.json"
    path.write_bytes(b"[1")  # truncated JSON: ordinary parser refusal
    opened = spy_open(monkeypatch)
    with pytest.raises(json.JSONDecodeError):
        bridge._read(path, "catalog")
    assert opened[0][1].closed

    def boom(*args):
        raise OSError(5, "io")
    monkeypatch.setattr(Spy, "read", lambda self, *a: boom(*a))
    with pytest.raises(OSError):
        bridge._read(path, "catalog")
    assert opened[1][1].closed


def test_static_oversize_refuses_without_read(tmp_path, monkeypatch):
    path = tmp_path / "big.json"
    path.write_bytes(pad(b"{}", CAP + 1))
    opened = spy_open(monkeypatch)
    with pytest.raises(ValueError, match=BOUND):
        bridge._read(path, "plan")
    assert opened == []
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="must be a regular file"):
        bridge._read(link, "plan")
    assert opened == []


def test_exact_cap_and_utf8_raw_bytes_survive(tmp_path):
    exact = pad(json.dumps({"name": "Ensenada de Bahía — ñ"}, ensure_ascii=False).encode(), CAP)
    path = tmp_path / "exact.json"
    path.write_bytes(exact)
    value, raw = bridge._read(path, "catalog")
    assert len(raw) == CAP and raw == exact and value == {"name": "Ensenada de Bahía — ñ"}
    assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(exact).hexdigest()
    ordinary = '{"a": "é"}\n'.encode()
    path.write_bytes(ordinary)
    assert bridge._read(path, "catalog") == ({"a": "é"}, ordinary)


@pytest.mark.parametrize("after", [b"", b'{"truncated": '])
def test_shrunk_document_is_not_silently_completed(tmp_path, monkeypatch, after):
    path = tmp_path / "doc.json"
    path.write_bytes(b'{"a": 1, "b": 2}')
    grow_after_lstat(monkeypatch, path, after)
    with pytest.raises(json.JSONDecodeError):
        bridge._read(path, "catalog")


def test_shorter_complete_document_remains_admissible(tmp_path, monkeypatch):
    path = tmp_path / "doc.json"
    path.write_bytes(b'{"a": 1, "b": 2}')
    grow_after_lstat(monkeypatch, path, b'{"a": 1}')
    assert bridge._read(path, "catalog") == ({"a": 1}, b'{"a": 1}')


def test_source_free_success_unchanged(world, monkeypatch):
    opened = spy_open(monkeypatch)
    plan = fx.plan(world["catalog"], world["sha"], [world["sel"]])
    receipt = bridge.run(world["root"], world["path"], plan, world["root"] / "bridge", allowlist=ALLOW)
    assert len(receipt["jobs"]) == 1 and receipt["execution_authorized"] is False
    assert receipt["output"]["bytes"] == len((world["root"] / receipt["output"]["path"]).read_bytes())
    assert [p for p, _ in opened] == [world["path"]]  # only the metadata catalog is read
