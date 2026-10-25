"""SC168: complete offline ledger graphs; no source/native execution authority."""
from contextlib import ExitStack, contextmanager
import copy
import hashlib
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
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
TOKEN = 'distinct_segment_campaign_ledgers_required'
EXPECTED = {
    'test_regression': ['exact', 'relative_absolute', 'dot', 'dotdot', 'string_path',
                        'preflight_before_payload_schema_reference', 'no_filesystem_resolution'],
    'test_compatibility': ['independent_chains', 'idempotency', 'crash_prefix',
                           'symlink_leaf', 'symlink_ancestor', 'hardlink_ledger', 'hardlink_lock'],
    'test_negative_control': ['mutant_first_write_detected', 'mutant_distinct_positive',
                              'restored_refusal', 'restored_distinct_positive'],
    'test_preservation': ['existing_ledgers_and_receipts', 'invalid_payload',
                          'descriptor_ownership', 'patch_restoration'],
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root):
    return {p.relative_to(root).as_posix(): digest(p)
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


def denied(*args, **kwargs):
    raise RuntimeError('SC168 offline boundary: network/model/child execution forbidden')


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'litellm'}:
            denied()
        return None


@contextmanager
def offline(root):
    """Reversible fixture-scoped guards precede every product import.

    Existing peer modules are parked, not modified; candidate modules and parent
    package attributes are restored afterward. No audit hook or environment edit.
    """
    prefixes = ('skippercast', 'coast_', 'validate_coast_receipt', 'review_common',
                'prepare_round', 'open_packet', 'write_verdict', 'tests.coast_',
                'tests._coastal_catalog_fixture', 'tests.gis.test_coast_sign_off_graph')
    def owned(name):
        return name == 'tests.gis' or any(name.startswith(p) for p in prefixes)
    saved = {k: v for k, v in sys.modules.items() if owned(k)}
    parents = {k: dict(vars(v)) for k, v in sys.modules.items()
               if k in {'tests', 'tests.gis'} and v is not None}
    old_path, old_meta, old_bytecode = sys.path[:], sys.meta_path[:], sys.dont_write_bytecode
    try:
        with ExitStack() as stack:
            for obj, names in [(socket.socket, ('connect', 'connect_ex', 'sendto')),
                               (socket, ('create_connection', 'getaddrinfo')),
                               (subprocess, ('Popen', 'run', 'call', 'check_call', 'check_output')),
                               (os, ('system', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp',
                                     'execv', 'execve', 'execl', 'execlp', 'execvp', 'execvpe')),
                               (urllib.request, ('urlopen',))]:
                for name in names:
                    if hasattr(obj, name):
                        stack.enter_context(mock.patch.object(obj, name, denied))
            sys.meta_path.insert(0, NoModels())
            sys.dont_write_bytecode = True
            for name in saved:
                sys.modules.pop(name)
            sys.path[:0] = [str(ROOT / 'src'), str(ROOT),
                            str(ROOT / 'skills/coast-campaign-shared/scripts'),
                            str(ROOT / 'skills/coast-sign-off/scripts')]
            paths = importlib.import_module('skippercast.paths')
            stack.enter_context(mock.patch.object(paths, 'repo_root', return_value=root / 'synthetic-repo'))
            graph = importlib.import_module('tests.gis.test_coast_sign_off_graph')
            validator = graph.validator
            schemas = root / 'synthetic-repo/skills/coast-campaign-shared/schemas'
            schemas.mkdir(parents=True)
            for source in sorted((ROOT / 'skills/coast-campaign-shared/schemas').glob('*.json')):
                (schemas / source.name).write_bytes(source.read_bytes())
            config = schemas.parent / 'config'
            config.mkdir()
            for source in sorted((ROOT / 'skills/coast-campaign-shared/config').glob('*.json')):
                (config / source.name).write_bytes(source.read_bytes())
            stack.enter_context(mock.patch.object(validator, 'SCHEMAS', schemas))
            stack.enter_context(mock.patch.object(validator, 'SHARED', schemas.parent))
            contracts = importlib.import_module('skippercast.platform.contracts')
            if contracts.REPO != root / 'synthetic-repo':
                raise RuntimeError('contracts imported before root redirection')
            origins = {name: str(Path(module.__file__).resolve())
                       for name, module in sys.modules.items()
                       if owned(name) and getattr(module, '__file__', None)}
            if not all(Path(p).is_relative_to(ROOT) for p in origins.values()):
                raise RuntimeError('non-candidate product module')
            yield graph, origins
            # Include lazily reached product modules, not just import-time closure.
            origins.update({name: str(Path(module.__file__).resolve())
                            for name, module in sys.modules.items()
                            if owned(name) and getattr(module, '__file__', None)})
            if not all(Path(p).is_relative_to(ROOT) for p in origins.values()):
                raise RuntimeError('non-candidate lazy product module')
    finally:
        for name in list(sys.modules):
            if owned(name):
                sys.modules.pop(name)
        sys.modules.update(saved)
        for name, attrs in parents.items():
            module = sys.modules[name]
            for key in set(vars(module)) - set(attrs):
                delattr(module, key)
            vars(module).update(attrs)
        sys.path[:] = old_path
        sys.meta_path[:] = old_meta
        sys.dont_write_bytecode = old_bytecode


class LedgerDistinctTests(unittest.TestCase):
    output_parent = None
    events = []
    origins = {}
    control = {}

    @classmethod
    def setUpClass(cls):
        inherited = os.environ.get('TMPDIR') if os.environ.get('CI') else None
        parent = cls.output_parent or (Path(inherited) if inherited else ROOT.parent / 'out/discovery')
        parent.mkdir(parents=True, exist_ok=True)
        cls.run_root = Path(tempfile.mkdtemp(prefix='sc168-', dir=parent))
        cls.events, cls.control = [], {}
        cls.peer = (sys.path[:], sys.meta_path[:], sys.dont_write_bytecode,
                    socket.socket.connect, subprocess.Popen, dict(os.environ))
        cls.context = offline(cls.run_root)
        try:
            cls.graph, cls.origins = cls.context.__enter__()
        except BaseException:
            cls.context.__exit__(*sys.exc_info())
            raise
        cls.addClassCleanup(cls.finish)

    @classmethod
    def finish(cls):
        cls.context.__exit__(None, None, None)
        current = (sys.path[:], sys.meta_path[:], sys.dont_write_bytecode,
                   socket.socket.connect, subprocess.Popen, dict(os.environ))
        if current != cls.peer:
            raise AssertionError('harmless peer observes leaked global state')
        (cls.run_root / 'discovery.json').write_text(json.dumps({
            'events': cls.events, 'origins': cls.origins, 'control': cls.control,
            'peer_before_after_equal': True}, indent=2) + '\n')
        print('SC168 evidence_root=' + str(cls.run_root), flush=True)

    @contextmanager
    def case(self, name):
        self.events.append({'method': self._testMethodName, 'case': name})
        print('SC168 ' + self._testMethodName + '/' + name, flush=True)
        with self.subTest(case=name):
            yield

    def fresh(self, label):
        return Path(tempfile.mkdtemp(prefix=label + '-', dir=self.run_root))

    def fixture(self, label):
        root = self.fresh(label)
        c = self.graph.Cycle(root).round()
        self.assertEqual(c.open(), 0)
        captured = {}
        def capture(segment, campaign, payload, **kwargs):
            captured.update(payload=copy.deepcopy(payload), kwargs=kwargs)
            return {}
        with mock.patch.object(self.graph.writer, 'append_index', capture):
            c.write(c.decisions())
        payload, kwargs = captured['payload'], captured['kwargs']
        # A complete full_graph positive is a prerequisite, not a fake validator.
        self.graph.validator.validate(dict(payload, seq=1, prev_row_sha256='0' * 64),
                                      kwargs['resolver'], root_id=kwargs['root_id'])
        return root, c, payload, kwargs

    def no_first_write(self, segment, campaign, payload, kwargs, *, watched):
        before = {p: p.read_bytes() if p.exists() else None for p in watched}
        error = None
        try:
            self.graph.ledger_module.append_index(segment, campaign, payload, **kwargs)
        except ValueError as caught:
            error = caught
        after = {p: p.read_bytes() if p.exists() else None for p in watched}
        self.assertEqual(after, before, 'no-first-write violated: segment ledger or lock changed')
        self.assertIsNotNone(error, 'equal destinations must refuse')
        self.assertIn(TOKEN, str(error))

    def positive(self, label):
        root, c, payload, kwargs = self.fixture(label)
        a, b = c.queue / 'ledger.jsonl', root / 'campaign-ledger.jsonl'
        result = self.graph.ledger_module.append_index(a, b, payload, **kwargs)
        for path, role in [(a, 'segment'), (b, 'campaign')]:
            rows = self.graph.ledger_module.verify(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['ledger_role'], role)
            self.assertEqual(rows[0]['seq'], 1)
            self.assertEqual(rows[0]['prev_row_sha256'], '0' * 64)
            self.assertEqual(result[role + '_row_sha256'], digest(path))
        self.assertNotEqual(digest(a), digest(b))
        self.assertEqual(result['campaign_row']['segment_row_sha256'], digest(a))
        return root, c, payload, kwargs, a, b, result

    def test_regression(self):
        root, c, payload, kwargs = self.fixture('regression')
        a = c.queue / 'ledger.jsonl'
        aliases = [('exact', a, a),
                   ('relative_absolute', os.path.relpath(a), a),
                   ('dot', str(a.parent) + '/./ledger.jsonl', a),
                   ('dotdot', str(a.parent) + '/absent/../ledger.jsonl', a),
                   ('string_path', str(a), a)]
        for name, segment, campaign in aliases:
            with self.case(name):
                self.no_first_write(segment, campaign, payload, kwargs,
                                    watched=[a, a.with_name(a.name + '.lock')])
        with self.case('preflight_before_payload_schema_reference'):
            with ExitStack() as stack:
                for obj, name in [(self.graph.ledger_module, 'append'),
                                  (self.graph.validator, 'validate_schema'),
                                  (kwargs['resolver'], 'read')]:
                    stack.enter_context(mock.patch.object(obj, name, side_effect=AssertionError('late gate reached')))
                with self.assertRaisesRegex(ValueError, TOKEN):
                    self.graph.ledger_module.append_index(a, a, None, **kwargs)
        with self.case('no_filesystem_resolution'):
            with ExitStack() as stack:
                for obj, name in [(Path, 'resolve'), (os, 'stat'), (os, 'lstat'), (os, 'open')]:
                    stack.enter_context(mock.patch.object(obj, name, side_effect=AssertionError('filesystem touched')))
                with self.assertRaisesRegex(ValueError, TOKEN):
                    self.graph.ledger_module.append_index(a, str(a.parent) + '/x/../ledger.jsonl', payload, **kwargs)

    def test_compatibility(self):
        with self.case('independent_chains'):
            root, c, payload, kwargs, a, b, result = self.positive('compatible')
        with self.case('idempotency'):
            before = snapshot(root)
            self.assertEqual(self.graph.ledger_module.append_index(a, b, payload, **kwargs), result)
            self.assertEqual(snapshot(root), before)
        with self.case('crash_prefix'):
            root2, c2, p2, kw2 = self.fixture('crash')
            s, t = c2.queue / 'ledger.jsonl', root2 / 'campaign-ledger.jsonl'
            self.graph.ledger_module.append(s, p2, **kw2)
            prefix = s.read_bytes()
            self.graph.ledger_module.append_index(s, t, p2, **kw2)
            self.assertEqual(s.read_bytes(), prefix)
            self.assertEqual(len(self.graph.ledger_module.verify(t)), 1)
        for mode in ('symlink_leaf', 'symlink_ancestor', 'hardlink_ledger', 'hardlink_lock'):
            with self.case(mode):
                folder = self.fresh(mode)
                source = folder / 'unchanged'
                source.write_bytes(b'')
                destination = folder / 'alias'
                if mode == 'symlink_leaf':
                    destination.symlink_to(source)
                elif mode == 'symlink_ancestor':
                    destination.symlink_to(folder, target_is_directory=True)
                    destination /= 'new-ledger'
                elif mode == 'hardlink_ledger':
                    os.link(source, destination)
                else:
                    os.link(source, destination.with_name(destination.name + '.lock'))
                with self.assertRaises((ValueError, OSError)):
                    self.graph.ledger_module.append_index(destination, folder / 'other', payload, **kwargs)
                self.assertEqual(source.read_bytes(), b'')
                self.assertFalse((folder / 'other').exists())

    def test_negative_control(self):
        module = self.graph.ledger_module
        with self.case('mutant_first_write_detected'):
            root, c, payload, kwargs = self.fixture('mutant-residue')
            a = c.queue / 'ledger.jsonl'
            with mock.patch.object(module, '_same_ledger_destination', return_value=False):
                with self.assertRaisesRegex(AssertionError, 'no-first-write violated') as caught:
                    self.no_first_write(a, a, payload, kwargs, watched=[a, a.with_name(a.name + '.lock')])
            self.assertEqual(len(module.verify(a)), 1)
            self.assertEqual(module.verify(a)[0]['ledger_role'], 'segment')
            self.control.update(inner_failure=str(caught.exception), residue=str(root),
                                segment_sha256=digest(a), rows=1)
        with self.case('mutant_distinct_positive'):
            with mock.patch.object(module, '_same_ledger_destination', return_value=False):
                self.positive('mutant-positive')
        with self.case('restored_refusal'):
            root, c, payload, kwargs = self.fixture('restored')
            a = c.queue / 'ledger.jsonl'
            self.no_first_write(a, a, payload, kwargs, watched=[a, a.with_name(a.name + '.lock')])
        with self.case('restored_distinct_positive'):
            self.positive('restored-positive')

    def test_preservation(self):
        root, c, payload, kwargs, a, b, result = self.positive('preservation')
        with self.case('existing_ledgers_and_receipts'):
            before = snapshot(root)
            self.no_first_write(a, a, payload, kwargs, watched=[a, b, a.with_name(a.name + '.lock')])
            self.assertEqual(snapshot(root), before)
        with self.case('invalid_payload'):
            folder = self.fresh('invalid-payload')
            before = snapshot(folder)
            with self.assertRaisesRegex(ValueError, 'requires segment payload'):
                self.graph.ledger_module.append_index(folder / 'a', folder / 'b', {}, **kwargs)
            self.assertEqual(snapshot(folder), before)
        with self.case('descriptor_ownership'):
            # Track actual OS opens/closes, without inspecting operational /proc.
            opened, closed = [], []
            real_open, real_close = os.open, os.close
            def track_open(*args, **kw):
                fd = real_open(*args, **kw)
                opened.append(fd)
                return fd
            real_dup = os.dup
            def track_dup(fd):
                duplicated = real_dup(fd)
                opened.append(duplicated)
                return duplicated
            def track_close(fd):
                closed.append(fd)
                return real_close(fd)
            with mock.patch.object(os, 'open', track_open), mock.patch.object(os, 'dup', track_dup), mock.patch.object(os, 'close', track_close):
                self.graph.ledger_module.append_index(a, b, payload, **kwargs)
                with self.assertRaisesRegex(ValueError, 'writer does not own'):
                    self.graph.ledger_module.append_index(a, b, payload, **dict(kwargs, writer='wrong'))
            self.assertCountEqual(opened, closed)
        with self.case('patch_restoration'):
            predicate = self.graph.ledger_module._same_ledger_destination
            with mock.patch.object(self.graph.ledger_module, '_same_ledger_destination', return_value=False):
                pass
            self.assertIs(self.graph.ledger_module._same_ledger_destination, predicate)
            self.assertEqual(dict(os.environ), self.peer[-1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
