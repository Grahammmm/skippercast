"""skippercast.fleet.ais listener, watch list and WebSocket client (CF-41, design.md section 10).

Everything runs offline: the aisstream source is given a fake socket factory,
time and sleep are injected, and the WebSocket framing is checked against an
in-memory stream. MMSIs are synthetic (999xxxxxx); geofences are made up.
"""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from skippercast.fleet.ais import listener as listener_module
from skippercast.fleet.ais import ws
from skippercast.fleet.ais.listener import Geofence, Listener, Settings, backoff_ceiling, build_listener
from skippercast.fleet.ais.sources.aisstream import AisstreamError, AisstreamSource
from skippercast.fleet.ais.sources.base import AisPosition, AisStatic, NotConfigured
from skippercast.fleet.ais.sources.datalastic import DatalasticSource
from skippercast.fleet.ais.store import AisStore, RetentionLimits
from skippercast.fleet.ais.watch import WatchFile, WatchFileError, parse_watch, read_watch, write_watch
from tests._support import FIXTURES

AIS_FIXTURES = FIXTURES / 'fleet' / 'ais' / 'aisstream'
BBOX = ((34.0, -122.0), (36.0, -119.0))
# A made-up harbor box around (35.36, -120.9); ring is (lon, lat).
HARBOR = Geofence(((-120.95, 35.33), (-120.85, 35.33), (-120.85, 35.39), (-120.95, 35.39), (-120.95, 35.33)))
RETENTION = RetentionLimits(raw_days=30, discovery_days=7, static_days=90)
NOW = datetime(2026, 7, 4, 18, 23, tzinfo=timezone.utc).timestamp()
WATCHED = 999000101
OTHER = 999000202


def ms(epoch_s):
    return int(epoch_s * 1000)


def position(mmsi=WATCHED, lat=35.36, lon=-120.9, ts=None):
    ts = ms(NOW) - 5_000 if ts is None else ts
    return AisPosition(mmsi=mmsi, ts=ts, lat=lat, lon=lon, sog=1.0, cog=10.0, heading=10, nav_status=0,
                       msg_type='PositionReport', source='aisstream', received_at=ts + 300)


def static(mmsi=OTHER, name='EXAMPLE TWO', ts=None):
    return AisStatic(mmsi=mmsi, ts=ms(NOW) if ts is None else ts, name=name, call_sign=None, imo=None,
                     ship_type=37, dim_bow=6, dim_stern=4, dim_port=2, dim_starboard=2, ais_class='B',
                     source='aisstream')


def envelope(mmsi=WATCHED, lat=35.36, lon=-120.9):
    doc = json.loads((AIS_FIXTURES / 'position-report.json').read_text(encoding='utf-8'))
    doc['MetaData']['MMSI'] = mmsi
    body = doc['Message']['PositionReport']
    body.update(UserID=mmsi, Latitude=lat, Longitude=lon)
    return json.dumps(doc)


class Stop(Exception):
    """Ends a loop under test from inside the injected sleep."""


class FakeClock:
    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now


class FakeSocket:
    """Plays a script: strings and bytes are messages, exceptions are raised, 'hang' waits forever."""

    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        self.closed = False

    async def send(self, text):
        self.sent.append(text)

    async def recv(self):
        if not self.script:
            raise ws.ConnectionClosed(1006, 'script over')
        item = self.script.pop(0)
        if item == 'hang':
            await asyncio.Event().wait()
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self):
        self.closed = True


class Connector:
    """A fake ``connect``: each call takes the next socket script, or raises the next exception."""

    def __init__(self, *plans):
        self.plans = list(plans)
        self.sockets = []
        self.calls = 0

    async def __call__(self, url):
        self.calls += 1
        plan = self.plans.pop(0) if self.plans else ConnectionRefusedError('no route')
        if isinstance(plan, BaseException):
            raise plan
        sock = FakeSocket(plan)
        self.sockets.append(sock)
        return sock


def make_listener(tmp, connector=None, *, watched=(WATCHED,), settings=None, clock=None, sleep=None,
                  jitter=None, mmsi_filter=False, source=None):
    root = Path(tmp) / 'CA' / 'ais'
    if watched is not None:
        write_watch(root / 'watch.json', 'CA', watched)
    watch = WatchFile(root / 'watch.json', 'CA')
    watch.poll()
    return Listener(region='CA', source=source or AisstreamSource(api_key='test-key', connect=connector or Connector()),
                    store=AisStore(root), bbox=BBOX, geofences=[HARBOR], retention=RETENTION, watch=watch,
                    heartbeat_path=root / 'heartbeat.json', mmsi_filter=mmsi_filter,
                    settings=settings or Settings(), clock=clock or FakeClock(),
                    sleep=sleep or asyncio.sleep, jitter=jitter or (lambda low, high: high), git_sha='abc1234')


def recording_sleep(limit, delays, on_sleep=None):
    async def sleep(seconds):
        delays.append(seconds)
        if on_sleep:
            on_sleep(seconds)
        if len(delays) >= limit:
            raise Stop()
        await asyncio.sleep(0)
    return sleep


def rows(store, table):
    out = []
    for day in store.days():
        with closing(sqlite3.connect(store.day_path(day))) as conn:
            out += conn.execute(f'SELECT mmsi, ts FROM {table} ORDER BY mmsi, ts').fetchall()
    return out


class ReconnectTest(unittest.TestCase):
    def test_backoff_ceiling_grows_and_caps(self):
        self.assertEqual([backoff_ceiling(a) for a in range(5)], [1, 2, 4, 8, 16])
        self.assertEqual(backoff_ceiling(9), 300)
        self.assertEqual(backoff_ceiling(500), 300)

    def test_failed_connections_reconnect_with_growing_delay(self):
        with tempfile.TemporaryDirectory() as tmp:
            delays = []
            connector = Connector()   # every call refuses
            listener = make_listener(tmp, connector, sleep=recording_sleep(6, delays))
            with self.assertRaises(Stop):
                asyncio.run(listener.read_forever())
            self.assertEqual(delays, [1, 2, 4, 8, 16, 32])
            self.assertEqual(connector.calls, 6)
            self.assertEqual(listener.counters.reconnects, 6)
            self.assertIn('ConnectionRefusedError', listener.last_error)

    def test_full_jitter_draws_below_the_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            delays, bounds = [], []
            listener = make_listener(tmp, Connector(), sleep=recording_sleep(4, delays),
                                     jitter=lambda low, high: bounds.append((low, high)) or high / 2)
            with self.assertRaises(Stop):
                asyncio.run(listener.read_forever())
            self.assertEqual(bounds, [(0.0, 1), (0.0, 2), (0.0, 4), (0.0, 8)])
            self.assertEqual(delays, [0.5, 1, 2, 4])

    def test_a_connection_that_delivered_resets_the_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            delays = []
            connector = Connector(ConnectionRefusedError('down'), ConnectionRefusedError('down'),
                                  [envelope()], [envelope()])
            listener = make_listener(tmp, connector, sleep=recording_sleep(4, delays))
            with self.assertRaises(Stop):
                asyncio.run(listener.read_forever())
            # refused, refused, then two sessions that each delivered a record before dropping
            self.assertEqual(delays, [1, 2, 1, 1])
            first = json.loads(connector.sockets[0].sent[0])
            self.assertEqual(first['APIKey'], 'test-key')
            self.assertEqual(first['BoundingBoxes'], [[[34.0, -122.0], [36.0, -119.0]]])
            self.assertNotIn('FiltersShipMMSI', first)
            self.assertTrue(all(s.closed for s in connector.sockets))

    def test_idle_connection_is_dropped_and_reopened(self):
        with tempfile.TemporaryDirectory() as tmp:
            delays = []
            listener = make_listener(tmp, Connector(['hang']), sleep=recording_sleep(1, delays),
                                     settings=Settings(idle_seconds=0.05))
            with self.assertRaises(Stop):
                asyncio.run(listener.read_forever())
            self.assertEqual(listener.counters.idle_reconnects, 1)
            self.assertEqual(listener.counters.reconnects, 1)
            self.assertEqual(delays, [1])

    def test_error_frame_reconnects_and_missing_key_is_fatal(self):
        error = (AIS_FIXTURES / 'error.json').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as tmp:
            delays = []
            listener = make_listener(tmp, Connector([error]), sleep=recording_sleep(1, delays))
            with self.assertRaises(Stop):
                asyncio.run(listener.read_forever())
            self.assertIn('AisstreamError', listener.last_error)
            keyless = make_listener(tmp, source=AisstreamSource(api_key=None, connect=Connector()))
            with self.assertRaises(NotConfigured):
                asyncio.run(keyless.read_forever())
            stub = make_listener(tmp, source=DatalasticSource())
            with self.assertRaises(NotConfigured):
                asyncio.run(stub.read_forever())


class QueueTest(unittest.TestCase):
    def test_full_queue_keeps_watched_positions_over_discovery_and_statics(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp, settings=Settings(queue_max=10, batch_rows=100))
            for i in range(8):                                   # 80% full with watched positions
                self.assertEqual(listener.accept(position(ts=ms(NOW) - 60_000 + i * 1000)), 'positions')
            self.assertIsNone(listener.accept(position(mmsi=OTHER)))              # discovery shed at 80%
            self.assertEqual(listener.accept(static(mmsi=OTHER)), 'statics')       # statics still fit below 90%
            self.assertIsNone(listener.accept(static(mmsi=999000303)))           # statics shed at 90%
            self.assertEqual(listener.accept(position(ts=ms(NOW) - 1000)), 'positions')   # watched fills to 100%
            self.assertIsNone(listener.accept(position(ts=ms(NOW) - 500)))       # only now are watched dropped
            self.assertEqual(len(listener.queue), 10)
            self.assertEqual(listener.counters.drops, {'positions': 1, 'discovery': 1, 'statics': 1, 'write_error': 0})
            kinds = [table for table, _ in listener.queue]
            self.assertEqual(kinds.count('positions'), 9)
            self.assertNotIn('discovery', kinds)
            listener.write_heartbeat()
            beat = json.loads(listener.heartbeat_path.read_text())
            self.assertEqual(beat['drops']['discovery'], 1)
            self.assertEqual(beat['queue_depth'], 10)

    def test_writer_batches_by_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp, settings=Settings(batch_rows=3))
            for i in range(7):
                listener.accept(position(ts=ms(NOW) - 60_000 + i * 1000))
            self.assertTrue(listener._batch_ready.is_set())
            batch = listener.take_batch()
            self.assertEqual(len(batch['positions']), 3)
            self.assertEqual(asyncio.run(listener.flush()), 4)
            self.assertEqual(len(rows(listener.store, 'positions')), 4)   # the batch taken by hand was not written
            self.assertFalse(listener.queue)


class RoutingTest(unittest.TestCase):
    def test_unwatched_positions_outside_geofences_are_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp)
            records = [
                position(),                                       # watched, in harbor
                position(lat=34.5, lon=-121.5, ts=ms(NOW) - 4000),  # watched, at sea: kept
                position(mmsi=OTHER),                             # unwatched, in harbor: discovery
                position(mmsi=999000303, lat=34.5, lon=-121.5),   # unwatched, at sea: never written
                position(mmsi=999000404, lat=40.0, lon=-125.0),   # unwatched, outside the bbox
                static(),                                         # statics for every vessel
            ]
            tables = [listener.accept(r) for r in records]
            self.assertEqual(tables, ['positions', 'positions', 'discovery', None, None, 'statics'])
            asyncio.run(listener.flush())
            store = listener.store
            self.assertEqual({m for m, _ in rows(store, 'positions')}, {WATCHED})
            self.assertEqual(len(rows(store, 'positions')), 2)
            self.assertEqual({m for m, _ in rows(store, 'discovery')}, {OTHER})
            self.assertEqual({m for m, _ in rows(store, 'statics')}, {OTHER})
            everywhere = {m for t in ('positions', 'discovery', 'statics') for m, _ in rows(store, t)}
            self.assertNotIn(999000303, everywhere)
            self.assertNotIn(999000404, everywhere)
            self.assertEqual(listener.counters.ignored, 2)
            self.assertEqual(listener.counters.written, {'positions': 2, 'discovery': 1, 'statics': 1})

    def test_a_geofence_point_outside_the_bbox_is_not_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp)
            listener.router.bbox = ((35.37, -122.0), (36.0, -119.0))   # bbox now excludes the harbor's south half
            self.assertIsNone(listener.accept(position(mmsi=OTHER, lat=35.35)))

    def test_statics_are_deduplicated_in_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp)
            self.assertEqual(listener.accept(static()), 'statics')
            self.assertIsNone(listener.accept(static(ts=ms(NOW) + 1000)))                 # same content
            self.assertEqual(listener.accept(static(name='RENAMED', ts=ms(NOW) + 2000)), 'statics')
            next_day = ms(datetime(2026, 7, 5, 0, 0, 1, tzinfo=timezone.utc).timestamp())
            listener.clock.now = next_day / 1000
            self.assertEqual(listener.accept(static(name='RENAMED', ts=next_day)), 'statics')   # new day file

    def test_records_for_expired_days_or_far_future_are_not_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp)
            eight_days = ms(NOW) - 8 * 86_400_000
            self.assertIsNone(listener.accept(position(mmsi=OTHER, ts=eight_days)))       # discovery keeps 7
            self.assertEqual(listener.accept(position(ts=eight_days)), 'positions')        # positions keep 30
            self.assertIsNone(listener.accept(position(ts=ms(NOW) - 31 * 86_400_000)))
            self.assertIsNone(listener.accept(position(ts=ms(NOW) + 600_000)))
            self.assertEqual(listener.counters.stale, 3)


class DayFileTest(unittest.TestCase):
    def test_no_day_file_is_held_open_and_retention_runs_between_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp)
            store = listener.store
            old_day = datetime(2026, 3, 1, tzinfo=timezone.utc).date()   # past all three limits
            store.connect(old_day).close()
            listener.accept(position())
            asyncio.run(listener.flush())
            fd_dir = Path('/proc/self/fd')
            if fd_dir.is_dir():
                open_files = set()
                for entry in fd_dir.iterdir():
                    try:
                        open_files.add(os.readlink(entry))
                    except OSError:
                        pass
                self.assertFalse([p for p in open_files if '/ais/raw/' in p], open_files)
            asyncio.run(listener.retain())
            self.assertFalse(store.day_path(old_day).exists())
            self.assertTrue(store.day_path(datetime(2026, 7, 4).date()).exists())
            self.assertIsNotNone(listener.last_retention_at)

    def test_write_failures_are_counted_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            listener = make_listener(tmp)

            def broken(*args):
                raise sqlite3.OperationalError('disk I/O error')
            listener.store.write = broken
            listener.accept(position())
            asyncio.run(listener.flush())
            self.assertEqual(listener.counters.drops['write_error'], 1)
            self.assertIn('disk I/O error', listener.last_error)


class HeartbeatTest(unittest.TestCase):
    def test_heartbeat_updates_every_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock()
            beats, delays = [], []
            listener = None

            def tick(seconds):
                beats.append(json.loads(listener.heartbeat_path.read_text()))
                for i in range(30):   # 30 records per interval, 6 of them watched
                    listener.accept(position(mmsi=WATCHED if i < 6 else OTHER, ts=ms(clock.now) - 1000 - i)
                                    if i < 12 else static(mmsi=999000500 + i, ts=ms(clock.now)))
                clock.now += seconds

            listener = make_listener(tmp, clock=clock, sleep=recording_sleep(3, delays, tick))
            with self.assertRaises(Stop):
                asyncio.run(listener.heartbeat_forever())
            self.assertEqual(delays, [60.0, 60.0, 60.0])
            self.assertEqual(len(beats), 3)
            self.assertEqual([b['written_at'] for b in beats],
                             ['2026-07-04T18:23:00Z', '2026-07-04T18:24:00Z', '2026-07-04T18:25:00Z'])
            last = beats[-1]
            self.assertEqual(last['messages_per_min'], 30.0)
            self.assertEqual(last['watched_messages_per_min'], 6.0)
            self.assertEqual(last['vessels'], 20)
            self.assertEqual(last['started_at'], '2026-07-04T18:23:00Z')
            self.assertEqual(last['git_sha'], 'abc1234')
            self.assertEqual(last['watch_size'], 1)
            self.assertEqual(last['region'], 'CA')
            self.assertEqual(last['schema_version'], 1)
            self.assertNotIn('test-key', json.dumps(beats))
            self.assertEqual([p.name for p in listener.heartbeat_path.parent.iterdir() if p.name.endswith('.tmp')], [])


class WatchTest(unittest.TestCase):
    def test_format_round_trip_and_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'watch.json'
            self.assertEqual(len(read_watch(path, 'CA')), 0)    # missing file: empty list
            written = write_watch(path, 'CA', [999000202, 999000101, 999000101],
                                  generated_at=datetime(2026, 8, 1, 12, 3, 11, tzinfo=timezone.utc))
            doc = json.loads(path.read_text())
            self.assertEqual(doc, {'schema_version': 1, 'region': 'CA', 'generated_at': '2026-08-01T12:03:11Z',
                                   'watched': [999000101, 999000202]})
            self.assertEqual(read_watch(path, 'CA'), written)
            good = {'schema_version': 1, 'region': 'CA', 'generated_at': None, 'watched': [1]}
            for bad in ({**good, 'region': 'OR'}, {**good, 'schema_version': 2}, {**good, 'watched': [0]},
                        {**good, 'watched': [True]}, {**good, 'watched': [5, 5]}, {**good, 'extra': 1}, []):
                with self.assertRaises(WatchFileError):
                    parse_watch(bad, 'CA')

    def test_bad_file_keeps_the_previous_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'watch.json'
            write_watch(path, 'CA', [WATCHED])
            watch = WatchFile(path, 'CA')
            self.assertTrue(watch.poll())
            self.assertFalse(watch.poll())     # unchanged file is not re-read as a change
            path.write_text('{not json')
            self.assertFalse(watch.poll())
            self.assertEqual(watch.current.watched, {WATCHED})
            self.assertEqual(watch.errors, 1)
            write_watch(path, 'CA', [WATCHED, OTHER])
            self.assertTrue(watch.poll())
            self.assertIsNone(watch.last_error)

    def test_reload_changes_routing_and_resubscribes_in_filter_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            delays = []
            connector = Connector([envelope(), 'hang'], [envelope(mmsi=OTHER)])
            listener = make_listener(tmp, connector, mmsi_filter=True, sleep=recording_sleep(1, delays),
                                     settings=Settings(idle_seconds=5))

            async def scenario():
                reader = asyncio.ensure_future(listener.read_forever())
                for _ in range(20):
                    await asyncio.sleep(0)
                write_watch(listener.watch.path, 'CA', [WATCHED, OTHER])
                self.assertTrue(listener.reload_watch())
                for _ in range(20):
                    await asyncio.sleep(0)
                with self.assertRaises(Stop):
                    await reader

            asyncio.run(scenario())
            first, second = (json.loads(s.sent[0]) for s in connector.sockets)
            self.assertEqual(first['FiltersShipMMSI'], ['999000101'])
            self.assertEqual(second['FiltersShipMMSI'], ['999000101', '999000202'])
            self.assertEqual(listener.counters.reconnects, 1)   # the resubscribe itself is not a failure
            self.assertEqual([t for t, _ in listener.queue], ['positions', 'positions'])


class RunTest(unittest.TestCase):
    def test_run_reads_writes_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_frame = (AIS_FIXTURES / 'ship-static-data.json').read_bytes()
            frames = [envelope(), envelope(mmsi=OTHER), envelope(mmsi=999000303, lat=34.5, lon=-121.5),
                      static_frame, 'not json', 'hang']
            # the static fixture was received at 18:25:00, so the clock reads just after it
            listener = make_listener(tmp, Connector(frames), settings=Settings(batch_seconds=0.01),
                                     clock=FakeClock(NOW + 180))

            async def scenario():
                stop = asyncio.Event()
                runner = asyncio.ensure_future(listener.run(stop))
                for _ in range(200):
                    await asyncio.sleep(0.005)
                    if listener.counters.written['positions']:
                        break
                stop.set()
                await runner

            asyncio.run(scenario())
            self.assertEqual({m for m, _ in rows(listener.store, 'positions')}, {WATCHED})
            self.assertEqual({m for m, _ in rows(listener.store, 'discovery')}, {OTHER})
            self.assertEqual(len(rows(listener.store, 'statics')), 1)
            self.assertEqual(listener.counters.malformed, 1)
            beat = json.loads(listener.heartbeat_path.read_text())
            self.assertEqual(beat['queue_depth'], 0)
            self.assertEqual(beat['written']['positions'], 1)

    def test_build_listener_reads_the_region_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            built = build_listener('CA', var=Path(tmp), environ={'AISSTREAM_API_KEY': 'secret-key-value',
                                                                  'SKIPPERCAST_GIT_SHA': 'deadbeef'})
            self.assertEqual(built.heartbeat_path, Path(tmp) / 'CA' / 'ais' / 'heartbeat.json')
            self.assertEqual(built.watch.path, Path(tmp) / 'CA' / 'ais' / 'watch.json')
            self.assertEqual(built.git_sha, 'deadbeef')
            self.assertGreater(len(built.router.geofences), 1)
            self.assertNotIn('secret-key-value', repr(built.source))
            self.assertEqual(json.loads(json.dumps(built.source.subscription(built.bbox)))['APIKey'], 'secret-key-value')
            keyless = build_listener('CA', var=Path(tmp), environ={})
            with self.assertRaises(NotConfigured):
                keyless.source.subscription(keyless.bbox)


class WebSocketTest(unittest.TestCase):
    @staticmethod
    def server_frame(opcode, payload=b'', fin=True, masked=False):
        head = bytes([(0x80 if fin else 0) | opcode])
        if len(payload) < 126:
            head += bytes([(0x80 if masked else 0) | len(payload)])
        else:
            head += bytes([(0x80 if masked else 0) | 126]) + struct.pack('!H', len(payload))
        return head + (b'\0\0\0\0' if masked else b'') + payload

    class Writer:
        def __init__(self):
            self.data = bytearray()
            self.closed = False

        def write(self, chunk):
            self.data += chunk

        async def drain(self):
            pass

        def close(self):
            self.closed = True

    def open_socket(self, *frames):
        async def build():
            reader = asyncio.StreamReader()
            for frame in frames:
                reader.feed_data(frame)
            reader.feed_eof()
            writer = self.Writer()
            return ws.WebSocket(reader, writer), writer
        return build

    def test_accept_key_matches_rfc_example(self):
        self.assertEqual(ws.accept_key('dGhlIHNhbXBsZSBub25jZQ=='), 's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')

    def test_client_frames_are_masked(self):
        frame = ws.encode_frame(ws.OP_TEXT, b'Hi', mask=b'\x01\x02\x03\x04')
        self.assertEqual(frame, bytes([0x81, 0x82, 1, 2, 3, 4, ord('H') ^ 1, ord('i') ^ 2]))
        long = ws.encode_frame(ws.OP_TEXT, b'x' * 300, mask=b'\0\0\0\0')
        self.assertEqual(long[1], 0x80 | 126)
        self.assertEqual(struct.unpack('!H', long[2:4])[0], 300)

    def test_messages_ping_fragments_and_close(self):
        async def scenario():
            sock, writer = await self.open_socket(
                self.server_frame(ws.OP_PING, b'p'),
                self.server_frame(ws.OP_BINARY, b'{"a":', fin=False),
                self.server_frame(ws.OP_CONT, b'1}'),
                self.server_frame(ws.OP_TEXT, 'é'.encode()),
                self.server_frame(ws.OP_CLOSE, struct.pack('!H', 1001) + b'bye'))()
            self.assertEqual(await sock.recv(), b'{"a":1}')
            self.assertEqual(writer.data[0], 0x80 | ws.OP_PONG)
            self.assertEqual(await sock.recv(), 'é')
            with self.assertRaises(ws.ConnectionClosed) as caught:
                await sock.recv()
            self.assertEqual(caught.exception.code, 1001)
            self.assertTrue(writer.closed)
        asyncio.run(scenario())

    def test_protocol_errors_and_eof(self):
        async def first_error(*frames):
            sock, _ = await self.open_socket(*frames)()
            try:
                await sock.recv()
            except ConnectionError as error:
                return error
        self.assertIsInstance(asyncio.run(first_error(self.server_frame(ws.OP_TEXT, b'x', masked=True))),
                              ws.ProtocolError)
        self.assertIsInstance(asyncio.run(first_error(bytes([0xC1, 0x01]) + b'x')), ws.ProtocolError)   # RSV1
        self.assertIsInstance(asyncio.run(first_error(self.server_frame(ws.OP_CONT, b'x'))), ws.ProtocolError)
        self.assertIsInstance(asyncio.run(first_error(self.server_frame(ws.OP_TEXT, b'\xff'))), ws.ProtocolError)
        self.assertIsInstance(asyncio.run(first_error(b'\x81')), ws.ConnectionClosed)

    def test_handshake_checks_the_accept_key(self):
        key = 'dGhlIHNhbXBsZSBub25jZQ=='

        def check(response):
            async def run():
                reader = asyncio.StreamReader()
                reader.feed_data(response.encode())
                reader.feed_eof()
                await ws.handshake_response(reader, key)
            asyncio.run(run())

        good = ('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                'Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n')
        check(good)
        for bad in (good.replace('101 Switching Protocols', '401 Unauthorized'),
                    good.replace('s3pPLMBiTxaQ9kYGzzhZRbK+xOo=', 'wrong='),
                    good.replace('\r\n\r\n', '\r\nSec-WebSocket-Extensions: permessage-deflate\r\n\r\n'),
                    'HTTP/1.1 101'):
            with self.assertRaises(ws.HandshakeError):
                check(bad)

    def test_connect_refuses_plain_ws(self):
        with self.assertRaises(ValueError):
            asyncio.run(ws.connect('ws://stream.aisstream.io/v0/stream'))


if __name__ == '__main__':
    unittest.main()
