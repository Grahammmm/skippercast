"""run_sampler failure diagnostics, tested at the subprocess boundary."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from skippercast.forecast import local


def proc(returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(['node'], returncode, stdout, stderr)


def run(result=None, **kwargs):
    with mock.patch.object(local.subprocess, 'run', return_value=result) as patched:
        out = local.run_sampler(Path('/r'), 'marine', 'q=1', **kwargs)
    return out, patched


def fail(result):
    with mock.patch.object(local.subprocess, 'run', return_value=result):
        with unittest.TestCase().assertRaises(ValueError) as caught:
            local.run_sampler(Path('/r'), 'marine', 'q=1')
    return str(caught.exception)


class ForecastLocalErrors(unittest.TestCase):
    def test_nonzero_empty_stdout_uses_stderr(self):
        self.assertEqual(fail(proc(1, '', 'Error: cannot find module\n')),
                         'Forecast sampler: Error: cannot find module')

    def test_nonzero_dict_without_reason_uses_stderr(self):
        for body in ({}, {'error': True}, {'error': True, 'reason': None}, {'error': True, 'reason': 5},
                     {'error': True, 'reason': ['x']}, {'error': True, 'reason': {'a': 1}},
                     {'error': True, 'reason': ''}, {'error': True, 'reason': '  \n'}):
            with self.subTest(body=body):
                original = json.dumps(body)
                self.assertEqual(fail(proc(2, original, ' boom \n')), 'Forecast sampler: boom')

    def test_reason_precedes_stderr_and_preserves_text(self):
        body = json.dumps({'error': True, 'reason': ' fixture refusal '})
        self.assertEqual(fail(proc(1, body, 'stderr text')), 'Forecast sampler:  fixture refusal ')
        self.assertEqual(fail(proc(0, body, 'stderr text')), 'Forecast sampler:  fixture refusal ')

    def test_missing_diagnostics_have_fixed_fallbacks(self):
        self.assertEqual(fail(proc(3, '', '  ')), 'Forecast sampler: process exited with status 3')
        self.assertEqual(fail(proc(4, '[1]', '')), 'Forecast sampler: process exited with status 4')
        self.assertEqual(fail(proc(0, '{"error": true}', '')), 'Forecast sampler: sampler reported an error')
        self.assertEqual(fail(proc(0, '{"error": true, "reason": null}', None)),
                         'Forecast sampler: sampler reported an error')
        self.assertEqual(fail(proc(1, '', 'a' * 100 + 'b' * 300)), 'Forecast sampler: ' + 'b' * 300)

    def test_success_and_subprocess_contract_unchanged(self):
        out, patched = run(proc(0, '{"hourly": {"time": []}}'), now=12.7)
        self.assertEqual(out, {'hourly': {'time': []}})
        args, kw = patched.call_args
        self.assertEqual(args[0][2:], ['/r', 'marine', 'q=1'])
        self.assertEqual(kw['timeout'], 120)
        self.assertEqual(kw['env']['SKIPPERCAST_NOW'], '12')
        self.assertTrue(kw['capture_output'] and kw['text'])
        self.assertEqual(run(proc(0, '[1, 2]'))[0], [1, 2])
        with mock.patch.object(local.subprocess, 'run', side_effect=OSError('no node')):
            with self.assertRaises(OSError):
                local.run_sampler(Path('/r'), 'marine', 'q')
        timeout = subprocess.TimeoutExpired('node', 120)
        with mock.patch.object(local.subprocess, 'run', side_effect=timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                local.run_sampler(Path('/r'), 'marine', 'q')

    # Contract: a crash whose stdout is not JSON still names the sampler and its
    # stderr reason. Bug caught: json.loads runs before the exit status is read,
    # so a node warning banner on stdout hides the real reason behind a bare
    # JSONDecodeError.
    def test_nonzero_non_json_stdout_names_sampler_and_stderr(self):
        message = fail(proc(1, 'node: warning banner\n', "Error: Cannot find module 'x'\n"))
        self.assertEqual(message, "Forecast sampler: Error: Cannot find module 'x'")
        self.assertEqual(fail(proc(1, '{not json', 'a' * 100 + 'b' * 300)), 'Forecast sampler: ' + 'b' * 300)

    # Bug caught: the exit-status step of the ladder skipped for non-JSON stdout
    # (empty stderr must still say the process exited with its status).
    def test_nonzero_non_json_stdout_without_stderr_uses_exit_status(self):
        self.assertEqual(fail(proc(3, 'banner', '')), 'Forecast sampler: process exited with status 3')
        self.assertEqual(fail(proc(3, 'banner', None)), 'Forecast sampler: process exited with status 3')
        self.assertEqual(fail(proc(3, 'banner', ' \n')), 'Forecast sampler: process exited with status 3')

    # Bug caught: a clean exit with garbage stdout escaping as a bare
    # JSONDecodeError (or being accepted) instead of the named refusal.
    def test_clean_exit_with_non_json_stdout_is_refused_with_name(self):
        self.assertEqual(fail(proc(0, '{not json', '')), 'Forecast sampler: sampler output was not JSON')
        self.assertEqual(fail(proc(0, 'banner', None)), 'Forecast sampler: sampler output was not JSON')
        self.assertEqual(fail(proc(0, 'banner', 'late warning\n')), 'Forecast sampler: late warning')

    # Control: the named refusal must not swallow JSON stdout or the empty-stdout success.
    def test_json_and_empty_success_still_pass(self):
        self.assertEqual(run(proc(0, ' {"ok": 1}\n'))[0], {'ok': 1})
        self.assertEqual(run(proc(0, '', 'noise'))[0], {})


class SamplePointLists(unittest.TestCase):
    def call(self, params, client=None):
        """Run sample() with no local tiles; return (sampler calls, stage calls) or the error."""
        with mock.patch.object(local, 'local_root', return_value=None), \
                mock.patch.object(local, 'run_sampler', return_value={'ok': 1}) as sampler, \
                mock.patch.object(local, '_stage') as stage:
            out = local.sample('ecmwf_wam', params, client if client is not None else object())
        return out, sampler, stage

    def refused(self, params, client=None):
        with mock.patch.object(local, 'local_root', return_value=None), \
                mock.patch.object(local, 'run_sampler') as sampler, \
                mock.patch.object(local, '_stage') as stage:
            with self.assertRaises(ValueError) as caught:
                local.sample('ecmwf_wam', params, client if client is not None else object())
        sampler.assert_not_called()
        stage.assert_not_called()
        return str(caught.exception)

    # Bug caught: zip() truncating 3 latitudes + 2 longitudes, so the third
    # point's tiles are never staged while the sampler is asked about all three.
    def test_unequal_lists_refused_before_any_call(self):
        message = self.refused({'latitude': '36.5,36.6,36.7', 'longitude': '-122.1,-122.2'})
        self.assertEqual(message, 'Forecast sampler: latitude and longitude lists differ in length (3 vs 2)')
        self.assertIn('(2 vs 3)', self.refused({'latitude': '36.5,36.6', 'longitude': '-122.1,-122.2,-122.3'}))

    # Bug caught: an empty or blank entry (trailing comma, empty list) being
    # skipped or read as a point instead of refused.
    def test_empty_entries_refused(self):
        for lat, lon in (('', ''), ('36.5,', '-122.1,-122.2'), ('36.5,36.6', '-122.1, '), (' ', '-122.1')):
            with self.subTest(lat=lat, lon=lon):
                self.assertTrue(self.refused({'latitude': lat, 'longitude': lon}).startswith('Forecast sampler:'))

    # Bug caught: a non-numeric or non-finite entry escaping as a bare float()
    # message, or NaN/inf reaching the tile-key floor() in staging.
    def test_non_numeric_entries_refused(self):
        for lat, lon in (('abc', '-122.1'), ('36.5', 'west'), ('nan', '-122.1'), ('36.5', 'inf'), ('36.5,x', '-122.1,-122.2')):
            with self.subTest(lat=lat, lon=lon):
                message = self.refused({'latitude': lat, 'longitude': lon})
                self.assertTrue(message.startswith('Forecast sampler: '))
                self.assertIn('number', message)

    # Control: equal lists (strings, spaces, a bare number) still reach the sampler
    # and staging with every point, and the query is unchanged.
    def test_equal_lists_unchanged(self):
        out, sampler, stage = self.call({'latitude': '36.5, 36.6,36.7', 'longitude': '-122.1,-122.2,-122.3'})
        self.assertEqual(out, {'ok': 1})
        self.assertEqual(stage.call_args[0][2], [(36.5, -122.1), (36.6, -122.2), (36.7, -122.3)])
        self.assertEqual(sampler.call_args[0][2], 'latitude=36.5%2C+36.6%2C36.7&longitude=-122.1%2C-122.2%2C-122.3&models=ecmwf_wam')
        out, sampler, stage = self.call({'latitude': 36.5, 'longitude': -122.1})
        self.assertEqual(stage.call_args[0][2], [(36.5, -122.1)])

    # Control: with local tiles the equal-list path never stages and the mismatch is still refused.
    def test_local_root_path_unchanged_and_validated(self):
        with mock.patch.object(local, 'local_root', return_value=Path('/r')), \
                mock.patch.object(local, 'run_sampler', return_value={'ok': 2}) as sampler:
            self.assertEqual(local.sample('ecmwf_wam', {'latitude': '1,2', 'longitude': '3,4'}), {'ok': 2})
            sampler.assert_called_once()
            with self.assertRaises(ValueError):
                local.sample('ecmwf_wam', {'latitude': '1,2,3', 'longitude': '3,4'})
            sampler.assert_called_once()


if __name__ == '__main__':
    unittest.main()
