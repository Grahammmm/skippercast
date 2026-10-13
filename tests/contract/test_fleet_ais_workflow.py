"""Execute the actual AIS dispatch script offline; no runner data or tokens."""
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest
from tests._support import ROOT

WORKFLOW = (ROOT / '.github/workflows/fleet-ais.yml').read_text()
SCRIPT = textwrap.dedent(WORKFLOW.split('      - name: Process AIS positions\n', 1)[1].split('        run: |\n', 1)[1])
SHA = 'a' * 40


class FleetAisWorkflowTests(unittest.TestCase):
    def run_script(self, *, trigger='schedule', cron='', **inputs):
        with tempfile.TemporaryDirectory() as temporary:
            env = {'REGION': 'CA', 'WINDOW_FROM': '', 'WINDOW_TO': '', 'BACKFILL_MONTH': '',
                   'VALIDATE': '', 'LABEL_IMPORT': '', 'SCHEDULE_CRON': cron,
                   'GITHUB_EVENT_NAME': trigger, 'GITHUB_SHA': SHA,
                   'SKIPPERCAST_FLEET_VAR': temporary,
                   'GITHUB_STEP_SUMMARY': str(Path(temporary) / 'summary')}
            env.update(inputs)
            # Bash functions replace the actual Python commands with argument receipts.
            # tee only writes the temporary summary. No application or network executes.
            stub = "python() { printf 'PY'; printf '\\t%s' \"$@\"; printf '\\n'; }\n"
            result = subprocess.run(['/bin/bash', '-c', stub + SCRIPT], env=env,
                                    capture_output=True, text=True, timeout=5)
            calls = [line.split('\t')[1:] for line in result.stdout.splitlines() if line.startswith('PY\t')]
            context = [line for line in result.stdout.splitlines() if line.startswith('AIS run kind=')]
            return result, calls, context

    def test_two_slots_preserve_half_hour_spacing_across_midnight(self):
        schedule = WORKFLOW.split('  schedule:\n', 1)[1].split('  workflow_dispatch:', 1)[0]
        crons = re.findall(r'cron: "([^\"]+)"', schedule)
        self.assertEqual(len(crons), 2)
        offsets = []
        for cron in crons:
            minute, *other = cron.split()
            self.assertEqual(other, ['*'] * 4)
            self.assertTrue(minute.isdigit())
            offsets.append(int(minute))
        times = sorted(hour * 60 + minute for hour in range(24) for minute in offsets)
        self.assertEqual(len(times), 48)
        self.assertTrue(all((times[(i + 1) % len(times)] - times[i]) % 1440 == 30 for i in range(48)))
        self.assertTrue(all(10 <= minute <= 50 for minute in offsets))

    def test_schedule_without_dispatch_inputs_runs_ordinary_process_and_sync(self):
        crons = re.findall(r'cron: "([^\"]+)"', WORKFLOW.split('  workflow_dispatch:', 1)[0])
        for cron in crons:
            with self.subTest(cron=cron):
                result, calls, context = self.run_script(cron=cron)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [['-m', 'skippercast.fleet.ais', 'process', '--region', 'CA'],
                                         ['-m', 'skippercast.fleet.ais', 'validate', '--region', 'CA', '--sync-only']])
                self.assertEqual(context, [f'AIS run kind=normal trigger=schedule cron={cron} source={SHA}'])

    def test_manual_normal_is_identified_separately_from_schedule(self):
        result, calls, context = self.run_script(trigger='workflow_dispatch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertEqual(context, [f'AIS run kind=normal trigger=workflow_dispatch cron=none source={SHA}'])

    def test_historical_modes_do_not_dispatch_normal_process_or_sync(self):
        cases = [({'BACKFILL_MONTH': '2026-06'}, 'backfill', ['backfill', '--region', 'CA', '--month', '2026-06']),
                 ({'WINDOW_FROM': '2026-06-01', 'WINDOW_TO': '2026-06-30'}, 'window',
                  ['process', '--region', 'CA', '--from', '2026-06-01', '--to', '2026-06-30']),
                 ({'VALIDATE': 'true'}, 'validation', ['validate', '--region', 'CA'])]
        for inputs, kind, args in cases:
            with self.subTest(kind=kind):
                result, calls, context = self.run_script(trigger='workflow_dispatch', **inputs)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [['-m', 'skippercast.fleet.ais', *args]])
                self.assertEqual(context, [f'AIS run kind={kind} trigger=workflow_dispatch cron=none source={SHA}'])
                for value in inputs.values():
                    self.assertNotIn(value, context[0])

    def test_invalid_historical_month_is_refused_before_python(self):
        result, calls, context = self.run_script(trigger='workflow_dispatch', BACKFILL_MONTH='2026-06; exit 0')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])
        self.assertIn('backfill_month takes YYYY-MM', result.stdout)
        self.assertEqual(context, [f'AIS run kind=backfill trigger=workflow_dispatch cron=none source={SHA}'])


if __name__ == '__main__':
    unittest.main()
