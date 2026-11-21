"""F32-12: the rematch CLI separates aggregate summaries from private review evidence."""
import json
import os
import sqlite3
import stat
from contextlib import closing

import pytest

from research.scripts import join_fleet_registries as joiner
from research.scripts import rematch_ais_names as rematcher
from tests._support import ROOT


VESSEL_ID = "synthetic-vessel-146"
OUR_NAME = "Audit Kestrel Two"
AIS_NAME = "AUDIT KESTREL 2"
MMSI = "999000146"
CALL = "WZZ1460"
PORT = "synthetic-home-port"
DAY = "2026-01-01"
RULE = "R3-numerals-words-roman"


@pytest.fixture
def rematch_cli(tmp_path, monkeypatch):
    state = tmp_path / "state.sqlite"
    with closing(sqlite3.connect(state)) as db, db:
        db.executescript(
            "CREATE TABLE match_statics (mmsi INTEGER, name TEXT, call_sign TEXT, ship_type INTEGER, length_m REAL);"
            "CREATE TABLE match_presence (mmsi INTEGER, port_id TEXT, day TEXT);"
        )
        db.execute("INSERT INTO match_statics VALUES (?, ?, ?, 37, 12.0)", (MMSI, AIS_NAME, CALL))
        db.execute("INSERT INTO match_presence VALUES (?, ?, ?)", (MMSI, PORT, DAY))
    resolved = tmp_path / "resolved.jsonl"
    resolved.write_text(json.dumps({"vessel_id": VESSEL_ID, "name": OUR_NAME, "port_id": PORT}) + "\n")
    out = tmp_path / "out"
    monkeypatch.setattr(joiner, "US_MIDS", frozenset({"999"}))

    def run():
        old_umask = os.umask(0o022)
        try:
            assert rematcher.main(["--resolved", str(resolved), "--state", str(state), "--out", str(out)]) == 0
        finally:
            os.umask(old_umask)

    return run, out


def test_shareable_summaries_contain_rule_counts_not_vessel_details(rematch_cli, capsys):
    run, out = rematch_cli
    run()
    pr = (out / "pr-table.md").read_text()
    stdout = capsys.readouterr().out
    for value in (VESSEL_ID, OUR_NAME, AIS_NAME, MMSI, CALL, PORT, DAY):
        assert value not in pr
        assert value not in stdout
    assert pr == (out / "rule-table.md").read_text()

    def cells(line):
        return [cell.strip() for cell in line.strip("|").split("|")]

    header, _, *rows = map(cells, pr.splitlines())
    assert header[:4] == ["Rule", "vessels_newly_matched", "clean", "ambiguous"]
    assert [row[0] for row in rows] == list(rematcher.RULE_ORDER)
    assert all(len(row) == len(header) and all(count.isdecimal() for count in row[1:]) for row in rows)
    assert next(row for row in rows if row[0] == RULE)[1:4] == ["1", "1", "0"]
    counts = json.loads(stdout)
    assert counts["per_rule"][RULE]["corroborated"] == 1
    assert counts["resolved_by_this_tool"] == 0
    assert "ais_state_read_only_proof" not in counts


def test_pair_files_are_owner_only_on_create_and_replace(rematch_cli):
    run, out = rematch_cli
    assert not out.resolve().is_relative_to(ROOT.resolve())
    pair_files = [out / "pairs.json", out / "pairs.md"]
    for replace in (False, True):
        if replace:
            for path in pair_files:
                path.write_text("stale")
                path.chmod(0o644)
        run()
        for path in pair_files:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.name
        report = json.loads(pair_files[0].read_text())
        pair, = report["pairs"]
        assert (pair["vessel_id"], pair["mmsi"], pair["home_port_days"], pair["status"]) == (
            VESSEL_ID, MMSI, 1, "corroborated",
        )
        markdown = pair_files[1].read_text()
        for value in (OUR_NAME, AIS_NAME, PORT, MMSI, CALL, "home-port presence 1d"):
            assert value in markdown
