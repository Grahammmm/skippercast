"""Authorization/Cookie never follow a redirect to another origin (offline, real Session redirect logic)."""
import unittest

from skippercast.http import ContractError
from tests.http_fixture import session

AUTH = 'Bearer synthetic-secret'
COOKIE = 'sid=synthetic'
HOSTS = ['source.test', 'other.test']


def _names(request):
    return {k.lower() for k in request['headers']}


def _redirect(status, location):
    return (status, b'', {'Location': location})


class RedirectCredentialTests(unittest.TestCase):
    def fetch(self, replies, url='https://source.test/a', headers=None, method='get', ports=(443,), **options):
        s, script, _ = session(*replies, allowed_hosts=HOSTS, ports=ports)
        headers = headers if headers is not None else {
            'aUtHoRiZaTiOn': AUTH, 'COOKIE': COOKIE, 'Accept': 'text/x', 'X-Note': 'plain'}
        before = dict(headers)
        args = (url, b'body') if method == 'post' else (url,)
        try:
            result = getattr(s, method)(*args, headers=headers, **options)
        finally:
            self.assertEqual(headers, before)
        return result, script

    def test_cross_origin_drops_credentials(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                response, script = self.fetch([_redirect(status, 'https://other.test/b'), (200, b'ok')])
                first, second = script.requests
                self.assertLessEqual({'authorization', 'cookie'}, _names(first))
                self.assertFalse(_names(second) & {'authorization', 'cookie'})
                self.assertEqual(second['host'], 'other.test')
                self.assertEqual(second['headers']['Accept'], 'text/x')
                self.assertEqual(second['headers']['X-Note'], 'plain')
                self.assertEqual(response.final_url, 'https://other.test/b')

    def test_same_origin_keeps_credentials(self):
        for location in ('/b', 'https://source.test/b', 'https://SOURCE.test:443/b'):
            with self.subTest(location=location):
                _, script = self.fetch([_redirect(302, location), (200, b'ok')])
                self.assertLessEqual({'authorization', 'cookie'}, _names(script.requests[1]))

    def test_other_port_strips(self):
        _, script = self.fetch([_redirect(302, 'https://source.test:8443/b'), (200, b'ok')],
                              ports=(443, 8443))
        self.assertFalse(_names(script.requests[1]) & {'authorization', 'cookie'})

    def test_chain_does_not_restore(self):
        _, script = self.fetch([_redirect(302, '/b'), _redirect(302, 'https://other.test/c'),
                                _redirect(302, 'https://source.test/d'), (200, b'ok')])
        keeps = [bool(_names(r) & {'authorization', 'cookie'}) for r in script.requests]
        self.assertEqual(keeps, [True, True, False, False])

    def test_post_semantics_unchanged(self):
        for status, method, body in ((302, 'GET', None), (303, 'GET', None), (307, 'POST', b'body'),
                                     (308, 'POST', b'body')):
            with self.subTest(status=status):
                _, script = self.fetch([_redirect(status, 'https://other.test/b'), (200, b'ok')],
                                       method='post', headers={'Authorization': AUTH, 'Content-Type': 'text/x',
                                                               'X-Note': 'plain'})
                second = script.requests[1]
                self.assertEqual((second['method'], second['body']), (method, body))
                self.assertNotIn('Authorization', second['headers'])
                self.assertEqual('Content-Type' in second['headers'], method == 'POST')
                self.assertEqual(second['headers']['X-Note'], 'plain')

    def test_refusals_and_return(self):
        s, script, _ = session(_redirect(302, 'https://denied.test/b'), allowed_hosts=HOSTS)
        with self.assertRaises(Exception):
            s.get('https://source.test/a', headers={'Authorization': AUTH})
        self.assertEqual(len(script.requests), 1)
        with self.assertRaises(ContractError):
            self.fetch([_redirect(302, 'https://other.test/b')], follow_redirects=False)
        response, script = self.fetch([_redirect(302, 'https://other.test/b')], follow_redirects='return', raise_for_status=False)
        self.assertEqual(len(script.requests), 1)
        self.assertEqual(response.status, 302)

    def test_retry_restarts_with_credentials(self):
        _, script = self.fetch([_redirect(302, 'https://other.test/b'), (503, b''),
                                _redirect(302, 'https://other.test/b'), (200, b'ok')], attempts=2)
        keeps = [bool(_names(r) & {'authorization', 'cookie'}) for r in script.requests]
        self.assertEqual(keeps, [True, False, True, False])


if __name__ == '__main__':
    unittest.main()
