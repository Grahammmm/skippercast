"""AIS WebSocket client: invalid UTF-8 close reasons are a protocol error (RF1951-3). Offline."""
import asyncio
import struct
import unittest

from skippercast.fleet.ais import ws


def frame(opcode, payload=b''):
    return bytes([0x80 | opcode, len(payload)]) + payload


class SpyWriter:
    def __init__(self):
        self.close_calls = 0
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    async def drain(self):
        pass

    def close(self):
        self.close_calls += 1


def make(data):
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    writer = SpyWriter()
    return ws.WebSocket(reader, writer), writer


def close_frame(reason):
    return frame(ws.OP_CLOSE, struct.pack('!H', 1000) + reason)


class CloseReasonUtf8Tests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_close_reason_is_protocol_error(self):
        sock, _ = make(close_frame(b'\xff'))
        with self.assertRaises(ws.ProtocolError) as caught:
            await sock.recv()
        self.assertNotIsInstance(caught.exception, ws.ConnectionClosed)

    async def test_truncated_multibyte_close_reason_is_refused(self):
        for name, reason in {'truncated': b'ok\xe2\x82', 'surrogate': b'\xed\xa0\x80'}.items():
            with self.subTest(name):
                sock, writer = make(close_frame(reason))
                with self.assertRaises(ws.ProtocolError) as caught:
                    await sock.recv()
                self.assertEqual(str(caught.exception), 'close reason is not UTF-8')
                self.assertIsNone(caught.exception.__cause__)
                await sock.close()
                await sock.close()
                self.assertEqual(writer.close_calls, 1)

    async def test_valid_close_reason_controls(self):
        for name, reason in {'ascii': 'bye', 'unicode': 'ça va \u2603', 'empty': ''}.items():
            with self.subTest(name):
                sock, writer = make(close_frame(reason.encode('utf-8')))
                with self.assertRaises(ws.ConnectionClosed) as caught:
                    await sock.recv()
                self.assertEqual((caught.exception.code, caught.exception.reason), (1000, reason))
                self.assertEqual(writer.close_calls, 1)
                self.assertEqual(len(writer.writes), 1)
                self.assertEqual(writer.writes[0][0], 0x80 | ws.OP_CLOSE)

    async def test_invalid_text_still_uses_existing_error(self):
        sock, _ = make(frame(ws.OP_TEXT, b'\xff'))
        with self.assertRaises(ws.ProtocolError) as caught:
            await sock.recv()
        self.assertEqual(str(caught.exception), 'text message is not UTF-8')


if __name__ == '__main__':
    unittest.main()
