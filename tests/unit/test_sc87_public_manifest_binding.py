"""SC87: synthetic full-descriptor public-route contract, no socket or server.

The runner supplies a private copy of manifest.json. Ordinary test discovery
uses the committed read-only fixture and never installs process-global guards.
"""
import copy
import json
import unittest
from unittest.mock import patch

from skippercast.seafloor import verify
from tests import http_fixture
from tests._support import FIXTURES

FIXTURE_ROOT = FIXTURES / 'sc87-public-manifest-binding'
MISMATCH = 'Public manifest does not match R2 publication'
RAW = b'PMTiles\x03' + b'\0' * 119


def manifest():
    return json.loads((FIXTURE_ROOT / 'manifest.json').read_text())


def probe_session(served, *, raw=RAW, status=206, headers=None, size=500):
    headers = headers if headers is not None else {
        'Content-Range': f'bytes 0-126/{size}',
        'X-Feed-Source': 'r2', 'Cache-Control': 'no-store'}
    session, script, _ = http_fixture.session(
        (200, json.dumps(served).encode()), (status, raw, headers))
    return session, script


def assert_rejected_before_range(test, expected, session, script):
    error = None
    try:
        verify.verify_public('morro-bay', expected, session=session)
    except ValueError as exc:
        error = exc
    test.assertEqual(len(script.requests), 1)
    test.assertIsNotNone(error)
    test.assertEqual(str(error), MISMATCH)


class RegressionTests(unittest.TestCase):
    def test_matching_manifest_and_exact_request(self):
        expected = manifest()
        before = copy.deepcopy(expected)
        session, script = probe_session(expected)
        receipt = verify.verify_public('morro-bay', expected, session=session)
        self.assertEqual(receipt, {
            'region': 'morro-bay',
            'url': 'https://skippercast.com/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles',
            'archive_sha256': 'a' * 64, 'range_status': 206})
        self.assertEqual(expected, before)
        self.assertEqual(len(script.requests), 2)
        self.assertEqual(script.requests[0]['target'], '/feeds/tiles/seafloor/manifest-morro-bay.json')
        self.assertEqual(script.requests[1]['target'], '/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles')
        for request in script.requests:
            self.assertEqual(request['headers']['Cache-Control'], 'no-cache')
        self.assertEqual(script.requests[1]['headers']['Range'], 'bytes=0-126')

    def test_extra_metadata(self):
        expected = manifest()
        session, script = probe_session({**expected, 'unrelated': {'nested': True}})
        self.assertEqual(verify.verify_public('morro-bay', expected, session=session)['range_status'], 206)
        self.assertEqual(len(script.requests), 2)

    def test_minimum_archive_size(self):
        expected = {**manifest(), 'archive_bytes': 127}
        session, script = probe_session(expected, size=127)
        self.assertEqual(verify.verify_public('morro-bay', expected, session=session)['range_status'], 206)
        self.assertEqual(len(script.requests), 2)

    def test_default_session_still_supported(self):
        expected = manifest()
        session, script = probe_session(expected)
        with patch.object(verify.http, 'default_session', return_value=session) as default:
            verify.verify_public('morro-bay', expected)
        default.assert_called_once_with()
        self.assertEqual(len(script.requests), 2)

    def test_request_bounds_and_options(self):
        expected = manifest()
        session, script = probe_session(expected)
        with patch.object(session, 'get', wraps=session.get) as get:
            verify.verify_public('morro-bay', expected, session=session)
        self.assertEqual(len(script.requests), 2)
        self.assertEqual([c.kwargs['max_bytes'] for c in get.call_args_list], [1_000_000, 128])
        for call in get.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 30)
            self.assertEqual(call.kwargs['allowed_hosts'], ['skippercast.com'])
            self.assertIs(call.kwargs['use_cache'], False)

    def test_existing_safe_region_grammar(self):
        for region in ('a--b', '-', '123'):
            expected = {**manifest(), 'region': region, 'archive': f'seafloor-{region}.pmtiles'}
            session, script = probe_session(expected)
            self.assertEqual(verify.verify_public(region, expected, session=session)['region'], region)
            self.assertEqual(len(script.requests), 2)


# Each matrix row is an executed test ID, rather than a hidden loop/count.
MISSING = object()
SERVED_CASES = {
    'wrong_region': ('region', 'other-region'),
    'wrong_archive': ('archive', 'seafloor-other-region.pmtiles'),
    'wrong_bytes': ('archive_bytes', 501),
    'wrong_hash': ('archive_sha256', 'b' * 64),
    'wrong_status': ('status', 'updating'),
    'bytes_boolean_true': ('archive_bytes', True),
    'bytes_boolean_false': ('archive_bytes', False),
    'bytes_float_equal': ('archive_bytes', 500.0),
    'bytes_string': ('archive_bytes', '500'),
    'bytes_small': ('archive_bytes', 126),
    'bytes_negative': ('archive_bytes', -1),
    'archive_traversal': ('archive', '../seafloor-morro-bay.pmtiles'),
    'hash_short': ('archive_sha256', 'a' * 63),
    'hash_nonhex': ('archive_sha256', 'z' * 64),
}
for field in ('region', 'archive', 'archive_bytes', 'archive_sha256', 'status'):
    SERVED_CASES[field + '_missing'] = (field, MISSING)
    SERVED_CASES[field + '_null'] = (field, None)
    SERVED_CASES[field + '_list'] = (field, [])


def served_case(field, value):
    def test(self):
        expected = manifest()
        served = dict(expected)
        if value is MISSING:
            served.pop(field)
        else:
            served[field] = value
        session, script = probe_session(served)
        assert_rejected_before_range(self, expected, session, script)
    return test


for name, (field, value) in SERVED_CASES.items():
    setattr(RegressionTests, 'test_served_' + name, served_case(field, value))


def served_shape(value):
    def test(self):
        session, script = probe_session(value)
        with self.assertRaisesRegex(ValueError, MISMATCH):
            verify.verify_public('morro-bay', manifest(), session=session)
        self.assertEqual(len(script.requests), 1)
    return test


for name, value in [('list', []), ('null', None), ('string', 'ready'), ('number', 12)]:
    setattr(RegressionTests, 'test_served_root_' + name, served_shape(value))

EXPECTED_CASES = {
    'archive_traversal': ('archive', '../seafloor-morro-bay.pmtiles'),
    'archive_absolute': ('archive', '/seafloor-morro-bay.pmtiles'),
    'archive_url': ('archive', 'https://example.test/a.pmtiles'),
    'archive_wrong_basename': ('archive', 'other.pmtiles'),
    'region_traversal': ('region', '../other'),
    'region_empty': ('region', ''),
    'region_upper': ('region', 'Morro-bay'),
    'region_unicode': ('region', 'morró-bay'),
    'region_newline': ('region', 'morro-bay\n'),
    'hash_nonhex': ('archive_sha256', 'z' * 64),
    'hash_short': ('archive_sha256', 'a' * 63),
    'hash_upper': ('archive_sha256', 'A' * 64),
    'bytes_boolean': ('archive_bytes', True),
    'bytes_float': ('archive_bytes', 500.0),
    'bytes_zero': ('archive_bytes', 0),
    'bytes_negative': ('archive_bytes', -1),
    'bytes_below_min': ('archive_bytes', 126),
}
for field in ('region', 'archive', 'archive_bytes', 'archive_sha256'):
    for label, value in [('missing', MISSING), ('null', None), ('list', [])]:
        EXPECTED_CASES[field + '_' + label] = (field, value)


def expected_case(field, value):
    def test(self):
        expected = manifest()
        region = 'morro-bay'
        if value is MISSING:
            expected.pop(field)
        else:
            expected[field] = value
            if field == 'region':
                region = value
                expected['archive'] = f'seafloor-{region}.pmtiles'
        with patch.object(verify.http, 'default_session') as default:
            with self.assertRaises(ValueError):
                verify.verify_public(region, expected)
            default.assert_not_called()
    return test


for name, (field, value) in EXPECTED_CASES.items():
    setattr(RegressionTests, 'test_expected_' + name, expected_case(field, value))


def expected_shape(value):
    def test(self):
        with patch.object(verify.http, 'default_session') as default:
            with self.assertRaisesRegex(ValueError, 'Invalid public verification target'):
                verify.verify_public('morro-bay', value)
            default.assert_not_called()
    return test


for name, value in [('list', []), ('null', None), ('string', 'ready'), ('number', 12)]:
    setattr(RegressionTests, 'test_expected_root_' + name, expected_shape(value))


def range_case(**changes):
    def test(self):
        expected = manifest()
        session, script = probe_session(expected, **changes)
        with self.assertRaises(ValueError):
            verify.verify_public('morro-bay', expected, session=session)
        self.assertEqual(len(script.requests), 2)
    return test


for name, changes in {
    'oversized': {'raw': RAW + b'xx'},
    'short': {'raw': RAW[:-1]},
    'magic': {'raw': b'NotTiles' + RAW[8:]},
    'status': {'status': 200},
    'content_range': {'headers': {'Content-Range': 'bytes 0-126/501', 'X-Feed-Source': 'r2', 'Cache-Control': 'no-store'}},
    'source': {'headers': {'Content-Range': 'bytes 0-126/500', 'X-Feed-Source': 'old', 'Cache-Control': 'no-store'}},
    'cache': {'headers': {'Content-Range': 'bytes 0-126/500', 'X-Feed-Source': 'r2', 'Cache-Control': 'public'}},
    'missing_headers': {'headers': {}},
}.items():
    setattr(RegressionTests, 'test_range_' + name, range_case(**changes))


class CompatibilityTests(RegressionTests):
    """Only named positives are selected by the compatibility runner."""
    def test_target_region_mismatch_before_session(self):
        with patch.object(verify.http, 'default_session') as default:
            with self.assertRaises(ValueError):
                verify.verify_public('other', manifest())
            default.assert_not_called()

    def test_non_https_before_session(self):
        with patch.object(verify.http, 'default_session') as default:
            with self.assertRaises(ValueError):
                verify.verify_public('morro-bay', manifest(), base='http://example.test')
            default.assert_not_called()


class NegativeControlTests(unittest.TestCase):
    def test_mutant_detected_and_positive_restored(self):
        expected = manifest()
        real_comparison = verify._public_descriptor_matches
        observed = {}

        def ignore_descriptor_comparison(current, pinned):
            # The comparison alone is disabled. Expected validation, ready status,
            # hash value and all range/transport gates stay otherwise unchanged.
            self.assertEqual(current['archive_sha256'], pinned['archive_sha256'])
            return True

        with patch.object(verify, '_public_descriptor_matches', side_effect=ignore_descriptor_comparison):
            session, script = probe_session({**expected, 'region': 'other-region'})
            # Execute the SAME regression assertion; no unrelated gate may fail.
            with self.assertRaisesRegex(AssertionError, '2 != 1'):
                assert_rejected_before_range(self, expected, session, script)
            observed['mutant_detected'] = len(script.requests) == 2
        self.assertIs(verify._public_descriptor_matches, real_comparison)
        session, script = probe_session(expected)
        self.assertEqual(verify.verify_public('morro-bay', expected, session=session)['range_status'], 206)
        self.assertEqual(len(script.requests), 2)
        observed['positive_passed'] = True
        self.assertEqual(observed, {'mutant_detected': True, 'positive_passed': True})
        print(json.dumps(observed, sort_keys=True))
