"""Ordered aggregate inventory refuses incomplete directory scans."""
import os

import pytest

from skippercast.coastal.coordinator import ordered_trial

CAP_MODE = "observed admission/checkpoint; not filesystem quota"


def _prep(tmp_path, out_cap=8, scratch_cap=64):
    out = tmp_path / "output"
    scr = tmp_path / "scratch"
    return dict(output_roots=[str(out)], scratch_roots=[str(scr)],
                output_cap_bytes=out_cap, scratch_cap_bytes=scratch_cap), out, scr


def _fail_scan(monkeypatch, target, exc):
    real = os.scandir

    def scandir(path="."):
        if os.fspath(path) == str(target):
            raise exc
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)


def _tree(root):
    (root / "nested").mkdir(parents=True)
    (root / "a.bin").write_bytes(b"1234")
    (root / "nested" / "b.bin").write_bytes(b"x" * 16)


def _snapshot(root):
    return sorted((str(p), p.read_bytes()) for p in root.rglob("*") if p.is_file())


@pytest.mark.parametrize("which", ["output", "scratch"])
@pytest.mark.parametrize("where", ["root", "nested"])
def test_unreadable_root_or_descendant_refuses(tmp_path, monkeypatch, which, where):
    prep, out, scr = _prep(tmp_path, out_cap=1000, scratch_cap=1000)
    base = out if which == "output" else scr
    _tree(base)
    other = scr if which == "output" else out
    other.mkdir()
    target = base if where == "root" else base / "nested"
    before = _snapshot(base)
    _fail_scan(monkeypatch, target, PermissionError(13, "denied"))
    with pytest.raises(ValueError, match="aggregate inventory traversal failed") as ei:
        ordered_trial.inventory(prep)
    assert isinstance(ei.value.__cause__, PermissionError)
    monkeypatch.undo()
    assert _snapshot(base) == before


@pytest.mark.parametrize("exc", [OSError(5, "EIO"), FileNotFoundError(2, "gone")])
def test_nonpermission_scan_errors_refuse(tmp_path, monkeypatch, exc):
    prep, out, _ = _prep(tmp_path, out_cap=1000)
    _tree(out)
    _fail_scan(monkeypatch, out / "nested", exc)
    with pytest.raises(ValueError, match="traversal failed"):
        ordered_trial.inventory(prep)


def test_readable_counts_and_cap_edges_unchanged(tmp_path):
    prep, out, scr = _prep(tmp_path, out_cap=20)
    _tree(out)
    (scr / "empty").mkdir(parents=True)
    assert ordered_trial.inventory(prep) == dict(
        output=dict(bytes=20, regular_files=2),
        scratch=dict(bytes=0, regular_files=0), cap_mode=CAP_MODE)
    (out / "c.bin").write_bytes(b"z")
    with pytest.raises(ValueError, match="checkpoint cap"):
        ordered_trial.inventory(prep)


def test_absent_roots_zero(tmp_path):
    prep, _, _ = _prep(tmp_path)
    got = ordered_trial.inventory(prep)
    assert got["output"] == got["scratch"] == dict(bytes=0, regular_files=0)


def test_child_symlink_still_refuses(tmp_path):
    prep, out, _ = _prep(tmp_path, out_cap=1000)
    _tree(out)
    (out / "link").symlink_to(out / "a.bin")
    with pytest.raises(ValueError, match="symlink"):
        ordered_trial.inventory(prep)


def test_next_independent_read_works_after_seam_removed(tmp_path, monkeypatch):
    prep, out, _ = _prep(tmp_path, out_cap=1000)
    _tree(out)
    with monkeypatch.context() as m:
        _fail_scan(m, out, PermissionError(13, "denied"))
        with pytest.raises(ValueError, match="traversal failed"):
            ordered_trial.inventory(prep)
    assert ordered_trial.inventory(prep)["output"] == dict(bytes=20, regular_files=2)
