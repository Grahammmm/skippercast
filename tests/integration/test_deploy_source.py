"""Offline production source-gate failure and workflow ordering checks."""
import copy
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from tests._support import ROOT
spec = importlib.util.spec_from_file_location('check_deploy_source', ROOT / 'scripts/check_deploy_source.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
SHA = 'a' * 40
REPO = 'Grahammmm/skippercast'
REF = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': SHA}}
RUN = {'id': 101, 'name': 'Offline checks', 'path': '.github/workflows/ci.yml',
       'event': 'push', 'head_branch': 'main', 'head_sha': SHA,
       'head_repository': {'full_name': REPO}, 'status': 'completed', 'conclusion': 'success'}


class DeploySourceTests(unittest.TestCase):
    def check(self, runs=None, main=None, listing=None):
        requests = []
        runs = [copy.deepcopy(RUN)] if runs is None else runs
        listing = {'total_count': len(runs), 'workflow_runs': runs} if listing is None else listing
        def read(path):
            requests.append(path)
            return copy.deepcopy(REF if main is None else main) if '/git/ref/' in path else listing
        result = guard.verify_source(REPO, 'refs/heads/main', SHA, read)
        return result, requests

    def test_current_main_exact_push_ci_passes(self):
        run, requests = self.check()
        self.assertEqual(run, 101)
        self.assertEqual(requests[0], '/repos/' + REPO + '/git/ref/heads/main')
        self.assertIn('/actions/workflows/ci.yml/runs?', requests[1])
        self.assertIn('head_sha=' + SHA, requests[1])
        self.assertIn('event=push&branch=main', requests[1])

    def test_branches_tags_and_invalid_identity_fail_before_reads(self):
        for repo, ref, sha in [(REPO, 'refs/heads/topic', SHA), (REPO, 'refs/tags/main', SHA),
                               (REPO, '', SHA), ('../other', 'refs/heads/main', SHA),
                               (REPO, 'refs/heads/main', ''), (REPO, 'refs/heads/main', 'zz')]:
            with self.subTest(repo=repo, ref=ref, sha=sha):
                with patch.object(guard, 'public_metadata') as read:
                    with self.assertRaises(guard.SourceError):
                        guard.verify_source(repo, ref, sha, read)
                    read.assert_not_called()

    def test_stale_sha_and_bad_main_ref_fail(self):
        for main in ({'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'b' * 40}},
                     {}, [], {'ref': 'refs/heads/topic', 'object': REF['object']},
                     {'ref': 'refs/heads/main', 'object': {'type': 'tag', 'sha': SHA}}):
            with self.subTest(main=main), self.assertRaises(guard.SourceError):
                self.check(main=main)

    def test_non_success_and_wrong_provenance_fail(self):
        cases = [('status', 'queued'), ('status', 'in_progress'), ('conclusion', None),
                 ('conclusion', 'failure'), ('conclusion', 'cancelled'), ('conclusion', 'skipped'),
                 ('conclusion', 'neutral'), ('path', '.github/workflows/other.yml'),
                 ('name', 'Other checks'), ('event', 'pull_request'), ('event', 'workflow_dispatch'),
                 ('head_branch', 'topic'), ('head_sha', 'b' * 40),
                 ('head_repository', {'full_name': 'someone/skippercast'}), ('head_repository', None),
                 ('id', '101'), ('id', True), ('id', 0), ('id', -1)]
        for key, value in cases:
            bad = copy.deepcopy(RUN)
            bad[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(guard.SourceError):
                self.check(runs=[bad])

    def test_latest_failed_pending_or_failed_rerun_cannot_use_old_success(self):
        for status, conclusion in [('completed', 'failure'), ('queued', None), ('in_progress', None)]:
            newer = {**RUN, 'id': 102, 'status': status, 'conclusion': conclusion, 'run_attempt': 2}
            with self.subTest(status=status), self.assertRaises(guard.SourceError):
                self.check(runs=[newer, RUN])
        self.assertEqual(self.check(runs=[{**RUN, 'id': 102}, {**RUN, 'conclusion': 'failure'}])[0], 102)

    def test_empty_incomplete_or_malformed_listing_fails(self):
        for listing in ({}, [], {'total_count': 0, 'workflow_runs': []},
                        {'total_count': 2, 'workflow_runs': [RUN]},
                        {'total_count': 101, 'workflow_runs': [RUN]},
                        {'total_count': True, 'workflow_runs': [RUN]},
                        {'total_count': 1, 'workflow_runs': [None]},
                        {'total_count': 1, 'workflow_runs': {}},
                        {'total_count': '1', 'workflow_runs': [RUN]}):
            with self.subTest(listing=listing), self.assertRaises(guard.SourceError):
                self.check(listing=listing)

    def test_cli_read_failure_blocks_following_production_write(self):
        env = {'GITHUB_REPOSITORY': REPO, 'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': SHA}
        for error in (URLError('metadata unavailable'), json.JSONDecodeError('bad', 'x', 0), TimeoutError('timeout')):
            writes = []
            with self.subTest(error=error), patch.dict(os.environ, env), patch.object(guard, 'verify_source', side_effect=error):
                status = guard.main()
                if status == 0:
                    writes.append('production')
                self.assertEqual(status, 1)
                self.assertEqual(writes, [])

    def test_public_metadata_sends_only_the_workflow_read_token(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return b'{"ok":true}'
        env = {k: v for k, v in os.environ.items() if k != 'SOURCE_READ_TOKEN'}
        with patch.dict(os.environ, env, clear=True), patch.object(guard, 'urlopen', return_value=Response()) as open_url:
            self.assertEqual(guard.public_metadata('/repos/' + REPO + '/git/ref/heads/main'), {'ok': True})
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/' + REPO + '/git/ref/heads/main')
        self.assertIsNone(request.get_header('Authorization'), 'no token set: anonymous, as before')
        self.assertEqual(open_url.call_args.kwargs['timeout'], 15)
        with patch.dict(os.environ, {'SOURCE_READ_TOKEN': 'read-only'}), patch.object(guard, 'urlopen', return_value=Response()) as open_url:
            guard.public_metadata('/repos/' + REPO + '/git/ref/heads/main')
        self.assertEqual(open_url.call_args.args[0].get_header('Authorization'), 'Bearer read-only')
        # The workflow supplies only its own token under contents: read; never a repository secret.
        text = (ROOT / '.github/workflows/deploy-cloudflare.yml').read_text()
        self.assertIn('permissions:\n  contents: read\n', text)
        keys = [line for line in text.splitlines() if re.match(r'\s*permissions:', line)]
        self.assertEqual(keys, ['permissions:'], 'no job widens the top-level contents: read')
        tokens = [line.strip() for line in text.splitlines() if 'SOURCE_READ_TOKEN:' in line]
        self.assertEqual(tokens, ['SOURCE_READ_TOKEN: ${{ github.token }}'] * 3)

    def redirect_servers(self):
        """Origin A answers 302 to origin B (another port); B records any request and its Authorization."""
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        seen = []
        class Target(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            def log_message(self, *args):
                pass
        b = ThreadingHTTPServer(('127.0.0.1', 0), Target)
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302); self.send_header('Location', 'http://127.0.0.1:%d/elsewhere' % b.server_port); self.end_headers()
            def log_message(self, *args):
                pass
        a = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        for server in (a, b):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:%d/repos/x/git/ref/heads/main' % a.server_port, seen

    def assert_refuses_redirects(self, open_url, handler):
        from urllib.request import Request
        start, seen = self.redirect_servers()
        with self.assertRaises(OSError):
            open_url(Request(start, headers={'Authorization': 'Bearer read-only'}), timeout=5)
        self.assertEqual(seen, [], 'a cross-origin redirect target receives no request, so no token')
        request = Request('https://api.github.com/repos/' + REPO + '/git/ref/heads/main', headers={'Authorization': 'Bearer read-only'})
        for target in ('http://api.github.com/repos/' + REPO + '/git/ref/heads/main', 'https://example.org/'):
            with self.subTest(target=target), self.assertRaises(OSError):
                handler().redirect_request(request, None, 301, 'Moved', {}, target)

    def test_script_metadata_reader_refuses_redirects(self):
        self.assert_refuses_redirects(guard.urlopen, guard.RefuseRedirect)

    def test_inline_source_check_refuses_redirects(self):
        from urllib.request import build_opener
        text = (ROOT / '.github/workflows/deploy-cloudflare.yml').read_text()
        source = text.split('\n  source:', 1)[1].split('\n  deploy:', 1)[0]
        block = source.split("python3 - <<'PY'\n", 1)[1].split('          try:', 1)[0]
        namespace = {}
        exec('\n'.join(line[10:] for line in block.splitlines()), namespace)
        self.assertNotRegex(source, r'(?<![\w.])urlopen\(', 'the inline check never uses the redirect-following urlopen')
        self.assertIn('build_opener(RefuseRedirect).open(request, timeout=15)', source)
        handler = namespace['RefuseRedirect']
        self.assert_refuses_redirects(lambda request, timeout: build_opener(handler).open(request, timeout=timeout), handler)

    def test_workflow_guard_precedes_dependencies_and_keeps_rollback_separate(self):
        text = (ROOT / '.github/workflows/deploy-cloudflare.yml').read_text()
        deploy, rollback = text.split('\n  rollback:', 1)
        first = deploy.index('Reject manual non-main deployment before checkout')
        checkout = deploy.index('- uses: actions/checkout')
        ci = deploy.index('run: python3 scripts/check_deploy_source.py')
        self.assertLess(first, checkout)
        self.assertLess(checkout, ci)
        for later in ('- uses: actions/setup-node', 'Install locked web dependencies', 'id: deploy'):
            self.assertLess(ci, deploy.index(later))
        self.assertIn("github.event.workflow_run.conclusion == 'success'", deploy)
        self.assertIn("github.event.workflow_run.event == 'push'", deploy)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", deploy)
        self.assertNotIn('check_deploy_source', rollback)
        self.assertIn("inputs.action == 'rollback'", rollback)
        # Execute the actual pre-checkout shell block with a fake next step.
        block = deploy[first:checkout].split('run: |\n', 1)[1]
        block = '\n'.join(line[10:] for line in block.splitlines())
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'checkout-ran'
            for ref, expected in [('refs/heads/topic', 1), ('refs/tags/main', 1), ('refs/heads/main', 0)]:
                env = {**os.environ, 'GITHUB_REF': ref, 'CHECKOUT_MARKER': str(marker)}
                proc = subprocess.run(['bash', '-e', '-c', block + '\ntouch "$CHECKOUT_MARKER"'], env=env, capture_output=True, text=True)
                self.assertEqual(proc.returncode, expected, proc.stderr)
                self.assertEqual(marker.exists(), expected == 0)
                if marker.exists():
                    marker.unlink()


if __name__ == '__main__':
    unittest.main()
