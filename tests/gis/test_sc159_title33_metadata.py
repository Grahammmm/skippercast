"""SC159 synthetic title ingress tests; safe ordinary unittest discovery.

No product imports, writes, audit hooks, environment changes or native stubs
occur at module import time. Product imports happen only inside OfflineProduct.
"""
import builtins
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import hashlib
import importlib
import importlib.abc
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


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'litellm',
                                     'hermes_tools', 'transformers'}:
            raise RuntimeError('offline model import refused')
        return None


class OfflineProduct:
    """Fixture-scoped seams, installed before any product import.

    This is an accidental-side-effect guard, not a hostile-code sandbox. No
    permanent audit hooks or fake native libraries are installed. Native library
    data lookups needed for ordinary imports remain genuine staged dependencies.
    """
    def __init__(self, state):
        self.state = Path(state).resolve()
        self.stack = ExitStack()
        self.events = []

    def refuse(self, *args, **kwargs):
        self.events.append('refused-side-effect')
        raise RuntimeError('offline network/model/child execution refused')

    def __enter__(self):
        self.old_path = sys.path[:]
        self.old_meta = sys.meta_path[:]
        self.old_bytecode = sys.dont_write_bytecode
        self.old_modules = {k: v for k, v in sys.modules.items()
                            if k == 'skippercast' or k.startswith('skippercast.')}
        for key in self.old_modules:
            sys.modules.pop(key)
        sys.path.insert(0, str(REPO / 'src'))
        sys.dont_write_bytecode = True
        sys.meta_path.insert(0, NoModels())
        try:
            for target in ('socket.create_connection', 'socket.getaddrinfo',
                           'socket.socket.connect', 'socket.socket.connect_ex',
                           'socket.socket.sendto', 'subprocess.Popen', 'os.system',
                           'os.popen', 'os.execv', 'os.execve', 'os.execl',
                           'os.execlp', 'os.execvp', 'os.execvpe', 'os.spawnv',
                           'os.spawnve', 'os.spawnvp', 'os.spawnvpe', 'os.fork',
                           'os.posix_spawn', 'os.posix_spawnp'):
                module, name = target.rsplit('.', 1)
                owner = importlib.import_module(module) if module != 'socket.socket' else socket.socket
                if hasattr(owner, name):
                    self.stack.enter_context(patch.object(owner, name, self.refuse))
            # Refuse Python-level host/catalog/cache reads during product imports.
            # Reads of source bytes, genuine installed packages and synthetic state
            # are allowed. Writes are confined to the test's own state.
            for owner, name in ((builtins, 'open'), (io, 'open')):
                original = getattr(owner, name)
                def guarded(file, mode='r', *args, _open=original, **kwargs):
                    if isinstance(file, (str, bytes, os.PathLike)):
                        path = Path(os.fsdecode(file)).absolute()
                        write = any(ch in mode for ch in 'wax+')
                        if write and not path.is_relative_to(self.state):
                            raise RuntimeError('offline write outside synthetic state')
                        allowed = (path.is_relative_to(self.state)
                                   or path.is_relative_to(REPO / 'src')
                                   or path.is_relative_to(REPO / 'tests')
                                   or path.is_relative_to(Path(sys.prefix))
                                   or path.is_relative_to(Path(sys.base_prefix))
                                   or str(path) in {'/dev/null', '/proc/meminfo'})
                        if not allowed:
                            raise RuntimeError('offline host/source read refused')
                    return _open(file, mode, *args, **kwargs)
                self.stack.enter_context(patch.object(owner, name, guarded))
            paths = importlib.import_module('skippercast.paths')
            self.stack.enter_context(patch.object(paths, 'repo_root', return_value=self.state))
            http = importlib.import_module('skippercast.http')
            self.stack.enter_context(patch.object(http, 'default_session', self.refuse))
            self.stack.enter_context(patch.object(http.Session, 'get', self.refuse))
            self.stack.enter_context(patch.object(http.Session, 'download', self.refuse))
            self.product = importlib.import_module('skippercast.seafloor.screen_sources')
            contracts = importlib.import_module('skippercast.platform.contracts')
            if contracts.REPO != self.state or self.product.refresh.__defaults__[0] != self.state:
                raise RuntimeError('synthetic root/default redirection failed')
            for name, module in list(sys.modules.items()):
                if name == 'skippercast' or name.startswith('skippercast.'):
                    origin = getattr(module, '__file__', None)
                    if origin and not Path(origin).resolve().is_relative_to(REPO / 'src'):
                        raise RuntimeError('product imported outside candidate')
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, *exc):
        self.stack.close()
        for key in list(sys.modules):
            if key == 'skippercast' or key.startswith('skippercast.'):
                sys.modules.pop(key)
        sys.modules.update(self.old_modules)
        sys.path[:] = self.old_path
        sys.meta_path[:] = self.old_meta
        sys.dont_write_bytecode = self.old_bytecode


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
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=self._testMethodName + '-')
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.assertEqual(digest(FIXTURE / 'notice.xml'), NOTICE_SHA)
        self.assertEqual(digest(FIXTURE / 'titles.json'), TITLES_SHA)
        self.payload = json.loads((FIXTURE / 'titles.json').read_text())
        self.body = (FIXTURE / 'notice.xml').read_bytes()

    @contextmanager
    def product(self):
        with OfflineProduct(self.state) as context:
            yield context.product
            self.assertEqual(context.events, [])

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
                                  'titles_sha256': hashlib.sha256(raw).hexdigest(),
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
                        with self.subTest(date=date, notice=notice):
                            self.assert_positive(product, date, notice)

    def test_rejects_malformed(self):
        with self.product() as product:
            for name, payload in malformed_cases().items():
                with self.subTest(case=name):
                    self.assert_invalid(product, payload)

    def test_baseline_compatibility(self):
        # Direct real-API compatibility, not a claim to have run original GIS
        # suites which consume catalog/source fixtures outside this card's input.
        with self.product() as product:
            for classification in ('outside-reviewed-scope', 'trip-time-vessel-restriction'):
                with self.subTest(classification=classification):
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
                with self.subTest(case=name):
                    config = self.config()
                    key = 'reviewed_xml_sha256' if name == 'hash' else name
                    config['reviewed_notice_sections'][0][key] = value
                    with self.assertRaisesRegex(ValueError, pattern):
                        self.call(product, self.payload, config)
            with self.subTest(case='security-xml-hash-preserved'):
                config = {'security_zones': [{'section': '334.9999',
                                              'reviewed_xml_sha256': '0' * 64}]}
                with self.assertRaisesRegex(ValueError, 'Security text changed'):
                    self.call(product, self.payload, config)

    def peer_test(self):
        old_path = sys.path[:]
        old_modules = {k: v for k, v in sys.modules.items()
                       if k == 'tests' or k.startswith('tests.')}
        try:
            # The repository root is already importable (pytest `pythonpath`);
            # tests never edit sys.path themselves.
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

    def test_isolation(self):
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

    def test_deciding_negative_control(self):
        cases = malformed_cases()
        with self.product() as product:
            genuine = product._title33_issue
            def legacy(document):
                return next(row for row in document['titles'] if row['number'] == 33)['up_to_date_as_of']
            for name in ('duplicate-int', 'date-query'):
                with self.subTest(case=name):
                    # Same real security_layer, same getter/config and SAME deciding
                    # regression assertion. Only the synthetic selector seam differs.
                    with patch.object(product, '_title33_issue', legacy):
                        with self.assertRaisesRegex(AssertionError, 'ValueError not raised'):
                            self.assert_invalid(product, cases[name])
                        self.assert_positive(product)
                    self.assertIs(product._title33_issue, genuine)
                    self.assert_invalid(product, cases[name])
                    self.assert_positive(product)
            self.assert_positive(product, '2024-02-29', notice=True)


if __name__ == '__main__':
    unittest.main()
