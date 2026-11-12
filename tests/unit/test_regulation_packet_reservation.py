"""RF0640-7: one collector owns a packet folder while it fetches and writes.

Offline: synthetic fake source transport, real scratch folders, interleaving
forced at the folder-creation and source seams (no sleeps).
"""
from contextlib import redirect_stderr
from datetime import datetime, timezone, timedelta
import io
from pathlib import Path
import tempfile
import threading
from unittest import TestCase
from unittest.mock import patch

from skippercast.pipeline import regulation_review as rr

IDENT = 'california-southern'
MARKER = '.collection-in-progress'
REFUSED = 'Use a new packet directory; preserve previous evidence'
T0 = datetime(2026, 9, 22, 18, tzinfo=timezone.utc)


def clock(n):
    return T0 + timedelta(minutes=n)


class Reservation(TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.out = Path(holder.name) / 'packet'
        self.calls = []          # (collector clock, source id)
        self.on_source = None    # optional hook(now, source_id)
        self.fail_source = None  # optional exception raised after evidence is written
        real_mkdir = Path.mkdir
        self.mkdir_hook = None   # one-shot hook run before the first mkdir of self.out

        def fake_source(ident, *rest, now=None, client_factory=None):
            self.calls.append((now, ident))
            (self.out / (ident + '.html')).write_text(f'evidence {ident} {now.isoformat()}')
            if self.on_source:
                self.on_source(now, ident)
            if self.fail_source:
                raise self.fail_source
            return {'id': ident, 'status': 'ok', 'data': {'content_sha256': 'a' * 64}}

        def mkdir(path, *args, **kwargs):
            if path == self.out and self.mkdir_hook:
                hook, self.mkdir_hook = self.mkdir_hook, None
                hook()
            return real_mkdir(path, *args, **kwargs)

        for patcher in (
                patch.object(rr, 'source', fake_source),
                patch.object(rr, 'coverage', lambda registry, sources, now, ids=None: {'sources': sorted(sources)}),
                patch.object(rr, 'stamp', lambda now=None: (now or clock(99)).isoformat()),
                patch.object(Path, 'mkdir', mkdir)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def collect(self, n):
        return rr.collect_packet(IDENT, self.out, now=clock(n))

    def snapshot(self):
        return {p.name: p.read_bytes() for p in sorted(self.out.iterdir())}

    def test_active_collector_excludes_competing_collector(self):
        a_at_mkdir, a_may_acquire = threading.Event(), threading.Event()
        outcome = {}

        def a_hook():
            a_at_mkdir.set()          # A has passed its empty preflight
            a_may_acquire.wait(10)

        def run_a():
            self.mkdir_hook = a_hook
            try:
                self.collect(1)
            except Exception as error:
                outcome['a'] = error

        thread = threading.Thread(target=run_a)
        thread.start()
        self.assertTrue(a_at_mkdir.wait(10))
        b_calls = []

        def b_in_source(now, ident):
            if now != clock(2) or b_calls:
                return
            b_calls.append(ident)
            self.assertTrue((self.out / MARKER).exists())
            a_may_acquire.set()       # A now tries to acquire while B owns the folder
            thread.join(10)
            self.assertFalse(thread.is_alive())

        self.on_source = b_in_source
        packet = self.collect(2)      # B is the sole owner
        self.assertIsInstance(outcome['a'], ValueError)
        self.assertEqual(str(outcome['a']), REFUSED)
        self.assertEqual({n for n, _ in self.calls}, {clock(2)})   # A never reached a source
        self.assertEqual(packet['collected_at'], clock(2).isoformat())
        self.assertFalse((self.out / MARKER).exists())
        self.assertIn('packet.json', self.snapshot())
        self.assertIn('coverage.json', self.snapshot())

    def test_completed_competitor_after_preflight_is_preserved(self):
        results = {}

        def b_runs_to_completion():
            results['b'] = self.collect(2)
            results['after_b'] = self.snapshot()

        self.mkdir_hook = b_runs_to_completion   # fires after A's early preflight
        with self.assertRaises(ValueError) as caught:
            self.collect(1)
        self.assertEqual(str(caught.exception), REFUSED)
        self.assertEqual(self.snapshot(), results['after_b'])
        self.assertEqual({n for n, _ in self.calls}, {clock(2)})
        self.assertEqual(results['b']['collected_at'], clock(2).isoformat())
        self.assertNotIn(MARKER, self.snapshot())

    def test_missing_and_empty_output_remain_compatible(self):
        nested = self.out.parent / 'deep' / 'er' / 'packet'
        empty = self.out.parent / 'empty'
        empty.mkdir()
        packets = []
        for target in (nested, empty):
            self.out = target       # the fake source writes its evidence into self.out
            packets.append(self.collect(3))
        names = [sorted(p.name for p in t.iterdir()) for t in (nested, empty)]
        self.assertEqual(names[0], names[1])
        self.assertNotIn(MARKER, names[0])
        self.assertIn('packet.json', names[0])
        self.assertIn('coverage.json', names[0])
        self.assertEqual(sorted(packets[0]), sorted(packets[1]))
        for name in names[0]:
            self.assertEqual((nested / name).read_bytes(), (empty / name).read_bytes())

    def test_failed_acquisition_never_releases_another_owner(self):
        self.out.mkdir()
        (self.out / MARKER).write_bytes(b'other owner')
        (self.out / 'evidence.html').write_bytes(b'adjacent')
        with self.assertRaises(ValueError) as early:          # ordinary preflight refusal
            self.collect(1)
        self.assertEqual(str(early.exception), REFUSED)
        with self.assertRaises(ValueError) as direct:         # acquisition itself refuses
            with rr._reserve_packet_dir(self.out):
                self.fail('reservation must not be granted')
        self.assertEqual(str(direct.exception), REFUSED)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.snapshot(), {MARKER: b'other owner', 'evidence.html': b'adjacent'})

    def test_source_or_packet_failure_releases_only_owned_marker(self):
        self.fail_source = RuntimeError('source exploded')
        with self.assertRaisesRegex(RuntimeError, 'source exploded'):
            self.collect(1)
        kept = self.snapshot()
        self.assertTrue(kept)
        self.assertNotIn(MARKER, kept)
        self.assertTrue(all(name.endswith('.html') for name in kept))
        self.assertTrue(self.out.is_dir())
        # Packet failure after the first packet file: partial evidence stays, marker goes.
        self.fail_source = None
        other = self.out = self.out.parent / 'packet2'
        real = rr.atomic_json

        def flaky(path, value):
            real(path, value)
            if Path(path).name == 'packet.json':
                raise OSError('disk full')

        with patch.object(rr, 'atomic_json', flaky), self.assertRaisesRegex(OSError, 'disk full'):
            self.collect(2)
        names = {p.name for p in other.iterdir()}
        self.assertIn('packet.json', names)
        self.assertNotIn(MARKER, names)
        # An acquisition refusal in a folder with a foreign marker leaves that marker alone.
        self.fail_source = None
        third = self.out = self.out.parent / 'packet3'
        third.mkdir()
        (third / MARKER).write_bytes(b'foreign')
        with self.assertRaises(ValueError):
            self.collect(3)
        self.assertEqual((third / MARKER).read_bytes(), b'foreign')

    def test_cli_competing_collection_refuses_cleanly(self):
        self.mkdir_hook = lambda: self.collect(2)
        before = {}

        def main():
            err = io.StringIO()
            with redirect_stderr(err), patch('sys.argv', ['regulation_review', 'collect',
                                                          '--jurisdiction', IDENT, '--output', str(self.out)]):
                return rr.main(), err.getvalue()

        code, err = main()
        before.update(self.snapshot())
        self.assertEqual(code, 1)
        self.assertEqual(err, f'regulation review refused: {REFUSED}\n')
        self.assertNotIn('Traceback', err)
        self.assertNotIn(MARKER, before)
        # Sequential nonempty folder and file output keep their messages and bytes.
        code, err = main()
        self.assertEqual((code, err), (1, f'regulation review refused: {REFUSED}\n'))
        self.assertEqual(self.snapshot(), before)
        target = self.out.parent / 'file.txt'
        target.write_bytes(b'x')
        err = io.StringIO()
        with redirect_stderr(err), patch('sys.argv', ['regulation_review', 'collect',
                                                      '--jurisdiction', IDENT, '--output', str(target)]):
            code = rr.main()
        self.assertEqual((code, err.getvalue()), (1, 'regulation review refused: Packet output is not a folder\n'))
        self.assertEqual(target.read_bytes(), b'x')

    def test_release_error_preserves_primary_failure(self):
        real_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == MARKER:
                raise OSError('cannot release')
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', unlink):
            self.fail_source = RuntimeError('primary failure')
            with self.assertRaisesRegex(RuntimeError, 'primary failure'):
                self.collect(1)
            self.assertTrue((self.out / MARKER).exists())     # left for the operator, not hidden
            real_unlink(self.out / MARKER)
            for p in list(self.out.iterdir()):
                real_unlink(p)
            self.fail_source = None
            with self.assertRaisesRegex(OSError, 'cannot release'):   # clean work, failed release
                self.collect(2)
            self.assertIn('packet.json', self.snapshot())
