"""build_glyphs.py: versions line, missing font stack, --check against the pins (FE-72, #422). No font libraries needed."""
import hashlib
import importlib
import json
import sys

import pytest

from scripts.basemap import build_glyphs as bg

A, B, X = (bg.PREFIX + name for name in ("0-255.pbf", "8192-8447.pbf", "x.pbf"))
PINS = {A: hashlib.sha256(b"aa").hexdigest(), B: hashlib.sha256(b"bb").hexdigest()}


def hide_libs(monkeypatch):
    for name in ("fontTools", "brotli", "PIL", "numpy", "scipy"):
        monkeypatch.setitem(sys.modules, name, None)


def setup(tmp_path, monkeypatch, built, pins=PINS):
    (tmp_path / "out").mkdir()
    (tmp_path / "pins.json").write_text(pins if isinstance(pins, str) else json.dumps(pins))
    monkeypatch.setattr(bg, "OUT", tmp_path / "out")
    monkeypatch.setattr(bg, "PINS", tmp_path / "pins.json")
    monkeypatch.setattr(bg, "build", lambda: dict(built))
    return tmp_path / "out"


def test_imports_without_the_font_stack(monkeypatch):
    hide_libs(monkeypatch)
    monkeypatch.delitem(sys.modules, "scripts.basemap.build_glyphs")
    assert importlib.import_module("scripts.basemap.build_glyphs").RANGES == (0, 8192)


@pytest.mark.parametrize("argv", [[], ["--check"]])
def test_missing_libraries_exit_2_and_write_nothing(tmp_path, monkeypatch, capsys, argv):
    hide_libs(monkeypatch)
    monkeypatch.setattr(bg, "OUT", tmp_path / "out")
    with pytest.raises(SystemExit) as stop:
        bg.main(argv)
    assert stop.value.code == 2 and not (tmp_path / "out").exists()
    assert capsys.readouterr().err.endswith("(missing: fonttools, brotli, Pillow, numpy, scipy)\n")


def test_versions_line_first_in_fixed_order(tmp_path, monkeypatch, capsys):
    def version(package):
        if package == "brotli":
            raise bg.metadata.PackageNotFoundError(package)
        return {"fonttools": "4.1", "Pillow": "11.0", "numpy": "2.0", "scipy": "1.1"}[package]
    monkeypatch.setattr(bg.metadata, "version", version)
    monkeypatch.setattr(bg.platform, "python_version", lambda: "3.13.0")
    setup(tmp_path, monkeypatch, {A: b"aa", B: b"bb"})
    for argv in ([], ["--check"]):
        assert bg.main(argv) == 0
        line = capsys.readouterr().out.splitlines()[0]
        assert line == "versions: python=3.13.0 fonttools=4.1 brotli=absent pillow=11.0 numpy=2.0 scipy=1.1"


def test_default_mode_writes_each_range(tmp_path, monkeypatch, capsys):
    out = setup(tmp_path, monkeypatch, {A: b"aa", B: b"bbb"})
    assert bg.main([]) == 0
    assert capsys.readouterr().out.splitlines()[1:] == [f"{A}: 2 bytes", f"{B}: 3 bytes"]
    assert (out / "0-255.pbf").read_bytes() == b"aa" and (out / "8192-8447.pbf").read_bytes() == b"bbb"


@pytest.mark.parametrize("built, pins, lines, code", [
    ({A: b"aa", B: b"bb"}, PINS, [f"match {A}", f"match {B}"], 0),
    ({A: b"aa", B: b"bc"}, PINS, [f"match {A}", f"differs {B}"], 1),
    ({A: b"aa", B: b"bb", X: b"x"}, PINS, [f"match {A}", f"match {B}", f"unpinned {X}"], 1),
    ({A: b"aa"}, PINS, [f"match {A}", f"not built {B}"], 1),
    ({A: b"aa", B: b"bb"}, {**PINS, "web/app.js": "0", bg.PREFIX + "a.txt": "0"}, [f"match {A}", f"match {B}"], 0),
    ({}, {"web/app.js": "0"}, [], 1),
])
def test_check_lines_and_exit_without_writing(tmp_path, monkeypatch, capsys, built, pins, lines, code):
    out = setup(tmp_path, monkeypatch, built, pins)
    before = (tmp_path / "pins.json").read_bytes()
    assert bg.main(["--check"]) == code
    assert capsys.readouterr().out.splitlines()[1:] == lines
    assert list(out.iterdir()) == [] and (tmp_path / "pins.json").read_bytes() == before


@pytest.mark.parametrize("pins", ["not json", "[]", None])
def test_bad_pin_file_exit_2(tmp_path, monkeypatch, capsys, pins):
    out = setup(tmp_path, monkeypatch, {A: b"aa"}, pins or "{}")
    if pins is None:
        monkeypatch.setattr(bg, "PINS", tmp_path / "missing.json")
    assert bg.main(["--check"]) == 2 and list(out.iterdir()) == []
    assert capsys.readouterr().err == "build_glyphs: pin file unreadable\n"


@pytest.mark.parametrize("argv", [["--write"], ["--check", "extra"]])
def test_unknown_argument_exit_2(monkeypatch, argv):
    monkeypatch.setattr(bg, "build", lambda: pytest.fail("built"))
    with pytest.raises(SystemExit) as stop:
        bg.main(argv)
    assert stop.value.code == 2


def test_pure_helpers_unchanged():
    assert bg.varint(300) == b"\xac\x02" and bg.zigzag(-1) == 1 and bg.zigzag(2) == 4
    assert bg.field(1, b"ab") == b"\x0a\x02ab" and bg.field(7, 5) == b"\x38\x05"
