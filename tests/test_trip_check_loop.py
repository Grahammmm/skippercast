"""Trip checks run in their own job (scripts/trip_check_loop.py runs scripts/check_saved_trips.py) and cannot fail the conditions publisher."""
import json
from pathlib import Path
import re
import unittest

from scripts.trip_check_loop import watch

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


def run_watch(heads, finished_after=None, results=None, once=False, budget=10_000):
    """heads: branch head per poll (first entry is the baseline)."""
    clock, heads, polls, checked = Clock(), list(heads), [0], []
    results = list(results or [])

    def head():
        return heads.pop(0) if len(heads) > 1 else heads[0]

    def finished():
        polls[0] += 1
        return finished_after is not None and polls[0] >= finished_after

    def check():
        checked.append(clock.now)
        return results.pop(0) if results else True
    counts = watch(head=head, finished=finished, check=check, sleep=clock.sleep, clock=clock,
                   deadline=budget, poll=60, settle=90, once=once)
    return counts, checked, clock.now


class WatchTests(unittest.TestCase):
    def test_checks_once_per_new_publication_after_settling(self):
        (checks, failures), checked, _ = run_watch(['a', 'a', 'b', 'b', 'c'], finished_after=6)
        self.assertEqual((checks, failures), (2, 0))
        self.assertEqual(checked[0], 60 * 2 + 90)  # second poll saw b, then waited for R2

    def test_no_publication_means_no_check(self):
        (checks, _), checked, _ = run_watch(['a'], finished_after=3)
        self.assertEqual((checks, checked), (0, []))

    def test_stops_when_refresh_finishes_after_checking_its_last_publication(self):
        # The refresh job pushed "b" and finished before the same poll read them.
        (checks, _), _, now = run_watch(['a', 'b'], finished_after=1)
        self.assertEqual(checks, 1)
        self.assertLess(now, 1000)

    def test_failed_delivery_is_counted_and_later_publications_are_still_checked(self):
        (checks, failures), _, _ = run_watch(['a', 'b', 'c'], results=[False, True], finished_after=3)
        self.assertEqual((checks, failures), (2, 1))

    def test_once_stops_after_the_first_check(self):
        (checks, _), _, _ = run_watch(['a', 'b', 'c'], once=True)
        self.assertEqual(checks, 1)

    def test_budget_bounds_the_job_when_refresh_state_is_unknown(self):
        (checks, _), _, now = run_watch(['a'], budget=600)
        self.assertEqual(checks, 0)
        self.assertLessEqual(now, 660)

    def test_unknown_head_is_not_a_publication(self):
        (checks, _), _, _ = run_watch(['a', None, 'a'], finished_after=3)
        self.assertEqual(checks, 0)


def jobs(workflow):
    """Top-level job blocks of a workflow file, by job id (text-level; no YAML dependency)."""
    body = workflow.split('\njobs:\n', 1)[1]
    parts = re.split(r'^  ([a-z][a-z0-9_-]*):\n', body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


class LiveWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / '.github' / 'workflows' / 'live-conditions.yml').read_text()
        self.jobs = jobs(self.text)

    def test_workflow_grants_nothing_by_default(self):
        header = self.text.split('\njobs:\n', 1)[0]
        self.assertIn('\npermissions: {}\n', header)
        self.assertEqual(set(self.jobs), {'refresh', 'notify', 'next'})

    def test_publisher_can_push_but_has_no_identity_token_or_actions_write(self):
        refresh = self.jobs['refresh']
        self.assertIn('contents: write', refresh)
        self.assertNotIn('id-token', refresh)
        self.assertNotIn('actions:', refresh)
        self.assertIn('live_loop.py --skip-trips', refresh)
        self.assertNotIn('check_saved_trips', refresh)

    def test_only_notify_gets_the_oidc_identity_and_it_cannot_push(self):
        notify = self.jobs['notify']
        self.assertIn('id-token: write', notify)
        self.assertIn('contents: read', notify)
        self.assertNotIn('contents: write', notify)
        self.assertNotIn('actions: write', notify)
        self.assertNotIn('needs:', notify)  # runs beside the publisher, never gates it
        self.assertIn('scripts/trip_check_loop.py', notify)
        self.assertEqual(sum('id-token: write' in block for block in self.jobs.values()), 1)

    def test_notify_steps_aside_for_the_queue_but_stays_a_manual_trigger(self):
        # With ENABLE_QUEUES=true the Worker's cron queues trip checks
        # (server/trip-queue.ts); the job then runs only when dispatched with check_trips.
        notify = self.jobs['notify']
        self.assertIn("if: vars.ENABLE_QUEUES != 'true' || inputs.check_trips", notify)
        header = self.text.split('\njobs:\n', 1)[0]
        self.assertRegex(header, r'workflow_dispatch:\n    inputs:\n      check_trips:\n(?:        .*\n)*?        type: boolean\n        default: false')

    def test_only_next_can_dispatch_and_it_holds_no_secrets(self):
        chain = self.jobs['next']
        self.assertIn('actions: write', chain)
        self.assertIn('needs: refresh', chain)
        self.assertIn('gh workflow run live-conditions.yml', chain)
        self.assertNotIn('secrets.', chain)
        self.assertNotIn('actions: write', self.jobs['refresh'] + self.jobs['notify'])

    def test_scheduler_identity_still_names_this_workflow(self):
        # job-auth.js pins workflow_ref to this file, so trip checks must stay in it.
        policy = json.loads((ROOT / 'deployments' / 'production.json').read_text())
        self.assertEqual(policy['scheduler']['workflow'], '.github/workflows/live-conditions.yml')


class TokenScopeTests(unittest.TestCase):
    """Data jobs prefer the R2-only token; only the deploy uses the broad Cloudflare token alone."""

    def test_data_workflows_prefer_the_r2_publish_token(self):
        for name in ('daily-data.yml', 'live-conditions.yml', 'forecast-tiles.yml', 'seafloor.yml'):
            text = (ROOT / '.github' / 'workflows' / name).read_text()
            self.assertIn('CLOUDFLARE_API_TOKEN: ${{ secrets.R2_PUBLISH_TOKEN || secrets.CLOUDFLARE_API_TOKEN }}', text, name)
            self.assertNotIn('CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}', text, name)

    def test_deploy_keeps_the_full_token(self):
        text = (ROOT / '.github' / 'workflows' / 'deploy-cloudflare.yml').read_text()
        self.assertNotIn('R2_PUBLISH_TOKEN', text)


if __name__ == '__main__':
    unittest.main()
