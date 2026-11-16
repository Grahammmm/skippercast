"""Incomplete directory scans must refuse, never report free capacity."""
import os
from pathlib import Path

import pytest

from skippercast.coastal import cached_inventory as ci

_real_scandir = os.scandir


def deny(monkeypatch, target, exc=PermissionError, after=None):
    """Raise exc when os.walk enters `target`; forward everything else."""
    seen = []

    def fake(path="."):
        if str(path) == str(target):
            seen.append(path)
            raise exc(13, "denied", str(path))
        return _real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake)
    return seen


def make_tree(base):
    (base / "a").mkdir(parents=True)
    (base / "a" / "f.bin").write_bytes(b"x" * 10)
    (base / "hidden").mkdir()
    (base / "hidden" / "big.bin").write_bytes(b"y" * 100)
    (base / "top.bin").write_bytes(b"z" * 5)
    return base


@pytest.mark.parametrize("exc", [PermissionError, FileNotFoundError])
@pytest.mark.parametrize("where", ["root", "hidden"])
def test_output_tree_scan_errors_refuse_partial_totals(tmp_path, monkeypatch, exc, where):
    out = make_tree(tmp_path / "out")
    assert ci.output_tree_bytes(out) == 115
    target = out if where == "root" else out / "hidden"
    deny(monkeypatch, target, exc)
    with pytest.raises(ValueError, match="incomplete output directory scan") as info:
        ci.output_tree_bytes(out)
    assert isinstance(info.value.__cause__, exc)


@pytest.mark.parametrize("role", ["retained", "scratch"])
@pytest.mark.parametrize("where", ["root", "hidden"])
def test_resource_scan_errors_refuse_for_each_role(tmp_path, monkeypatch, role, where):
    roots = {"retained": make_tree(tmp_path / "r"), "scratch": make_tree(tmp_path / "s")}
    base = roots[role]
    deny(monkeypatch, base if where == "root" else base / "hidden")
    with pytest.raises(ValueError, match="incomplete output directory scan") as info:
        ci.resource_inventory(roots["retained"], roots["scratch"])
    assert isinstance(info.value.__cause__, PermissionError)


@pytest.mark.parametrize("role", ["retained", "scratch"])
def test_engineering_receipt_not_created_after_scan_failure(tmp_path, monkeypatch, role):
    roots = {"retained": make_tree(tmp_path / "r"), "scratch": make_tree(tmp_path / "s")}
    (roots["retained"] / "sentinel.json").write_bytes(b"keep")
    before = sorted(p.name for p in roots["retained"].rglob("*"))
    with monkeypatch.context() as m:
        deny(m, roots[role] / "hidden")
        with pytest.raises(ValueError, match="incomplete output directory scan"):
            ci.write_engineering_receipt(roots["retained"], roots["scratch"], "r.json", {"k": 1})
    assert not (roots["retained"] / "r.json").exists()
    assert sorted(p.name for p in roots["retained"].rglob("*")) == before
    assert (roots["retained"] / "sentinel.json").read_bytes() == b"keep"
    result = ci.write_engineering_receipt(roots["retained"], roots["scratch"], "r.json", {"k": 1})
    assert result["bytes"] == len(ci.encoded({"k": 1}))
    assert (roots["retained"] / "r.json").read_bytes() == ci.encoded({"k": 1})
    with pytest.raises(ValueError, match="preserve existing"):
        ci.write_engineering_receipt(roots["retained"], roots["scratch"], "r.json", {"k": 2})


def test_produce_scan_failure_precedes_artifact_writes(tmp_path, monkeypatch):
    out = tmp_path / "out"
    (out / "sub").mkdir(parents=True)
    (out / "sub" / "keep.bin").write_bytes(b"k")
    plan = {"output_root": str(out)}
    monkeypatch.setattr(ci, "metadata_reservation", lambda p: 0)
    deny(monkeypatch, out / "sub")
    with pytest.raises(ValueError, match="incomplete output directory scan"):
        ci.produce(tmp_path, plan, out, now=1.0, horizon=100.0)
    monkeypatch.setattr(os, "scandir", _real_scandir)
    assert sorted(p.name for p in out.rglob("*")) == ["keep.bin", "sub"]


def test_healthy_counts_caps_and_link_policies_unchanged(tmp_path):
    out = make_tree(tmp_path / "out")
    assert ci.output_tree_bytes(out) == 115
    (out / "ln").symlink_to(out / "top.bin")
    with pytest.raises(ValueError, match="symlink output tree rejected"):
        ci.output_tree_bytes(out)
    r = make_tree(tmp_path / "r")
    (r / "ln").symlink_to(r / "top.bin")
    values = ci.resource_inventory(r, tmp_path / "absent")
    assert values["retained"]["regular_bytes"] == 115
    assert values["retained"]["regular_files"] == 3
    assert values["retained"]["symlinks_preserved_not_followed"] == 1
    assert values["scratch"]["regular_files"] == 0
