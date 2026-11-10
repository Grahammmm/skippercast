"""RF1345-6: a watch.json the JSON parser refuses with a plain ValueError (an integer
longer than Python's integer-digit limit) follows the malformed-file path: the last
good list is kept, the refusal is counted once per file version, and a corrected
file is picked up. Polling, reload and listener startup stay alive.

Synthetic 999xxxxxx MMSIs and temporary directories only; no network.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from skippercast.fleet.ais import listener as listener_module
from skippercast.fleet.ais import watch as watch_module
from skippercast.fleet.ais.watch import WatchFile, WatchFileError, read_watch, write_watch
from tests.unit.test_fleet_listener import (OTHER, WATCHED, FakeClock, FakeSource, NOW, Settings, make_listener,
                                            position, position_from, run_until, stored)

LIMIT = 640          # the smallest finite limit Python accepts
DIGITS = LIMIT + 60  # a decimal token longer than LIMIT digits
NOT_JSON = 'watch.json is not JSON'
OVERSIZED_SCHEMA = '{"schema_version":1' + '0' * DIGITS + ',"region":"CA","generated_at":null,"watched":[999000101]}\n'
OVERSIZED_MMSI = '{"schema_version":1,"region":"CA","generated_at":null,"watched":[' + '9' * DIGITS + ']}\n'


@contextmanager
def digit_limit(limit=LIMIT):
    """Set a finite integer-digit limit for the test and always restore the host's."""
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(limit)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(previous)


def replace_text(path: Path, text: str) -> bytes:
    """Atomically replace ``path`` (temporary file, then rename) as the producer does; returns the bytes."""
    temporary = path.with_name(f'.{path.name}.test.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)
    return path.read_bytes()


class ReaderTest(unittest.TestCase):
    def test_oversized_json_integer_becomes_watch_file_error(self):
        with tempfile.TemporaryDirectory() as tmp, digit_limit():
            path = Path(tmp) / 'watch.json'
            for name, text in (('schema_version', OVERSIZED_SCHEMA), ('watched[0]', OVERSIZED_MMSI)):
                with self.subTest(token=name):
                    replace_text(path, text)
                    with self.assertRaises(ValueError):   # the parser itself refuses the token
                        json.loads(text)
                    with self.assertRaises(WatchFileError) as caught:
                        read_watch(path, 'CA')
                    self.assertEqual(str(caught.exception), NOT_JSON)
                    self.assertIsNone(caught.exception.__cause__)
                    self.assertTrue(caught.exception.__suppress_context__)
            written = write_watch(path, 'CA', [WATCHED, OTHER])
            self.assertEqual(read_watch(path, 'CA'), written)

    def test_parser_value_error_is_translated_without_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'watch.json'
            write_watch(path, 'CA', [WATCHED])
            marker = 'private-parser-detail-999000303'
            with mock.patch.object(watch_module.json, 'loads', side_effect=ValueError(marker)):
                with self.assertRaises(WatchFileError) as caught:
                    read_watch(path, 'CA')
            self.assertEqual(str(caught.exception), NOT_JSON)
            self.assertNotIn(marker, str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
            path.write_text('{not json', encoding='utf-8')
            with self.assertRaises(WatchFileError) as caught:
                read_watch(path, 'CA')
            self.assertEqual(str(caught.exception), NOT_JSON)

    def test_unrelated_parser_failures_still_propagate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'watch.json'
            write_watch(path, 'CA', [WATCHED])
            watch = WatchFile(path, 'CA')
            replace_text(path, path.read_text(encoding='utf-8'))
            with mock.patch.object(watch_module.json, 'loads', side_effect=RuntimeError('unrelated')):
                with self.assertRaises(RuntimeError):
                    read_watch(path, 'CA')
                with self.assertRaises(RuntimeError):
                    watch.poll()
            self.assertEqual(watch.errors, 0)


class PollTest(unittest.TestCase):
    def test_poll_preserves_good_list_and_bounds_repeated_bad_stamp(self):
        with tempfile.TemporaryDirectory() as tmp, digit_limit():
            path = Path(tmp) / 'watch.json'
            write_watch(path, 'CA', [WATCHED])
            watch = WatchFile(path, 'CA')
            self.assertTrue(watch.poll())
            good, generated = watch.current, watch.current.generated_at
            bad = replace_text(path, OVERSIZED_MMSI)
            with mock.patch.object(watch_module, 'read_watch', wraps=read_watch) as read:
                for _ in range(3):   # the bad version is read and counted once, then left alone
                    self.assertFalse(watch.poll())
                    self.assertIs(watch.current, good)
                    self.assertEqual(watch.current.generated_at, generated)
                    self.assertEqual(watch.errors, 1)
                    self.assertEqual(watch.last_error, NOT_JSON)
                    self.assertEqual(path.read_bytes(), bad)
                self.assertEqual(read.call_count, 1)
            replace_text(path, OVERSIZED_SCHEMA)   # a new bad version counts once more
            self.assertFalse(watch.poll())
            self.assertIs(watch.current, good)
            self.assertEqual(watch.errors, 2)
            write_watch(path, 'CA', [WATCHED, OTHER])
            self.assertTrue(watch.poll())
            self.assertEqual(watch.current.watched, {WATCHED, OTHER})
            self.assertIsNone(watch.last_error)
            self.assertEqual(watch.errors, 2)

    def test_invalid_initial_watch_remains_empty_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp, digit_limit():
            path = Path(tmp) / 'watch.json'
            bad = replace_text(path, OVERSIZED_SCHEMA)
            watch = WatchFile(path, 'CA')
            with mock.patch.object(watch_module, 'read_watch', wraps=read_watch) as read:
                for _ in range(2):
                    self.assertFalse(watch.poll())
                    self.assertEqual(len(watch.current), 0)
                    self.assertEqual(watch.errors, 1)
                    self.assertEqual(watch.last_error, NOT_JSON)
                    self.assertEqual(path.read_bytes(), bad)
                self.assertEqual(read.call_count, 1)
            write_watch(path, 'CA', [WATCHED])
            self.assertTrue(watch.poll())
            self.assertEqual(watch.current.watched, {WATCHED})
            self.assertIsNone(watch.last_error)


class ListenerTest(unittest.TestCase):
    def test_listener_reload_and_startup_survive_parser_limit(self):
        with tempfile.TemporaryDirectory() as tmp, digit_limit():
            source = FakeSource('aisstream', [position_from('aisstream'), 'hang'])
            listener = make_listener(tmp, source=source, settings=Settings(batch_seconds=0.01),
                                     clock=FakeClock(NOW + 60))
            good = listener.watch.current
            replace_text(listener.watch.path, OVERSIZED_MMSI)
            with self.assertLogs(listener_module.log, level='WARNING') as logs:
                run_until(listener, lambda: listener.counters.written['positions'])   # run() reloads first
            self.assertIn(NOT_JSON, '\n'.join(logs.output))
            self.assertIs(listener.watch.current, good)
            self.assertEqual(listener.watch.errors, 1)
            self.assertEqual({m for m, _, _ in stored(listener)}, {WATCHED})
            beat = json.loads(listener.heartbeat_path.read_text())
            self.assertEqual((beat['watch_size'], beat['watch_errors']), (1, 1))
            self.assertFalse(listener.reload_watch())   # the same bad version is not counted again
            self.assertEqual(listener.watch.errors, 1)
            write_watch(listener.watch.path, 'CA', [OTHER])
            self.assertTrue(listener.reload_watch())
            self.assertIsNone(listener.watch.last_error)
            self.assertEqual(listener.accept(position(mmsi=OTHER, lat=34.5, lon=-121.5)), 'positions')
            self.assertIsNone(listener.accept(position(lat=34.5, lon=-121.5)))

    def test_listener_starts_with_an_initially_refused_watch(self):
        with tempfile.TemporaryDirectory() as tmp, digit_limit():
            source = FakeSource('aisstream', [position_from('aisstream'), 'hang'])
            listener = make_listener(tmp, source=source, watched=None, settings=Settings(batch_seconds=0.01),
                                     clock=FakeClock(NOW + 60))
            listener.watch.path.parent.mkdir(parents=True, exist_ok=True)
            replace_text(listener.watch.path, OVERSIZED_SCHEMA)
            run_until(listener, lambda: listener.heartbeat_path.exists() and listener.watch.errors)
            self.assertEqual(len(listener.watch.current), 0)
            self.assertEqual(listener.watch.errors, 1)
            self.assertEqual(json.loads(listener.heartbeat_path.read_text())['watch_errors'], 1)
            write_watch(listener.watch.path, 'CA', [WATCHED])
            self.assertTrue(listener.reload_watch())
            self.assertEqual(listener.watch.current.watched, {WATCHED})
            self.assertIsNone(listener.watch.last_error)


if __name__ == '__main__':
    unittest.main()
