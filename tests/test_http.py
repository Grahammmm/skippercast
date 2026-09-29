"""skippercast.http.Session: policy, retries, cache, limits and receipts (offline).

The TLS tests run a real HTTPS server on 127.0.0.1 with a throwaway CA; a stub
resolver maps test hostnames to addresses, so the real socket, TLS, SNI and
address-pinning path is exercised without DNS or the network.
"""
from datetime import datetime, timedelta, timezone
import email.utils
import gzip
import hashlib
from io import BytesIO
import ipaddress
from pathlib import Path
import re
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from skippercast import __version__, http
from tests import http_fixture

LOOPBACK = ipaddress.ip_address('127.0.0.1')
ADDRESSES = {'source.test': '127.0.0.1', 'other.test': '127.0.0.1', 'wrong.test': '127.0.0.1',
             'unlisted.test': '127.0.0.1', 'internal.test': '10.0.0.7'}


def test_address_policy(address):
    """Production policy (public only), plus the fixture's loopback server."""
    return address == LOOPBACK or http.public_address(address)


class TLSFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        try:
            material = http_fixture.make_ca(cls.directory.name)
        except Exception as error:  # pragma: no cover - depends on the local openssl build
            material, cls.why = None, f'openssl could not make test certificates: {error}'
        else:
            cls.why = 'openssl is not installed'
        if material is None:
            cls.directory.cleanup()
            raise unittest.SkipTest(cls.why)
        cls.server = http_fixture.TLSServer(*material)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        cls.directory.cleanup()

    def setUp(self):
        self.server.routes.clear()
        self.server.requests.clear()
        self.server.sni.clear()
        self.resolved = []
        self.sleeps = []

    def resolver(self, host, port, **_kwargs):
        self.resolved.append(host)
        if host not in ADDRESSES:
            raise socket.gaierror(socket.EAI_NONAME, 'unknown test host')
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ADDRESSES[host], port))]

    def session(self, **options):
        options.setdefault('allowed_hosts', ['source.test', 'other.test', 'wrong.test', 'internal.test'])
        options.setdefault('context', self.server.client_context())
        options.setdefault('resolver', self.resolver)
        return http.Session(address_allowed=test_address_policy, proxies={}, ports=(443, self.server.port),
                            sleep=self.sleeps.append, rand=lambda: 0.5, **options)

    def url(self, path, host='source.test'):
        return self.server.url(path, host)


class TLSAndPinningTests(TLSFixture):
    def test_connects_to_the_checked_address_with_hostname_verification(self):
        self.server.routes['/data'] = [(200, b'observations', {'Content-Type': 'text/plain', 'ETag': '"a"'})]
        with patch('socket.getaddrinfo', side_effect=AssertionError('a second DNS lookup happened')):
            response = self.session().get(self.url('/data'))
        self.assertEqual(response.body, b'observations')
        self.assertEqual(self.resolved, ['source.test'])  # resolved once, by the policy check
        self.assertEqual(self.server.sni, ['source.test'])  # TLS still names the host
        self.assertEqual(self.server.requests[0]['headers']['host'], f'source.test:{self.server.port}')
        self.assertEqual(self.server.requests[0]['headers']['user-agent'], http.USER_AGENT)
        receipt = response.receipt
        self.assertEqual((receipt.url, receipt.final_url, receipt.status, receipt.attempts, receipt.bytes),
                         (self.url('/data'), self.url('/data'), 200, 1, 12))
        self.assertEqual(receipt.sha256, hashlib.sha256(b'observations').hexdigest())
        self.assertFalse(receipt.from_cache)
        self.assertIsNone(receipt.error_class)
        self.assertGreaterEqual(receipt.elapsed_ms, 0)
        self.assertEqual((receipt.content_type, receipt.etag), ('text/plain', '"a"'))
        self.assertLessEqual({'url', 'final_url', 'status', 'attempts', 'bytes', 'sha256', 'elapsed_ms',
                              'from_cache', 'error_class'}, set(receipt.as_dict()))

    def test_a_certificate_for_another_name_is_refused_and_not_retried(self):
        self.server.routes['/data'] = [(200, b'x')]
        with self.assertRaises(http.TLSVerificationError) as raised:
            self.session().get(self.url('/data', 'wrong.test'))
        self.assertEqual(raised.exception.receipt.attempts, 1)
        self.assertEqual(raised.exception.receipt.error_class, 'TLSVerificationError')
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.server.requests, [])

    def test_an_untrusted_certificate_authority_is_refused(self):
        with self.assertRaises(http.TLSVerificationError):
            self.session(context=http.ssl.create_default_context()).get(self.url('/data'))

    def test_names_resolving_to_private_addresses_are_refused_before_connecting(self):
        def rebinding(host, port, **_kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.1.2.3', port))]
        for resolver in (rebinding, lambda host, port, **_: [(socket.AF_INET, 1, 6, '', ('169.254.169.254', port))]):
            with self.assertRaisesRegex(http.DisallowedHost, 'non-public'):
                self.session(resolver=resolver).get(self.url('/data'))
        self.assertEqual(self.server.requests, [])

    def test_redirect_to_a_private_address_is_refused(self):
        for target in (self.url('/inside', 'internal.test'), 'https://169.254.169.254/latest/meta-data',
                       'https://[::1]/', f'http://source.test:{self.server.port}/plain'):
            with self.subTest(target=target):
                self.server.requests.clear()
                self.server.routes['/hop'] = [(302, b'', {'Location': target})]
                with self.assertRaises(http.DisallowedHost) as raised:
                    self.session().get(self.url('/hop'))
                self.assertEqual([r['path'] for r in self.server.requests], ['/hop'])
                self.assertEqual(raised.exception.receipt.error_class, 'DisallowedHost')
                self.assertIsInstance(raised.exception, ValueError)  # keeps callers' fail-closed paths

    def test_redirect_to_an_allowlisted_host_is_followed_and_recorded(self):
        self.server.routes['/hop'] = [(301, b'', {'Location': self.url('/final', 'other.test')})]
        self.server.routes['/final'] = [(200, b'done')]
        response = self.session().get(self.url('/hop'))
        self.assertEqual((response.body, response.final_url), (b'done', self.url('/final', 'other.test')))
        self.assertEqual(self.server.sni, ['source.test', 'other.test'])
        self.assertEqual(self.resolved, ['source.test', 'other.test'])

    def test_hosts_outside_the_allowlist_are_refused(self):
        with self.assertRaisesRegex(http.DisallowedHost, 'allowlist'):
            self.session().get(self.url('/data', 'unlisted.test'))
        self.assertEqual(self.resolved, [])  # refused before any network activity
        self.server.routes['/hop'] = [(302, b'', {'Location': self.url('/x', 'unlisted.test')})]
        with self.assertRaisesRegex(http.DisallowedHost, 'allowlist'):
            self.session().get(self.url('/hop'))
        # A caller's own narrower list and URL prefixes apply to every hop.
        self.server.routes['/hop'] = [(302, b'', {'Location': self.url('/elsewhere')})]
        with self.assertRaisesRegex(http.DisallowedHost, 'prefixes'):
            self.session().get(self.url('/hop'), allowed_hosts=['source.test'],
                               allowed_prefixes=(self.url('/hop'),))
        with self.assertRaisesRegex(http.DisallowedHost, 'allowlist'):
            self.session().get(self.url('/data', 'other.test'), allowed_hosts=['source.test'])

    def test_redirects_can_be_refused(self):
        self.server.routes['/hop'] = [(302, b'', {'Location': self.url('/final')})]
        with self.assertRaisesRegex(http.ContractError, 'Redirect refused'):
            self.session().get(self.url('/hop'), follow_redirects=False)


class RetryTests(TLSFixture):
    def test_server_errors_back_off_with_full_jitter(self):
        self.server.routes['/busy'] = [(503, b''), (502, b''), (200, b'ok')]
        response = self.session(attempts=3).get(self.url('/busy'))
        self.assertEqual(response.body, b'ok')
        self.assertEqual(self.sleeps, [0.5, 1.0])  # rand 0.5 x min(cap, 1 x 2**(n-1))
        self.assertEqual(response.receipt.attempts, 3)
        self.assertEqual([row['status'] for row in response.receipt.history], [503, 502, 200])

    def test_backoff_is_capped(self):
        delays = http.full_jitter(1.0, 5.0, lambda: 1.0)
        self.assertEqual([delays(n) for n in range(1, 6)], [1.0, 2.0, 4.0, 5.0, 5.0])

    def test_retry_after_seconds_date_and_cap(self):
        later = email.utils.format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20), usegmt=True)
        for header, expected in (('7', (7.0, 7.0)), (later, (17.0, 20.0)), ('9999', (60.0, 60.0))):
            with self.subTest(header=header):
                self.sleeps.clear()
                self.server.routes['/limited'] = [(429, b'', {'Retry-After': header}), (200, b'ok')]
                self.session(retry_after_cap=60).get(self.url('/limited'))
                self.assertEqual(len(self.sleeps), 1)
                self.assertTrue(expected[0] <= self.sleeps[0] <= expected[1], self.sleeps)

    def test_exhausted_retries_raise_with_a_receipt(self):
        self.server.routes['/busy'] = [(504, b'gateway')]
        with self.assertRaises(http.HTTPStatusError) as raised:
            self.session(attempts=3).get(self.url('/busy'))
        error = raised.exception
        self.assertEqual((error.status, error.receipt.attempts, error.receipt.error_class), (504, 3, 'HTTPStatusError'))
        self.assertEqual(len(self.sleeps), 2)

    def test_other_client_errors_are_not_retried(self):
        self.server.routes['/missing'] = [(404, b'')]
        with self.assertRaises(http.HTTPStatusError) as raised:
            self.session(attempts=3).get(self.url('/missing'))
        self.assertEqual((raised.exception.status, raised.exception.receipt.attempts), (404, 1))
        self.assertIsInstance(raised.exception, OSError)  # as urllib's HTTPError was
        self.assertEqual(self.sleeps, [])
        response = self.session().get(self.url('/missing'), raise_for_status=False)
        self.assertEqual(response.status, 404)

    def test_connection_errors_are_retried_then_raised(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        dead = listener.getsockname()[1]
        listener.close()
        session = http.Session(
            allowed_hosts=['source.test'], resolver=self.resolver, address_allowed=test_address_policy,
            proxies={}, ports=(dead,), context=self.server.client_context(), sleep=self.sleeps.append,
            rand=lambda: 0.5, attempts=3)
        with self.assertRaises(http.TransportError) as raised:
            session.get(f'https://source.test:{dead}/data', timeout=5)
        self.assertEqual(raised.exception.receipt.attempts, 3)
        self.assertEqual(self.sleeps, [0.5, 1.0])
        self.assertEqual({row['error_class'] for row in raised.exception.receipt.history}, {'TransportError'})

    def test_per_host_minimum_interval(self):
        session, _, sleeps = http_fixture.session((200, b'a'), (200, b'b'), (200, b'c'),
                                                  min_interval={'www.ecfr.gov': 3}, clock=lambda: 100.0)
        for _ in range(2):
            session.get('https://www.ecfr.gov/api/versioner/v1/titles.json')
        session.get('https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt')
        self.assertEqual(sleeps, [3.0])


class CacheAndLimitTests(TLSFixture):
    def conditional(self, handler):
        if handler.headers.get('If-None-Match') == '"v1"':
            return (304, b'', {'ETag': '"v1"'})
        return (200, b'payload', {'ETag': '"v1"', 'Last-Modified': 'Tue, 29 Sep 2026 10:00:00 GMT',
                                  'Content-Type': 'application/json'})

    def test_conditional_get_returns_the_cached_body_on_304(self):
        self.server.routes['/feed'] = [self.conditional]
        with tempfile.TemporaryDirectory() as directory:
            session = self.session(cache=directory)
            first = session.get(self.url('/feed'))
            second = session.get(self.url('/feed'))
            self.assertEqual((first.body, first.receipt.from_cache), (b'payload', False))
            self.assertEqual((second.body, second.receipt.from_cache, second.status), (b'payload', True, 304))
            self.assertEqual(second.receipt.sha256, hashlib.sha256(b'payload').hexdigest())
            self.assertEqual(second.receipt.content_type, 'application/json')
            sent = self.server.requests[1]['headers']
            self.assertEqual(sent['if-none-match'], '"v1"')
            self.assertEqual(sent['if-modified-since'], 'Tue, 29 Sep 2026 10:00:00 GMT')
            # A damaged cached body is not served: the source is fetched again in full.
            for path in Path(directory).glob('*.body'):
                path.write_bytes(b'tampered')
            third = session.get(self.url('/feed'))
            self.assertEqual((third.body, third.receipt.from_cache, third.status), (b'payload', False, 200))

    def test_cache_is_off_unless_enabled(self):
        self.server.routes['/feed'] = [self.conditional]
        session = self.session()
        session.get(self.url('/feed'))
        session.get(self.url('/feed'))
        self.assertNotIn('if-none-match', self.server.requests[1]['headers'])
        self.assertIsNone(http.cache_from_environment({}))
        self.assertIsNone(http.cache_from_environment({'SKIPPERCAST_HTTP_CACHE': '0'}))
        self.assertTrue(str(http.cache_from_environment({'SKIPPERCAST_HTTP_CACHE': '1'}).directory)
                        .endswith('var/http-cache'))

    def test_body_limits(self):
        self.server.routes['/declared'] = [(200, b'x' * 2000)]
        self.server.routes['/chunked'] = [(200, b'x' * 200_000, {'__chunked__': True})]
        self.server.routes['/bomb'] = [(200, gzip.compress(b'\0' * 1_000_000), {'Content-Encoding': 'gzip'})]
        for path, limit in (('/declared', 1000), ('/chunked', 100_000), ('/bomb', 10_000)):
            with self.subTest(path=path):
                with self.assertRaises(http.BodyTooLarge) as raised:
                    self.session().get(self.url(path), max_bytes=limit)
                self.assertIsInstance(raised.exception, ValueError)
                self.assertEqual(raised.exception.receipt.attempts, 1)  # not retried
        small = self.session().get(self.url('/bomb'), max_bytes=2_000_000)
        self.assertEqual((small.receipt.bytes, small.receipt.compressed_bytes > 0), (1_000_000, True))

    def test_download_streams_to_a_file_with_its_hash(self):
        body = bytes(range(256)) * 1000
        self.server.routes['/grid'] = [(503, b''), (200, body)]
        sink = BytesIO()
        response = self.session().download(self.url('/grid'), sink)
        self.assertIsNone(response.body)
        self.assertEqual(sink.getvalue(), body)
        self.assertEqual((response.receipt.bytes, response.receipt.sha256), (len(body), hashlib.sha256(body).hexdigest()))

    def test_range_requests_pass_through_and_are_never_cached(self):
        self.server.routes['/grib'] = [(206, b'GRIB', {'Content-Range': 'bytes 0-3/100', 'ETag': '"g"'})]
        with tempfile.TemporaryDirectory() as directory:
            response = self.session(cache=directory).get(self.url('/grib'), headers={'Range': 'bytes=0-3'})
            self.assertEqual((response.status, response.body), (206, b'GRIB'))
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(self.server.requests[0]['headers']['range'], 'bytes=0-3')


class PolicyUnitTests(unittest.TestCase):
    def test_user_agent_names_the_version_and_site(self):
        self.assertEqual(http.USER_AGENT, f'SkipperCast/{__version__} (+https://skippercast.com)')

    def test_default_allowlist_covers_the_source_catalog(self):
        text = (http.repo_root() / 'catalog/sources.json').read_text()
        hosts = {h.lower() for h in re.findall(r'https://([A-Za-z0-9.-]+)', text)}
        allowlist = http.default_allowlist()
        self.assertTrue(hosts)
        self.assertEqual({h for h in hosts if not allowlist.allows(h)}, set())
        self.assertTrue(all(allowlist.allows(h) for h in http.EXTRA_HOSTS))
        self.assertFalse(allowlist.allows('example.org'))
        self.assertTrue(http.default_allowlist(['example.org']).allows('EXAMPLE.org.'))

    def test_wildcards(self):
        allowlist = http.Allowlist(['*.usgs.gov', 'www.ecfr.gov'])
        self.assertTrue(allowlist.allows('pubs.usgs.gov'))
        self.assertFalse(allowlist.allows('usgs.gov.evil.example'))
        self.assertFalse(allowlist.allows('ecfr.gov'))

    def test_url_checks(self):
        session = http.Session(allowed_hosts=['*'], proxies={})
        for url in ('http://www.ecfr.gov/', 'https://localhost/', 'https://10.0.0.1/', 'https://[fe80::1]/',
                    'https://user:pw@www.ecfr.gov/', 'https://www.ecfr.gov:8443/', 'https://intranet/',
                    'https://metadata.google.internal/'):
            with self.subTest(url=url):
                self.assertRaises(http.DisallowedHost, session.check_url, url)

    def test_parse_retry_after(self):
        now = 1_800_000_000.0
        date = email.utils.formatdate(now + 30, usegmt=True)
        self.assertEqual(http.parse_retry_after('12', now), 12.0)
        self.assertEqual(http.parse_retry_after(date, now), 30.0)
        self.assertEqual(http.parse_retry_after(email.utils.formatdate(now - 30, usegmt=True), now), 0.0)
        self.assertIsNone(http.parse_retry_after('soon', now))
        self.assertIsNone(http.parse_retry_after(None, now))

    def test_truststore_is_preferred_when_installed(self):
        made = []
        fake = SimpleNamespace(SSLContext=lambda protocol: made.append(protocol) or 'os-trust-store')
        with patch.dict(sys.modules, {'truststore': fake}):
            self.assertEqual(http.tls_context(), 'os-trust-store')
        with patch.dict(sys.modules, {'truststore': None}):  # import fails
            context = http.tls_context()
        self.assertEqual(context.verify_mode, http.ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_scripted_receipt_history_and_refusal_before_network(self):
        session, script, _ = http_fixture.session((503, b''), (200, b'ok'))
        response = session.get('https://api.weather.gov/alerts')
        self.assertEqual([row['status'] for row in response.receipt.history], [503, 200])
        self.assertEqual(script.requests[0]['addresses'][0][1][0], http_fixture.PUBLIC_IP)
        with self.assertRaises(http.DisallowedHost) as raised:
            session.get('https://unreviewed.example.org/')
        self.assertEqual((raised.exception.receipt.attempts, raised.exception.receipt.error_class),
                         (0, 'DisallowedHost'))

    def test_fake_session(self):
        fake = http.FakeSession({'https://a.test/x': b'body', 'https://a.test/gone': (404, b'')})
        self.assertEqual(fake.get('https://a.test/x').body, b'body')
        with self.assertRaises(http.HTTPStatusError):
            fake.get('https://a.test/gone')
        with self.assertRaises(http.TransportError):
            fake.get('https://a.test/unknown')
        self.assertEqual([call[1] for call in fake.calls],
                         ['https://a.test/x', 'https://a.test/gone', 'https://a.test/unknown'])


if __name__ == '__main__':
    unittest.main()
