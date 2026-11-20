"""Retry-After delta-seconds admit only ASCII decimal digits."""
import email.utils
import unittest

from skippercast import http
from tests import http_fixture

SUPERSCRIPT = '\u00b2'


def session(*replies):
    return http_fixture.session(*replies, allowed_hosts=['source.test'])


class RetryAfterDigitsTest(unittest.TestCase):
    def test_superscript_retry_after_uses_fallback(self):
        s, script, sleeps = session((429, b'', {'Retry-After': SUPERSCRIPT}), (200, b'ok'))
        self.assertEqual(s.get('https://source.test/x').body, b'ok')
        self.assertEqual(len(script.requests), 2)
        self.assertEqual(sleeps, [0.5])

    def test_nonascii_digit_variants_are_not_seconds(self):
        for value in (SUPERSCRIPT, '1' + SUPERSCRIPT, '\u0661\u0662', '\uff11\uff12'):
            with self.subTest(value=value):
                self.assertIsNone(http.parse_retry_after(value))

    def test_ascii_seconds_and_dates_keep_policy(self):
        for value in (None, '', 'soon'):
            self.assertIsNone(http.parse_retry_after(value))
        self.assertEqual(http.parse_retry_after('0'), 0.0)
        self.assertEqual(http.parse_retry_after(' 00012 '), 12.0)
        now = 1_800_000_000.0
        future = email.utils.formatdate(now + 30, usegmt=True)
        past = email.utils.formatdate(now - 30, usegmt=True)
        self.assertEqual(http.parse_retry_after(future, now), 30.0)
        self.assertEqual(http.parse_retry_after(past, now), 0.0)

    def test_exhausted_invalid_header_keeps_http_error(self):
        bad = (429, b'', {'Retry-After': SUPERSCRIPT})
        s, script, sleeps = session(bad, bad, bad, bad, bad, bad)
        with self.assertRaises(http.HTTPStatusError):
            s.get('https://source.test/x')
        self.assertGreaterEqual(len(script.requests), 2)
        self.assertEqual(len(sleeps), len(script.requests) - 1)


if __name__ == '__main__':
    unittest.main()
