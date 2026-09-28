#!/usr/bin/env python3
"""Run live-conditions cycles on a fixed half-hour cadence inside one job.

GitHub throttles frequent scheduled workflows: the old every-30-minute cron
started only every 3-5 hours in practice. One job now refreshes every 30
minutes for most of its 6-hour limit, then the workflow dispatches its
successor (dispatch is not throttled like schedule).

Each cycle is independent: a failed cycle is reported and the next one runs.
Intelligence (models, currents, verification; ~15 minutes) runs when its last
run is older than --intelligence-minutes. Observations run every cycle.
"""
import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import time

SLOTS = (7, 37)  # minutes past the hour, matching the original schedule


def next_slot(now):
    """Next :07 or :37 strictly after now."""
    base = now.replace(second=0, microsecond=0)
    for minute in SLOTS:
        candidate = base.replace(minute=minute)
        if candidate > now:
            return candidate
    return (base + timedelta(hours=1)).replace(minute=SLOTS[0])


def intelligence_due(path, now, minutes):
    """True when the last intelligence output is missing or older than `minutes`."""
    if not path.is_file():
        return True
    age = now.timestamp() - path.stat().st_mtime
    return age >= minutes * 60


def run_cycle(intelligence, skip_trips):
    command = ['bash', 'scripts/live_cycle.sh']
    if intelligence:
        command.append('--intelligence')
    if skip_trips:
        command.append('--skip-trips')
    published = subprocess.run(command).returncode == 0
    report = subprocess.run([sys.executable, 'scripts/report_conditions.py',
                             '--outcome', 'success' if published else 'failure'])
    return published and report.returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--budget-minutes', type=float, default=330,
                        help='stop starting new cycles after this many minutes')
    parser.add_argument('--once', action='store_true', help='run a single cycle (push-triggered runs)')
    parser.add_argument('--intelligence-minutes', type=float, default=55)
    parser.add_argument('--skip-trips', action='store_true')
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    deadline = started + timedelta(minutes=args.budget_minutes)
    marker = Path('var/live/intelligence-health.json')
    cycles = successes = 0
    while True:
        now = datetime.now(timezone.utc)
        due = intelligence_due(marker, now, args.intelligence_minutes)
        print(f'::group::Cycle {cycles + 1} at {now:%H:%M}Z (intelligence: {"yes" if due else "no"})', flush=True)
        ok = run_cycle(due, args.skip_trips)
        print('::endgroup::', flush=True)
        cycles += 1
        successes += ok
        if not ok:
            print(f'::error title=Live cycle failed::Cycle {cycles} did not publish cleanly; continuing.', flush=True)
        if args.once:
            break
        slot = next_slot(datetime.now(timezone.utc))
        if slot >= deadline:
            break
        time.sleep(max(0, (slot - datetime.now(timezone.utc)).total_seconds()))
    summary = f'{successes}/{cycles} cycles published between {started:%H:%M}Z and {datetime.now(timezone.utc):%H:%M}Z.'
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            handle.write(f'\n## Live loop\n{summary}\n')
    raise SystemExit(0 if successes else 1)


if __name__ == '__main__':
    main()
