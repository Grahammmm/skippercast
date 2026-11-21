"""The live job reports the last cycle's result, not any earlier success."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

from scripts import live_loop


class LiveLoopResultTests(unittest.TestCase):
    def test_terminal_result_and_cycle_history(self):
        cases = (
            ('recovers', (1, 0, 0, 0), ('failure', 'success'), 0, (1,)),
            ('final report fails', (0, 0, 0, 1), ('success', 'success'), 1, (2,)),
            ('all fail', (1, 0, 1, 0), ('failure', 'failure'), 1, (1, 2)),
        )
        for name, codes, outcomes, exit_code, failed_cycles in cases:
            with self.subTest(name=name):
                now = datetime(2026, 1, 1, 10, 7, tzinfo=timezone.utc)

                def sleep(seconds):
                    nonlocal now
                    now += timedelta(seconds=seconds)

                with (
                    patch.object(live_loop.sys, 'argv', ['live_loop.py', '--budget-minutes', '60']),
                    patch.dict(live_loop.os.environ, {'GITHUB_STEP_SUMMARY': ''}),
                    patch.object(live_loop, 'datetime') as clock,
                    patch.object(live_loop, 'intelligence_due', return_value=False),
                    patch.object(live_loop.time, 'sleep', side_effect=sleep) as wait,
                    patch.object(live_loop.subprocess, 'run', side_effect=[
                        SimpleNamespace(returncode=code) for code in codes
                    ]) as run,
                    patch('builtins.print') as log,
                    self.assertRaises(SystemExit) as result,
                ):
                    clock.now.side_effect = lambda tz: now
                    live_loop.main()

                wait.assert_called_once_with(1800)
                self.assertEqual(run.call_args_list, [
                    invocation
                    for outcome in outcomes
                    for invocation in (
                        call(['bash', 'scripts/live_cycle.sh']),
                        call([live_loop.sys.executable, 'scripts/report_conditions.py', '--outcome', outcome]),
                    )
                ])
                errors = [args.args[0] for args in log.call_args_list if args.args[0].startswith('::error')]
                self.assertEqual([err.split('::')[2].split()[:2] for err in errors],
                                 [['Cycle', str(cycle)] for cycle in failed_cycles])
                self.assertTrue(log.call_args.args[0].startswith(f'{2 - len(failed_cycles)}/2 cycles published'))
                self.assertEqual(result.exception.code, exit_code)
