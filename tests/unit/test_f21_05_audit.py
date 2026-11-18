"""F21-05 offline controls, not an implementation of SCA-208.

Pytest exercises the receipt-aware reference. To compare the unchanged CLI
against the same expectations, run ``python -B -m tests.unit.test_f21_05_audit``
from the repository root. This read-only diagnostic exits 1 on a contract gap;
it is not a required check and its observed results are not test expectations.
"""
from contextlib import redirect_stdout
from io import StringIO
from itertools import count
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import trip_check_loop


# name, branch reads, completed producer receipt, last checked, expected (outcome, checks).
CASES = (
    ('observed-change', ('gen-a', 'gen-b'), 'gen-b', 'gen-a', ('checked', 1)),
    ('late-start', ('gen-b', 'gen-b'), 'gen-b', 'gen-a', ('checked', 1)),
    ('true-no-change', ('gen-a', 'gen-a'), 'gen-a', 'gen-a', ('no-change', 0)),
    ('unavailable', (None, None), None, 'gen-a', ('unknown', 0)),
)


def receipt_control(receipt, last_checked, check):
    """In-memory reference; None is unavailable, not evidence of no change."""
    if receipt is None:
        return 'unknown', last_checked
    if receipt == last_checked:
        return 'no-change', last_checked
    check(receipt)
    return 'checked', receipt


class TestReceiptControl(unittest.TestCase):
    def test_generation_contract_and_replay(self):
        # Catch first-read baselining, loss of the checkpoint on replay, and
        # calling unavailable evidence a no-op; existing watch tests only
        # exercise branch reads, not producer receipts or a saved checkpoint.
        for name, _, receipt, prior, expected in CASES:
            with self.subTest(case=name):
                checked = []
                outcome, checkpoint = receipt_control(receipt, prior, checked.append)
                self.assertEqual((outcome, len(checked)), expected)
                self.assertEqual(checked, [receipt] if expected[1] else [])
                self.assertEqual(checkpoint, receipt if expected[1] else prior)

                # New invocation, same receipt, only the checkpoint carried over.
                replayed = []
                outcome, replay_checkpoint = receipt_control(receipt, checkpoint, replayed.append)
                self.assertEqual(outcome, 'unknown' if receipt is None else 'no-change')
                self.assertEqual(replayed, [])
                self.assertEqual(replay_checkpoint, checkpoint)


def baseline_observation(heads):
    """Call the real watcher CLI without network, credentials, sleep or writes."""
    check = Mock(return_value=True)
    output = StringIO()
    ticks = count()
    with patch.multiple(
        trip_check_loop,
        remote_head=Mock(side_effect=heads),
        refresh_finished=lambda: True,
        check_trips=check,
        os=SimpleNamespace(environ={}),
        time=SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None),
    ), redirect_stdout(output):
        code = trip_check_loop.main(['--budget-minutes', '0.05', '--poll-seconds', '0', '--settle-seconds', '0'])
    summary = output.getvalue().strip().splitlines()[-1]
    if code:
        outcome = 'failed'
    elif summary == 'No new publication; trips not checked.':
        outcome = 'no-change'
    elif 'unknown' in summary.casefold():
        outcome = 'unknown'
    elif check.call_count:
        outcome = 'checked'
    else:
        outcome = 'unrecognized'
    return (outcome, check.call_count), code, summary


def report_baseline():
    mismatches = 0
    for name, heads, _, _, expected in CASES:
        actual, code, summary = baseline_observation(heads)
        gap = actual != expected
        mismatches += gap
        print(f'{name}: {"GAP" if gap else "MATCH"} expected={expected} observed={actual} '
              f'watcher_exit={code} summary={summary!r}')
    return int(bool(mismatches))


if __name__ == '__main__':
    raise SystemExit(report_baseline())
