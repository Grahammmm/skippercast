#!/usr/bin/env python3
"""Check private saved trips after each live-conditions publication.

Runs as the live workflow's `notify` job, beside the `refresh` job, so that
alert delivery has its own permissions (OIDC identity, read-only contents) and
a failed delivery can never stop the public feed from publishing.

The producer's receipt is the public feed itself: every completed cycle swaps
the R2 release that `/feeds/conditions/latest.json` is served from, and that
file names the run (`run_id`) and cycle (`published_at`) that wrote it
(scripts/verify_published_feed.py checks the same fields). The branch head is
not a receipt: it moves before the R2 copy is published and verified.

Each poll reads that receipt. A generation this run published that has not
been checked yet runs scripts/check_saved_trips.py once; the first read counts
too, so a watcher that starts after this run already published still checks
it. An earlier run's generation, or one already checked, is a no-op. A failed
or unreadable read is unknown, never "no new publication". The watcher stops
once the refresh job has finished, one more edge-cache window has passed and
a receipt read has been taken after that window (so its last publication is
seen even when settling and a check ran past it), after --once, or at the
time budget.
Exit status is non-zero when any check failed, which marks only this job red.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

FEED_PATH = '/feeds/conditions/latest.json'
DEPLOYMENT = Path(__file__).resolve().parents[1] / 'deployments' / 'production.json'


def feed_url():
    """The public conditions receipt on the origin check_saved_trips.py calls."""
    return json.loads(DEPLOYMENT.read_text())['public_origin'].rstrip('/') + FEED_PATH


def fetch_json(url):
    request = Request(url, headers={'User-Agent': 'SkipperCast-trip-watch/1.0', 'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def published_generation(url, fetch=None):
    """(run_id, published_at) of the completed publication the site serves, or None when unknown."""
    try:
        feed = (fetch or fetch_json)(url)
    except Exception:  # network, HTTP or JSON failure: unknown, not "no change"
        return None
    if not isinstance(feed, dict):
        return None
    run, stamp = feed.get('run_id'), feed.get('published_at')
    if not (isinstance(run, str) and run and isinstance(stamp, str) and stamp):
        return None
    return run, stamp


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


def watch(*, generation, run_id, finished, check, sleep, clock, deadline, poll, settle, linger, once):
    """Check trips once per completed generation `run_id` published.

    Returns (checks, failures, unknown); unknown is True when the last read (or
    every read) was unavailable, so a publication may have gone unchecked.
    """
    checked = set()  # this run's generations already checked (an edge may briefly serve an older one again)
    checks = failures = 0
    unknown = True
    stop_at = None
    while clock() < deadline:
        # Read "finished" before the receipt, so a publication completed just
        # before the refresh job ended is still seen and checked.
        if stop_at is None and finished():
            stop_at = clock() + linger
        read_at = clock()
        current = generation()
        unknown = current is None
        if current is not None and current[0] == run_id and current not in checked:
            sleep(settle)
            ok = check()
            checks += 1
            failures += not ok
            checked.add(current)
            print(f'Trip check after publication {current[1]}: {"ok" if ok else "FAILED"}', flush=True)
            if not ok:
                print('::error title=Trip check failed::delivery was not confirmed; the feed was not affected.', flush=True)
            if once:
                break
        if stop_at is not None and read_at >= stop_at:
            break  # this read was taken after the linger window: nothing newer can be unseen
        if stop_at is not None and clock() >= stop_at:
            continue  # settling and a check ran past the window: read the receipt once more before stopping
        sleep(poll)
    return checks, failures, unknown


def summarize(checks, failures, unknown):
    if not checks:
        return 'Publication state unknown; trips not checked.' if unknown else 'No new publication; trips not checked.'
    summary = f'{checks - failures}/{checks} trip checks succeeded.'
    if unknown:
        summary += ' Publication state unknown at the last read, so a later publication may be unchecked.'
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--feed-url', help=f'public conditions receipt (default: public_origin + {FEED_PATH})')
    parser.add_argument('--budget-minutes', type=float, default=345)
    parser.add_argument('--poll-seconds', type=float, default=60)
    parser.add_argument('--settle-seconds', type=float, default=90,
                        help='wait after a new generation before checking, so every edge serves it')
    parser.add_argument('--linger-seconds', type=float, default=120,
                        help='keep reading after the refresh job finishes, past the 60 s edge cache of latest.json')
    parser.add_argument('--once', action='store_true', help='stop after the first check (push-triggered runs)')
    args = parser.parse_args(argv)
    for flag, value in (('--budget-minutes', args.budget_minutes), ('--poll-seconds', args.poll_seconds),
                        ('--settle-seconds', args.settle_seconds), ('--linger-seconds', args.linger_seconds)):
        if not (math.isfinite(value) and value >= 0):
            parser.error(f'argument {flag}: must be finite and non-negative, got {value}')
    url = args.feed_url or feed_url()
    # The same identity the producer stamps into latest.json (skippercast.pipeline.collect.run_id).
    run_id = os.environ.get('GITHUB_RUN_ID', '').strip() or 'local'
    checks, failures, unknown = watch(
        generation=lambda: published_generation(url), run_id=run_id, finished=refresh_finished, check=check_trips,
        sleep=time.sleep, clock=time.monotonic, deadline=time.monotonic() + args.budget_minutes * 60,
        poll=args.poll_seconds, settle=args.settle_seconds, linger=args.linger_seconds, once=args.once)
    if unknown:
        print(f'::warning title=Trip check state unknown::could not read {url}; the feed was not affected.', flush=True)
    summary = summarize(checks, failures, unknown)
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            handle.write(f'\n## Trip checks\n{summary}\n')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
