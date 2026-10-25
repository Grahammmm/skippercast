"""Offline direct-API coverage for SC163; no worker execution or source access."""
import builtins
from contextlib import ExitStack, contextmanager
import importlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
EVENTS = []
ORIGINS = {}
CONTROL = {}


def peer_check(expected):
    def harmless_peer():
        actual = (list(sys.path), sys.dont_write_bytecode, dict(os.environ),
                  subprocess.Popen, socket.socket.connect, os.open)
        unittest.TestCase().assertEqual(actual, expected)
    result = unittest.TestResult()
    unittest.FunctionTestCase(harmless_peer).run(result)
    if not result.wasSuccessful() or result.testsRun != 1:
        raise AssertionError('harmless peer test failed: ' + str(result.failures + result.errors))


def forbidden(*args, **kwargs):
    raise RuntimeError('SC163 offline boundary: network/model/child/write forbidden')


@contextmanager
def readonly():
    original_open, original_os_open = builtins.open, os.open

    def open_file(file, mode='r', *args, **kwargs):
        if any(flag in mode for flag in 'wax+'):
            return forbidden()
        return original_open(file, mode, *args, **kwargs)

    def open_fd(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            return forbidden()
        return original_os_open(path, flags, *args, **kwargs)

    with mock.patch.object(builtins, 'open', open_file), mock.patch.object(io, 'open', open_file), \
            mock.patch.object(os, 'open', open_fd), \
            mock.patch.object(os, 'write', forbidden), mock.patch.object(os, 'mkdir', forbidden), \
            mock.patch.object(os, 'unlink', forbidden), mock.patch.object(os, 'rename', forbidden), \
            mock.patch.object(os, 'replace', forbidden):
        yield


def producer():
    # Vocabulary is the actual worker.run/completion producer identity, not a lease grant.
    return json.loads((REPO / 'tests/fixtures/sc163-worker-json/producer.json').read_text())


class WorkerJSONTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = (list(sys.path), sys.dont_write_bytecode, dict(os.environ),
                      subprocess.Popen, socket.socket.connect, os.open)
        peer_check(cls.before)
        base = globals().get('OUTPUT_ROOT')
        if base is None:
            base = Path(tempfile.gettempdir()) if os.environ.get('CI') else REPO.parent / 'out'
        base.mkdir(parents=True, exist_ok=True)
        cls.root = Path(tempfile.mkdtemp(prefix='sc163-discovery-', dir=base))
        cls.prior_output = cls.root / 'prior-output.txt'
        cls.prior_output.write_bytes(b'preserve prior synthetic output\n')
        cls.prior_stat = cls.prior_output.stat()
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.saved = {k: v for k, v in sys.modules.items() if k == 'skippercast' or k.startswith('skippercast.')}
        for key in cls.saved:
            del sys.modules[key]
        cls.stack.callback(cls.restore_modules)
        cls.stack.enter_context(mock.patch.object(sys, 'path', [str(REPO / 'src'), *sys.path]))
        cls.stack.enter_context(mock.patch.object(sys, 'dont_write_bytecode', True))
        # Install before any product/native import; never pre-initialize numpy or GIS libraries.
        for obj, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                          (socket, 'create_connection'), (socket, 'getaddrinfo'),
                          (subprocess, 'Popen'), (os, 'system'), (os, 'fork'),
                          (os, 'posix_spawn'), (os, 'posix_spawnp')):
            cls.stack.enter_context(mock.patch.object(obj, name, forbidden))
        with readonly():
            cls.worker = importlib.import_module('skippercast.coastal.authenticated_v1.worker')
        for name, module in list(sys.modules.items()):
            if name == 'skippercast' or name.startswith('skippercast.'):
                origin = Path(module.__file__).resolve()
                if not origin.is_relative_to(REPO / 'src'):
                    raise RuntimeError('noncandidate product module: ' + str(origin))
                ORIGINS[name] = str(origin)
        # These are not invoked. Their sentinels prove direct read_job cannot start work.
        for name in ('main', 'run', 'runtime_limits', 'bind_reserved_source', 'authenticate',
                     'read_header', 'plan_header', 'produce_snapshot', 'verify_snapshot', 'write'):
            cls.stack.enter_context(mock.patch.object(cls.worker, name, forbidden))

    @classmethod
    def restore_modules(cls):
        for key in list(sys.modules):
            if key == 'skippercast' or key.startswith('skippercast.'):
                del sys.modules[key]
        sys.modules.update(cls.saved)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        after = (list(sys.path), sys.dont_write_bytecode, dict(os.environ),
                 subprocess.Popen, socket.socket.connect, os.open)
        if after != cls.before:
            raise AssertionError('peer state not restored')
        peer_check(cls.before)
        (cls.root / 'discovery.json').write_text(json.dumps(dict(
            events=EVENTS, origins=ORIGINS, control=CONTROL, peer_state_restored=True,
            ids=[cls.__module__ + '.' + cls.__qualname__ + '.' + name
                 for name in sorted({event['method'] for event in EVENTS})],
            method_count=len({event['method'] for event in EVENTS}),
            named_check_count=len(EVENTS), harmless_peer_tests=2), indent=2) + '\n')
        print('SC163 discovery evidence: ' + str(cls.root / 'discovery.json'))

    def note(self, name):
        EVENTS.append({'method': self._testMethodName, 'subcase': name})

    def request(self, data):
        root = Path(tempfile.mkdtemp(prefix='case-', dir=self.root))
        path = root / 'var/coastal/jobs/job/lease/job.json'
        path.parent.mkdir(parents=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return path

    def read(self, path, *, fingerprint=False, truncate=False, grow=False):
        """Track actual descriptor ownership and unchanged files for every API call."""
        original_open, original_close, original_fstat, original_read = os.open, os.close, os.fstat, os.read
        opened, closed, active = [], [], set()
        before = [(p, p.read_bytes(), p.stat()) for p in path.parent.iterdir() if p.is_file() and not p.is_symlink()]
        entries = sorted(p.name for p in path.parent.iterdir())
        stat_count = 0

        def track_open(*args, **kwargs):
            self.assertFalse(args[1] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            fd = original_open(*args, **kwargs)
            opened.append(fd)
            active.add(fd)
            return fd

        def track_close(fd):
            self.assertIn(fd, active)
            active.remove(fd)
            closed.append(fd)
            return original_close(fd)

        def changed_stat(fd):
            nonlocal stat_count
            st = original_fstat(fd)
            stat_count += 1
            if fingerprint and stat_count == 2:
                from types import SimpleNamespace
                return SimpleNamespace(st_dev=st.st_dev, st_ino=st.st_ino, st_size=st.st_size,
                                       st_mtime_ns=st.st_mtime_ns + 1, st_ctime_ns=st.st_ctime_ns)
            return st

        def read_bytes(fd, count):
            if truncate:
                return b''
            data = original_read(fd, count)
            return b'x' if grow and not data and count == 1 else data

        try:
            with readonly(), mock.patch.object(os, 'open', track_open), \
                    mock.patch.object(os, 'close', track_close), mock.patch.object(os, 'fstat', changed_stat), \
                    mock.patch.object(os, 'read', read_bytes):
                return self.worker.read_job(path)
        finally:
            self.assertEqual(active, set(), 'descriptor leak')
            self.assertEqual(self.prior_output.read_bytes(), b'preserve prior synthetic output\n')
            prior = self.prior_output.stat()
            self.assertEqual((prior.st_ino, prior.st_size, prior.st_mtime_ns, prior.st_ctime_ns),
                             (self.prior_stat.st_ino, self.prior_stat.st_size,
                              self.prior_stat.st_mtime_ns, self.prior_stat.st_ctime_ns))
            self.assertEqual(len(opened), len(closed))
            self.assertEqual(entries, sorted(p.name for p in path.parent.iterdir()))
            for p, data, st in before:
                self.assertEqual(p.read_bytes(), data)
                current = p.stat()
                self.assertEqual((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns),
                                 (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))

    def reject_duplicate_stage(self, path):
        with self.assertRaisesRegex(ValueError, 'invalid_job_request_json'):
            self.read(path)

    def test_regression(self):
        valid = json.dumps(producer())
        variants = {
            'stage_conflict': valid[:-1] + ',"stage":"qualify"}',
            'stage_equal': valid[:-1] + ',"stage":"acquire"}',
            'lease_conflict': valid[:-1] + ',"lease_token":"other"}',
            'lease_equal': valid[:-1] + ',"lease_token":"synthetic-lease"}',
            'job_identity': valid[:-1] + ',"job_id":"synthetic:other"}',
            'nested_conflict': valid[:-1] + ',"nested":{"x":1,"x":2}}',
            'nested_equal': valid[:-1] + ',"nested":{"x":1,"x":1}}',
            'array_nested': valid[:-1] + ',"nested":[{"x":1,"x":2}]}',
            'escaped_key': valid[:-1] + ',"st\\u0061ge":"qualify"}',
            'positive_overflow': valid[:-1] + ',"overflow":1e999}',
            'negative_overflow': valid[:-1] + ',"overflow":-1e999}',
            'nested_overflow': valid[:-1] + ',"overflow":[{"value":1e999}]}',
        }
        for name, text in variants.items():
            with self.subTest(case=name):
                self.note(name)
                self.reject_duplicate_stage(self.request(text))

    def test_compatibility(self):
        valid = producer()
        cases = {'unique_finite': json.dumps(valid), 'finite_exponent': '{"n":1e20,"tiny":-1e-999}',
                 'unicode': '{"é":"雪","nested":{"a":1},"other":{"a":2}}',
                 'qualify_optional': json.dumps(dict(valid, stage='qualify', extra='Infinity'))}
        for name, text in cases.items():
            with self.subTest(case=name):
                self.note(name)
                self.assertEqual(self.read(self.request(text)), json.loads(text))
        for token in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(case=token):
                self.note(token)
                with self.assertRaises(ValueError):
                    self.read(self.request('{"n":' + token + '}'))

    def test_negative_control(self):
        path = self.request(json.dumps(producer())[:-1] + ',"stage":"qualify"}')
        valid = self.request(json.dumps(producer()))
        original_loads = json.loads

        def legacy_decoder(data):
            return original_loads(data, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite request')))

        self.note('legacy_positive')
        # Baseline has no private decoder yet; this branch permits honest expected-red execution.
        if not hasattr(self.worker, '_decode_job_request'):
            self.assertEqual(self.read(valid), producer())
            self.note('baseline_duplicate_stage_expected_red')
            self.reject_duplicate_stage(path)
            return
        genuine = self.worker._decode_job_request
        with mock.patch.object(self.worker, '_decode_job_request', legacy_decoder):
            self.assertEqual(self.read(valid), producer())
            self.assertEqual(self.read(path)['stage'], 'qualify')
            self.note('same_assertion_detects_legacy_acceptance')
            try:
                self.reject_duplicate_stage(path)
            except AssertionError as error:
                self.assertIn('ValueError not raised', str(error))
                CONTROL.update(inner_assertion=str(error), detected=True)
            else:
                self.fail('duplicate-stage assertion did not detect legacy acceptance')
        self.assertIs(self.worker._decode_job_request, genuine)
        self.note('restored_duplicate_rejected')
        self.reject_duplicate_stage(path)
        self.note('restored_unique_positive')
        self.assertEqual(self.read(valid), producer())
        CONTROL['restored_positive'] = True

    def test_preservation(self):
        cases = {'empty': (b'', 'bounded single-link'), 'oversize': (b' ' * (2 * 1024 * 1024 + 1), 'bounded single-link'),
                 'list': (b'[]', 'object request'), 'null': (b'null', 'object request'),
                 'scalar': (b'1', 'object request'), 'malformed_json': (b'{', None),
                 'malformed_utf8': (b'{"x":"\xff"}', None)}
        for name, (data, reason) in cases.items():
            with self.subTest(case=name):
                self.note(name)
                if reason:
                    with self.assertRaisesRegex(ValueError, reason):
                        self.read(self.request(data))
                else:
                    with self.assertRaises(ValueError):
                        self.read(self.request(data))
        for name in ('fingerprint', 'truncate', 'grow'):
            with self.subTest(case=name):
                self.note(name)
                with self.assertRaisesRegex(ValueError, 'request truncated' if name == 'truncate' else 'request changed'):
                    self.read(self.request('{}'), **{name: True})
        self.note('exact_byte_limit')
        self.assertEqual(self.read(self.request(b'{}' + b' ' * (2 * 1024 * 1024 - 2))), {})
        self.note('wrong_namespace')
        path = self.request('{}')
        wrong = path.with_name('other.json')
        wrong.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'namespace'):
            self.read(wrong)
        self.note('hardlink')
        os.link(path, path.with_name('hardlink'))
        with self.assertRaisesRegex(ValueError, 'single-link'):
            self.read(path)
        self.note('symlink_leaf')
        leaf = self.request('{}')
        target = leaf.with_name('target')
        leaf.rename(target)
        leaf.symlink_to(target.name)
        with self.assertRaises(OSError):
            self.read(leaf)
        self.note('symlink_ancestor')
        real = self.request('{}')
        alias = real.parent.parent / 'alias'
        alias.symlink_to(real.parent.name, target_is_directory=True)
        with self.assertRaises(OSError):
            self.read(alias / 'job.json')
        self.note('nonregular_directory')
        fifo = self.request('{}').parent / 'fifo'
        fifo.mkdir()
        # A directory at the leaf tests regular-file refusal without waiting on any pipe.
        bad = fifo / 'var/coastal/jobs/job/lease/job.json'
        bad.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'single-link'):
            self.read(bad)


if __name__ == '__main__':
    unittest.main()
