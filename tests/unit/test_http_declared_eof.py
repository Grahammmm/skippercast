"""Declared-length EOF: a real HTTPResponse that ends early is a TransportError (offline)."""
from http.client import HTTPResponse
from io import BytesIO
import hashlib
import tempfile
import unittest

from skippercast import http
from tests import http_fixture

URL = 'https://api.weather.gov/data'


class _Socket:
    def __init__(self, wire):
        self._wire = BytesIO(wire)

    def makefile(self, *_args, **_kwargs):
        return self._wire


def wire(body, length=None, status=200, extra=b''):
    head = b'HTTP/1.1 %d OK\r\n' % status
    if length is not None:
        head += b'Content-Length: %d\r\n' % length
    return head + extra + b'\r\n' + body


class Connection:
    def __init__(self, script):
        self.script, self.closed = script, False

    def request(self, method, target, body=None, headers=None):
        self.method = method

    def getresponse(self):
        response = HTTPResponse(_Socket(self.script.wires.pop(0)), method=self.method)
        response.begin()
        return response

    def close(self):
        self.script.closed += 1


class Script:
    def __init__(self, *wires):
        self.wires, self.closed = list(wires), 0

    def __call__(self, host, port, addresses, *, context, timeout):
        return Connection(self)


def session(*wires, **options):
    script = Script(*wires)
    built = http.Session(resolver=http_fixture.public_resolver, connection_factory=script, proxies={},
                         sleep=lambda _s: None, rand=lambda: 0.5, context=object(), allowed_hosts=None,
                         **options)
    return built, script


class DeclaredEofTests(unittest.TestCase):
    def test_premature_declared_eof_is_transport_error(self):
        with tempfile.TemporaryDirectory() as directory:
            built, script = session(wire(b'abc', 8), attempts=1, cache=http.HTTPCache(directory))
            with self.assertRaises(http.TransportError) as raised:
                built.get(URL)
            self.assertIn('IncompleteRead', str(raised.exception))
            self.assertEqual(raised.exception.receipt.attempts, 1)
            self.assertEqual(raised.exception.receipt.error_class, 'TransportError')
            self.assertEqual(script.closed, 1)
            self.assertIsNone(built.cache.lookup(URL))

    def test_retry_discards_short_attempt(self):
        built, script = session(wire(b'abc', 8), wire(b'complete', 8), attempts=2)
        sink = BytesIO()
        response = built.download(URL, sink)
        self.assertEqual(response.receipt.attempts, 2)
        self.assertEqual(sink.getvalue(), b'complete')
        self.assertEqual(response.receipt.sha256, hashlib.sha256(b'complete').hexdigest())
        self.assertEqual(script.closed, 2)
        built, _ = session(wire(b'abc', 8), wire(b'complete', 8), attempts=2)
        self.assertEqual(built.get(URL).body, b'complete')

    def test_complete_and_unknown_length_controls(self):
        for raw, expected in ((wire(b'abc', 3), b'abc'), (wire(b'', 0), b''), (wire(b'abc'), b'abc')):
            with self.subTest(expected=expected):
                response = session(raw, attempts=1)[0].get(URL)
                self.assertEqual((response.body, response.receipt.bytes, response.receipt.attempts),
                                 (expected, len(expected), 1))

    def test_sample_and_bodyless_boundaries(self):
        built, _ = session(wire(b'abcdefgh', 8), attempts=1)
        response = built.get(URL, max_bytes=3, truncate=True)
        self.assertEqual((response.body, response.receipt.truncated), (b'abcd', True))
        built, _ = session(wire(b'', 99), attempts=1)
        self.assertEqual(built.head(URL).status, 200)


if __name__ == '__main__':
    unittest.main()
