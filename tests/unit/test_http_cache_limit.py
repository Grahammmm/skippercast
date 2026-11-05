"""A 304-revalidated cached body obeys the current call's max_bytes (offline, scripted)."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from skippercast import http
from tests import http_fixture

URL = 'https://www.example.com/feed'
HOSTS = ['www.example.com']
BODY = b'0123456789'
FIRST = (200, BODY, {'ETag': '"one"'})
NOT_MODIFIED = (304, b'', {'ETag': '"one"'})


class CachedBodyLimit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def prime(self, *replies, **options):
        session, script, sleeps = http_fixture.session(FIRST, *replies, cache=self.tmp.name, allowed_hosts=HOSTS, **options)
        session.get(URL)
        return session, script, sleeps

    def body_files(self):
        return list(Path(self.tmp.name).glob('*.body'))

    def test_oversized_hit_is_refused_with_receipt_and_cache_kept(self):
        session, script, sleeps = self.prime(NOT_MODIFIED)
        with self.assertRaises(http.BodyTooLarge) as caught:
            session.get(URL, max_bytes=3)
        self.assertEqual(caught.exception.receipt.error_class, 'BodyTooLarge')
        self.assertEqual(len(caught.exception.receipt.history), 1)
        self.assertEqual((len(script.requests), sleeps), (2, []))  # no refetch, no retry
        self.assertEqual(self.body_files()[0].read_bytes(), BODY)

    def test_boundary_and_unlimited(self):
        session, _, _ = self.prime(NOT_MODIFIED, NOT_MODIFIED, NOT_MODIFIED)
        hit = session.get(URL, max_bytes=10)
        self.assertEqual((hit.body, hit.status, hit.receipt.from_cache), (BODY, 304, True))
        self.assertEqual(hit.receipt.sha256, hashlib.sha256(BODY).hexdigest())
        with self.assertRaises(http.BodyTooLarge):
            session.get(URL, max_bytes=9)
        self.assertEqual(session.get(URL, max_bytes=None).body, BODY)

    def test_session_default_limit_applies_to_a_cache_another_session_filled(self):
        self.prime()
        small, _, _ = http_fixture.session(NOT_MODIFIED, cache=self.tmp.name, allowed_hosts=HOSTS, max_bytes=4)
        with self.assertRaises(http.BodyTooLarge):
            small.get(URL)

    def test_zero_limit(self):
        session, _, _ = self.prime(NOT_MODIFIED)
        with self.assertRaises(http.BodyTooLarge):  # metadata bytes cannot hide a bigger file
            session.get(URL, max_bytes=0)
        cache = http.HTTPCache(self.tmp.name)
        meta = cache.lookup(URL)
        meta['bytes'] = 0
        with self.assertRaises(http.BodyTooLarge):
            cache.body(URL, meta, 0)
        self.body_files()[0].write_bytes(b'')
        meta['sha256'] = hashlib.sha256(b'').hexdigest()
        self.assertEqual(cache.body(URL, meta, 0), b'')

    def test_missing_or_tampered_body_still_refetches_without_validators(self):
        for damage in (lambda p: p.unlink(), lambda p: p.write_bytes(b'bad')):
            with self.subTest():
                session, script, _ = self.prime(NOT_MODIFIED, (200, BODY, {'ETag': '"one"'}))
                damage(self.body_files()[0])
                again = session.get(URL, max_bytes=10)
                self.assertEqual((again.body, again.status, again.receipt.from_cache), (BODY, 200, False))
                self.assertNotIn('if-none-match', {k.lower() for k in script.requests[-1]['headers']})

    def test_read_is_bounded_to_limit_plus_one(self):
        cache = http.HTTPCache(self.tmp.name)
        cache.store(URL, BODY, {'ETag': '"one"'})
        meta = cache.lookup(URL)
        sizes = []
        real_open = Path.open

        class Spy:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                self.handle.__enter__()
                return self

            def __exit__(self, *exc):
                return self.handle.__exit__(*exc)

            def read(self, size=-1):
                sizes.append(size)
                return self.handle.read(size)

        def spy_open(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            return Spy(handle) if path.suffix == '.body' else handle

        Path.open = spy_open
        try:
            with self.assertRaises(http.BodyTooLarge):
                cache.body(URL, meta, 3)
        finally:
            Path.open = real_open
        self.assertEqual(sizes, [4])


if __name__ == '__main__':
    unittest.main()
