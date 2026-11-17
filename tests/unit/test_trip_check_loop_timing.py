"""CLI timing admission for scripts/trip_check_loop.py (synthetic; every boundary patched)."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import trip_check_loop

FLAGS = ('--budget-minutes', '--poll-seconds', '--settle-seconds')


def run_main(argv, summary=None):
    """Run main with watch and the clock faked; returns (status, stdout, stderr, watch mock, clock mock)."""
    out, err = io.StringIO(), io.StringIO()
    env = {'GITHUB_STEP_SUMMARY': str(summary)} if summary else {}
    status = None
    with mock.patch.object(trip_check_loop, 'watch', return_value=(1, 0)) as watch, \
            mock.patch.object(trip_check_loop.time, 'monotonic', return_value=1000.0) as clock, \
            mock.patch.dict(trip_check_loop.os.environ, env, clear=True), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            status = trip_check_loop.main(argv)
        except SystemExit as exc:
            status = exc.code
    return status, out.getvalue(), err.getvalue(), watch, clock


class TripCheckLoopTimingTests(unittest.TestCase):
    def assert_rejected(self, flag, value):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary.md'
            status, out, err, watch, clock = run_main([f'{flag}={value}'], summary)
            self.assertEqual(status, 2, (flag, value))
            self.assertIn(flag, err)
            self.assertIn('finite and non-negative', err)
            self.assertNotIn('Traceback', err)
            self.assertEqual(out, '')
            watch.assert_not_called()
            clock.assert_not_called()
            self.assertFalse(summary.exists())

    def test_nonfinite_timing_is_rejected_before_monitoring(self):
        for flag in FLAGS:
            for value in ('nan', 'inf', '-inf'):
                with self.subTest(flag=flag, value=value):
                    self.assert_rejected(flag, value)

    def test_negative_timing_is_rejected_before_monitoring(self):
        for flag in FLAGS:
            for value in ('-1', '-0.001'):
                with self.subTest(flag=flag, value=value):
                    self.assert_rejected(flag, value)

    def test_zero_and_fractional_timings_are_preserved(self):
        for budget, poll, settle in (('0', '0', '0'), ('-0', '-0', '-0'), ('1.5', '0.25', '2.5')):
            with self.subTest(budget=budget, poll=poll, settle=settle), tempfile.TemporaryDirectory() as tmp:
                summary = Path(tmp) / 'summary.md'
                status, out, err, watch, _ = run_main(
                    ['--budget-minutes', budget, '--poll-seconds', poll, '--settle-seconds', settle], summary)
                self.assertEqual((status, err), (0, ''))
                kwargs = watch.call_args.kwargs
                self.assertEqual(kwargs['deadline'], 1000.0 + float(budget) * 60)
                self.assertEqual((kwargs['poll'], kwargs['settle']), (float(poll), float(settle)))
                self.assertIn('1/1 trip checks succeeded.', out)
                self.assertEqual(summary.read_text(), '\n## Trip checks\n1/1 trip checks succeeded.\n')

    def test_default_timing_branch_and_once_are_preserved(self):
        _, _, _, watch, _ = run_main([])
        kwargs = watch.call_args.kwargs
        self.assertEqual((kwargs['deadline'], kwargs['poll'], kwargs['settle'], kwargs['once']),
                         (1000.0 + 345 * 60, 60, 90, False))
        with mock.patch.object(trip_check_loop, 'remote_head', return_value='abc') as remote_head:
            run_main(['--branch', 'other', '--once'])
            _, _, _, watch, _ = run_main(['--branch', 'other', '--once'])
            self.assertTrue(watch.call_args.kwargs['once'])
            watch.call_args.kwargs['head']()
        remote_head.assert_called_with('other')

    def test_valid_timing_keeps_failure_exit_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary.md'
            out = io.StringIO()
            with mock.patch.object(trip_check_loop, 'watch', return_value=(1, 1)), \
                    mock.patch.dict(trip_check_loop.os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}, clear=True), \
                    contextlib.redirect_stdout(out):
                status = trip_check_loop.main(['--budget-minutes', '1'])
            self.assertEqual(status, 1)
            self.assertIn('0/1 trip checks succeeded.', out.getvalue())
            self.assertEqual(summary.read_text(), '\n## Trip checks\n0/1 trip checks succeeded.\n')


if __name__ == '__main__':
    unittest.main()
