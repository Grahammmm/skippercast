"""AIS WebSocket client: an abrupt EOF releases the writer at once (RF0824-9). Offline, no sockets."""
import asyncio
import json
import struct
import unittest

from skippercast.fleet.ais import ws
from skippercast.fleet.ais.sources.aisstream import AisstreamSource
from skippercast.fleet.ais.sources.base import AisPosition
from tests._support import FIXTURES

POSITION = FIXTURES / 'fleet' / 'ais' / 'aisstream' / 'position-report.json'


def server_frame(opcode, payload=b'', fin=True):
    head = bytes([(0x80 if fin else 0) | opcode])
    if len(payload) < 126:
        return head + bytes([len(payload)]) + payload
    return head + bytes([126]) + struct.pack('!H', len(payload)) + payload


class SpyWriter:
    def __init__(self):
        self.close_calls = 0
        self.writes = []
        self.drains = 0

    def write(self, data):
        self.writes.append(data)

    async def drain(self):
        self.drains += 1

    def close(self):
        self.close_calls += 1


def make(data):
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    writer = SpyWriter()
    return ws.WebSocket(reader, writer), writer


EOF_CASES = {
    'empty': b'',
    'one-header-byte': b'\x81',
    'truncated-16-bit-length': b'\x81\x7e\x01',
    'truncated-64-bit-length': b'\x81\x7f\x00\x00',
    'truncated-payload': b'\x81\x05ab',
    'fragment-then-eof': server_frame(ws.OP_TEXT, b'ab', fin=False),
}


class AbruptEofTests(unittest.IsolatedAsyncioTestCase):
    async def test_eof_closes_writer_at_each_frame_read_boundary(self):
        for name, data in EOF_CASES.items():
            with self.subTest(name):
                sock, writer = make(data)
                with self.assertRaises(ws.ConnectionClosed) as caught:
                    await sock.recv()
                self.assertIsNone(caught.exception.code)
                self.assertEqual(caught.exception.reason, 'stream ended')
                self.assertEqual(writer.close_calls, 1)
                self.assertEqual((writer.writes, writer.drains), ([], 0))

    async def test_close_after_eof_is_idempotent(self):
        for name, data in EOF_CASES.items():
            with self.subTest(name):
                sock, writer = make(data)
                with self.assertRaises(ws.ConnectionClosed):
                    await sock.recv()
                await sock.close()
                await sock.close()
                with self.assertRaises(ws.ConnectionClosed):
                    await sock.send('x')
                with self.assertRaises(ws.ConnectionClosed):
                    await sock.recv()
                self.assertEqual(writer.close_calls, 1)
                self.assertEqual((writer.writes, writer.drains), ([], 0))

    async def test_graceful_close_and_explicit_close_still_release_once(self):
        sock, writer = make(server_frame(ws.OP_CLOSE, struct.pack('!H', 1000) + b'bye'))
        with self.assertRaises(ws.ConnectionClosed) as caught:
            await sock.recv()
        self.assertEqual((caught.exception.code, caught.exception.reason), (1000, 'bye'))
        self.assertEqual(writer.close_calls, 1)
        self.assertEqual(len(writer.writes), 1)   # the close handshake reply
        self.assertEqual(writer.writes[0][0], 0x80 | ws.OP_CLOSE)
        await sock.close()
        self.assertEqual((writer.close_calls, len(writer.writes)), (1, 1))

        sock, writer = make(b'')
        await sock.close()
        await sock.close()
        self.assertEqual((writer.close_calls, len(writer.writes)), (1, 1))
        with self.assertRaises(ws.ConnectionClosed):
            await sock.recv()
        self.assertEqual(writer.close_calls, 1)

    async def test_aisstream_finally_releases_eof_transport(self):
        envelope = json.dumps(json.loads(POSITION.read_text(encoding='utf-8')))
        for name, frames in (('before-envelope', b''), ('after-position', server_frame(ws.OP_TEXT, envelope.encode()))):
            with self.subTest(name):
                sock, writer = make(frames)
                malformed = []

                async def connect(url):
                    return sock

                source = AisstreamSource(api_key='fictional-test-key', connect=connect, on_malformed=malformed.append)
                seen = []
                with self.assertRaises(ws.ConnectionClosed) as caught:
                    async for record in source.stream(((34.0, -122.0), (36.0, -119.0)), {999000123}):
                        seen.append(record)
                self.assertEqual((caught.exception.code, caught.exception.reason), (None, 'stream ended'))
                self.assertEqual(malformed, [])
                self.assertEqual(len(seen) > 0, name == 'after-position')
                if seen:
                    self.assertIsInstance(seen[0], AisPosition)
                self.assertEqual(writer.close_calls, 1)
                await sock.close()
                self.assertEqual(writer.close_calls, 1)
                self.assertEqual(len(writer.writes), 1)   # only the subscription


if __name__ == '__main__':
    unittest.main()
