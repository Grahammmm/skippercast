"""Post-publish check that the public route serves this run's feed (offline, with fakes)."""
import unittest

from scripts.verify_published_feed import bust, check, main, verify


class FakeSite:
    """Serves a sequence of responses (dicts or exceptions), then repeats the last."""
    def __init__(self, *responses):
        self.responses, self.urls = list(responses), []

    def __call__(self, url):
        self.urls.append(url)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


URL = 'https://site.example/feeds/conditions/latest.json'
NEW = {'run_id': '42', 'published_at': '2026-09-28T12:07:40Z'}
OLD = {'run_id': '41', 'published_at': '2026-09-28T11:37:40Z'}


class VerifyTests(unittest.TestCase):
    def test_matching_run_passes_first_time(self):
        site, sleeps = FakeSite(NEW), []
        ok, message = verify(URL, '42', fetch=site, sleep=sleeps.append)
        self.assertTrue(ok, message)
        self.assertEqual((len(site.urls), sleeps), (1, []))

    def test_retries_through_errors_and_stale_copies(self):
        site, sleeps = FakeSite(OSError('reset'), OLD, NEW), []
        ok, message = verify(URL, '42', attempts=5, delay=2, fetch=site, sleep=sleeps.append)
        self.assertTrue(ok, message)
        self.assertIn('after 3 attempt(s)', message)
        self.assertEqual(sleeps, [2, 2])

    def test_stale_public_copy_fails_after_all_attempts(self):
        site, sleeps = FakeSite(OLD), []
        ok, message = verify(URL, '42', attempts=3, delay=1, fetch=site, sleep=sleeps.append)
        self.assertFalse(ok)
        self.assertIn("run_id is '41', expected '42'", message)
        self.assertEqual((len(site.urls), sleeps), (3, [1, 1]))

    def test_earlier_cycle_of_the_same_run_is_not_enough(self):
        earlier = {**NEW, 'published_at': '2026-09-28T11:37:40Z'}
        ok, message = verify(URL, '42', NEW['published_at'], attempts=1, fetch=FakeSite(earlier), sleep=None)
        self.assertFalse(ok)
        self.assertIn('published_at', message)
        self.assertTrue(verify(URL, '42', NEW['published_at'], attempts=1, fetch=FakeSite(NEW), sleep=None)[0])

    def test_feed_without_run_id_or_not_an_object_fails(self):
        self.assertFalse(check({'completed_at': 'x'}, '42')[0])
        self.assertFalse(check([], '42')[0])

    def test_requests_bypass_caches(self):
        self.assertEqual(bust(URL, '42-1'), URL + '?verify=42-1')
        self.assertEqual(bust(URL + '?a=1', 'x'), URL + '?a=1&verify=x')
        site = FakeSite(OLD, NEW)
        verify(URL, '42', attempts=2, delay=0, fetch=site, sleep=lambda s: None)
        self.assertEqual(len(set(site.urls)), 2)

    def test_command_line_exit_status(self):
        from unittest.mock import patch
        with patch('scripts.verify_published_feed.fetch_json', FakeSite(NEW)), patch('builtins.print'):
            self.assertEqual(main([URL, '42', '--attempts', '1']), 0)
        with patch('scripts.verify_published_feed.fetch_json', FakeSite(OLD)), patch('builtins.print') as printed:
            self.assertEqual(main([URL, '42', '--attempts', '1', '--delay', '0']), 1)
        self.assertIn('::error title=Public feed not updated::', printed.call_args[0][0])


if __name__ == '__main__':
    unittest.main()
