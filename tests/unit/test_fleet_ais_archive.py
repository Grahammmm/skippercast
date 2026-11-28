"""skippercast.fleet.ais archive: the long-term copy of closed raw day files.

Synthetic MMSIs (999xxxxxx) only.
"""
from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from unittest import mock

from skippercast.fleet.ais import __main__ as ais_cli
from skippercast.fleet.ais.archive import archive
from skippercast.fleet.ais.sources.base import AisPosition
from skippercast.fleet.ais.store import AisStore, RetentionLimits

TODAY = date(2026, 11, 28)


def ms(y, m, d, h=12):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def pos(ts, mmsi=999000001):
    return AisPosition(mmsi=mmsi, ts=ts, lat=35.3, lon=-120.9, sog=2.0, cog=90.0, heading=90, nav_status=0,
                       msg_type="PositionReport", source="aisstream", received_at=ts + 1000)


def count(path, table="positions"):
    with closing(sqlite3.connect(path)) as con:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.store = AisStore(base / "ais")
        self.raw = self.store.root / "raw"
        self.dest = base / "archive" / "CA"

    def tearDown(self):
        self.tmp.cleanup()

    def test_copies_closed_days_only(self):
        self.store.write(positions=[pos(ms(2026, 11, 26)), pos(ms(2026, 11, 27)), pos(ms(2026, 11, 28))])
        result = archive(self.raw, self.dest, today=TODAY, min_free_bytes=0)
        self.assertEqual((result.files, result.copied, result.open_days, result.rows), (2, 2, 1, 2))
        archive(self.raw, self.dest, today=TODAY, min_free_bytes=0)   # reading the copies leaves no sidecars
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["2026-11-26.sqlite", "2026-11-27.sqlite"])
        self.assertEqual(count(self.dest / "2026-11-27.sqlite"), 1)
        self.assertEqual(count(self.raw / "2026-11-28.sqlite"), 1, "the store is only read")

    def test_rerun_keeps_and_late_rows_replace(self):
        self.store.write(positions=[pos(ms(2026, 11, 27))])
        archive(self.raw, self.dest, today=TODAY, min_free_bytes=0)
        again = archive(self.raw, self.dest, today=TODAY, min_free_bytes=0)
        self.assertEqual((again.copied, again.kept), (0, 1))
        self.store.write(positions=[pos(ms(2026, 11, 27, 13), mmsi=999000002)])   # a late receipt
        late = archive(self.raw, self.dest, today=TODAY, min_free_bytes=0)
        self.assertEqual(late.copied, 1)
        self.assertEqual(count(self.dest / "2026-11-27.sqlite"), 2)

    def test_retention_emptied_file_never_overwrites_archive(self):
        self.store.write(positions=[pos(ms(2026, 10, 1)), pos(ms(2026, 10, 1, 13), mmsi=999000002)])
        archive(self.raw, self.dest, today=date(2026, 10, 2), min_free_bytes=0)
        self.store.apply_retention(RetentionLimits(30, 400, 400), today=TODAY)
        self.assertEqual(count(self.raw / "2026-10-01.sqlite"), 0, "retention emptied the store copy")
        result = archive(self.raw, self.dest, today=TODAY, min_free_bytes=0)
        self.assertEqual((result.copied, result.kept), (0, 1))
        self.assertEqual(count(self.dest / "2026-10-01.sqlite"), 2)

    def test_low_space_copies_nothing(self):
        self.store.write(positions=[pos(ms(2026, 11, 27))])
        result = archive(self.raw, self.dest, today=TODAY, min_free_bytes=float("inf"))
        self.assertTrue(result.low_space)
        self.assertEqual(result.copied, 0)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_cli_needs_destination_and_prints_counts_only(self):
        base = Path(self.tmp.name)
        AisStore.for_region("CA", base).write(positions=[pos(ms(2020, 1, 1))])
        env = {"SKIPPERCAST_FLEET_VAR": str(base)}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("SKIPPERCAST_FLEET_ARCHIVE", None)
            self.assertEqual(ais_cli.main(["archive", "--region", "CA"]), 2)
            out = io.StringIO()
            with redirect_stdout(out):
                code = ais_cli.main(["archive", "--region", "CA", "--dest", str(base / "arc"),
                                     "--min-free-gb", "0"])
        self.assertEqual(code, 0)
        line = json.loads(out.getvalue())
        self.assertEqual(line["archive"]["copied"], 1)
        self.assertNotIn("999000001", out.getvalue())
        self.assertTrue((base / "arc" / "CA" / "2020-01-01.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
