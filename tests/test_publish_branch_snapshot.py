"""scripts/publish_branch_snapshot.sh keeps feed branches to one commit, offline against a local bare repo."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'publish_branch_snapshot.sh'
GIT_ENV = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}


@unittest.skipUnless(shutil.which('git'), 'git not installed')
class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env = {**os.environ, **GIT_ENV}
        self.origin = self.base / 'origin.git'
        self.git('init', '-q', '--bare', '-b', 'main', str(self.origin))
        self.url = self.origin.as_uri()  # file:// so shallow fetches behave as they do against GitHub
        self.checkout = self.clone('checkout')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.base, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def clone(self, name):
        path = self.base / name
        path.mkdir()
        self.git('init', '-q', '-b', 'main', cwd=path)
        self.git('remote', 'add', 'origin', self.url, cwd=path)
        return path

    def run_script(self, *args, cwd=None):
        return subprocess.run(['bash', str(SCRIPT), *args], cwd=cwd or self.checkout, env=self.env,
                              capture_output=True, text=True, timeout=60)

    def load(self, branch, directory, cwd=None):
        out = self.run_script('--load', branch, directory, cwd=cwd)
        self.assertEqual(out.returncode, 0, out.stderr)
        return (cwd or self.checkout) / directory

    def publish(self, branch, directory, message='snapshot', cwd=None):
        return self.run_script(branch, directory, message, cwd=cwd)

    def remote_commits(self, branch):
        return int(self.git('--git-dir', str(self.origin), 'rev-list', '--count', f'refs/heads/{branch}'))

    def remote_files(self, branch):
        listing = self.git('--git-dir', str(self.origin), 'ls-tree', '-r', f'refs/heads/{branch}')
        return {line.split('\t')[1]: self.git('--git-dir', str(self.origin), 'cat-file', 'blob', line.split()[2])
                for line in listing.splitlines()}

    def remote_head(self, branch):
        return self.git('--git-dir', str(self.origin), 'rev-parse', f'refs/heads/{branch}')

    def seed_history(self, branch, commits):
        """An existing feed branch with ordinary multi-commit history, like `conditions` today."""
        seed = self.clone('seed')
        self.git('checkout', '-q', '--orphan', branch, cwd=seed)
        for n in range(commits):
            (seed / 'latest.json').write_text(f'{{"n":{n}}}')
            self.git('add', '-A', cwd=seed)
            self.git('commit', '-q', '-m', f'cycle {n}', cwd=seed)
        self.git('push', '-q', 'origin', f'HEAD:refs/heads/{branch}', cwd=seed)

    def test_first_publish_creates_one_commit_matching_the_directory(self):
        pub = self.load('conditions', 'var/live-published')
        (pub / 'regions' / 'morro-bay').mkdir(parents=True)
        (pub / 'latest.json').write_text('{"v":1}')
        (pub / 'regions' / 'morro-bay' / 'latest.json').write_text('{"r":1}')
        out = self.publish('conditions', 'var/live-published')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.remote_commits('conditions'), 1)
        self.assertEqual(self.remote_files('conditions'),
                         {'latest.json': '{"v":1}', 'regions/morro-bay/latest.json': '{"r":1}'})
        # HEAD is the published commit, which is what publish_branch_r2.sh archives.
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=pub), self.remote_head('conditions'))

    def test_second_publish_replaces_the_commit_and_drops_removed_files(self):
        pub = self.load('data', 'var/published')
        (pub / 'latest.json').write_text('{"v":1}')
        (pub / 'old.json').write_text('{}')
        self.assertEqual(self.publish('data', 'var/published').returncode, 0)
        first = self.remote_head('data')
        (pub / 'latest.json').write_text('{"v":2}')
        (pub / 'old.json').unlink()
        out = self.publish('data', 'var/published')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.remote_commits('data'), 1)
        self.assertNotEqual(self.remote_head('data'), first)
        self.assertEqual(self.remote_files('data'), {'latest.json': '{"v":2}'})

    def test_existing_history_is_squashed_by_the_next_publish(self):
        self.seed_history('conditions', 5)
        self.assertEqual(self.remote_commits('conditions'), 5)
        pub = self.load('conditions', 'var/live-published')
        self.assertEqual((pub / 'latest.json').read_text(), '{"n":4}')  # previous generation is readable
        (pub / 'latest.json').write_text('{"n":5}')
        out = self.publish('conditions', 'var/live-published')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.remote_commits('conditions'), 1)
        self.assertEqual(self.remote_files('conditions'), {'latest.json': '{"n":5}'})

    def test_unchanged_content_is_not_republished(self):
        pub = self.load('data', 'var/published')
        (pub / 'latest.json').write_text('{}')
        self.assertEqual(self.publish('data', 'var/published').returncode, 0)
        head = self.remote_head('data')
        out = self.publish('data', 'var/published')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('unchanged', out.stdout)
        self.assertEqual(self.remote_head('data'), head)

    def test_lease_refuses_to_clobber_a_concurrent_publish_then_reload_recovers(self):
        self.seed_history('conditions', 2)
        ours = self.load('conditions', 'var/live-published')
        # Another job publishes after we loaded.
        other = self.clone('other')
        theirs = self.load('conditions', 'var/pub', cwd=other)
        (theirs / 'latest.json').write_text('{"by":"other"}')
        self.assertEqual(self.publish('conditions', 'var/pub', cwd=other).returncode, 0)
        concurrent = self.remote_head('conditions')

        (ours / 'latest.json').write_text('{"by":"us"}')
        out = self.publish('conditions', 'var/live-published')
        self.assertEqual(out.returncode, 1)
        self.assertIn('not overwritten', out.stderr)
        self.assertEqual(self.remote_head('conditions'), concurrent)
        self.assertEqual(self.remote_files('conditions'), {'latest.json': '{"by":"other"}'})

        # The next cycle reloads the newer generation and publishes on top of it.
        reload = self.run_script('--load', 'conditions', 'var/live-published')
        self.assertEqual(reload.returncode, 0, reload.stderr)
        self.assertIn('moved on origin', reload.stdout)
        self.assertEqual((ours / 'latest.json').read_text(), '{"by":"other"}')
        (ours / 'latest.json').write_text('{"by":"us"}')
        self.assertEqual(self.publish('conditions', 'var/live-published').returncode, 0)
        self.assertEqual(self.remote_commits('conditions'), 1)
        self.assertEqual(self.remote_files('conditions'), {'latest.json': '{"by":"us"}'})

    def test_lease_refuses_to_create_a_branch_someone_else_created(self):
        ours = self.load('forecasts', 'var/forecasts-published')  # branch absent: empty repository
        other = self.clone('other')
        theirs = self.load('forecasts', 'var/pub', cwd=other)
        (theirs / 'index.json').write_text('{"by":"other"}')
        self.assertEqual(self.publish('forecasts', 'var/pub', cwd=other).returncode, 0)
        (ours / 'index.json').write_text('{"by":"us"}')
        self.assertEqual(self.publish('forecasts', 'var/forecasts-published').returncode, 1)
        self.assertEqual(self.remote_files('forecasts'), {'index.json': '{"by":"other"}'})

    def test_a_plain_folder_inside_the_checkout_is_refused(self):
        (self.checkout / 'tracked.txt').write_text('main')
        self.git('add', 'tracked.txt', cwd=self.checkout)
        self.git('commit', '-q', '-m', 'main', cwd=self.checkout)
        folder = self.checkout / 'var' / 'published'
        folder.mkdir(parents=True)
        (folder / 'latest.json').write_text('{}')
        out = self.publish('data', 'var/published')
        self.assertEqual(out.returncode, 1)
        self.assertIn('not a published-feed repository', out.stderr)
        self.assertEqual(self.git('status', '--porcelain', '--untracked-files=no', cwd=self.checkout), '')
        self.assertEqual(self.git('ls-remote', 'origin', cwd=self.checkout), '')
        self.assertEqual(self.run_script('--load', 'data', 'var/published').returncode, 1)


class WiringTests(unittest.TestCase):
    """Every feed branch goes through the snapshot helper; none commits with history."""

    def test_publishers_use_the_snapshot_helper(self):
        cycle = (ROOT / 'scripts' / 'live_cycle.sh').read_text()
        daily = (ROOT / '.github' / 'workflows' / 'daily-data.yml').read_text()
        forecasts = (ROOT / 'scripts' / 'publish_forecasts.sh').read_text()
        self.assertIn('publish_branch_snapshot.sh conditions var/live-published', cycle)
        self.assertIn('publish_branch_snapshot.sh data var/published', daily)
        self.assertIn('publish_branch_snapshot.sh forecasts "$pub"', forecasts)
        for text in (cycle, daily, forecasts):
            self.assertNotIn('git -C var/live-published commit', text)
            self.assertNotIn('git -C var/published commit', text)
            self.assertNotIn('push -q --force origin', text)
            self.assertIn('publish_branch_snapshot.sh --load', text)


if __name__ == '__main__':
    unittest.main()
