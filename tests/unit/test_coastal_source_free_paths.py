"""Producer database opens in source_free use the literal path, read-only."""
import inspect
import sqlite3

import pytest

from skippercast.coastal.coordinator import source_free

NAMES = ["plain", "hash#dir", "query?dir", "pct%23dir", "pct%3Fdir", "sp ace", "uni\u00e9", "a?mode=rw#b%25"]


def _make(path, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE marker(v TEXT)")
    con.execute("INSERT INTO marker VALUES (?)", (marker,))
    con.commit()
    con.close()


def _marker(con):
    try:
        return con.execute("SELECT v FROM marker").fetchone()[0]
    finally:
        con.close()


def _inventory(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*") if p.is_file())


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("where", ["parent", "basename"])
def test_literal_reserved_path_selects_requested_database(tmp_path, name, where):
    target = tmp_path / name / "p.sqlite" if where == "parent" else tmp_path / (name + ".sqlite")
    _make(target, "requested")
    before = _inventory(tmp_path)
    assert _marker(source_free._open_producer(target)) == "requested"
    assert _inventory(tmp_path) == before


def test_decoded_or_truncated_decoy_is_not_selected(tmp_path):
    requested = tmp_path / "a%23b?mode=rw.sqlite"
    _make(requested, "requested")
    _make(tmp_path / "a#b?mode=rw.sqlite", "decoded")
    _make(tmp_path / "a%23b", "truncated")
    before = _inventory(tmp_path)
    assert _marker(source_free._open_producer(requested)) == "requested"
    assert _inventory(tmp_path) == before


def test_missing_after_closed_check_never_created(tmp_path, monkeypatch):
    target = tmp_path / "q?x#y.sqlite"
    _make(target, "m")
    real = source_free.require_closed_database

    def check_then_remove(path):
        out = real(path)
        target.unlink()
        return out

    monkeypatch.setattr(source_free, "require_closed_database", check_then_remove)
    with pytest.raises(sqlite3.OperationalError):
        source_free._open_producer(target)
    assert _inventory(tmp_path) == []


def test_closed_sidecars_still_required(tmp_path):
    target = tmp_path / "d.sqlite"
    _make(target, "m")
    (tmp_path / "d.sqlite-journal").write_bytes(b"")
    assert _marker(source_free._open_producer(target)) == "m"
    for suffix in ("-wal", "-journal"):
        sidecar = tmp_path / ("d.sqlite" + suffix)
        sidecar.write_bytes(b"x")
        with pytest.raises(ValueError):
            source_free._open_producer(target)
        sidecar.unlink()
    link = tmp_path / "d.sqlite-wal"
    link.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        source_free._open_producer(target)


def test_both_producer_open_sites_use_exact_open():
    body = inspect.getsource(source_free.import_retained)
    assert body.count("_open_producer(source_db)") == 2
    assert "sqlite3.connect" not in body
