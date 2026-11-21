"""F07-12: a failed static batch must not poison same-day deduplication."""

import asyncio
from dataclasses import replace
import sqlite3
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.unit import test_fleet_listener as fixture


class StaticWriteRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_static_can_recover_without_forgetting_newer_pending_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener = fixture.make_listener(tmp, watched=None, source=SimpleNamespace(id="aisstream"))
            store = listener.store
            ts = fixture.ms(fixture.NOW)
            failed = fixture.static(ts=ts - 3000)
            other_failed = fixture.static(mmsi=fixture.WATCHED, ts=ts - 3000)
            retry = replace(failed, ts=ts - 1000)
            changed = replace(other_failed, name="EXAMPLE RENAMED", ts=ts - 2000)
            restored = replace(other_failed, ts=ts - 1000)
            loop = asyncio.get_running_loop()
            writing = asyncio.Event()
            release_write = Event()

            def fail_write(*args):
                loop.call_soon_threadsafe(writing.set)
                if not release_write.wait(timeout=10):
                    raise AssertionError("test did not release the writer")
                raise sqlite3.OperationalError("synthetic disk error")

            self.assertEqual(listener.accept(failed), "statics")
            self.assertEqual(listener.accept(other_failed), "statics")
            with patch.object(store, "write", side_effect=fail_write) as write:
                flush = asyncio.create_task(listener.flush())
                try:
                    await asyncio.wait_for(writing.wait(), timeout=10)
                    self.assertIsNone(listener.accept(retry), "the first report is still in flight")
                    self.assertEqual(listener.accept(changed), "statics")
                    self.assertEqual(listener.accept(restored), "statics")
                finally:
                    release_write.set()
                    self.assertEqual(await flush, 2)
                write.assert_called_once()

            self.assertEqual(listener.counters.drops["write_error"], 2)
            self.assertIn("synthetic disk error", listener.last_error or "")
            self.assertEqual(list(store.read_statics(ts - 3000, ts + 1)), [])
            # The newest pending report has the failed report's signature, but not its generation.
            self.assertIsNone(listener.accept(replace(restored, ts=ts)), "failure forgot a newer pending report")
            self.assertEqual(listener.accept(retry), "statics", "same-day repeat of the failed write must queue")
            self.assertEqual(await listener.flush(), 3)
            self.assertIsNone(listener.accept(replace(retry, ts=ts)), "successful repeat must be deduplicated")
            self.assertEqual(await listener.flush(), 0)
            self.assertCountEqual(store.read_statics(ts - 3000, ts + 1), [changed, restored, retry])
