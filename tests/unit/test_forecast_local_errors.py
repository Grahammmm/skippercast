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
        with self.assertRaises(json.JSONDecodeError):
            run(proc(0, '{not json'))
        with mock.patch.object(local.subprocess, 'run', side_effect=OSError('no node')):
            with self.assertRaises(OSError):
                local.run_sampler(Path('/r'), 'marine', 'q')
        timeout = subprocess.TimeoutExpired('node', 120)
        with mock.patch.object(local.subprocess, 'run', side_effect=timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                local.run_sampler(Path('/r'), 'marine', 'q')


if __name__ == '__main__':
    unittest.main()
