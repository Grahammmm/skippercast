"""Contract tests for conservative CI selection, aggregate gates and partitioning."""
from collections import Counter
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from scripts.ci_plan import check_gate, changed_paths, plan
from scripts.ci_survey import junit_id, partition, verify
from tests._support import ROOT


class SelectionTests(unittest.TestCase):
    def test_regular_pr_keeps_313_and_unknown_paths_run_all(self):
        for paths in (None, [], ['new-directory/file'], ['docs/claim.md'], ['catalog/coasts.json'],
                      ['.github/workflows/ci.yml'], ['pyproject.toml'], ['pnpm-lock.yaml'], ['../bad']):
            with self.subTest(paths=paths):
                self.assertEqual(plan('pull_request', 'feature/a', paths),
                                 {'python': ['3.13'], 'survey': True, 'e2e': True})

    def test_main_batch_and_manual_never_filter(self):
        for event, branch in [('push', 'main'), ('pull_request', 'batch/123'),
                              ('workflow_dispatch', 'bot/pr'), ('pull_request', 'main')]:
            self.assertEqual(plan(event, branch, ['.github/ISSUE_TEMPLATE/bug.yml']),
                             {'python': ['3.11', '3.12', '3.13'], 'survey': True, 'e2e': True})

    def test_forms_skip_only_long_suites(self):
        self.assertEqual(plan('pull_request', 'feature/a', ['.github/pull_request_template.md', '.github/ISSUE_TEMPLATE/bug.yml']),
                         {'python': ['3.13'], 'survey': False, 'e2e': False})

    def test_python_only_still_runs_every_python_test(self):
        for path in ['src/skippercast/coastal/mapping.py', 'tests/gis/test_new.py', 'research/tests/test_new.py']:
            result = plan('pull_request', 'feature/a', [path])
            self.assertTrue(result['survey'])
            self.assertFalse(result['e2e'])
            self.assertTrue(plan('pull_request', 'feature/a', [path, 'dist/regions/new.json'])['e2e'])

    def test_browser_changes_and_renames_cannot_hide_in_ignore_paths(self):
        for path in ['web/app.tsx', 'server/index.ts', 'scripts/build-worker.mjs', 'e2e/test.spec.ts',
                     'package.json', 'regions/a/region.json', 'deployments/production.json', 'tests/test_app.mjs']:
            self.assertTrue(plan('pull_request', 'feature/a', ['tests/unit/test_a.py', path])['e2e'])

    def test_diff_uses_both_trees_all_names_and_no_rename_filter(self):
        env = {'CI_BASE_SHA': 'a' * 40, 'CI_HEAD_SHA': 'b' * 40}
        with patch('scripts.ci_plan.subprocess.run') as fetch, patch('scripts.ci_plan.subprocess.check_output', return_value=b'web/old.ts\0tests/new.py\0') as diff:
            self.assertEqual(changed_paths(env), ['web/old.ts', 'tests/new.py'])
            self.assertIn('--no-renames', diff.call_args.args[0])
            self.assertEqual(diff.call_args.args[0][-2:], ['a' * 40, 'b' * 40])
            fetch.assert_called_once()
        self.assertIsNone(changed_paths({'CI_BASE_SHA': 'bad', 'CI_HEAD_SHA': 'b' * 40}))


class AggregateTests(unittest.TestCase):
    def needs(self, survey='true', e2e='true'):
        return {'changes': {'result': 'success', 'outputs': {'survey': survey, 'e2e': e2e}},
                'survey-shard': {'result': 'success' if survey == 'true' else 'skipped'},
                'e2e-tests': {'result': 'success' if e2e == 'true' else 'skipped'},
                'check': {'result': 'success'}, 'web': {'result': 'success'}}

    def test_positive_full_and_explicit_skips(self):
        for survey, e2e in [('true', 'true'), ('true', 'false'), ('false', 'false')]:
            self.assertIn('passed', check_gate(self.needs(survey, e2e), 'survey-science'))
            self.assertIn('passed', check_gate(self.needs(survey, e2e), 'e2e'))

    def test_failure_cancel_and_unexpected_skip_fail_closed(self):
        for job in ('changes', 'survey-shard', 'e2e-tests', 'check', 'web'):
            for state in ('failure', 'cancelled', 'skipped', ''):
                needs = self.needs()
                needs[job]['result'] = state
                with self.subTest(job=job, state=state), self.assertRaises(ValueError):
                    check_gate(needs, 'survey-science')

    def test_missing_and_malformed_selection_fails(self):
        for value in ('', 'TRUE', None):
            needs = self.needs()
            needs['changes']['outputs']['survey'] = value
            with self.assertRaises(ValueError):
                check_gate(needs, 'survey-science')
        needs = self.needs('false', 'false')
        needs['survey-shard']['result'] = 'failure'
        with self.assertRaises(ValueError):
            check_gate(needs, 'survey-science')


class ShardTests(unittest.TestCase):
    def test_new_and_weighted_nodes_all_run_once_deterministically(self):
        nodes = [f'tests/gis/test_a.py::test_a[{n}]' for n in range(31)]
        weights = {junit_id(nodes[0]): 40, junit_id(nodes[1]): 30}
        groups = partition(nodes, 4, weights)
        self.assertEqual(Counter(n for group in groups for n in group), Counter(nodes))
        self.assertEqual(groups, partition(list(reversed(nodes)), 4, weights))
        self.assertTrue(all(groups))
        self.assertNotEqual(next(i for i, g in enumerate(groups) if nodes[0] in g),
                            next(i for i, g in enumerate(groups) if nodes[1] in g))
        self.assertEqual(junit_id('tests/unit/test_a.py::A::test_b'), 'tests.unit.test_a.A::test_b')

    def receipts(self):
        nodes = [f'tests/test_a.py::test_{i}' for i in range(12)]
        return [{'shard': i + 1, 'count': 4, 'head': 'a' * 40, 'exit_code': 0,
                 'collected': nodes, 'selected': group, 'executed': group.copy()}
                for i, group in enumerate(partition(nodes, 4, {}))]

    def test_receipt_success(self):
        self.assertEqual(verify(self.receipts(), 4, 'a' * 40), 12)

    def test_missing_duplicate_stale_failed_and_incomplete_receipts_fail(self):
        good = self.receipts()
        bad = [good[:-1], good + [good[0]], [good[0]] * 4]
        for key, value in [('head', 'b' * 40), ('exit_code', 1), ('count', 3),
                           ('collected', []), ('selected', []), ('executed', [])]:
            rows = deepcopy(good)
            rows[0][key] = value
            bad.append(rows)
        rows = deepcopy(good)
        rows[0]['selected'] = rows[1]['selected']
        rows[0]['executed'] = rows[1]['executed']
        bad.append(rows)
        for rows in bad:
            with self.assertRaises(ValueError):
                verify(rows, 4, 'a' * 40)

    def test_bad_partition_parameters_fail(self):
        for nodes, count, weights in [([], 4, {}), (['x', 'x'], 4, {}), (['x'], 0, {}),
                                      (['x'], 4, {'x': float('nan')}), (['x'], 4, {'x': -1})]:
            with self.assertRaises(ValueError):
                partition(nodes, count, weights)

    def test_weights_are_placement_hints_from_recorded_run(self):
        weights = json.loads((ROOT / 'scripts/ci-survey-weights.json').read_text())
        self.assertEqual(weights['source_run'], 40609252018)
        self.assertTrue(all(v >= 1 for v in weights['seconds'].values()))


class WorkflowTests(unittest.TestCase):
    def test_all_required_layers_and_failure_checks_remain(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('shard: [1, 2, 3, 4]', text)
        self.assertIn('fail-fast: false', text)
        self.assertIn('SKIPPERCAST_REQUIRE_GIS: "1"', text)
        self.assertIn('--strict-skips', text)
        self.assertIn('python -m pytest -m "not gis"', text)
        self.assertIn('needs: [changes, survey-shard, e2e-tests, check, web]\n    if: always()', text)
        self.assertIn('ci_survey.py verify', text)
        self.assertEqual(text.count('run: node --test tests/test_*.mjs'), 1)
        self.assertIn('cache: pip\n          cache-dependency-path: |\n            pyproject.toml', text)
        self.assertEqual(text.count('cache: pnpm'), 2)
        self.assertIn("hashFiles('pnpm-lock.yaml')", text)
        self.assertNotIn('paths-ignore:', text)
        self.assertNotIn('continue-on-error:', text)

    def test_deploy_cannot_follow_a_pull_request(self):
        deploy = (ROOT / '.github/workflows/deploy-cloudflare.yml').read_text()
        self.assertNotIn('\n  pull_request:', deploy)
        self.assertEqual(deploy.count("github.event.workflow_run.event == 'push'"), 2)
        self.assertEqual(deploy.count("github.event.workflow_run.head_branch == 'main'"), 2)


if __name__ == '__main__':
    unittest.main()
