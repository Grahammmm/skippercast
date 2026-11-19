"""F21-05: the trip watcher checks the published generation even when it starts late.

Drives the real CLI (scripts/trip_check_loop.py main) offline: the public
latest.json receipt, the refresh-job status, the trip check and the clock are
all synthetic, so nothing touches the network, credentials or the repository.
``python -B -m tests.unit.test_f21_05_audit`` from the repository root prints
MATCH/GAP per case and exits 1 on any gap.
"""
from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import URLError

from scripts import trip_check_loop
from tests._support import ROOT

RUN = 'run-7'
URL = 'https://feed.invalid/feeds/conditions/latest.json'
EARLIER = {'run_id': 'run-6', 'published_at': '2026-11-18T10:37:00Z', 'regions': []}
GEN_A = {'run_id': RUN, 'published_at': '2026-11-18T11:07:00Z', 'regions': []}
GEN_B = {'run_id': RUN, 'published_at': '2026-11-18T11:37:00Z', 'regions': []}

# name, successive public receipt reads (a dict body or a fetch error), expected (outcome, checks).
CASES = (
    ('observed-change', (EARLIER, GEN_A), ('checked', 1)),
    ('late-start', (GEN_A,), ('checked', 1)),
    ('true-no-change', (EARLIER,), ('no-change', 0)),
    ('unavailable', (URLError('offline'),), ('unknown', 0)),
    ('replay-is-a-no-op', (GEN_A, GEN_A, GEN_A), ('checked', 1)),
    ('two-generations', (GEN_A, GEN_B), ('checked', 2)),
    ('recovers-after-unknown', (OSError('reset'), GEN_A), ('checked', 1)),
    ('unknown-after-check', (GEN_A, ValueError('bad json')), ('unknown', 1)),
    ('receipt-without-cycle', ({'run_id': RUN},), ('unknown', 0)),
    ('receipt-not-an-object', (['latest'],), ('unknown', 0)),
)


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


def run_cli(reads):
    """Run the watcher CLI on synthetic reads; refresh has already finished (late start)."""
    reads, clock, checked, urls = list(reads), Clock(), [], set()

    def fetch(url):
        urls.add(url)
        item = reads.pop(0) if len(reads) > 1 else reads[0]
        if isinstance(item, Exception):
            raise item
        return item

    def check():
        checked.append(clock.now)
        return True

    output = StringIO()
    with patch.multiple(trip_check_loop, fetch_json=fetch, refresh_finished=lambda: True, check_trips=check,
                        time=SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep)), \
            patch.dict(trip_check_loop.os.environ, {'GITHUB_RUN_ID': RUN}, clear=True), redirect_stdout(output):
        code = trip_check_loop.main(['--feed-url', URL, '--budget-minutes', '30', '--poll-seconds', '60',
                                     '--settle-seconds', '0', '--linger-seconds', '120'])
    summary = output.getvalue().strip().splitlines()[-1]
    if code:
        outcome = 'failed'
    elif summary == 'No new publication; trips not checked.':
        outcome = 'no-change'
    elif 'unknown' in summary.casefold():
        outcome = 'unknown'
    elif checked:
        outcome = 'checked'
    else:
        outcome = 'unrecognized'
    return (outcome, len(checked)), code, summary, clock.now, urls


class LateWatcherTests(unittest.TestCase):
    def test_published_generation_contract(self):
        for name, reads, expected in CASES:
            with self.subTest(case=name):
                actual, code, summary, now, urls = run_cli(reads)
                self.assertEqual(actual, expected, summary)
                self.assertEqual((code, urls), (0, {URL}))
                self.assertLessEqual(now, 120)  # stops one edge-cache window after refresh finished

    def test_default_receipt_is_the_public_feed_on_the_production_origin(self):
        origin = json.loads((ROOT / 'deployments' / 'production.json').read_text())['public_origin']
        self.assertEqual(trip_check_loop.feed_url(), origin.rstrip('/') + '/feeds/conditions/latest.json')


def report():
    gaps = 0
    for name, reads, expected in CASES:
        actual, code, summary, _, _ = run_cli(reads)
        gap = actual != expected
        gaps += gap
        print(f'{name}: {"GAP" if gap else "MATCH"} expected={expected} observed={actual} '
              f'watcher_exit={code} summary={summary!r}')
    return int(bool(gaps))


if __name__ == '__main__':
    raise SystemExit(report())
