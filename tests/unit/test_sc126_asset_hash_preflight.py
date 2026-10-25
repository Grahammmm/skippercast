"""SC126: verified_file refuses a malformed SHA-256 declaration before any cache or download work.

Offline and synthetic only. Destinations and sessions in the refusal cases are
fail-on-access sentinels, so the download path is never exercised; network
and subprocess entry points are refused for every test. The cached asset is a
small text fixture whose digest was frozen independently with sha256sum.
The product module is imported in setUp, after those sentinels are in place.
A cold import binds some entry points as defaults (skippercast.http.Session
resolver=socket.getaddrinfo), so cleanup rebinds any default or module global
that captured a sentinel back to the original before the patches stop.
"""
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'sc126-asset-hash-preflight' / 'cached-asset.json'
CODE = 'invalid_asset_sha256'
HELPER = '_require_asset_sha256_declaration'
URL = 'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/sc126/synthetic.tif'
ASSET = json.loads(FIXTURE.read_text(encoding='utf-8'))
DIGEST = ASSET['sha256']
DECIDING_VALUE = 'z' * 64   # 64 characters, none of them hex
NEGATIVE_CONTROL_EVIDENCE = {}
ISOLATION_EVIDENCE = []


def mixed_case(text):
    return ''.join(c.upper() if i % 2 else c.lower() for i, c in enumerate(text))


MALFORMED = (
    ('null', None),
    ('bool_true', True),
    ('bool_false', False),
    ('integer', 0),
    ('bytes_hex', DIGEST.encode('ascii')),
    ('bytearray_hex', bytearray(DIGEST.encode('ascii'))),
    ('list', [DIGEST]),
    ('dict', {'sha256': DIGEST}),
    ('object', object()),
    ('empty', ''),
    ('short_63', DIGEST[:63]),
    ('long_65', DIGEST + '0'),
    ('long_128', DIGEST * 2),
    ('nonhex_last_g', DIGEST[:63] + 'g'),
    ('nonhex_all_z', DECIDING_VALUE),
    ('hex_prefix_0x', '0x' + DIGEST[:62]),
    ('non_ascii_digits', '\u0663' * 64),
    ('fullwidth_hex', '\uff41' * 64),
    ('leading_space', ' ' + DIGEST),
    ('trailing_space', DIGEST + ' '),
    ('internal_space', DIGEST[:32] + ' ' + DIGEST[33:]),
    ('tab', DIGEST[:63] + '\t'),
    ('trailing_newline', DIGEST + '\n'),
    ('trailing_crlf', DIGEST + '\r\n'),
    ('newline_in_64', DIGEST[:63] + '\n'),
)


class UnapprovedActivity(AssertionError):
    """A filesystem, session, network or subprocess action this contract does not admit."""


class DestinationAccessed(UnapprovedActivity):
    pass


class SessionAccessed(UnapprovedActivity):
    pass


class FailOnAccessDestination:
    """Destination stand-in: any attribute or path use is recorded, then refused."""

    def __init__(self, log):
        object.__setattr__(self, '_log', log)

    def __getattr__(self, name):
        object.__getattribute__(self, '_log').append(name)
        raise DestinationAccessed(f'destination accessed: {name}')

    def __fspath__(self):
        object.__getattribute__(self, '_log').append('__fspath__')
        raise DestinationAccessed('destination accessed: __fspath__')

    def __repr__(self):
        return '<FailOnAccessDestination>'


class FailOnAccessSession:
    """Session stand-in: any attribute use is recorded, then refused."""

    def __init__(self, log):
        object.__setattr__(self, '_log', log)

    def __getattr__(self, name):
        object.__getattribute__(self, '_log').append(name)
        raise SessionAccessed(f'session accessed: {name}')

    def __repr__(self):
        return '<FailOnAccessSession>'


def _preflight_disabled(expected):
    """SC126 negative control: the declaration preflight switched off in memory."""
    return None


REFUSED_ENTRY_POINTS = (
    (socket.socket, 'connect', 'socket.socket.connect'),
    (socket, 'create_connection', 'socket.create_connection'),
    (socket, 'getaddrinfo', 'socket.getaddrinfo'),
    (subprocess, 'Popen', 'subprocess.Popen'),
    (os, 'system', 'os.system'),
)


def _functions(holder):
    if isinstance(holder, (staticmethod, classmethod)):
        holder = holder.__func__
    if isinstance(holder, property):
        return [f for f in (holder.fget, holder.fset, holder.fdel) if isinstance(f, types.FunctionType)]
    return [holder] if isinstance(holder, types.FunctionType) else []


def import_captures(module_names, lookup, apply=False):
    """Find module globals, class attributes and function defaults holding a replaced object.

    lookup(value) returns (True, original) for a captured object. With apply,
    each capture is rebound to its original. Returns the capture locations.
    """
    found = []
    for name in sorted(module_names):
        module = sys.modules.get(name)
        if module is None:
            continue
        for key, value in list(vars(module).items()):
            hit, original = lookup(value)
            if hit:
                found.append(f'{name}.{key}')
                if apply:
                    setattr(module, key, original)
                continue
            if isinstance(value, type) and value.__module__ == name:
                owner, holders = value, list(vars(value).items())
            elif isinstance(value, types.FunctionType) and value.__module__ == name:
                owner, holders = None, [(key, value)]
            else:
                continue
            for attr, holder in holders:
                where = f'{name}.{key}' + (f'.{attr}' if owner is not None else '')
                hit, original = lookup(holder)
                if hit and owner is not None:
                    found.append(where)
                    if apply:
                        setattr(owner, attr, original)
                    continue
                for function in _functions(holder):
                    defaults = function.__defaults__ or ()
                    if any(lookup(d)[0] for d in defaults):
                        found.append(f'{where}.__defaults__')
                        if apply:
                            function.__defaults__ = tuple(
                                lookup(d)[1] if lookup(d)[0] else d for d in defaults)
                    for kw, default in list((function.__kwdefaults__ or {}).items()):
                        hit, original = lookup(default)
                        if hit:
                            found.append(f'{where}.__kwdefaults__[{kw}]')
                            if apply:
                                function.__kwdefaults__[kw] = original
    return found


def tree(root):
    """Every path under root with its bytes (None for a directory)."""
    return {p.relative_to(root).as_posix(): (None if p.is_dir() else p.read_bytes())
            for p in sorted(Path(root).rglob('*'))}


class AssetHashPreflightTest(unittest.TestCase):

    def setUp(self):
        self.activity, self.replaced = {}, {}
        preloaded_http = sys.modules.get('skippercast.http')
        self.resolver_before = (preloaded_http.Session.__init__.__kwdefaults__['resolver']
                                if preloaded_http is not None else socket.getaddrinfo)
        for owner, name, label in REFUSED_ENTRY_POINTS:
            original = getattr(owner, name)
            double = self._refuse(owner, name, label)
            self.activity[label] = double
            self.replaced[id(double)] = (double, original, label)
        loaded = set(sys.modules)
        self.io = importlib.import_module('skippercast.seafloor.io')
        self.scanned = {n for n in sys.modules if n not in loaded or n.split('.')[0] == 'skippercast'}
        self.addCleanup(self._assert_isolated)
        self.addCleanup(self._rebind_import_captures)
        self.activity['http.default_session'] = self._refuse(self.io.http, 'default_session',
                                                             'default_session')
        spy = mock.patch.object(self.io, 'sha256', wraps=self.io.sha256)
        self.hashes = spy.start()
        self.addCleanup(spy.stop)
        self.addCleanup(self._assert_no_activity)
        temporary = tempfile.TemporaryDirectory(prefix='sc126-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cached = self.root / 'cache' / ASSET['file_name']
        self.cached.parent.mkdir()
        self.cached.write_bytes(ASSET['payload'].encode('utf-8'))
        self.assertEqual(hashlib.sha256(self.cached.read_bytes()).hexdigest(), DIGEST)

    def _refuse(self, owner, name, label):
        def refused(*args, **kwargs):
            raise UnapprovedActivity(f'unapproved activity: {label}')
        patcher = mock.patch.object(owner, name, side_effect=refused)
        double = patcher.start()
        self.addCleanup(patcher.stop)
        return double

    def _lookup(self, value):
        entry = self.replaced.get(id(value))
        return (True, entry[1]) if entry is not None and entry[0] is value else (False, None)

    def _rebind_import_captures(self):
        """Rebind defaults/globals that a cold import bound to a sentinel back to the original."""
        rebound = import_captures(self.scanned, self._lookup, apply=True)
        ISOLATION_EVIDENCE.append(dict(test=self.id().rsplit('.', 1)[-1], rebound=rebound))

    def _assert_isolated(self):
        self.assertEqual(import_captures(self.scanned, self._lookup), [])
        resolver = self.io.http.Session.__init__.__kwdefaults__['resolver']
        self.assertIs(resolver, self.resolver_before)

    def _assert_no_activity(self):
        self.assertEqual({k: v.call_count for k, v in self.activity.items() if v.call_count}, {})

    def _refusal_without_io(self, value, fetch):
        """Call the real API on sentinels; return the destination and session access logs."""
        destination_log, session_log = [], []
        before = self.hashes.call_count
        try:
            self.io.verified_file(URL, value, FailOnAccessDestination(destination_log), fetch,
                                  session=FailOnAccessSession(session_log))
        except ValueError as error:
            self.assertIn(CODE, str(error))
        else:
            self.fail(f'{CODE} was not raised')
        self.assertEqual(destination_log, [])
        self.assertEqual(session_log, [])
        self.assertEqual(self.hashes.call_count, before)

    def test_regression(self):
        for label, value in MALFORMED:
            for fetch in (True, False):
                with self.subTest(case=label, fetch=fetch):
                    self._refusal_without_io(value, fetch)

    def test_compatibility(self):
        session_log = []
        for label, value in (('lowercase', DIGEST.lower()), ('uppercase', DIGEST.upper()),
                             ('mixed_case', mixed_case(DIGEST))):
            for fetch in (True, False):
                with self.subTest(case=label, fetch=fetch):
                    before = self.hashes.call_count
                    actual = self.io.verified_file(URL, value, self.cached, fetch,
                                                   session=FailOnAccessSession(session_log))
                    self.assertEqual(actual, DIGEST)
                    self.assertEqual(self.hashes.call_count - before, 1)
                    self.assertEqual(self.cached.read_bytes(), ASSET['payload'].encode('utf-8'))
        for label, value in (('mismatch_lower', '0' * 64), ('mismatch_upper', 'ABCDEF' + '0' * 58)):
            with self.subTest(case=label):
                self.assertNotEqual(value.lower(), DIGEST)
                with self.assertRaises(ValueError) as caught:
                    self.io.verified_file(URL, value, self.cached, False)
                self.assertEqual(str(caught.exception), f'SHA-256 mismatch for {ASSET["file_name"]}')
                self.assertNotIn(CODE, str(caught.exception))
        for label, value in (('cache_miss_lower', DIGEST), ('cache_miss_upper', DIGEST.upper())):
            with self.subTest(case=label):
                missing = self.root / 'missing' / ASSET['file_name']
                before = self.hashes.call_count
                with self.assertRaises(FileNotFoundError) as caught:
                    self.io.verified_file(URL, value, missing, False,
                                          session=FailOnAccessSession(session_log))
                self.assertEqual(caught.exception.args, (missing,))
                self.assertFalse(missing.parent.exists())
                self.assertEqual(self.hashes.call_count, before)
        self.assertEqual(session_log, [])

    def _deciding(self):
        """The deciding zero-I/O regression for one malformed value, both fetch modes."""
        for fetch in (True, False):
            self._refusal_without_io(DECIDING_VALUE, fetch)

    def test_negative_control(self):
        product = Path(self.io.__file__)
        product_bytes = product.read_bytes()
        original = getattr(self.io, HELPER)
        function = self.io.verified_file
        hashes_before = self.hashes.call_count
        inner = None
        setattr(self.io, HELPER, _preflight_disabled)
        try:
            try:
                self._deciding()
            except AssertionError as error:
                inner = error
        finally:
            setattr(self.io, HELPER, original)
        self.assertIs(getattr(self.io, HELPER), original)
        self.assertIs(self.io.verified_file, function)
        self.assertEqual(product.read_bytes(), product_bytes)
        detected = isinstance(inner, DestinationAccessed)
        NEGATIVE_CONTROL_EVIDENCE.update(
            disabled_with=_preflight_disabled.__name__, deciding_value='z*64',
            inner_failure_class=type(inner).__name__ if inner else None,
            inner_failure_message=str(inner) if inner else None,
            detected_first_destination_access=detected,
            hashes_while_disabled=self.hashes.call_count - hashes_before)
        self.assertIsInstance(inner, DestinationAccessed)
        self.assertEqual(str(inner), 'destination accessed: exists')
        self.assertEqual(self.hashes.call_count, hashes_before)
        actual = self.io.verified_file(URL, DIGEST, self.cached, False)
        self.assertEqual(actual, DIGEST)
        self._deciding()
        NEGATIVE_CONTROL_EVIDENCE.update(restored_positive_passed=True, restored_deciding_passed=True)

    def test_preservation(self):
        bystander = self.root / 'bystander.txt'
        bystander.write_bytes(b'sc126 bystander bytes\n')
        cases = (
            ('accepted_cached_lower', DIGEST, self.cached, False, None),
            ('accepted_cached_upper_fetch', DIGEST.upper(), self.cached, True, None),
            ('rejected_list_container', [DIGEST], self.cached, False, ValueError),
            ('rejected_dict_container', {'sha256': DIGEST, 'nested': [DIGEST]}, self.cached, True, ValueError),
            ('rejected_existing_cache_short', DIGEST[:63], self.cached, False, ValueError),
            ('rejected_missing_fetch', DIGEST + '\n', self.root / 'new' / 'asset.tif', True, ValueError),
        )
        for label, value, destination, fetch, refusal in cases:
            with self.subTest(case=label):
                snapshot, copied = tree(self.root), copy.deepcopy(value)
                before = self.hashes.call_count
                session_log = []
                session = FailOnAccessSession(session_log)
                if refusal is None:
                    self.assertEqual(self.io.verified_file(URL, value, destination, fetch, session=session), DIGEST)
                    self.assertEqual(self.hashes.call_count - before, 1)
                else:
                    with self.assertRaises(refusal) as caught:
                        self.io.verified_file(URL, value, destination, fetch, session=session)
                    self.assertIn(CODE, str(caught.exception))
                    self.assertEqual(self.hashes.call_count, before)
                self.assertEqual(value, copied)
                self.assertEqual(tree(self.root), snapshot)
                self.assertEqual(session_log, [])
                self._assert_no_activity()
        self.assertEqual(bystander.read_bytes(), b'sc126 bystander bytes\n')
        self.assertFalse(any(name.endswith('.part') for name in os.listdir(self.cached.parent)))


if __name__ == '__main__':
    unittest.main()
