"""Synthetic private-report contracts; no API, fleet store, or service required."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.scripts.diagnose_cadence import main, report


def run(identity, minute, event='schedule'):
    return {'id': identity, 'event': event, 'status': 'completed', 'conclusion': 'success',
            'created_at': f'2026-10-15T{minute//60:02d}:{minute%60:02d}:00Z'}


def job(identity, minute):
    return {'run_id': identity, 'jobs': [{'started_at': run(identity, minute)['created_at'],
            'completed_at': run(identity, minute+1)['created_at'], 'conclusion': 'success'}]}


def published(identity, minute, kind='normal'):
    return {'run_id': identity, 'run_kind': kind, 'published_at': run(identity, minute)['created_at']}


def fixture():
    return [run(1, 0), run(2, 30)], [job(1, 0), job(2, 30)], [published(1, 1), published(2, 31)]


class PrivateReportTests(unittest.TestCase):
    def assess(self, runs=None, jobs=None, pubs=None, **options):
        return report(runs, jobs, pubs, observed_at=options.pop('observed_at', '2026-10-15T00:35:00Z'),
                      freshness_bound_minutes=options.pop('freshness_bound_minutes', 40), **options)

    def test_complete_synthetic_evidence_is_only_a_configured_test(self):
        result = self.assess(*fixture())
        self.assertEqual(result['natural_creation']['status'], 'observed')
        self.assertEqual(result['execution']['max_job_start_delay_seconds'], 0)
        self.assertEqual(result['publication_freshness']['natural']['status'], 'within_test_bound')
        self.assertEqual(result['operational_acceptance'], 'not_evaluated')
        self.assertIn('no owner-approved', result['freshness_bound']['policy'])
        self.assertEqual(result['freshness_bound']['proposed_test_minutes'], 40)

    def test_missing_input_is_unknown_never_zero_or_healthy(self):
        result = self.assess()
        for part in ('natural_creation', 'execution'):
            self.assertEqual(result[part]['status'], 'unknown')
        self.assertEqual(result['publication_freshness']['natural']['status'], 'unknown')
        runs, jobs, _ = fixture()
        result = self.assess(runs, jobs)
        self.assertEqual(result['natural_creation']['status'], 'observed')
        self.assertEqual(result['publication_freshness']['ordinary']['status'], 'unknown')

    def test_job_success_never_substitutes_for_publication(self):
        runs, jobs, pubs = fixture()
        for evidence in (None, [], pubs[:1]):
            with self.subTest(evidence=evidence):
                result = self.assess(runs, jobs, evidence)
                self.assertEqual(result['publication_freshness']['natural']['status'], 'unknown')

    def test_no_bound_is_assumed_and_no_observation_time_is_assumed(self):
        for options in ({'freshness_bound_minutes': None}, {'observed_at': None}):
            result = self.assess(*fixture(), **options)
            self.assertEqual(result['publication_freshness']['natural']['status'], 'unknown')

    def test_manual_normal_can_show_freshness_but_cannot_mask_natural_staleness(self):
        runs = [run(1, 0), run(2, 120, 'workflow_dispatch')]
        result = self.assess(runs, [job(1, 0), job(2, 120)], [published(1, 1), published(2, 121)],
                             observed_at='2026-10-15T02:05:00Z')
        self.assertEqual(result['publication_freshness']['ordinary']['status'], 'outside_test_bound')
        self.assertEqual(result['publication_freshness']['ordinary']['age_minutes'], 4)
        self.assertEqual(result['publication_freshness']['ordinary']['latest_trigger'], 'workflow_dispatch')
        self.assertEqual(result['publication_freshness']['natural']['age_minutes'], 124)
        self.assertEqual(result['publication_freshness']['natural']['status'], 'outside_test_bound')
        self.assertEqual(result['natural_creation']['scheduled_runs'], 1)

    def test_backfill_and_validation_are_not_ordinary_publication(self):
        runs, jobs, pubs = fixture()
        for kind in ('window', 'backfill', 'validation', 'label-import'):
            result = self.assess(runs, jobs, [published(1, 1, kind), published(2, 31, kind)])
            self.assertEqual(result['publication_freshness']['ordinary']['status'], 'unknown')

    def test_latest_fresh_publication_does_not_erase_an_observed_gap(self):
        runs = [run(1, 0), run(2, 120)]
        result = self.assess(runs, [job(1, 0), job(2, 120)], [published(1, 1), published(2, 121)],
                             observed_at='2026-10-15T02:05:00Z')
        self.assertEqual(result['publication_freshness']['natural']['age_minutes'], 4)
        self.assertEqual(result['publication_freshness']['natural']['max_observed_publication_gap_minutes'], 120)
        self.assertEqual(result['publication_freshness']['natural']['status'], 'outside_test_bound')
        self.assertEqual(result['execution']['max_job_start_delay_seconds'], 0)
        self.assertTrue(result['trigger_delivery_cause'].startswith('unknown'))

    def test_pending_missing_and_invalid_jobs_do_not_pass(self):
        runs, jobs, pubs = fixture()
        cases = (None, [], [jobs[0]], [jobs[0], jobs[0]], [{'run_id': 1, 'jobs': None}],
                 [{'run_id': 1, 'jobs': [{'conclusion': 'not-a-conclusion'}]}])
        for rows in cases:
            self.assertEqual(self.assess(runs, rows, pubs)['execution']['status'], 'unknown')
        jobs[0]['jobs'][0]['completed_at'] = '2026-10-14T23:59:00Z'
        self.assertEqual(self.assess(runs, jobs, pubs)['execution']['status'], 'unknown')

    def test_failed_or_incomplete_run_never_becomes_execution_success(self):
        for value in ('failure', 'cancelled', None):
            runs, jobs, pubs = fixture()
            runs[1]['conclusion'] = value
            result = self.assess(runs, jobs, pubs)
            self.assertNotEqual(result['execution']['status'], 'observed')
            self.assertEqual(result['publication_freshness']['natural']['status'], 'unknown')

    def test_malformed_or_future_publications_are_unknown(self):
        runs, jobs, pubs = fixture()
        for bad in ({'run_id': 1}, published(100, 1), published(True, 1), published(1, 1, 'unknown'),
                    published(1, 36), published(1, 1) | {'published_at': '2026-10-15T00:01:00'}):
            self.assertEqual(self.assess(runs, jobs, [bad, pubs[1]])['publication_freshness']['natural']['status'], 'unknown')
        self.assertEqual(self.assess(runs, jobs, pubs + [pubs[0]])['publication_freshness']['natural']['status'], 'unknown')

    def test_invalid_runs_and_unapproved_test_values_do_not_pass(self):
        runs, jobs, pubs = fixture()
        for invalid in ([], {}, [runs[0], runs[0]], [run(3, 60)], [{'id': 1}]):
            self.assertEqual(self.assess(invalid, jobs, pubs)['natural_creation']['status'], 'unknown')
        for bound in (-1, 0, True, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                self.assess(*fixture(), freshness_bound_minutes=bound)

    def test_unknown_data_never_emits_private_input_fields(self):
        runs, jobs, pubs = fixture()
        runs[0]['actor'] = 'synthetic-private-actor'
        jobs[0]['private_notes'] = 'synthetic-private-note'
        output = json.dumps(self.assess(runs, jobs, pubs))
        self.assertNotIn('synthetic-private', output)

    def test_cli_is_create_only_private_and_keeps_unknown_out_of_summaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs, jobs, pubs = fixture()
            for label, value in (('runs', runs), ('jobs', jobs), ('publications', pubs)):
                (root / (label + '.json')).write_text(json.dumps(value))
            summary, output = root / 'public-summary', root / 'private-report.json'
            args = ['--runs', str(root / 'runs.json'), '--jobs', str(root / 'jobs.json'),
                    '--observed-at', '2026-10-15T00:35:00Z', '--output', str(output)]
            with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}), contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(main(args), 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertFalse(summary.exists())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            result = json.loads(output.read_text())
            self.assertIsNone(result['freshness_bound']['minutes'])
            self.assertEqual(result['publication_freshness']['ordinary']['status'], 'unknown')
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                main(args)
            self.assertEqual(output.read_bytes(), before)
            output.unlink()
            args += ['--publications', str(root / 'publications.json'), '--freshness-bound-minutes', '40']
            self.assertEqual(main(args), 0)
            self.assertIsNotNone(json.loads(output.read_text())['input_sha256']['runs'])
            output.unlink()
            (root / 'runs.json').write_text('broken JSON')
            self.assertEqual(main(args), 2)
            self.assertEqual(json.loads(output.read_text())['unreadable_or_invalid_inputs'], ['runs'])


if __name__ == '__main__':
    unittest.main()
