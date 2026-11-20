import contextlib
import io
import unittest
from unittest import mock

from scripts import verify_published_feed as vpf

URL = 'https://feed.invalid/latest.json'


def run(*args, result=(True, 'ok')):
    err = io.StringIO()
    out = io.StringIO()
    with mock.patch.object(vpf, 'verify', return_value=result) as verify, \
            mock.patch.object(vpf, 'fetch_json') as fetch, \
            contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        try:
            rc = vpf.main([URL, 'run1', *args])
        except SystemExit as exit_:
            rc = exit_.code
    return rc, verify, fetch, err.getvalue(), out.getvalue()


class AttemptCountTests(unittest.TestCase):
    def test_nonpositive_attempts_fail_before_dispatch(self):
        for value in ['0', '-1', '-100']:
            with self.subTest(value=value):
                rc, verify, fetch, err, out = run(f'--attempts={value}')
                self.assertEqual(rc, 2)
                verify.assert_not_called()
                fetch.assert_not_called()
                self.assertIn('--attempts must be a positive integer', err)
                self.assertNotIn('::error', out)

    def test_positive_boundary_and_default_are_forwarded(self):
        for args, expected in [(['--attempts=1'], 1), (['--attempts=2'], 2), (['--attempts=8'], 8), ([], 8)]:
            with self.subTest(args=args):
                rc, verify, _, _, _ = run('--published-at', 'T1', '--delay=0', *args)
                self.assertEqual(rc, 0)
                verify.assert_called_once_with(URL, 'run1', 'T1', attempts=expected, delay=0.0)

    def test_noninteger_attempts_remain_argparse_errors(self):
        for value in ['1.5', 'nan', '', 'abc']:
            with self.subTest(value=value):
                rc, verify, fetch, _, _ = run(f'--attempts={value}')
                self.assertEqual(rc, 2)
                verify.assert_not_called()
                fetch.assert_not_called()

    def test_delay_validation_precedence_is_unchanged(self):
        for attempts in ['0', '-1', '3']:
            with self.subTest(attempts=attempts):
                rc, verify, _, err, _ = run(f'--attempts={attempts}', '--delay=-1')
                self.assertEqual(rc, 2)
                verify.assert_not_called()
                self.assertIn('--delay must be finite and non-negative', err)
                self.assertNotIn('--attempts must be', err)

    def test_valid_attempt_count_keeps_success_and_failure_output(self):
        rc, _, _, _, out = run('--attempts=3')
        self.assertEqual(rc, 0)
        self.assertIn('Verified: ok', out)
        rc, _, _, _, out = run('--attempts=3', result=(False, 'stale'))
        self.assertEqual(rc, 1)
        self.assertIn('::error title=Public feed not updated::stale', out)
