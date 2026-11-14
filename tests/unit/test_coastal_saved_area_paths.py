"""validate_adoption opens the exact saved-area producer database, never a URI reinterpretation.

Boundary: only the metadata prerequisites before the database open are isolated; the
real continuation_grant, path checks, closed-database gate and SQLite open run.
"""
import sqlite3
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from skippercast.coastal.coordinator import saved_area, source_free

RESERVED = ['q?x', 'h#x', 'p%23x', 'p%3Fx', 'bare%', 'sp ace', 'uni\u00e9', 'a?b#c%23d', 'x?mode=rw']


class Reached(Exception):
    pass


def _grant(contract, out):
    return dict(saved_area_continuation_contract=contract, window_count=4, window_side=128,
                source_reuse_contract=None, larger_runtime_contract='coastal-managed-eight-copy-four128-v1',
                source=dict(bytes=36757568), source_volume_cap_bytes=220545408,
                prior_effective_bytes=895006524, cumulative_limit_bytes=1115551932,
                execution_authorized=True, window_set=[1], source_root='s', source_relative_path='r',
                output_root=out)


def _make_db(path, marker, jobs=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE marker(v TEXT)')
    con.execute('INSERT INTO marker VALUES(?)', (marker,))
    if jobs:
        con.execute('CREATE TABLE jobs(job_id TEXT,state TEXT,stage TEXT,result_sha TEXT,record_json TEXT)')
    con.commit()
    con.close()


def _inventory(base):
    return {str(p.relative_to(base)): (p.read_bytes() if p.is_file() else None) for p in sorted(base.rglob('*'))}


class Harness:
    def __init__(self, test, base, origin):
        self.test, self.base, self.origin = test, base, origin
        self.opened = []
        self.closed = 0
        self.stop_after_open = True
        self.hook_after_gate = None
        self.marker = None

    def run(self):
        h = self
        real_connect = sqlite3.connect

        class Conn:
            def __init__(self, c):
                self.c = c

            def __getattr__(self, n):
                return getattr(self.c, n)

            def execute(self, *a):
                return self.c.execute(*a)

            @property
            def row_factory(self):
                return self.c.row_factory

            @row_factory.setter
            def row_factory(self, v):
                self.c.row_factory = v

            def close(self):
                h.closed += 1
                self.c.close()

        def connect(target, **kw):
            h.opened.append((target, kw))
            c = Conn(real_connect(target, **kw))
            if h.stop_after_open:
                try:
                    h.marker = c.c.execute('SELECT v FROM marker').fetchone()[0]
                finally:
                    c.close()
                raise Reached(h.marker)
            return c

        old_grant = _grant(None, 'old-out')
        docs = iter([dict(origin_root=str(self.origin), original_grant={}, origin_stop={},
                          qualified_result=dict(sha256='x'), origin_database={}), old_grant])
        orig_gate = source_free.require_closed_database

        def gate(path):
            r = orig_gate(path)
            if h.hook_after_gate:
                h.hook_after_gate(path)
            return r

        def load(root, ref, contract=None):
            if contract == 'coastal-four128-stop-proof-v1':
                return dict(descendants_empty=True, stop_exit_code=0, query_exit_code=0,
                            properties=dict(ActiveState='inactive', ControlGroup=''))
            return dict(job_id='j1')

        saved = {n: getattr(saved_area, n) for n in ('metadata_document', 'load', 'resolve', 'sqlite3')}
        saved_gate = source_free.require_closed_database
        saved_area.metadata_document = lambda *a: next(docs)
        saved_area.load = load
        saved_area.resolve = lambda *a, **k: self.origin / 'var/coastal/authenticated.sqlite'
        saved_area.sqlite3 = types.SimpleNamespace(connect=connect, Row=sqlite3.Row)
        source_free.require_closed_database = gate
        try:
            saved_area.validate_adoption(self.base / 'root', {}, _grant(saved_area.CONTRACT, 'new-out'),
                                         now=100.0, horizon=200.0)
        finally:
            for n, v in saved.items():
                setattr(saved_area, n, v)
            source_free.require_closed_database = saved_gate


class SavedAreaPaths(unittest.TestCase):
    def _setup(self, tmp, ancestor, marker='target', jobs=False):
        base = Path(tmp).resolve()
        (base / 'root').mkdir()
        origin = base / ancestor / 'origin'
        _make_db(origin / 'var/coastal/authenticated.sqlite', marker, jobs)
        return base, origin

    def test_reserved_ancestor_opens_literal_saved_producer(self):
        for name in RESERVED:
            with self.subTest(name), TemporaryDirectory() as tmp:
                base, origin = self._setup(tmp, name)
                before = _inventory(base)
                h = Harness(self, base, origin)
                with self.assertRaises(Reached):
                    h.run()
                self.assertEqual(h.marker, 'target')
                self.assertEqual(_inventory(base), before)
                self.assertEqual(h.closed, 1)

    def test_uri_lookalike_decoy_never_selected(self):
        with TemporaryDirectory() as tmp:
            base, origin = self._setup(tmp, 'dec?oy%23x')
            # truncated and percent-decoded candidates
            _make_db(base / 'dec', 'decoy-truncated')
            _make_db(base / 'dec#oyx/origin/var/coastal/authenticated.sqlite', 'decoy-decoded')
            before = _inventory(base)
            h = Harness(self, base, origin)
            with self.assertRaises(Reached):
                h.run()
            self.assertEqual(h.marker, 'target')
            self.assertEqual(_inventory(base), before)

    def test_ordinary_readonly_immutable_control(self):
        with TemporaryDirectory() as tmp:
            base, origin = self._setup(tmp, 'plain')
            before = _inventory(base)
            h = Harness(self, base, origin)
            with self.assertRaises(Reached):
                h.run()
            uri, kw = h.opened[0]
            self.assertTrue(uri.endswith('?mode=ro&immutable=1'))
            self.assertIs(kw.get('uri'), True)
            con = sqlite3.connect(uri, uri=True)
            with self.assertRaises(sqlite3.OperationalError):
                con.execute('INSERT INTO marker VALUES(?)', ('w',))
            con.close()
            self.assertEqual(_inventory(base), before)

    def test_missing_after_closed_check_never_created(self):
        for name in ('q?x', 'h#x'):
            with self.subTest(name), TemporaryDirectory() as tmp:
                base, origin = self._setup(tmp, name)
                db = origin / 'var/coastal/authenticated.sqlite'
                aside = base / 'aside.bin'
                h = Harness(self, base, origin)
                h.hook_after_gate = lambda p: db.rename(aside)
                before = _inventory(base)
                with self.assertRaises(sqlite3.OperationalError):
                    h.run()
                after = _inventory(base)
                self.assertFalse(db.exists())
                expected = dict(before)
                expected.pop(str(db.relative_to(base)))
                expected['aside.bin'] = before[str(db.relative_to(base))]
                self.assertEqual(after, expected)

    def test_closed_database_gate_still_precedes_connect(self):
        for suffix in ('-wal', '-journal'):
            with self.subTest(suffix), TemporaryDirectory() as tmp:
                base, origin = self._setup(tmp, 'g?x')
                db = origin / 'var/coastal/authenticated.sqlite'
                side = db.with_name(db.name + suffix)
                side.write_bytes(b'dirty')
                h = Harness(self, base, origin)
                with self.assertRaisesRegex(ValueError, 'closed checkpointed SQLite'):
                    h.run()
                self.assertEqual(h.opened, [])
                side.write_bytes(b'')
                with self.assertRaises(Reached):
                    Harness(self, base, origin).run()
                side.unlink()
                side.symlink_to(db)
                with self.assertRaisesRegex(ValueError, 'closed checkpointed SQLite'):
                    Harness(self, base, origin).run()

    def test_post_open_refusal_closes_connection(self):
        with TemporaryDirectory() as tmp:
            base, origin = self._setup(tmp, 'p?x', jobs=True)
            before = _inventory(base)
            h = Harness(self, base, origin)
            h.stop_after_open = False
            with self.assertRaisesRegex(ValueError, 'original committed qualified producer required'):
                h.run()
            self.assertEqual(h.closed, 1)
            self.assertEqual(_inventory(base), before)


if __name__ == '__main__':
    unittest.main()
