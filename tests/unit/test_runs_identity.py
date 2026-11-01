"""Run manifest identity: git_sha is a commit id or None; r2_key stays under runs/<job>/ (stdlib only, offline)."""
import subprocess
import unittest
from unittest import mock

from skippercast import runs

SHA1 = 'abcdef0123456789abcdef0123456789abcdef01'
SHA256 = '0123456789abcdef' * 4


def rev_parse(stdout, returncode=0):
    return mock.patch.object(runs.subprocess, 'run', return_value=subprocess.CompletedProcess(
        ['git', 'rev-parse', 'HEAD'], returncode, stdout=stdout, stderr=''))


class GitSha(unittest.TestCase):
    def test_actions_sha_is_stripped_and_lower_cased(self):
        with mock.patch.object(runs.subprocess, 'run') as run:
            self.assertEqual(runs.git_sha({'GITHUB_SHA': f'  {SHA1.upper()} \n'}), SHA1)
        run.assert_not_called()

    def test_sha256_commit_id_is_accepted(self):
        self.assertEqual(runs.git_sha({'GITHUB_SHA': SHA256}), SHA256)
        self.assertEqual(runs.git_sha({'GITHUB_SHA': SHA256.upper()}), SHA256)

    def test_non_commit_values_fall_back_to_git(self):
        for value in ('main', 'abc', SHA1 + 'a', SHA1[:-1], f'{SHA1[:20]} {SHA1[20:]}', 'g' * 40, SHA256 + '0'):
            with self.subTest(value=value), rev_parse(SHA1 + '\n') as run:
                self.assertEqual(runs.git_sha({'GITHUB_SHA': value}), SHA1)
                run.assert_called_once()

    def test_git_fallback_failures_give_none(self):
        with rev_parse('', returncode=128):
            self.assertIsNone(runs.git_sha({'GITHUB_SHA': 'main'}))
        with rev_parse('not-a-sha\n'):
            self.assertIsNone(runs.git_sha({'GITHUB_SHA': 'main'}))
        with rev_parse(SHA1 + 'zz\n'):
            self.assertIsNone(runs.git_sha({}))
        for error in (OSError('no git'), subprocess.TimeoutExpired(['git'], 10)):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(runs.subprocess, 'run', side_effect=error):
                self.assertIsNone(runs.git_sha({'GITHUB_SHA': 'abc'}))

    def test_git_sha256_and_upper_case_output_is_accepted(self):
        with rev_parse(SHA256 + '\n'):
            self.assertEqual(runs.git_sha({}), SHA256)
        with rev_parse(SHA1.upper() + '\n'):
            self.assertEqual(runs.git_sha({'GITHUB_SHA': ''}), SHA1)


class R2Key(unittest.TestCase):
    def key(self, job='refresh-live', run_id='42', attempt=None):
        return runs.RunManifest(job, run_id, run_attempt=attempt).r2_key()

    def test_safe_keys_are_unchanged(self):
        self.assertEqual(self.key(attempt=3), 'runs/refresh-live/42-3.json')
        self.assertEqual(self.key(attempt=1), 'runs/refresh-live/42.json')
        self.assertEqual(self.key(attempt=None), 'runs/refresh-live/42.json')
        self.assertEqual(self.key(run_id='local-20261031T180000Z'), 'runs/refresh-live/local-20261031T180000Z.json')
        self.assertEqual(self.key(job='forecast-build', run_id=555, attempt=2), 'runs/forecast-build/555-2.json')
        self.assertEqual(self.key(run_id='a' * 100), f'runs/refresh-live/{"a" * 100}.json')

    def test_unsafe_run_ids_are_refused_without_echo(self):
        for value in ('../../x', 'a/b', '.hidden', '', 'a' * 101, '..', 'a..b', 'a\\b', 'x y', '42\n', '-42', 'é1'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    self.key(run_id=value)
                # The fixed message is the whole message, so no part of the value is echoed.
                self.assertEqual(str(caught.exception), 'unsafe run manifest run id')
                self.assertEqual(caught.exception.args, ('unsafe run manifest run id',))

    def test_unsafe_job_names_are_refused_without_echo(self):
        for value in ('../runs', 'refresh/live', '.git', 'a' * 101, 'a..b', '_x'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    self.key(job=value)
                self.assertEqual(str(caught.exception), 'unsafe run manifest job name')

    def test_bad_env_does_not_stop_a_job_until_a_key_is_built(self):
        run = runs.RunManifest.start('refresh-live', environ={'GITHUB_RUN_ID': '../../x', 'GITHUB_SHA': SHA1})
        self.assertEqual((run.run_id, run.git_sha), ('../../x', SHA1))
        run.finish(0)
        with self.assertRaisesRegex(ValueError, '^unsafe run manifest run id$'):
            run.r2_key()


if __name__ == '__main__':
    unittest.main()
