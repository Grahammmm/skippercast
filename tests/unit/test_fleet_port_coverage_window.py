"""RF2311-6: the port-coverage report counts no presence day later than the report clock's region-local day.

Real SQLite scratch files and the real CLI entry point; the CA region's zone is America/Los_Angeles.
"""
import contextlib
import io
import os
import sqlite3
from collections import namedtuple
from pathlib import Path
from unittest import mock

import pytest

from skippercast.fleet.ais import __main__ as ais_main
from skippercast.fleet.ais import port_coverage as pc
from skippercast.fleet.config import load_region

Port = namedtuple("Port", "id name")
PORTS = [Port("aa", "Alpha Harbor"), Port("bb", "Bravo Bay")]
DDL = "CREATE TABLE match_presence (mmsi INTEGER NOT NULL, port_id TEXT NOT NULL, day TEXT NOT NULL, " \
      "PRIMARY KEY (mmsi, port_id, day))"


def make_db(path, rows):
    db = sqlite3.connect(path)
    db.execute(DDL)
    db.executemany("INSERT INTO match_presence VALUES (?,?,?)", rows)
    db.commit()
    db.close()


def run_cli(tmp_path, rows, now):
    region = load_region("CA")
    root = tmp_path / "CA" / "ais"
    root.mkdir(parents=True)
    make_db(root / "state.sqlite", [(m, region.ports[i].id, d) for m, i, d in rows])
    before = (root / "state.sqlite").read_bytes()
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(tmp_path)}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ais_main.main(["port-coverage", "--region", "CA", "--now", now])
    assert code == 0
    assert (root / "state.sqlite").read_bytes() == before
    assert sorted(p.name for p in root.iterdir()) == ["state.sqlite"]
    return region, out.getvalue(), err.getvalue()


def test_cli_excludes_future_local_days(tmp_path):
    rows = [(999000001, 0, "2026-11-05"), (999000002, 0, "2099-01-01"), (999000003, 1, "2099-01-01")]
    region, out, err = run_cli(tmp_path, rows, "2026-11-05T12:00:00+00:00")
    assert f"| {region.ports[0].name} | 1 | 1 |" in out
    assert f"| {region.ports[1].name} | 0 | 0 |" in out
    assert region.ports[1].name in out.split("Never heard")[1]
    assert "99900000" not in out + err


def test_upper_day_uses_region_zone(tmp_path):
    # 2026-11-06T03:00Z is still 2026-11-05 in Los Angeles: the UTC next date must not qualify.
    rows = [(999000001, 0, "2026-11-05"), (999000002, 0, "2026-11-06")]
    region, out, _ = run_cli(tmp_path, rows, "2026-11-06T03:00:00+00:00")
    assert f"| {region.ports[0].name} | 1 | 1 |" in out


def test_aware_offset_equals_utc_and_naive_is_utc(tmp_path):
    rows = [(999000001, 0, "2026-11-05"), (999000002, 0, "2026-11-06")]
    outputs = []
    for i, now in enumerate(["2026-11-06T03:00:00+00:00", "2026-11-05T19:00:00-08:00", "2026-11-06T03:00:00"]):
        outputs.append(run_cli(tmp_path / str(i), rows, now)[1])
    assert outputs[0] == outputs[1] == outputs[2]


@pytest.mark.parametrize("now", ["2026-03-08T20:00:00+00:00", "2026-11-01T20:00:00+00:00"])
def test_dst_days_are_local(tmp_path, now):
    local = pc._day(int(pc.datetime.fromisoformat(now).timestamp() * 1000), pc.ZoneInfo("America/Los_Angeles"))
    rows = [(999000001, 0, local), (999000002, 0, "2026-12-31")]
    region, out, _ = run_cli(tmp_path, rows, now)
    assert f"| {region.ports[0].name} | 1 | 1 |" in out


def test_bounds_are_inclusive(tmp_path):
    days = ["2026-10-05", "2026-10-06", "2026-10-20", "2026-11-05", "2026-11-06", "2099-01-01"]
    path = tmp_path / "s.sqlite"
    make_db(path, [(999000001, "aa", d) for d in days] + [(999000001, "bb", "2026-10-20")])
    result = pc.port_coverage(path, PORTS, "2026-10-06", until_day="2026-11-05")
    assert result["ports"]["aa"] == {"mmsis": 1, "mmsi_days": 3}
    assert result["ports"]["bb"] == {"mmsis": 1, "mmsi_days": 1}


def test_legacy_three_argument_call_is_unbounded(tmp_path):
    path = tmp_path / "s.sqlite"
    make_db(path, [(999000001, "aa", "2026-11-05"), (999000001, "aa", "2099-01-01")])
    assert pc.port_coverage(path, PORTS, "2026-10-06")["ports"]["aa"]["mmsi_days"] == 2
    assert pc.port_coverage(path, PORTS, "2026-10-06", until_day="2026-11-05")["ports"]["aa"]["mmsi_days"] == 1


def test_missing_and_tableless_state_stay_unknown(tmp_path):
    assert pc.port_coverage(tmp_path / "none.sqlite", PORTS, "2026-10-06", until_day="2026-11-05") is None
    empty = tmp_path / "e.sqlite"
    sqlite3.connect(empty).close()
    assert pc.port_coverage(empty, PORTS, "2026-10-06", until_day="2026-11-05") is None
