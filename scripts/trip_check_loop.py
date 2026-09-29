#!/usr/bin/env python3
"""Check private saved trips after each live-conditions publication.

Runs as the live workflow's `notify` job, beside the `refresh` job, so that
alert delivery has its own permissions (OIDC identity, read-only contents) and
a failed delivery can never stop the public feed from publishing. It watches
the `conditions` branch head; when a new generation appears it waits for the
R2 copy (uploaded and verified right after the git push), then runs
scripts/check_saved_trips.py once. It stops when the refresh job has finished
(after checking its last publication), after --once, or at the time budget.
Exit status is non-zero when any check failed, which marks only this job red.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from urllib.request import Request, urlopen


def remote_head(branch):
    """Commit the branch points at on origin, or None when unknown."""
    try:
        out = subprocess.run(['git', 'ls-remote', 'origin', f'refs/heads/{branch}'],
                             capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    return out.stdout.split()[0] if out.returncode == 0 and out.stdout.strip() else None


def refresh_finished(job='refresh'):
    """True once this run's refresh job has completed; False when unknown."""
    try:
        api, repo = os.environ['GITHUB_API_URL'], os.environ['GITHUB_REPOSITORY']
        run, attempt = os.environ['GITHUB_RUN_ID'], os.environ.get('GITHUB_RUN_ATTEMPT', '1')
        request = Request(f'{api}/repos/{repo}/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100',
                          headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                                   'Accept': 'application/vnd.github+json'})
        with urlopen(request, timeout=20) as response:
            jobs = json.load(response)['jobs']
    except Exception:  # an API hiccup must not end alert checks early
        return False
    return any(row.get('name') == job and row.get('status') == 'completed' for row in jobs)


def check_trips():
    return subprocess.run([sys.executable, 'scripts/check_saved_trips.py']).returncode == 0


def watch(*, head, finished, check, sleep, clock, deadline, poll, settle, once):
    """Check trips once per new branch head. Returns (checks, failures)."""
    last = head()
    checks = failures = 0
    while clock() < deadline:
        sleep(poll)
        # Read "finished" before the head, so a publication pushed just before
        # the refresh job ended is still seen and checked.
        done = finished()
        current = head()
        if current and current != last:
            sleep(settle)
            ok = check()
            checks += 1
            failures += not ok
            last = current
            print(f'Trip check after {current[:12]}: {"ok" if ok else "FAILED"}', flush=True)
            if not ok:
                print('::error title=Trip check failed::delivery was not confirmed; the feed was not affected.', flush=True)
            if once:
                break
        if done:
            break
    return checks, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--branch', default='conditions')
    parser.add_argument('--budget-minutes', type=float, default=345)
    parser.add_argument('--poll-seconds', type=float, default=60)
    parser.add_argument('--settle-seconds', type=float, default=90,
                        help='wait after a new head so the R2 copy the site serves is current')
    parser.add_argument('--once', action='store_true', help='stop after the first check (push-triggered runs)')
    args = parser.parse_args(argv)
    checks, failures = watch(head=lambda: remote_head(args.branch), finished=refresh_finished, check=check_trips,
                             sleep=time.sleep, clock=time.monotonic,
                             deadline=time.monotonic() + args.budget_minutes * 60,
                             poll=args.poll_seconds, settle=args.settle_seconds, once=args.once)
    summary = f'{checks - failures}/{checks} trip checks succeeded.' if checks else 'No new publication; trips not checked.'
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            handle.write(f'\n## Trip checks\n{summary}\n')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
