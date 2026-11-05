"""Gzip responses: every member is decoded under one aggregate bound, or the response is refused."""
import gzip
import hashlib
from pathlib import Path
import tempfile
import unittest

from skippercast import http
from tests import http_fixture

URL = 'https://www.example.com/data'
A, B = b'A' * 100, b'B' * 100


def member(data):
    return gzip.compress(data)


def get(wire, *, encoding='gzip', **options):
    headers = {'Content-Encoding': encoding}
    options.setdefault('allowed_hosts', ['www.example.com'])
    session, _, sleeps = http_fixture.session((200, wire, headers), **options)
    return session, sleeps


class GzipMembers(unittest.TestCase):
    def test_members_are_concatenated_in_order(self):
        for encoding in ('gzip', 'x-gzip'):
            with self.subTest(encoding=encoding):
                wire = member(A) + member(b'') + member(B) + member(b'C')
                session, _ = get(wire, encoding=encoding)
                response = session.get(URL, max_bytes=1000)
                expected = A + B + b'C'
                self.assertEqual(response.body, expected)
                self.assertEqual((response.receipt.bytes, response.receipt.compressed_bytes), (201, len(wire)))
                self.assertEqual(response.receipt.sha256, hashlib.sha256(expected).hexdigest())

    def test_aggregate_bound(self):
        wire = member(A) + member(B)
        self.assertEqual(get(wire)[0].get(URL, max_bytes=200).body, A + B)
        with self.assertRaises(http.BodyTooLarge) as raised:
            get(wire)[0].get(URL, max_bytes=199)
        self.assertEqual(raised.exception.receipt.attempts, 1)
        bomb = member(A) + member(b'\0' * 1_000_000)
        with self.assertRaises(http.BodyTooLarge):
            get(bomb)[0].get(URL, max_bytes=10_000)
        self.assertEqual(len(get(bomb)[0].get(URL, max_bytes=None).body), 1_000_100)

    def test_malformed_tails_refuse_the_whole_response(self):
        bad_crc = bytearray(member(B))
        bad_crc[-5] ^= 0xFF
        second = member(B)
        cases = {'crc': member(A) + bytes(bad_crc), 'truncated-trailer': member(A) + second[:-4],
                 'truncated-header': member(A) + second[:5], 'junk': member(A) + b'trailing text',
                 'padding-then-junk': member(A) + b'\0\0\0junk', 'empty': b''}
        for name, wire in cases.items():
            with self.subTest(case=name):
                session, sleeps = get(wire)
                with self.assertRaises(http.ContractError) as raised:
                    session.get(URL, max_bytes=1000)
                self.assertNotIsInstance(raised.exception, http.BodyTooLarge)
                receipt = raised.exception.receipt
                self.assertEqual((receipt.attempts, sleeps, receipt.error_class), (1, [], 'ContractError'))

    def test_empty_member_and_terminal_zero_padding(self):
        self.assertEqual(get(member(b''))[0].get(URL, max_bytes=1000).body, b'')
        response = get(member(A) + b'\0' * 7)[0].get(URL, max_bytes=1000)
        self.assertEqual(response.body, A)

    def test_zero_limit_at_the_decoder_seam(self):
        session = get(b'')[0]
        self.assertEqual(session._decode(member(b''), {'Content-Encoding': 'gzip'}, 0)[0], b'')
        with self.assertRaises(http.BodyTooLarge):
            session._decode(member(b'x'), {'Content-Encoding': 'gzip'}, 0)
        with self.assertRaises(http.BodyTooLarge):
            session._decode(member(b'') + member(b'x'), {'Content-Encoding': 'gzip'}, 0)

    def test_refused_gzip_is_not_cached(self):
        wire = member(A) + b'junk'
        with tempfile.TemporaryDirectory() as tmp:
            session, _, _ = http_fixture.session((200, wire, {'Content-Encoding': 'gzip', 'ETag': '"v1"'}),
                                                 allowed_hosts=['www.example.com'], cache=tmp)
            with self.assertRaises(http.ContractError):
                session.get(URL, max_bytes=1000)
            self.assertEqual([p for p in Path(tmp).rglob('*') if p.is_file()], [])


if __name__ == '__main__':
    unittest.main()
