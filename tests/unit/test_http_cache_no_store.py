"""Response Cache-Control no-store is honored by the conditional HTTP cache (offline)."""
from pathlib import Path
import tempfile
import unittest

from skippercast import http
from tests import http_fixture

URL = 'https://source.test/feed'
OTHER = 'https://source.test/other'
ETAG = {'ETag': '"v1"'}


def files(directory):
    return sorted(Path(directory).iterdir())


class NoStoreCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = http.HTTPCache(Path(self.tmp.name))

    def session(self, *replies):
        return http_fixture.session(*replies, cache=self.cache, allowed_hosts=['source.test'])

    def test_no_store_200_never_creates_cache(self):
        for directive in ('no-store', 'NO-STORE', 'public ,  No-Store, max-age=0'):
            with self.subTest(directive=directive):
                session, script, _ = self.session(
                    (200, b'one', {**ETAG, 'Cache-Control': directive}), (200, b'two', ETAG))
                self.assertEqual(session.get(URL).body, b'one')
                self.assertEqual(files(self.tmp.name), [])
                self.assertEqual(session.get(URL).body, b'two')
                self.assertNotIn('If-None-Match', script.requests[1]['headers'])
                self.cache.forget(URL)

    def test_no_store_replacement_forgets_old_entry(self):
        for headers in ({**ETAG, 'Cache-Control': 'no-store'}, {'Cache-Control': 'no-store'}):
            with self.subTest(headers=headers):
                session, script, _ = self.session(
                    (200, b'old', ETAG), (200, b'other', ETAG), (200, b'fresh', headers), (200, b'next', ETAG))
                session.get(URL)
                session.get(OTHER)
                self.assertEqual(len(files(self.tmp.name)), 4)
                self.assertEqual((session.get(URL).body, script.requests[2]['headers']['If-None-Match']),
                                 (b'fresh', '"v1"'))
                self.assertIsNone(self.cache.lookup(URL))
                self.assertIsNotNone(self.cache.lookup(OTHER))
                self.assertEqual(session.get(URL).body, b'next')
                self.assertNotIn('If-None-Match', script.requests[3]['headers'])
                self.cache.forget(URL)
                self.cache.forget(OTHER)

    def test_no_store_304_returns_current_body_then_evicts(self):
        session, script, _ = self.session(
            (200, b'payload', ETAG), (304, b'', {**ETAG, 'Cache-Control': 'no-store'}), (200, b'fresh', ETAG))
        session.get(URL)
        second = session.get(URL)
        self.assertEqual((second.body, second.receipt.from_cache, second.status), (b'payload', True, 304))
        self.assertEqual(files(self.tmp.name), [])
        self.assertEqual(session.get(URL).body, b'fresh')
        self.assertNotIn('If-None-Match', script.requests[2]['headers'])

    def test_ordinary_directives_and_false_matches_keep_cache(self):
        for directive in ('max-age=60', 'no-store-like', 'x-ext="no-store"', 'private, extension=no-store', None):
            with self.subTest(directive=directive):
                extra = {} if directive is None else {'Cache-Control': directive}
                session, script, _ = self.session((200, b'payload', {**ETAG, **extra}), (304, b'', {**ETAG, **extra}))
                session.get(URL)
                second = session.get(URL)
                self.assertEqual((second.body, second.receipt.from_cache), (b'payload', True))
                self.assertEqual(script.requests[1]['headers']['If-None-Match'], '"v1"')
                self.cache.forget(URL)

    def test_direct_store_no_validator_still_evicts(self):
        self.cache.store(URL, b'old', http.Headers([('ETag', '"v1"')]))
        self.assertEqual(len(files(self.tmp.name)), 2)
        self.cache.store(URL, b'new', http.Headers([('Cache-Control', 'no-store')]))
        self.assertEqual(files(self.tmp.name), [])
        self.assertIsNone(self.cache.lookup(URL))


if __name__ == '__main__':
    unittest.main()
