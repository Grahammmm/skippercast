"""SC159 synthetic title ingress tests; safe ordinary unittest discovery.

All five contract methods are unittest tests. No product imports, writes, audit
hooks, environment changes or native stubs occur at module import time.
"""
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from tests._support import ROOT as REPO

FIXTURE = REPO / 'tests/fixtures/sc159-title33-metadata'
TITLES_URL = 'https://www.ecfr.gov/api/versioner/v1/titles'
NOTICE_SHA = '29c2983abd732a0e9ee44c69ed1bd7c024fd425749271ae00aaabe2bad440745'
TITLES_SHA = '52f28cd6b52520d53f2908beccc761b6118bdf7873eaaf36f7ff9c04c7c48244'


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError('missing test support')
    module = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
    return module


def malformed_cases():
    row = {'number': 33, 'up_to_date_as_of': '2026-09-24'}
    def envelope(*rows):
        return {'titles': list(rows)}
    cases = {
        'missing-title': envelope({'number': 50}),
        'empty-list': envelope(),
        'duplicate-int': envelope(row, deepcopy(row)),
        'duplicate-float-after': envelope(row, dict(row, number=33.0)),
        'duplicate-float-before': envelope(dict(row, number=33.0), row),
        'float-only': envelope(dict(row, number=33.0)),
        'exponent-float-only': envelope(dict(row, number=3.3e1)),
        'string-only': envelope(dict(row, number='33')),
        'bool-only': envelope(dict(row, number=True)),
        'no-number': envelope({'up_to_date_as_of': '2026-09-24'}),
        'null-envelope': None, 'list-envelope': [], 'string-envelope': 'titles',
        'no-titles-key': {}, 'null-list': {'titles': None},
        'object-list': {'titles': {'number': 33}}, 'string-list': {'titles': '33'},
        'non-object-row-first': envelope(None, row),
        'non-object-row-last': envelope(row, []),
        'non-object-string-row': envelope(row, 'other title'),
        'no-date': envelope({'number': 33}),
    }
    dates = {
        'null': None, 'integer': 20260924, 'float': 2026.0924, 'bool': True,
        'list': [], 'object': {}, 'empty': '',
        'non-leap': '2025-02-29', 'century-non-leap': '1900-02-29',
        'bad-month': '2026-13-01', 'zero-month': '2026-00-01',
        'bad-day': '2026-04-31', 'zero-day': '2026-01-00',
        'zero-year': '0000-01-01', 'compact': '20260924',
        'week-date': '2026-W39-4', 'short-month': '2026-9-24',
        'short-day': '2026-09-4', 'five-year': '02026-09-24',
        'time': '2026-09-24T00:00:00Z', 'space-time': '2026-09-24 00:00:00',
        'leading-space': ' 2026-09-24', 'trailing-space': '2026-09-24 ',
        'newline': '2026-09-24\n', 'tab': '\t2026-09-24',
        'unicode-space': '\u00a02026-09-24', 'unicode-digits': '２０２６-０９-２４',
        'slash': '2026/09/24', 'slash-suffix': '2026-09-24/other',
        'query': '2026-09-24?x=1', 'fragment': '2026-09-24#x',
        'percent': '2026-09-24%2F',
    }
    cases.update({'date-' + key: envelope(dict(row, up_to_date_as_of=value))
                  for key, value in dates.items()})
    return cases


class Title33MetadataTests(unittest.TestCase):
    OUTPUT_ROOT = None

    @classmethod
    def setUpClass(cls):
        cls.support = load_file('sc159_support', REPO / 'tools/run_sc159_title33_metadata.py')
        if cls.OUTPUT_ROOT is None:
            # CI may supply an already admitted output root. Never mutate env.
            inherited = os.environ.get('SKIPPERCAST_TEST_OUTPUT_ROOT')
            prefix = Path(inherited) if inherited else REPO.parent / 'out/discovery'
            cls.run_root = prefix / ('sc159-' + uuid.uuid4().hex)
            cls.run_root.mkdir(parents=True, exist_ok=False)
        else:
            cls.run_root = Path(cls.OUTPUT_ROOT)
        cls.cases = []
        cls.origins = {}
        cls.methods = []

    @classmethod
    def tearDownClass(cls):
        cls.support.dump(cls.run_root / 'test-details.json', {
            'case_ids': cls.cases, 'module_origins': cls.origins,
            'method_ids': cls.methods,
            'fixture_hashes': {p.name: cls.support.digest(p) for p in sorted(FIXTURE.iterdir())
                               if p.is_file()},
        })
        print('SC159_DETAILS=' + str(cls.run_root / 'test-details.json'))

    def setUp(self):
        self.__class__.methods.append(self.id())
        self.temp = tempfile.TemporaryDirectory(prefix=self._testMethodName + '-', dir=self.run_root)
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.assertEqual(self.support.digest(FIXTURE / 'notice.xml'), NOTICE_SHA)
        self.assertEqual(self.support.digest(FIXTURE / 'titles.json'), TITLES_SHA)
        self.payload = json.loads((FIXTURE / 'titles.json').read_text())
        self.body = (FIXTURE / 'notice.xml').read_bytes()

    @contextmanager
    def case(self, name):
        self.__class__.cases.append(self._testMethodName + ':' + name)
        yield

    @contextmanager
    def product(self):
        with self.support.OfflineProduct(self.state) as context:
            yield context.product
            self.assertEqual(context.events, [])
            self.__class__.origins.update(context.origins)

    def config(self):
        return {'security_zones': [], 'reviewed_notice_sections': [{
            'section': '334.9999', 'classification': 'outside-reviewed-scope',
            'review_basis': 'Inert synthetic scope review; not a real restriction',
            'reviewed_xml_sha256': NOTICE_SHA}]}

    def call(self, product, payload, config):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        calls = []
        def getter(url):
            calls.append(url)
            return raw if url == TITLES_URL else self.body
        result = product.security_layer(config, getter)
        return result, calls, raw

    def assert_invalid(self, product, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        calls = []
        config = self.config()
        before = deepcopy(config)
        def getter(url):
            calls.append(url)
            return raw if url == TITLES_URL else self.body
        with self.assertRaisesRegex(ValueError, 'invalid title 33 metadata'):
            product.security_layer(config, getter)
        self.assertEqual(calls, [TITLES_URL], 'section getter called for invalid metadata')
        self.assertEqual(config, before)

    def assert_positive(self, product, date='2026-09-24', notice=False):
        payload = deepcopy(self.payload)
        payload['titles'][1]['up_to_date_as_of'] = date
        # Other valid title rows remain intact and never become the selected row.
        before = deepcopy(payload)
        config = self.config() if notice else {'security_zones': [], 'reviewed_notice_sections': []}
        ((layer, receipt), calls, raw) = self.call(product, payload, config)
        expected_sections = []
        expected_calls = [TITLES_URL]
        if notice:
            url = f'https://www.ecfr.gov/api/versioner/v1/full/{date}/title-33.xml?section=334.9999'
            expected_calls.append(url)
            expected_sections.append({'url': url, 'sha256': NOTICE_SHA,
                                      'up_to_date_as_of': date,
                                      'classification': 'outside-reviewed-scope'})
        self.assertEqual(calls, expected_calls)
        self.assertEqual(layer, {'type': 'FeatureCollection', 'features': []})
        self.assertEqual(receipt, {'titles_url': TITLES_URL,
                                  'titles_sha256': self.support.hashlib.sha256(raw).hexdigest(),
                                  'sections': expected_sections, 'up_to_date_as_of': date})
        self.assertEqual(payload, before)

    def test_positive_contract(self):
        with self.product() as product:
            # Empty zones/notices never instantiate geometry or parse DMS.
            with patch.object(product, 'Geod', side_effect=AssertionError('geometry entered')), \
                 patch.object(product, 'Polygon', side_effect=AssertionError('geometry entered')), \
                 patch.object(product, 'reviewed_dms_polygon', side_effect=AssertionError('DMS entered')), \
                 patch.object(product, 'reviewed_dms_coastal_envelope', side_effect=AssertionError('DMS entered')):
                for date in ('2026-09-24', '2024-02-29', '2000-02-29', '0001-01-01', '9999-12-31'):
                    for notice in (False, True):
                        with self.subTest(date=date, notice=notice), self.case(f'{date}-notice={notice}'):
                            self.assert_positive(product, date, notice)

    def test_rejects_malformed(self):
        with self.product() as product:
            for name, payload in malformed_cases().items():
                with self.subTest(case=name), self.case(name):
                    self.assert_invalid(product, payload)

    def test_baseline_compatibility(self):
        # Direct real-API compatibility, not a claim to have run original GIS
        # suites which consume catalog/source fixtures outside this card's input.
        with self.product() as product:
            for classification in ('outside-reviewed-scope', 'trip-time-vessel-restriction'):
                with self.subTest(classification=classification), self.case(classification):
                    config = self.config()
                    config['reviewed_notice_sections'][0]['classification'] = classification
                    ((layer, receipt), calls, _) = self.call(product, self.payload, config)
                    self.assertEqual(layer['features'], [])
                    self.assertEqual(receipt['sections'][0]['classification'], classification)
                    self.assertEqual(receipt['sections'][0]['sha256'], NOTICE_SHA)
                    self.assertEqual(len(calls), 2)
            for name, value, pattern in (
                ('hash', '0' * 64, 'scope review required'),
                ('classification', 'unreviewed', 'Invalid reviewed notice section'),
                ('section', '../bad', 'Invalid reviewed notice section'),
            ):
                with self.subTest(case=name), self.case('preserve-' + name):
                    config = self.config()
                    key = 'reviewed_xml_sha256' if name == 'hash' else name
                    config['reviewed_notice_sections'][0][key] = value
                    with self.assertRaisesRegex(ValueError, pattern):
                        self.call(product, self.payload, config)
            with self.case('security-xml-hash-preserved'):
                config = {'security_zones': [{'section': '334.9999',
                                              'reviewed_xml_sha256': '0' * 64}]}
                with self.assertRaisesRegex(ValueError, 'Security text changed'):
                    self.call(product, self.payload, config)

    def peer_test(self):
        old_path = sys.path[:]
        old_modules = {k: v for k, v in sys.modules.items()
                       if k == 'tests' or k.startswith('tests.')}
        try:
            # The repository root is already importable (pytest `pythonpath`, or
            # the SC159 runner); tests never edit sys.path themselves.
            for key in old_modules:
                sys.modules.pop(key)
            peer = load_file('sc159_peer_dco', REPO / 'tests/unit/test_check_dco.py')
            stream = io.StringIO()
            result = unittest.TextTestRunner(stream=stream).run(unittest.TestSuite([
                peer.DcoTests('test_outside_contributor_with_matching_sign_off_passes')]))
            self.assertEqual(result.testsRun, 1)
            self.assertTrue(result.wasSuccessful(), stream.getvalue())
            self.assertEqual(result.skipped, [])
            return stream.getvalue().splitlines()[-1]
        finally:
            sys.path[:] = old_path
            for key in list(sys.modules):
                if key == 'tests' or key.startswith('tests.'):
                    sys.modules.pop(key)
            sys.modules.update(old_modules)

    def test_isolation_and_discovery(self):
        with self.case('original-peer-before-after'):
            before_peer = self.peer_test()
            before = (sys.path[:], sys.meta_path[:], dict(os.environ), sys.dont_write_bytecode,
                      socket.create_connection, subprocess.Popen)
            modules = {k: v for k, v in sys.modules.items()
                       if k == 'skippercast' or k.startswith('skippercast.')}
            with self.product() as product:
                self.assertEqual(product.REPO, self.state)
                self.assertEqual(product.refresh.__defaults__[0], self.state)
                self.assertNotEqual(subprocess.Popen, before[-1])
                self.assertNotEqual(socket.create_connection, before[-2])
                self.assert_positive(product, notice=True)
            after = (sys.path[:], sys.meta_path[:], dict(os.environ), sys.dont_write_bytecode,
                     socket.create_connection, subprocess.Popen)
            self.assertEqual(before, after)
            self.assertEqual(modules, {k: v for k, v in sys.modules.items()
                                      if k == 'skippercast' or k.startswith('skippercast.')})
            self.assertEqual(self.peer_test(), before_peer)
        with self.case('ordinary-loader-five-required-methods'):
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(type(self))
            expected = {name for names in self.support.METHODS.values() for name in names}
            self.assertEqual({test._testMethodName for test in suite}, expected)
            self.assertEqual(suite.countTestCases(), 5)
        with self.case('evidence-complete-positive'):
            logs = self.state / 'logs'
            logs.mkdir()
            (logs / 'stdout.txt').write_text('complete\n')
            (logs / 'stderr.txt').write_text('complete\n')
            frozen = self.support.log_inventory(logs)
            self.assertTrue(self.support.verify_logs(logs, frozen))
        with self.case('evidence-missing-log'):
            missing = self.state / 'missing-logs'
            missing.mkdir()
            (missing / 'stdout.txt').write_text('complete\n')
            with self.assertRaisesRegex(ValueError, 'missing evidence log'):
                self.support.verify_logs(missing, frozen)
        with self.case('evidence-mutated-log'):
            (logs / 'stdout.txt').write_text('mutated!\n')
            with self.assertRaisesRegex(ValueError, 'changed evidence log'):
                self.support.verify_logs(logs, frozen)
        with self.case('evidence-late-append'):
            late = self.state / 'late-logs'
            late.mkdir()
            (late / 'stdout.txt').write_text('complete\n')
            (late / 'stderr.txt').write_text('complete\n')
            original = self.support.log_inventory(late)
            with (late / 'stderr.txt').open('a') as writer:
                writer.write('late writer output\n')
            with self.assertRaisesRegex(ValueError, 'changed evidence log'):
                self.support.verify_logs(late, original)
        with self.case('evidence-new-complete-positive'):
            fresh = self.state / 'fresh-complete-logs'
            fresh.mkdir()
            (fresh / 'stdout.txt').write_text('finished fresh writer\n')
            (fresh / 'stderr.txt').write_text('finished fresh writer\n')
            self.assertTrue(self.support.verify_logs(fresh, self.support.log_inventory(fresh)))

    def test_deciding_negative_control(self):
        cases = malformed_cases()
        with self.product() as product:
            genuine = product._title33_issue
            def legacy(document):
                return next(row for row in document['titles'] if row['number'] == 33)['up_to_date_as_of']
            for name in ('duplicate-int', 'date-query'):
                with self.subTest(case=name), self.case('mutant-detected-' + name):
                    # Same real security_layer, same getter/config and SAME deciding
                    # regression assertion. Only the synthetic selector seam differs.
                    with patch.object(product, '_title33_issue', legacy):
                        with self.assertRaisesRegex(AssertionError, 'ValueError not raised') as failure:
                            self.assert_invalid(product, cases[name])
                        print('INTENDED_MUTANT_FAILURE ' + name + ': ' + str(failure.exception))
                        self.assert_positive(product)
                    self.assertIs(product._title33_issue, genuine)
                    self.assert_invalid(product, cases[name])
                    self.assert_positive(product)
            with self.case('restored-positive-leap-day'):
                self.assert_positive(product, '2024-02-29', notice=True)


if __name__ == '__main__':
    unittest.main()
