"""Effort decisions must retain stagnation and downstream holds."""
import copy
import importlib.util
import unittest

from tests._support import ROOT

SCRIPT = ROOT / 'skills/skippercast-map-coast/scripts/check_progress.py'
SPEC = importlib.util.spec_from_file_location('mapping_progress_control', SCRIPT)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


def checkpoint():
    return {'progress_control': {
        'run_id': 'one-mission', 'batch_id': 'one-reach', 'purpose': 'publication',
        'phase': 'qualification', 'accounting': {'scope': 'aggregate-goal-counter', 'start': 1000, 'current': 5000},
        'active_minutes': 8, 'stage_active_minutes': 5, 'active_minutes_since_public_delta': 8,
        'candidate_tokens': 4000, 'repair_tokens': None, 'outcomes': [],
        'qualified_handoffs_waiting': [], 'gates': dict.fromkeys(GUARD.GATES, 'verified'),
    }}


class MappingProgressControlTests(unittest.TestCase):
    def test_ready_batch_allowed_without_mutation_or_science_approval(self):
        state = checkpoint()
        before = copy.deepcopy(state)
        result = GUARD.decide(state)
        self.assertEqual(result['action'], 'RUN_BOUNDED_BATCH')
        self.assertFalse(result['scientific_or_publication_approval'])
        self.assertEqual(state, before)

    def test_private_proof_and_green_fix_do_not_clear_failed_batch_streak(self):
        state = checkpoint()
        state['progress_control']['outcomes'] = [{'kind': 'blocked'}, {'kind': 'pipeline_fix'},
                                                 {'kind': 'maintenance'}, {'kind': 'private_proof'}]
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')

    def test_actual_public_delta_resets_batch_streak_but_not_run_spend(self):
        state = checkpoint()
        control = state['progress_control']
        control['outcomes'] = [{'kind': 'blocked'}, {'kind': 'published_delta', 'new_outlines': 1,
                                'readback_receipt': 'verified-private-receipt'}, {'kind': 'no_delta'}]
        self.assertEqual(GUARD.decide(state)['action'], 'RUN_BOUNDED_BATCH')
        control['accounting']['current'] = 501000
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')

    def test_green_refresh_cannot_be_declared_public_progress(self):
        for event in [{'kind': 'published_delta', 'new_outlines': 0, 'readback_receipt': 'r'},
                      {'kind': 'published_delta', 'new_outlines': 1},
                      {'kind': 'published_delta', 'new_outlines': .0001, 'readback_receipt': 'r'}]:
            with self.subTest(event=event), self.assertRaises(ValueError):
                state = checkpoint()
                state['progress_control']['outcomes'] = [event]
                GUARD.decide(state)

    def test_held_qualified_candidates_fill_queue(self):
        state = checkpoint()
        state['progress_control']['qualified_handoffs_waiting'] = ['rights-held', 'region-held']
        self.assertEqual(GUARD.decide(state)['action'], 'HOLD_DISCOVERY')

    def test_missing_southern_pipeline_prevents_more_qualification(self):
        state = checkpoint()
        state['progress_control']['gates']['native_pipeline'] = 'blocked'
        state['progress_control']['gates']['screen_path'] = 'unknown'
        self.assertEqual(GUARD.decide(state)['action'], 'PREFLIGHT_ONLY')

    def test_repair_must_remove_named_reproduced_last_blocker(self):
        state = checkpoint()
        control = state['progress_control']
        control['phase'] = 'repair'
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')
        control['repair'] = {'batch_id': 'one-reach', 'failure_receipt': 'before-failure',
                             'only_remaining_known_blocker': False}
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')
        control['repair']['only_remaining_known_blocker'] = True
        self.assertEqual(GUARD.decide(state)['action'], 'REPAIR_ONLY')

    def test_reserve_finishes_existing_job_without_replenishing_allowance(self):
        state = checkpoint()
        control = state['progress_control']
        control['accounting']['current'] = 476000
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')
        control['phase'] = 'finalize'
        with self.assertRaises(ValueError):
            GUARD.decide(state)
        control['finalization_job_id'] = 'already-running-publisher'
        self.assertEqual(GUARD.decide(state)['action'], 'FINISH_NAMED_JOB_ONLY')
        control['accounting']['current'] = 501000
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')

    def test_absent_token_measurement_uses_time_and_attempt_limits(self):
        state = checkpoint()
        control = state['progress_control']
        control['accounting'] = {'scope': 'unavailable', 'start': None, 'current': None}
        result = GUARD.decide(state)
        self.assertIsNone(result['accounted_tokens_used'])
        control['active_minutes'] = 30
        control['active_minutes_since_public_delta'] = 30
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')

    def test_preparation_finishes_one_deliverable_and_waits_without_a_model(self):
        state = checkpoint()
        control = state['progress_control']
        control['purpose'] = 'preparation'
        control['outcomes'] = [{'kind': 'private_proof'}]
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')
        control['outcomes'] = []
        control['phase'] = 'waiting'
        self.assertEqual(GUARD.decide(state)['action'], 'WAIT_WITHOUT_MODEL')

    def test_corrupt_or_incomplete_counters_fail_closed(self):
        for field, value in [('active_minutes', float('nan')), ('stage_active_minutes', -1),
                             ('candidate_tokens', True)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                state = checkpoint()
                state['progress_control'][field] = value
                GUARD.decide(state)
        state = checkpoint()
        state['progress_control']['accounting']['current'] = 0
        with self.assertRaises(ValueError):
            GUARD.decide(state)

    def test_larger_allowance_cannot_be_self_issued(self):
        state = checkpoint()
        control = state['progress_control']
        control['limits'] = {'accounted_tokens': 1000000}
        with self.assertRaises(ValueError):
            GUARD.decide(state)
        control['owner_limit_override'] = 'retained explicit owner instruction'
        self.assertEqual(GUARD.decide(state)['action'], 'RUN_BOUNDED_BATCH')

    def test_last_blocker_assertion_cannot_hide_multiple_unready_gates(self):
        state = checkpoint()
        control = state['progress_control']
        control['phase'] = 'repair'
        control['repair'] = {'batch_id': 'one-reach', 'failure_receipt': 'before-failure',
                             'only_remaining_known_blocker': True}
        control['gates']['native_pipeline'] = 'blocked'
        control['gates']['screen_path'] = 'unknown'
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')

    def test_stage_counters_cannot_exceed_total_run_counters(self):
        for field, value in [('stage_active_minutes', 19),
                             ('active_minutes_since_public_delta', 29),
                             ('candidate_tokens', 4001), ('repair_tokens', 4001)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                state = checkpoint()
                state['progress_control'][field] = value
                GUARD.decide(state)

    def test_named_publisher_does_not_bypass_finalization_stage_cap(self):
        state = checkpoint()
        control = state['progress_control']
        control.update(phase='finalize', finalization_job_id='already-running-publisher',
                       active_minutes=34, stage_active_minutes=25)
        self.assertEqual(GUARD.decide(state)['action'], 'STOP_ACTIVE_WORK')


if __name__ == '__main__':
    unittest.main()
