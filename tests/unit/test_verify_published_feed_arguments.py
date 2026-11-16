import contextlib
import io
import unittest
from unittest import mock

from scripts import verify_published_feed as vpf

URL = 'https://feed.invalid/latest.json'


def run(*args):
    err = io.StringIO()
    out = io.StringIO()
    with mock.patch.object(vpf, 'verify', return_value=(True, 'ok')) as verify, \
            mock.patch.object(vpf, 'fetch_json') as fetch, \
            contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        try:
            rc = vpf.main([URL, 'run1', *args])
        except SystemExit as exit_:
            rc = exit_.code
    return rc, verify, fetch, err.getvalue(), out.getvalue()


class DelayArgumentTests(unittest.TestCase):
    def test_invalid_delays_rejected_before_dispatch(self):
        for value in ['-1', '-0.5', 'nan', 'NaN', 'inf', '+inf', '-inf', '1e309', '-1e309']:
            for extra in ([], ['--attempts', '1']):
                with self.subTest(value=value, extra=extra):
                    rc, verify, fetch, err, _ = run(f'--delay={value}', *extra)
                    self.assertEqual(rc, 2)
                    verify.assert_not_called()
                    fetch.assert_not_called()
                    self.assertIn('--delay must be finite and non-negative', err)
                    self.assertNotIn('Traceback', err)

    def test_unparseable_delays_still_argparse_errors(self):
        for value in ['abc', '']:
            with self.subTest(value=value):
                rc, verify, fetch, err, _ = run(f'--delay={value}')
                self.assertEqual(rc, 2)
                verify.assert_not_called()
                fetch.assert_not_called()

    def test_accepted_delays_dispatch_once(self):
        for value, expected in [('0', 0.0), ('-0.0', 0.0), ('0.25', 0.25), ('15', 15.0)]:
            with self.subTest(value=value):
                rc, verify, _, _, out = run(f'--delay={value}')
                self.assertEqual(rc, 0)
                verify.assert_called_once()
                self.assertEqual(verify.call_args.kwargs['delay'], expected)
                self.assertIn('Verified:', out)

    def test_defaults_and_forwarding(self):
        rc, verify, _, _, _ = run('--published-at', 'T1')
        self.assertEqual(rc, 0)
        verify.assert_called_once_with(URL, 'run1', 'T1', attempts=8, delay=15.0)

    def test_failure_output(self):
        out = io.StringIO()
        with mock.patch.object(vpf, 'verify', return_value=(False, 'stale')), contextlib.redirect_stdout(out):
            rc = vpf.main([URL, 'run1'])
        self.assertEqual(rc, 1)
        self.assertIn('::error title=Public feed not updated::', out.getvalue())


if __name__ == '__main__':
    unittest.main()
