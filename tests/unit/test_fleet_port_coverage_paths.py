"""RF1345-7: the port-coverage reader opens exactly the requested state.sqlite, read-only, whatever its path bytes.

Real SQLite files under a temporary directory; ``?``, ``#`` and ``%`` in a parent or basename are filename
characters, never URI query, fragment or escape syntax, so no other file is read or created.
"""
import contextlib
import io
import os
import sqlite3
from collections import namedtuple
from pathlib import Path

import pytest

from skippercast.fleet.ais import __main__ as ais_main
from skippercast.fleet.ais import port_coverage as pc
from skippercast.fleet.config import load_region

Port = namedtuple("Port", "id name")
PORTS = [Port("aa", "Alpha Harbor"), Port("bb", "Bravo Bay")]
SINCE = "2026-10-06"
DDL = "CREATE TABLE match_presence (mmsi INTEGER NOT NULL, port_id TEXT NOT NULL, day TEXT NOT NULL, " \
      "PRIMARY KEY (mmsi, port_id, day))"
REQUESTED_ROWS = [(999000001, "aa", "2026-10-10")]
DECOY_ROWS = [(999000002, "bb", "2026-10-10"), (999000003, "bb", "2026-10-11"), (999000004, "bb", "2026-10-12")]
REQUESTED = {"ports": {"aa": {"mmsis": 1, "mmsi_days": 1}, "bb": {"mmsis": 0, "mmsi_days": 0}},
             "never_heard": ["bb"]}

NAMES = ["state?mark.sqlite", "state#mark.sqlite", "state%mark.sqlite", "state%23mark.sqlite", "state%3Fmark.sqlite",
         "state mark.sqlite", "état ünï 港.sqlite", "s t?a#t%e%23%3F é?mode=rw#x.sqlite"]
PARENTS = ["plain", "dir?q=1#frag %23 é%3F"]


def make_db(path, rows):
    db = sqlite3.connect(path)
    db.execute(DDL)
    db.executemany("INSERT INTO match_presence VALUES (?,?,?)", rows)
    db.commit()
    db.close()


def inventory(root):
    """Every file and directory under ``root`` with each file's bytes."""
    found = {}
    for path in Path(root).rglob("*"):
        found[path.relative_to(root).as_posix()] = path.read_bytes() if path.is_file() else None
    return found


@pytest.mark.parametrize("parent", PARENTS)
@pytest.mark.parametrize("name", NAMES)
def test_reserved_characters_read_exact_state_without_creation(tmp_path, parent, name):
    folder = tmp_path / parent
    folder.mkdir()
    make_db(folder / name, REQUESTED_ROWS)
    before = inventory(tmp_path)
    assert pc.port_coverage(folder / name, PORTS, SINCE) == REQUESTED
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("requested, decoy", [
    ("state%23mark.sqlite", "state#mark.sqlite"),   # %23 would decode to the existing '#' file
    ("state?mode=rw.sqlite", "state"),              # a query would truncate to 'state' and ask for rw
    ("state#frag.sqlite", "state"),                 # a fragment would truncate to 'state'
    ("st%61te.sqlite", "state.sqlite"),             # %61 would decode to 'a'
])
def test_uri_lookalike_path_cannot_select_decoy(tmp_path, requested, decoy):
    make_db(tmp_path / requested, REQUESTED_ROWS)
    make_db(tmp_path / decoy, DECOY_ROWS)
    before = inventory(tmp_path)
    assert pc.port_coverage(tmp_path / requested, PORTS, SINCE) == REQUESTED
    assert inventory(tmp_path) == before


def test_relative_reserved_path_uses_same_read_only_target(tmp_path, monkeypatch):
    folder = tmp_path / "rel ?#%23"
    folder.mkdir()
    make_db(folder / "state%3F#x.sqlite", REQUESTED_ROWS)
    make_db(tmp_path / "rel ", DECOY_ROWS)
    before = inventory(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert pc.port_coverage(Path("rel ?#%23") / "state%3F#x.sqlite", PORTS, SINCE) == REQUESTED
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("name", ["gone.sqlite", "gone?x=1#y.sqlite", "gone%23.sqlite"])
def test_state_disappearing_after_preflight_never_gets_created(tmp_path, monkeypatch, name):
    with monkeypatch.context() as patch:
        patch.setattr(pc.Path, "is_file", lambda self: True)   # the file vanished after the preflight
        result = pc.port_coverage(tmp_path / name, PORTS, SINCE)
    assert result is None
    assert inventory(tmp_path) == {}


def _corrupt(path):
    path.write_bytes(b"not a database " * 100)


def _table_less(path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE other (x INTEGER)")
    db.commit()
    db.close()


@pytest.mark.parametrize("seed", [None, _table_less, _corrupt])
def test_unknown_states_keep_old_contract(tmp_path, seed):
    folder = tmp_path / "var ?#%23"
    folder.mkdir()
    if seed:
        seed(folder / "state?.sqlite")
    before = inventory(tmp_path)
    result = pc.port_coverage(folder / "state?.sqlite", PORTS, SINCE)
    assert result is None
    assert pc.render(result, PORTS) == "### AIS coverage by port\n\nNo processor state yet: coverage unknown.\n"
    assert inventory(tmp_path) == before


def _cli(var, monkeypatch):
    monkeypatch.setenv("SKIPPERCAST_FLEET_VAR", str(var))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = ais_main.main(["port-coverage", "--region", "CA", "--now", "2026-11-05T12:00:00+00:00"])
    return code, out.getvalue()


def test_cli_reads_special_character_root_like_ordinary_root(tmp_path, monkeypatch):
    region = load_region("CA")
    rows = [(999000001, region.ports[0].id, "2026-11-01")]
    outputs = []
    for var in (tmp_path / "ordinary", tmp_path / "fleet ?mode=rw#x%23 é"):
        root = var / "CA" / "ais"
        root.mkdir(parents=True)
        make_db(root / "state.sqlite", rows)
        before = inventory(tmp_path)
        code, text = _cli(var, monkeypatch)
        assert code == 0
        assert inventory(tmp_path) == before
        assert f"| {region.ports[0].name} | 1 | 1 |" in text
        assert "999000001" not in text
        outputs.append(text)
    assert outputs[0] == outputs[1]
