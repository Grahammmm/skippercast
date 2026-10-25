"""SC162: full-module, synthetic-only descriptor-bound JSON acceptance.

Fixture vocabulary mirrors BatchOwner.create's state dictionary, without invoking
that lifecycle. No control read here attests authority or scientific acceptance.
"""
from contextlib import contextmanager, ExitStack
import copy
import errno
import importlib
import importlib.abc
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
FIXTURE = REPO / "tests/fixtures/sc162-batch-control-json/control.json"
MODULE = "skippercast.coastal.authenticated_v1.source_reuse"
REGRESSION_CASES = {
    "root-equal": b'"state":"ready","state":"ready"',
    "root-conflict": b'"state":"refused","state":"ready"',
    "nested-equal": b'"leases":{"0:acquire":{"state":"leased","state":"leased"}}',
    "nested-conflict": b'"leases":{"0:acquire":{"state":"leased","state":"completed"}}',
    "escaped-root": b'"state":"refused","st\\u0061te":"ready"',
    "escaped-nested": b'"leases":{"x":{"token":1,"t\\u006fken":2}}',
    "array-nested": b'"extra":[{"x":1,"x":2}]',
    "nan": b'"extra":NaN',
    "infinity": b'"extra":Infinity',
    "negative-infinity": b'"extra":-Infinity',
    "overflow": b'"extra":1e999',
    "negative-overflow": b'"extra":-1e999',
    "nested-overflow": b'"extra":{"array":[1e999]}',
    "invalid-utf8": b'"extra":"\xff"',
    "trailing-comma": b'"extra":1,',
}
TOP_CASES = {
    "list": b'[]', "null": b'null', "string": b'"ready"',
    "integer": b'1', "float": b'1.5', "boolean": b'true',
    "incomplete": b'{', "trailing-json": b'{}{}', "whitespace": b' ',
    "utf16": '{"state":"ready"}'.encode('utf-16'),
    "utf32": '{"state":"ready"}'.encode('utf-32'),
    "nested-incomplete": b'{"extra":' + b'[' * 2000,
}
COMPATIBILITY_CASES = (
    "admitted", "ready", "refused", "closed", "nested-finite-unicode",
    "exact-byte-limit", "below-byte-limit",
)
PRESERVATION_CASES = (
    "empty", "oversize", "hardlink", "directory", "fifo", "symlink",
    "truncated", "changed-fingerprint", "partial-reads", "patch-restoration", "decoder-recursion",
)
REQUIRED_CASES = {
    "test_regression": set(REGRESSION_CASES) | set(TOP_CASES),
    "test_compatibility": set(COMPATIBILITY_CASES),
    "test_negative_control": {"legacy-detected", "restored-rejection", "restored-positive"},
    "test_preservation": set(PRESERVATION_CASES),
}


def output_parent():
    # Operator-staged local candidate, otherwise CI's inherited temporary root.
    if (REPO.parent / "SOURCE-MANIFEST.json").is_file():
        parent = REPO.parent / "out"
    else:
        parent = Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    return parent


def forbidden(*args, **kwargs):
    raise RuntimeError("SC162 offline sentinel: network/model/child execution forbidden")


class NoModelImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {"openai", "anthropic", "ollama", "litellm", "hermes"}:
            forbidden()
        return None


@contextmanager
def offline_module():
    """Real complete imports; reversible guards precede any product import.

    Static closure: source_reuse -> budget/receipts/runner -> _owned_processes.
    No platform.contracts, native library or model startup is reachable. Preserve
    pre-existing peer imports, and unload only modules introduced in this scope.
    """
    old_path = list(sys.path)
    old_bytecode = sys.dont_write_bytecode
    old_meta = list(sys.meta_path)
    before = set(sys.modules)
    parents = {name: dict(vars(value)) for name, value in sys.modules.copy().items()
               if name == "skippercast" or name.startswith("skippercast.")}
    finder = NoModelImports()
    try:
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(REPO / "src"))
        sys.meta_path.insert(0, finder)
        with ExitStack() as stack:
            for target in ("socket.socket.connect", "socket.socket.connect_ex",
                           "socket.create_connection", "socket.getaddrinfo",
                           "subprocess.Popen", "os.system", "os.fork", "os.forkpty",
                           "os.posix_spawn", "os.posix_spawnp", "os.execve", "os.execv",
                           "os.execvpe", "os.execvp", "os.spawnv", "os.spawnve",
                           "os.spawnvp", "os.spawnvpe", "os.popen"):
                stack.enter_context(mock.patch(target, forbidden))
            module = importlib.import_module(MODULE)
            for name, value in sys.modules.copy().items():
                if name == "skippercast" or name.startswith("skippercast."):
                    origin = getattr(value, "__file__", None)
                    if origin and not Path(origin).resolve().is_relative_to(REPO / "src"):
                        raise RuntimeError(f"noncandidate module origin: {name}: {origin}")
            # Fail before lifecycle/source/process paths could execute accidentally.
            for attr in ("_process", "_open_source", "_hash_fd", "_check_origin", "boot_id"):
                stack.enter_context(mock.patch.object(module, attr, forbidden))
            stack.enter_context(mock.patch.object(module.BatchOwner, "create", forbidden))
            stack.enter_context(mock.patch.object(module.Budget, "__init__", forbidden))
            yield module
    finally:
        for name in set(sys.modules) - before:
            if name == "skippercast" or name.startswith("skippercast."):
                del sys.modules[name]
        for name, attributes in parents.items():
            current = vars(sys.modules[name])
            for attr in set(current) - set(attributes):
                del current[attr]
            current.update(attributes)
        sys.meta_path[:] = old_meta
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_bytecode


class BatchControlJSONTests(unittest.TestCase):
    # Assigned per instance by runner, never global environment mutation.
    output_root = None

    def setUp(self):
        parent = Path(self.output_root) if self.output_root else output_parent()
        self.root = Path(tempfile.mkdtemp(prefix="sc162-", dir=parent))
        self.prior = self.root / "prior-output.txt"
        self.prior.write_bytes(b"preserve prior output\n")
        self.control = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.module = self.stack.enter_context(offline_module())
        self.origins = {name: value.__file__ for name, value in sys.modules.copy().items()
                        if (name == 'skippercast' or name.startswith('skippercast.'))
                        and getattr(value, '__file__', None)}
        self.events = []
        self.addCleanup(self.save_events)

    def save_events(self):
        (self.root / "events.json").write_text(json.dumps(self.events, indent=2) + "\n")

    def shaped(self, fragment):
        # Drop the replaced keys, so each subcase isolates only its intended defect.
        value = copy.deepcopy(self.control)
        if fragment.startswith(b'"state"'):
            del value["state"]
        if fragment.startswith(b'"leases"'):
            del value["leases"]
        return json.dumps(value, ensure_ascii=False).encode('utf-8')[:-1] + b',' + fragment + b'}'

    def snapshot(self):
        result = {}
        for path in sorted(self.root.iterdir()):
            st = path.lstat()
            data = path.read_bytes() if path.is_file() and not path.is_symlink() else None
            result[path.name] = (st.st_dev, st.st_ino, st.st_mode, st.st_size,
                                 st.st_mtime_ns, st.st_ctime_ns, st.st_nlink, data)
        return result

    def checked_load(self, path, expected=None, error=None, closes=1, seam=None, error_errno=None):
        before = self.snapshot()
        real_open, real_close = os.open, os.close
        opened, closed = [], []

        def opening(*args, **kwargs):
            self.assertEqual(Path(args[0]), path, 'only the synthetic control may be opened')
            self.assertEqual(args[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            fd = real_open(*args, **kwargs)
            opened.append(fd)
            return fd

        def closing(fd):
            closed.append(fd)
            return real_close(fd)

        try:
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(self.module.os, 'open', opening))
                stack.enter_context(mock.patch.object(self.module.os, 'close', closing))
                if seam:
                    stack.enter_context(seam)
                if error:
                    with self.assertRaisesRegex(error[0], error[1]) as refused:
                        self.module._load(path)
                    if error_errno is not None:
                        self.assertEqual(refused.exception.errno, error_errno)
                else:
                    self.assertEqual(self.module._load(path), expected)
        finally:
            self.assertEqual(self.snapshot(), before, "control/prior output changed or new side effect")
            self.assertEqual(len(closed), closes)
            self.assertEqual(closed, opened)
            for fd in opened:
                with self.assertRaises(OSError) as raised:
                    os.fstat(fd)
                self.assertEqual(raised.exception.errno, errno.EBADF)

    def input_file(self, raw):
        path = self.root / ("control-" + str(len(list(self.root.iterdir()))) + ".json")
        path.write_bytes(raw)
        return path

    def assert_invalid(self, raw):
        self.checked_load(self.input_file(raw), error=(ValueError, "invalid_batch_control_json"))

    def record(self, case, **details):
        self.events.append(dict(id=self.id(), method=self._testMethodName, case=case, **details))

    def test_regression(self):
        for case, fragment in REGRESSION_CASES.items():
            with self.subTest(case=case):
                self.assert_invalid(self.shaped(fragment))
                self.record(case)
        for case, raw in TOP_CASES.items():
            with self.subTest(case=case):
                self.assert_invalid(raw)
                self.record(case)

    def test_compatibility(self):
        for state in ("admitted", "ready", "refused", "closed"):
            with self.subTest(case=state):
                value = dict(self.control, state=state)
                self.checked_load(self.input_file(json.dumps(value).encode()), expected=value)
                self.record(state)
        with self.subTest(case="nested-finite-unicode"):
            value = dict(self.control, extra={"海": [1.25e100, 1e-300, -0.0, True, None,
                                                  {"NaN": "NaN", "Infinity": "-Infinity"}]})
            self.checked_load(self.input_file(json.dumps(value, ensure_ascii=False).encode()), expected=value)
            self.record("nested-finite-unicode")
        for case, size in (("exact-byte-limit", 131072), ("below-byte-limit", 131071)):
            with self.subTest(case=case):
                raw = json.dumps(self.control).encode()
                self.checked_load(self.input_file(raw + b' ' * (size - len(raw))), expected=self.control)
                self.record(case)

    def test_negative_control(self):
        raw = self.shaped(REGRESSION_CASES["root-conflict"])
        genuine = self.module._decode_batch_control_json
        with self.subTest(case="legacy-detected"):
            with mock.patch.object(self.module, '_decode_batch_control_json', json.loads):
                with self.assertRaisesRegex(AssertionError, 'ValueError not raised') as caught:
                    self.assert_invalid(raw)
                self.record("legacy-detected", inner_assertion=str(caught.exception),
                            mutated_callable="json.loads", legacy_value=json.loads(raw)["state"])
        self.assertIs(self.module._decode_batch_control_json, genuine)
        with self.subTest(case="restored-rejection"):
            self.assert_invalid(raw)
            self.record("restored-rejection")
        with self.subTest(case="restored-positive"):
            self.checked_load(self.input_file(json.dumps(self.control).encode()), expected=self.control)
            self.record("restored-positive")

    def test_preservation(self):
        # Existing gates must decide before any decode attempt.
        for case, raw in (("empty", b''), ("oversize", b'x' * 131073), ("hardlink", b'{')):
            with self.subTest(case=case):
                path = self.input_file(raw)
                if case == "hardlink":
                    os.link(path, self.root / 'hardlink-alias')
                with mock.patch.object(self.module.json, 'loads', side_effect=AssertionError('parser reached')):
                    self.checked_load(path, error=(ValueError, 'bounded single-link batch control required'))
                self.record(case)
        for case in ("directory", "fifo"):
            with self.subTest(case=case):
                path = self.root / case
                path.mkdir() if case == "directory" else os.mkfifo(path)
                with mock.patch.object(self.module.json, 'loads', side_effect=AssertionError('parser reached')):
                    self.checked_load(path, error=(ValueError, 'bounded single-link batch control required'))
                self.record(case)
        with self.subTest(case="symlink"):
            target = self.input_file(b'{')
            path = self.root / 'symlink'
            path.symlink_to(target.name)
            with mock.patch.object(self.module.json, 'loads', side_effect=AssertionError('parser reached')):
                self.checked_load(path, error=(OSError, ''), closes=0, error_errno=errno.ELOOP)
            self.record("symlink")
        with self.subTest(case="truncated"):
            path = self.input_file(b'{')
            self.checked_load(path, error=(ValueError, 'batch control truncated'),
                              seam=mock.patch.object(self.module.os, 'read', return_value=b''))
            self.record("truncated")
        with self.subTest(case="changed-fingerprint"):
            path = self.input_file(b'{')
            with mock.patch.object(self.module, '_fingerprint', side_effect=[('after',), ('before',)]):
                with mock.patch.object(self.module.json, 'loads', side_effect=AssertionError('parser reached')):
                    self.checked_load(path, error=(ValueError, 'batch control changed while reading'))
            self.record("changed-fingerprint")
        with self.subTest(case="decoder-recursion"):
            path = self.input_file(b'{}')
            self.checked_load(path, error=(ValueError, 'invalid_batch_control_json'),
                              seam=mock.patch.object(self.module.json, 'loads', side_effect=RecursionError))
            self.record("decoder-recursion")
        with self.subTest(case="partial-reads"):
            path = self.input_file(json.dumps(self.control).encode())
            original_read = os.read
            self.checked_load(path, expected=self.control,
                              seam=mock.patch.object(self.module.os, 'read',
                                                     lambda fd, n: original_read(fd, min(n, 7))))
            self.record("partial-reads")
        with self.subTest(case="patch-restoration"):
            peer_before = (socket.socket.connect, subprocess.Popen, os.system, list(sys.path),
                           list(sys.meta_path), sys.dont_write_bytecode)
            with offline_module() as nested:
                self.assertIs(nested, self.module)
                self.checked_load(self.input_file(b'{}'), expected={})
            self.assertEqual(peer_before, (socket.socket.connect, subprocess.Popen, os.system,
                                          list(sys.path), list(sys.meta_path), sys.dont_write_bytecode))
            self.record("patch-restoration")


if __name__ == '__main__':
    unittest.main(verbosity=2)
