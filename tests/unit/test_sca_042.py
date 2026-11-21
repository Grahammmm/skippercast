"""M-01: search events by trip without changing window or kind semantics."""

import sqlite3
from contextlib import closing

from tests._support import ROOT

DRIZZLE = ROOT / "drizzle"
MIGRATION = DRIZZLE / "0018_fleet_event_trip.sql"

# The AIS replace window from server/fleet/activity.ts.
DELETE = """
DELETE FROM fleet_events WHERE trip_id IN (
    SELECT id FROM fleet_trips
    WHERE region=? AND source=? AND mmsi=? AND departed_at>=? AND departed_at<?
)
"""
WINDOW = ("CA", "aisstream", "999000001", "2026-01-01", "2026-01-02")

# The correlated kind predicate and pagination from server/fleet/map.ts.
FILTER = """
SELECT t.id FROM fleet_trips t
LEFT JOIN fleet_vessels v ON v.id=t.vessel_id
WHERE t.region=? AND EXISTS (
    SELECT 1 FROM fleet_events k WHERE k.trip_id=t.id AND k.kind IN (?)
)
ORDER BY t.departed_at DESC, t.id DESC LIMIT ?
"""

INSERT_EVENT = """
INSERT INTO fleet_events (id, trip_id, segment_id, vessel_id, region, kind, lat, lon,
    started_at, ended_at, dwell_min, season, source, rights, classifier_version)
VALUES (?, ?, 'synthetic-segment', 'synthetic-vessel', 'CA', ?, 0, 0,
    '2026-01-01', '2026-01-01', 1, '2026', 'aisstream', 'fixture', 'fixture')
"""


def _seed(db):
    db.executemany(
        """
        INSERT INTO fleet_trips (id, departed_at, region, mmsi, vessel_id,
            local_date, season, source, rights, classifier_version, computed_at)
        VALUES (?, ?, 'CA', '999000001', 'synthetic-vessel', '2026-01-01',
            '2026', 'aisstream', 'fixture', 'fixture', '2026-01-01')
        """,
        [("target", "2026-01-01"), ("edge", "2026-01-02"), ("no-event", "2026-01-01")],
    )
    db.executemany(INSERT_EVENT, [
        ("old-match", "target", "drift-anchor"),
        ("old-other-kind", "target", "troll-slow"),
        ("keep", "edge", "troll-slow"),
    ])


def _event_access(db, sql, args, alias):
    plan = [row[-1] for row in db.execute("EXPLAIN QUERY PLAN " + sql, args)]
    return [detail for detail in plan if detail.split()[:2] in (
        ["SCAN", alias], ["SEARCH", alias],
    )]


def _check_window_and_filter(db):
    args = ("CA", "drift-anchor", 51)
    db.execute("SAVEPOINT replace_window")
    try:
        assert db.execute(FILTER, args).fetchall() == [("target",)]
        assert db.execute(DELETE, WINDOW).rowcount == 2
        assert db.execute(FILTER, args).fetchall() == []
        assert db.execute("SELECT id FROM fleet_events").fetchall() == [("keep",)]
        db.execute(INSERT_EVENT, ("new-match", "target", "drift-anchor"))
        assert db.execute(FILTER, args).fetchall() == [("target",)]
    finally:
        db.execute("ROLLBACK TO replace_window")
        db.execute("RELEASE replace_window")


def test_fleet_event_trip_index():
    with closing(sqlite3.connect(":memory:")) as db:
        for migration in sorted(DRIZZLE.glob("*.sql")):
            if migration >= MIGRATION:
                break
            db.executescript(migration.read_text(encoding="utf-8"))
        _seed(db)
        queries = [(DELETE, WINDOW, "fleet_events"), (FILTER, ("CA", "drift-anchor", 51), "k")]
        for sql, args, alias in queries:
            access = _event_access(db, sql, args, alias)
            print("Before:", *access)
            assert access == [f"SCAN {alias}"]
        _check_window_and_filter(db)

        db.executescript(MIGRATION.read_text(encoding="utf-8"))
        for sql, args, alias in queries:
            access = _event_access(db, sql, args, alias)
            print("After:", *access)
            assert len(access) == 1 and access[0].startswith(f"SEARCH {alias} ")
            assert " ev_trip (trip_id=?)" in access[0]
        _check_window_and_filter(db)
