"""build_glyphs.write: all ranges or none, via fsynced temp files; a linked folder or range file refused by name (RF0550-9)."""
import os
import stat

import pytest

from scripts.basemap import build_glyphs as bg

A, B = (bg.PREFIX + name for name in ("0-255.pbf", "8192-8447.pbf"))
BUILT = {A: b"new-a", B: b"new-bbb"}
DIR = bg.PREFIX.rstrip("/")


def out_at(tmp_path, monkeypatch, old=None):
    out = tmp_path / "out"
    if old is not None:
        out.mkdir()
        (out / "0-255.pbf").write_bytes(old[0])
        (out / "8192-8447.pbf").write_bytes(old[1])
    monkeypatch.setattr(bg, "OUT", out)
    return out


def files(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir()}


def test_empty_folder_both_written_0644_no_temp(tmp_path, monkeypatch, capsys):
    out = out_at(tmp_path, monkeypatch)
    bg.write(dict(BUILT))
    assert files(out) == {"0-255.pbf": b"new-a", "8192-8447.pbf": b"new-bbb"}
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o644 for p in out.iterdir())
    assert capsys.readouterr().out.splitlines() == [f"{A}: 5 bytes", f"{B}: 7 bytes"]


def test_old_ranges_both_replaced(tmp_path, monkeypatch):
    out = out_at(tmp_path, monkeypatch, (b"old-a", b"old-b"))
    bg.write(dict(BUILT))
    assert files(out) == {"0-255.pbf": b"new-a", "8192-8447.pbf": b"new-bbb"}


def test_phase1_failure_on_second_range_leaves_old_files(tmp_path, monkeypatch, capsys):
    out = out_at(tmp_path, monkeypatch, (b"old-a", b"old-b"))
    calls, real = [], os.fsync

    def fsync(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("disk full")
        real(fd)
    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(SystemExit) as stop:
        bg.write(dict(BUILT))
    assert stop.value.code == f"build_glyphs: {B}: write failed (OSError)"
    assert files(out) == {"0-255.pbf": b"old-a", "8192-8447.pbf": b"old-b"}
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("old", [(b"old-a", b"old-b"), None])
def test_phase2_failure_restores_previous_ranges_and_leaves_no_temp(tmp_path, monkeypatch, capsys, old):
    out = out_at(tmp_path, monkeypatch, old)
    real = os.replace

    def replace(src, dst):
        if str(dst).endswith("8192-8447.pbf"):
            raise PermissionError("denied")
        real(src, dst)
    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(SystemExit) as stop:
        bg.write(dict(BUILT))
    assert stop.value.code == f"build_glyphs: {B}: write failed (PermissionError)"
    assert files(out) == ({"0-255.pbf": b"old-a", "8192-8447.pbf": b"old-b"} if old else {})
    assert capsys.readouterr().out == ""


def test_out_symlink_refused_other_folder_untouched(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    (other / "0-255.pbf").write_bytes(b"keep")
    out = out_at(tmp_path, monkeypatch)
    out.symlink_to(other, target_is_directory=True)
    with pytest.raises(SystemExit) as stop:
        bg.write(dict(BUILT))
    assert stop.value.code == f"build_glyphs: {DIR}: not a regular file or folder"
    assert files(other) == {"0-255.pbf": b"keep"}


def test_dangling_out_symlink_refused(tmp_path, monkeypatch):
    out = out_at(tmp_path, monkeypatch)
    out.symlink_to(tmp_path / "missing")
    with pytest.raises(SystemExit) as stop:
        bg.write(dict(BUILT))
    assert stop.value.code == f"build_glyphs: {DIR}: not a regular file or folder"
    assert not (tmp_path / "missing").exists()


def test_out_regular_file_refused(tmp_path, monkeypatch):
    out = out_at(tmp_path, monkeypatch)
    out.write_bytes(b"file")
    with pytest.raises(SystemExit) as stop:
        bg.write(dict(BUILT))
    assert stop.value.code == f"build_glyphs: {DIR}: not a regular file or folder"
    assert out.read_bytes() == b"file"


@pytest.mark.parametrize("kind", ["symlink", "dangling", "folder"])
def test_range_not_regular_refused_nothing_written(tmp_path, monkeypatch, capsys, kind):
    out = out_at(tmp_path, monkeypatch, (b"old-a", b"old-b"))
    victim = tmp_path / "victim"
    victim.write_bytes(b"victim")
    (out / "8192-8447.pbf").unlink()
    if kind == "folder":
        (out / "8192-8447.pbf").mkdir()
    else:
        (out / "8192-8447.pbf").symlink_to(victim if kind == "symlink" else tmp_path / "gone")
    with pytest.raises(SystemExit) as stop:
        bg.write(dict(BUILT))
    assert stop.value.code == f"build_glyphs: {B}: not a regular file or folder"
    assert (out / "0-255.pbf").read_bytes() == b"old-a" and victim.read_bytes() == b"victim"
    assert sorted(p.name for p in out.iterdir()) == ["0-255.pbf", "8192-8447.pbf"]
    assert not (tmp_path / "gone").exists() and capsys.readouterr().out == ""
