"""SqliteSink closes the connection it acquired when initialization fails (synthetic journals only)."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from skippercast.fleet import sinks
from skippercast.fleet.sinks import SinkRefused, SqliteSink

CLOCK = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)  # noqa: E731


class _Tracking:
    """Wraps a real connection; records close and can raise after really closing."""

    def __init__(self, real, close_error=None):
        self.real, self.closed, self.close_error = real, 0, close_error

    def close(self):
        self.closed += 1
        self.real.close()
        if self.close_error:
            raise self.close_error

    def __getattr__(self, name):
        return getattr(self.real, name)


class SinkInitializationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "root"
        (self.root / "drizzle" / "meta").mkdir(parents=True)
        self.db_path = self.tmp / "staging.db"
        self.conns: list[_Tracking] = []

    def journal(self, tags):
        entries = [{"idx": i, "tag": t} for i, t in enumerate(tags)]
        (self.root / "drizzle" / "meta" / "_journal.json").write_text(json.dumps({"entries": entries}))

    def migration(self, tag, sql):
        (self.root / "drizzle" / f"{tag}.sql").write_text(sql)

    def build(self, close_error=None, **kw):
        real_connect = sqlite3.connect

        def connect(*a, **k):
            t = _Tracking(real_connect(*a, **k), close_error)
            self.conns.append(t)
            return t

        with mock.patch.object(sinks.sqlite3, "connect", connect):
            return SqliteSink(self.db_path, "socal", "run-1", root=self.root, clock=CLOCK, **kw)

    def assert_closed(self):
        self.assertEqual(len(self.conns), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            self.conns[0].real.execute("SELECT 1")

    def test_missing_or_malformed_journal_closes_connection(self):
        with self.assertRaises(FileNotFoundError):
            self.build()
        self.assert_closed()
        self.conns.clear()
        (self.root / "drizzle" / "meta" / "_journal.json").write_text("{not json")
        with self.assertRaises(json.JSONDecodeError):
            self.build()
        self.assert_closed()
        self.conns.clear()
        (self.root / "drizzle" / "meta" / "_journal.json").write_text(json.dumps({"entries": [{"idx": 0}]}))
        with self.assertRaises(KeyError):
            self.build()
        self.assert_closed()

    def test_failed_migration_closes_after_rollback(self):
        self.journal(["0000_a", "0001_b"])
        self.migration("0000_a", "CREATE TABLE a (x INTEGER)")
        self.migration("0001_b", "CREATE TABLE b (x INTEGER)--> statement-breakpoint\nNOT VALID SQL")
        with self.assertRaises(sqlite3.OperationalError):
            self.build()
        self.assert_closed()
        db = sqlite3.connect(self.db_path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("SELECT tag FROM _skippercast_migrations").fetchall(), [("0000_a",)])
        names = {n for (n,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("a", names)
        self.assertNotIn("b", names)

    def test_interruption_also_closes(self):
        interrupt = KeyboardInterrupt()
        with mock.patch.object(SqliteSink, "migrate", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt) as ctx:
                self.build()
        self.assertIs(ctx.exception, interrupt)
        self.assert_closed()

    def test_close_failure_does_not_mask_initialization_error(self):
        original = RuntimeError("migration boom")
        with mock.patch.object(SqliteSink, "migrate", side_effect=original):
            with self.assertRaises(RuntimeError) as ctx:
                self.build(close_error=OSError("close boom"))
        self.assertIs(ctx.exception, original)
        self.assertEqual(self.conns[0].closed, 1)

    def test_preacquisition_failures_do_not_close_unowned_resources(self):
        connect = mock.Mock(side_effect=sqlite3.OperationalError("cannot open"))
        migrate = mock.Mock()
        with mock.patch.object(sinks.sqlite3, "connect", connect), mock.patch.object(SqliteSink, "migrate", migrate):
            with self.assertRaises(SinkRefused):
                SqliteSink(self.db_path, "BAD REGION!", "run-1", root=self.root)
            connect.assert_not_called()
            with self.assertRaises(sqlite3.OperationalError):
                SqliteSink(self.db_path, "socal", "run-1", root=self.root)
            migrate.assert_not_called()

    def test_successful_constructor_retains_normal_ownership(self):
        self.journal(["0000_a"])
        self.migration("0000_a", "CREATE TABLE a (x INTEGER)")
        sink = self.build()
        self.assertEqual(self.conns[0].closed, 0)
        self.assertEqual(sink.db.execute("SELECT count(*) FROM _skippercast_migrations").fetchone(), (1,))
        sink.migrate(self.root)  # idempotent
        self.journal(["0000_a", "0001_b"])
        self.migration("0001_b", "NOT VALID SQL")
        with self.assertRaises(sqlite3.OperationalError):
            sink.migrate(self.root)
        self.assertEqual(self.conns[0].closed, 0)
        self.assertEqual(sink.db.execute("SELECT 1").fetchone(), (1,))
        sink.close()
        self.assertEqual(self.conns[0].closed, 1)


if __name__ == "__main__":
    unittest.main()
