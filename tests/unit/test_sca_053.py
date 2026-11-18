"""Synthetic AIS hourly-read comparison. Run this file directly for the benchmark.

The projection and candidate indexes are experiments, not production changes.
Timings are informational and never used as CI thresholds.
"""
from collections import defaultdict
from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from skippercast.fleet.ais.process import HOUR, hour_counts
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic
from skippercast.fleet.ais.store import AisStore, TABLES, day_of

DAY = date(2000, 1, 2)
MIDNIGHT = 946771200000
MMSI = 999000001


def position(ts, vessel=MMSI, source="synthetic"):
    return AisPosition(vessel, ts, 0, 0, None, None, None, None, "1", source, ts)


def static(ts, vessel=MMSI):
    return AisStatic(vessel, ts, None, None, None, None, None, None, None, None, "B", "synthetic")


def projection_sql(tables):
    return " UNION ALL ".join(
        f"SELECT ts, mmsi, {int(table == 'positions')} AS watched "
        f"FROM {table} WHERE ts >= :start AND ts < :end" for table in tables
    ) + " ORDER BY ts"


def projected_hour(store, start, now):
    end = start + HOUR
    first, last = day_of(start), day_of(end - 1)
    vessels = set()
    messages = watched = gap = 0
    previous = start
    # Canonical day files have disjoint timestamp ranges, so concatenating
    # each day's ordered projection gives global order across a UTC rollover.
    for day in store.days():
        if not first <= day <= last:
            continue
        uri = store.day_path(day).as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            available = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type IN ('table', 'view')"
            )}
            tables = [table for table in TABLES if table in available]
            if not tables:
                continue
            for ts, vessel, is_watched in conn.execute(projection_sql(tables), {"start": start, "end": end}):
                messages += 1
                watched += is_watched
                vessels.add(vessel)
                gap = max(gap, ts - previous)
                previous = ts
    # The existing producer clamps the trailing edge but does not use now
    # to filter rows. Preserve that behavior, including future-stamped rows.
    gap = max(gap, max(start, min(end, now)) - previous)
    return dict(messages=messages, watched_messages=watched, vessels=len(vessels), max_gap_s=gap // 1000)


def test_empty_missing_and_materialized_partitions(tmp_path):
    store = AisStore(tmp_path)
    expected = dict(messages=0, watched_messages=0, vessels=0, max_gap_s=123)
    now = MIDNIGHT + 123999
    assert projected_hour(store, MIDNIGHT, now) == hour_counts(store, MIDNIGHT, now) == expected
    assert not store.raw_dir.exists()
    with closing(store.connect(DAY)) as conn, conn:
        conn.execute("DROP TABLE statics")
    assert projected_hour(store, MIDNIGHT, now) == hour_counts(store, MIDNIGHT, now) == expected
    for now, gap in ((MIDNIGHT - 1, 0), (MIDNIGHT + 2 * HOUR, 3600)):
        assert projected_hour(store, MIDNIGHT, now) == hour_counts(store, MIDNIGHT, now) == dict(
            expected, max_gap_s=gap,
        )


def test_mixed_tables_and_duplicate_times(tmp_path):
    store = AisStore(tmp_path)
    start = MIDNIGHT
    t = start + 720000
    store.write(
        positions=[position(t), position(t), position(t, source="synthetic-second")],
        discovery=[position(t), position(start + 1800000, MMSI + 1)],
        statics=[static(start + 2700000), static(start + 3000000, MMSI + 2)],
    )
    expected = dict(messages=6, watched_messages=2, vessels=3, max_gap_s=1080)
    assert projected_hour(store, start, start + HOUR) == hour_counts(store, start, start + HOUR) == expected


def test_half_open_window_and_clamped_trailing_edge_across_days(tmp_path):
    store = AisStore(tmp_path)
    start = MIDNIGHT - HOUR // 2
    end = start + HOUR
    store.write(
        positions=[position(start - 1, MMSI + 1), position(start), position(end - 1)],
        discovery=[position(end, MMSI + 2)],
        statics=[static(MIDNIGHT - 1), static(MIDNIGHT)],
    )
    expected = dict(messages=4, watched_messages=2, vessels=1, max_gap_s=1799)
    for now in (start - 1, MIDNIGHT, end, end + HOUR):
        assert projected_hour(store, start, now) == hour_counts(store, start, now) == expected


def benchmark(root):
    # Both layouts get the same full synthetic day in the same 24 transactions.
    # 8000 position, 2000 discovery and 200 static rows per hour. A vessel is
    # distributed through the day; timestamp keys are interleaved across tables.
    batches = []
    for hour in range(24):
        t = MIDNIGHT + hour * HOUR
        batches.append(dict(
            positions=[position(t + i * 400, MMSI + i % 400) for i in range(8000)],
            discovery=[position(t + i * 1500 + 1, MMSI + i % 200) for i in range(2000)],
            statics=[static(t + i * 15000 + 2, MMSI + i % 80) for i in range(200)],
        ))
    start = MIDNIGHT + 12 * HOUR
    end = start + HOUR
    samples = defaultdict(list)
    print(f"Python {sys.version.split()[0]}, SQLite {sqlite3.sqlite_version}; {24 * 10200:,} rows/day")
    for repeat in range(3):
        for indexed in ((False, True) if repeat % 2 == 0 else (True, False)):
            layout = "ts-index" if indexed else "primary-key-only"
            store = AisStore(root / f"{layout}-{repeat}")
            with closing(store.connect(DAY)) as conn, conn:
                if indexed:
                    for table in TABLES:
                        conn.execute(f"CREATE INDEX {table}_by_ts ON {table}(ts)")
            t0 = perf_counter()
            for batch in batches:
                assert store.write(**batch).total == 10200
            samples[layout, "write 24 batches (ms)"].append((perf_counter() - t0) * 1000)
            samples[layout, "closed DB (bytes)"].append(store.day_path(DAY).stat().st_size)

            reads = {
                "current hour (ms)": lambda: hour_counts(store, start, end),
                "projected hour (ms)": lambda: projected_hour(store, start, end),
                "single-vessel positions (ms)": lambda: list(store.read_positions(start, end, [MMSI])),
            }
            expected = dict(messages=10200, watched_messages=8000, vessels=400, max_gap_s=400)
            assert reads["current hour (ms)"]() == reads["projected hour (ms)"]() == expected
            assert len(reads["single-vessel positions (ms)"]()) == 20
            for _ in range(9):
                for label, read in reads.items():
                    t0 = perf_counter()
                    read()
                    samples[layout, label].append((perf_counter() - t0) * 1000)

            if repeat == 0:
                with closing(sqlite3.connect(store.day_path(DAY))) as conn:
                    queries = {
                        "current positions slice": ("SELECT * FROM positions WHERE ts >= ? AND ts < ?", (start, end)),
                        "projected hour": (projection_sql(TABLES), {"start": start, "end": end}),
                        "single-vessel slice": (
                            "SELECT * FROM positions WHERE ts >= ? AND ts < ? AND mmsi IN (?)", (start, end, MMSI)
                        ),
                    }
                    for label, (sql, params) in queries.items():
                        plan = [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params)]
                        print(f"{layout} {label}: {'; '.join(plan)}")

    for (layout, label), values in samples.items():
        print(f"{layout:16s} {label:28s} median {median(values):12,.3f} (n={len(values)})")


if __name__ == "__main__":
    with TemporaryDirectory(prefix="sca-053-") as scratch:
        benchmark(Path(scratch))
