"""skippercast.fleet.ais archive: the long-term copy of closed raw day files.

Synthetic MMSIs (999xxxxxx) only.
"""
from datetime import date, datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from unittest import mock

from skippercast.fleet.ais import __main__ as ais_cli
from skippercast.fleet.ais import archive as archive_mod
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

    def names(self):
        return sorted(p.name for p in self.dest.iterdir())

    def test_copies_closed_days_only(self):
        self.store.write(positions=[pos(ms(2026, 11, 26)), pos(ms(2026, 11, 27)), pos(ms(2026, 11, 28))])
        result = archive(self.raw, self.dest, today=TODAY)
        self.assertEqual((result.files, result.copied, result.open_days, result.rows), (2, 2, 1, 2))
        archive(self.raw, self.dest, today=TODAY)   # reading the copies leaves no sidecars
        self.assertEqual(self.names(), [".archive.lock", "2026-11-26.sqlite", "2026-11-27.sqlite"])
        self.assertEqual(count(self.dest / "2026-11-27.sqlite"), 1)
        self.assertEqual(count(self.raw / "2026-11-28.sqlite"), 1, "the store is only read")

    def test_rerun_keeps_and_late_rows_replace(self):
        self.store.write(positions=[pos(ms(2026, 11, 27))])
        archive(self.raw, self.dest, today=TODAY)
        again = archive(self.raw, self.dest, today=TODAY)
        self.assertEqual((again.copied, again.kept), (0, 1))
        self.store.write(positions=[pos(ms(2026, 11, 27, 13), mmsi=999000002)])   # a late receipt
        late = archive(self.raw, self.dest, today=TODAY)
        self.assertEqual(late.copied, 1)
        self.assertEqual(count(self.dest / "2026-11-27.sqlite"), 2)

    def test_retention_emptied_file_never_overwrites_archive(self):
        self.store.write(positions=[pos(ms(2026, 10, 1)), pos(ms(2026, 10, 1, 13), mmsi=999000002)])
        archive(self.raw, self.dest, today=date(2026, 10, 2))
        self.store.apply_retention(RetentionLimits(30, 400, 400), today=TODAY)
        self.assertEqual(count(self.raw / "2026-10-01.sqlite"), 0, "retention emptied the store copy")
        result = archive(self.raw, self.dest, today=TODAY)
        self.assertEqual((result.copied, result.kept), (0, 1))
        self.assertEqual(count(self.dest / "2026-10-01.sqlite"), 2)

    def test_retention_during_the_run_never_overwrites_archive(self):
        day = self.raw / "2026-10-01.sqlite"
        self.store.write(positions=[pos(ms(2026, 10, 1)), pos(ms(2026, 10, 1, 13), mmsi=999000002)])
        archive(self.raw, self.dest, today=TODAY)
        self.store.write(positions=[pos(ms(2026, 10, 1, 14), mmsi=999000003)])   # now 3 rows: picked for a copy
        real = archive_mod._snapshot

        def retention_first(src, tmp):   # retention empties the day between the pre-count and the backup
            with closing(sqlite3.connect(src)) as con, con:
                con.execute("DELETE FROM positions")
            real(src, tmp)

        with mock.patch.object(archive_mod, "_snapshot", retention_first):
            result = archive(self.raw, self.dest, today=TODAY)
        self.assertEqual((result.copied, result.kept, result.rows), (0, 1, 0))
        self.assertEqual(count(self.dest / day.name), 2)
        self.assertFalse((self.dest / (day.name + ".part")).exists())

    def test_disk_full_during_a_snapshot_leaves_no_part(self):
        # The checker's case: the first day is copied, the second day's snapshot is created and then
        # the disk fills (SQLITE_FULL). The failed .part goes, the complete first copy stays, exit 1.
        self.store.write(positions=[pos(ms(2026, 11, 26)), pos(ms(2026, 11, 27))])
        real = archive_mod._snapshot

        def full_on_second(src, tmp):
            if src.name == "2026-11-27.sqlite":
                os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
                raise sqlite3.OperationalError("database or disk is full")
            real(src, tmp)

        with mock.patch.object(archive_mod, "_snapshot", full_on_second):
            result = archive(self.raw, self.dest, today=TODAY)
        self.assertTrue(result.failed)
        self.assertEqual((result.copied, result.rows), (1, 1))
        self.assertEqual(self.names(), [".archive.lock", "2026-11-26.sqlite"], "no .part left")
        self.assertEqual(count(self.dest / "2026-11-26.sqlite"), 1)
        retry = archive(self.raw, self.dest, today=TODAY)   # space freed: the next run finishes the job
        self.assertEqual((retry.failed, retry.copied, retry.kept), (False, 1, 1))

    def test_failed_replace_keeps_the_older_copy_and_leaves_no_part(self):
        self.store.write(positions=[pos(ms(2026, 11, 27))])
        archive(self.raw, self.dest, today=TODAY)
        self.store.write(positions=[pos(ms(2026, 11, 27, 13), mmsi=999000002)])
        with mock.patch.object(archive_mod.os, "replace", side_effect=OSError(28, "No space left on device")):
            result = archive(self.raw, self.dest, today=TODAY)
        self.assertEqual((result.failed, result.copied), (True, 0))
        self.assertEqual(self.names(), [".archive.lock", "2026-11-27.sqlite"])
        self.assertEqual(count(self.dest / "2026-11-27.sqlite"), 1, "the older complete copy stays")

    def test_cli_exits_1_when_a_snapshot_fails(self):
        base = Path(self.tmp.name)
        AisStore.for_region("CA", base).write(positions=[pos(ms(2020, 1, 1))])
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(base)}, clear=False), \
                mock.patch.object(archive_mod, "_snapshot",
                                  side_effect=sqlite3.OperationalError("database or disk is full")), \
                redirect_stdout(out):
            code = ais_cli.main(["archive", "--region", "CA", "--dest", str(base / "arc")])
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(out.getvalue())["archive"]["failed"])

    def test_second_run_waits_for_the_lock(self):
        self.store.write(positions=[pos(ms(2026, 11, 27))])
        self.dest.mkdir(parents=True)
        with open(self.dest / ".archive.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            result = archive(self.raw, self.dest, today=TODAY)
        self.assertTrue(result.busy)
        self.assertEqual(result.copied, 0)
        self.assertFalse((self.dest / "2026-11-27.sqlite").exists())
        self.assertEqual(archive(self.raw, self.dest, today=TODAY).copied, 1)

    def test_copies_are_private_whatever_the_umask(self):
        self.store.write(positions=[pos(ms(2026, 11, 27))])
        dest = Path(self.tmp.name) / "fresh" / "CA"
        old = os.umask(0o022)
        try:
            archive(self.raw, dest, today=TODAY)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(dest.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((dest / "2026-11-27.sqlite").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((dest / ".archive.lock").stat().st_mode), 0o600)

    def test_cli_needs_destination_and_prints_counts_only(self):
        base = Path(self.tmp.name)
        AisStore.for_region("CA", base).write(positions=[pos(ms(2020, 1, 1))])
        env = {"SKIPPERCAST_FLEET_VAR": str(base)}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("SKIPPERCAST_FLEET_ARCHIVE", None)
            self.assertEqual(ais_cli.main(["archive", "--region", "CA"]), 2)
            out = io.StringIO()
            with redirect_stdout(out):
                code = ais_cli.main(["archive", "--region", "CA", "--dest", str(base / "arc")])
        self.assertEqual(code, 0)
        line = json.loads(out.getvalue())
        self.assertEqual(line["archive"]["copied"], 1)
        self.assertNotIn("999000001", out.getvalue())
        self.assertTrue((base / "arc" / "CA" / "2020-01-01.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
