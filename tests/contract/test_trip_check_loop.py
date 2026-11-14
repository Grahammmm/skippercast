"""Trip checks run in their own job (scripts/trip_check_loop.py runs scripts/check_saved_trips.py) and cannot fail the conditions publisher."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

from scripts.trip_check_loop import watch
from tests._support import ROOT


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


def run_block(block):
    """Extract one literal workflow shell step without a YAML dependency."""
    return textwrap.dedent(block.split('        run: |\n', 1)[1].split('\n      - ', 1)[0])


def run_shell(script, mocks, **values):
    """Exercise the actual workflow shell with offline commands and task-local files."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path, log, summary = root / 'step.sh', root / 'log', root / 'summary'
        path.write_text(textwrap.dedent(mocks) + '\n' + script)
        env = dict(os.environ, TEST_LOG=str(log), GITHUB_STEP_SUMMARY=str(summary),
                   GITHUB_SERVER_URL='https://example.invalid', GITHUB_REPOSITORY='fixture/repo',
                   GITHUB_RUN_ID='1', **values)
        result = subprocess.run(['bash', '-e', '-o', 'pipefail', str(path)], env=env,
                                capture_output=True, text=True, timeout=10)
        return result, log.read_text() if log.exists() else '', summary.read_text() if summary.exists() else ''


class LiveWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / '.github' / 'workflows' / 'live-conditions.yml').read_text()
        self.jobs = jobs(self.text)

    def test_workflow_grants_nothing_by_default(self):
        header = self.text.split('\njobs:\n', 1)[0]
        self.assertIn('\npermissions: {}\n', header)
        self.assertEqual(set(self.jobs), {'refresh', 'notify', 'next', 'alarm-clock'})

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

    def test_only_next_and_alarm_clock_can_dispatch_and_hold_no_secrets(self):
        chain = self.jobs['next']
        self.assertIn('actions: write', chain)
        self.assertIn('needs: refresh', chain)
        self.assertIn('gh workflow run live-conditions.yml', chain)
        self.assertNotIn('secrets.', chain)
        self.assertNotIn('actions: write', self.jobs['refresh'] + self.jobs['notify'])
        self.assertEqual({name for name, block in self.jobs.items() if 'actions: write' in block},
                         {'next', 'alarm-clock'})
        self.assertEqual({name for name, block in self.jobs.items() if 'feed-freshness.yml' in block},
                         {'alarm-clock'})

    def test_alarm_clock_is_isolated_and_least_privilege(self):
        alarm = self.jobs['alarm-clock']
        self.assertIn("if: github.ref == 'refs/heads/main'", alarm)
        self.assertNotIn('needs:', alarm)
        self.assertNotIn('secrets.', alarm)
        self.assertNotIn('id-token', alarm)
        self.assertNotIn('contents:', alarm)
        permissions = alarm.split('    permissions:\n', 1)[1].split('    steps:', 1)[0]
        self.assertEqual(permissions.strip(), 'actions: write')
        timeout = re.search(r'timeout-minutes: (\d+)', alarm)
        self.assertIsNotNone(timeout)
        assert timeout is not None
        self.assertLessEqual(int(timeout[1]), 345)
        self.assertEqual(re.findall(r'gh workflow run ([^\s]+)', alarm), ['feed-freshness.yml'])
        self.assertIn('gh workflow run feed-freshness.yml --ref main', alarm)
        self.assertNotIn('needs: alarm-clock', self.text)

    def test_alarm_ticks_hourly_even_when_dispatch_fails(self):
        script = run_block(self.jobs['alarm-clock']).replace('SECONDS', 'test_seconds')
        for status in (0, 1):
            with self.subTest(dispatch_exit=status):
                result, log, _ = run_shell(script, '''
                    test_seconds=0
                    gh() { printf '%s|%s\\n' "$test_seconds" "$*" >> "$TEST_LOG"; return "$DISPATCH_EXIT"; }
                    timeout() {
                      shift
                      "$@"
                      status=$?
                      test_seconds=$((test_seconds + 60))
                      return "$status"
                    }
                    sleep() { test_seconds=$((test_seconds + $1)); }
                ''', DISPATCH_EXIT=str(status))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([int(line.split('|')[0]) for line in log.splitlines()],
                                 [0, 3600, 7200, 10800, 14400, 18000])
                self.assertTrue(all(line.endswith('workflow run feed-freshness.yml --ref main')
                                    for line in log.splitlines()))
                self.assertEqual(result.stdout.count('::warning::'), 6 if status else 0)

    def test_loop_starts_only_from_schedule_or_dispatch_never_push(self):
        # A push run always waited behind the running loop's concurrency group and was cancelled.
        header = self.text.split('\njobs:\n', 1)[0]
        self.assertIn('\n  schedule:\n', header)
        self.assertIn('\n  workflow_dispatch:\n', header)
        self.assertNotIn('\n  push:\n', header)
        for name, block in self.jobs.items():
            self.assertNotIn("github.event_name == 'push'", block, name)
            self.assertNotIn("github.event_name != 'push'", block, name)
        self.assertIn('live_loop.py --skip-trips --budget-minutes 330', self.jobs['refresh'])

    def test_scheduler_identity_still_names_this_workflow(self):
        # job-auth.js pins workflow_ref to this file, so trip checks must stay in it.
        policy = json.loads((ROOT / 'deployments' / 'production.json').read_text())
        self.assertEqual(policy['scheduler']['workflow'], '.github/workflows/live-conditions.yml')


class RulesAlarmWorkflowTests(unittest.TestCase):
    REGIONS = ('morro-bay', 'cambria-san-simeon', 'south-big-sur-san-simeon',
               'big-sur-coast', 'monterey-point-sur', 'point-arguello-conception')
    MOCKS = '''
        node() {
          printf 'probe|%s\\n' "$3" >> "$TEST_LOG"
          echo "region: $3"
          if [ "$3" = "$FAIL_REGION" ]; then return "$PROBE_EXIT"; fi
        }
        gh() {
          printf 'gh|%s\\n' "$*" >> "$TEST_LOG"
          if [ "$1 $2" = 'issue list' ]; then
            if [ "$LIST_FAIL" = 1 ]; then return 1; fi
            if [ "$EXISTING" = 1 ]; then echo 42; fi
          fi
        }
    '''

    def run_rules(self, **values):
        workflow = (ROOT / '.github/workflows/feed-freshness.yml').read_text()
        step = workflow.split('      - name: Probe the rules card and alert once when it is blank\n', 1)[1]
        defaults = dict(FAIL_REGION='', PROBE_EXIT='3', EXISTING='0', LIST_FAIL='0')
        defaults.update(values)
        result, log, summary = run_shell(run_block(step), self.MOCKS, **defaults)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line.split('|')[1] for line in log.splitlines() if line.startswith('probe|')],
                         list(self.REGIONS))
        self.assertTrue(all(region in summary for region in self.REGIONS))
        return log

    def test_any_missing_region_or_crash_opens_one_aggregate_issue(self):
        for region, code in ((self.REGIONS[0], '3'), (self.REGIONS[2], '3'),
                             (self.REGIONS[-1], '3'), (self.REGIONS[1], '1'), (self.REGIONS[3], '127')):
            with self.subTest(region=region, exit=code):
                log = self.run_rules(FAIL_REGION=region, PROBE_EXIT=code)
                self.assertEqual(log.count('gh|issue create'), 1)
                self.assertNotIn('gh|issue close', log)
                self.assertIn(f'{region} (probe exit {code})', log)

    def test_existing_issue_is_refreshed_not_closed_by_healthy_regions(self):
        log = self.run_rules(FAIL_REGION=self.REGIONS[0], EXISTING='1')
        self.assertEqual(log.count('gh|issue edit 42'), 1)
        self.assertNotIn('gh|issue create', log)
        self.assertNotIn('gh|issue close', log)

    def test_only_all_six_healthy_closes_the_issue(self):
        log = self.run_rules(EXISTING='1')
        self.assertEqual(log.count('gh|issue close 42'), 1)
        self.assertNotIn('gh|issue create', log)
        self.assertNotIn('gh|issue edit', log)

    def test_issue_list_failure_cannot_create_a_duplicate(self):
        log = self.run_rules(FAIL_REGION=self.REGIONS[0], LIST_FAIL='1')
        self.assertNotIn('gh|issue create', log)
        self.assertNotIn('gh|issue close', log)


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
