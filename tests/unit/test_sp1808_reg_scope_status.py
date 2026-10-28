"""SP-18-v1: additive coverage metadata, using complete real staged modules.

No product import or global safety mutation happens at test discovery. The scoped
sandbox is also used by the acceptance bootstrap for unchanged contract suites.
"""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

from tests._support import ROOT

FIXTURE = ROOT / 'tests/fixtures/sp1808_reg_scope_status/coverage.json'


def forbidden(*_args, **_kwargs):
    raise RuntimeError('SP1808 offline sentinel: network/collection/apply forbidden')


class OfflineSandbox(ExitStack):
    """Restore every patch/path on exit; bind repository defaults before imports."""

    def __init__(self, *, block_gate=True):
        super().__init__()
        self.block_gate = block_gate

    def __enter__(self):
        super().__enter__()
        old_path = list(sys.path)
        self.callback(lambda: sys.path.__setitem__(slice(None), old_path))
        sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
        self.enter_context(patch.object(socket, 'getaddrinfo', forbidden))
        self.enter_context(patch.object(socket.socket, 'connect', forbidden))
        self.enter_context(patch.object(socket.socket, 'connect_ex', forbidden))
        paths = importlib.import_module('skippercast.paths')
        self.enter_context(patch.object(paths, 'repo_root', return_value=ROOT))
        # Each defaults-bearing dependency now binds to this staged checkout,
        # never SKIPPERCAST_ROOT or the shared editable installation.
        for name in ('platform.contracts', 'pipeline.regulations',
                     'pipeline.settings', 'pipeline.regulation_review'):
            module = importlib.import_module('skippercast.' + name)
            if not module.__file__ or not Path(module.__file__).resolve().is_relative_to(ROOT / 'src'):
                raise RuntimeError('Product import escaped staged checkout')
        from skippercast.platform import contracts
        from skippercast.pipeline import regulations, regulation_review
        if contracts.REPO != ROOT or regulations.REGISTRY != ROOT / 'dist/data/regulations.json':
            raise RuntimeError('Repository constants were bound outside the staged checkout')
        defaults = regulation_review.jurisdiction_files.__defaults__
        if not defaults or defaults[0] != ROOT:
            raise RuntimeError('Repository function default escaped staged checkout')
        self.enter_context(patch.object(regulation_review, 'collect_packet', forbidden))
        if self.block_gate:
            self.enter_context(patch.object(regulation_review, 'approved_registry', forbidden))
        return self


class CoverageCase(unittest.TestCase):
    def setUp(self):
        sandbox = OfflineSandbox()
        self.addCleanup(sandbox.close)
        sandbox.__enter__()
        from skippercast.pipeline import regulations, regulation_review
        self.rules = regulations
        self.coverage = regulation_review.coverage
        fixture = json.loads(FIXTURE.read_text())
        self.now = datetime.fromisoformat(fixture['now'])
        self.registry = fixture['registry']
        self.sources = fixture['receipts']
        self.registry['approved_rules_content_sha256'] = self.rules.content_hash(self.registry)

    def check_scoped_row(self, row, required, issues, status, omitted):
        self.assertEqual(row['required_sources'], required)
        self.assertEqual(row['issues'], issues)
        self.assertEqual(row.get('assessment_status'), status)
        self.assertEqual(row.get('out_of_scope_sources'), omitted)

    def check_legacy(self, report, failed):
        expected_species = {
            'local': {'name': 'Synthetic local species', 'required_sources': ['local'],
                      'issues': ['local'] if failed else []},
            'remote': {'name': 'Synthetic remote species', 'required_sources': ['remote'], 'issues': []},
            'mixed': {'name': 'Synthetic mixed species', 'required_sources': ['remote-two', 'local', 'remote'],
                      'issues': ['local'] if failed else []},
        }
        expected_areas = {
            'local': {'name': 'Synthetic local area', 'required_sources': ['local'],
                      'live_clearance_required': True, 'issues': ['local'] if failed else []},
            'elsewhere': {'name': 'Synthetic remote area', 'required_sources': ['remote'],
                          'live_clearance_required': False, 'issues': []},
            'mixed': {'name': 'Synthetic mixed area', 'required_sources': ['remote-two', 'local', 'remote'],
                      'live_clearance_required': False, 'issues': ['local'] if failed else []},
            'empty': {'name': 'Synthetic empty dependency area', 'required_sources': [],
                      'live_clearance_required': False, 'issues': []},
        }
        self.assertEqual(report['species'], expected_species)
        self.assertEqual(report['areas'], expected_areas)
        self.assertEqual(report['review_required'], ['local'] if failed else [])
        self.assertEqual(set(report), {'jurisdiction_id', 'revision', 'reviewed_at', 'valid_through',
                         'rules_review_status', 'source_scope_ids', 'valid_for_current_date',
                         'checked_at', 'review_required', 'checks', 'areas', 'species'})
        self.assertIsNone(report['source_scope_ids'])


class BaselineTests(CoverageCase):
    def test_primary_regression(self):
        """A1: otherwise-valid scoped reporting lacks only the additive metadata."""
        report = self.coverage(self.registry, {'local': self.sources['local']}, self.now, ['local'])
        self.assertEqual(report['rules_review_status'], 'reviewed')
        self.assertEqual(report['review_required'], [])
        self.assertEqual(report['checks']['local']['status'], 'unchanged')
        self.assertEqual(report['checks']['remote']['status'], 'out-of-scope')
        self.assertEqual(report['species']['local']['issues'], [])
        self.assertEqual(report['species']['remote']['issues'], ['remote'])
        self.assertEqual(report['areas']['elsewhere']['issues'], ['remote'])
        # Frozen exact deciding assertion; baseline must fail here, not at setup.
        self.assertEqual(report['species']['remote'].get('assessment_status'), 'not-evaluated',
                         'A1_MISSING_SCOPED_ASSESSMENT')
        for group, ident in [('species', 'remote'), ('areas', 'elsewhere')]:
            self.check_scoped_row(report[group][ident], ['remote'], ['remote'],
                                  'not-evaluated', ['remote'])
        for group in ('species', 'areas'):
            self.check_scoped_row(report[group]['local'], ['local'], [], 'evaluated', [])

    def test_healthy_control(self):
        """Unscoped shape and genuinely failed-source issues remain exactly legacy."""
        self.check_legacy(self.coverage(self.registry, self.sources, self.now), False)
        self.sources['local'].update(status='failed', data=None, data_retrieved_at=None)
        report = self.coverage(self.registry, self.sources, self.now)
        self.check_legacy(report, True)
        self.assertEqual(report['checks']['local']['status'], 'unavailable')


class FocusedTests(CoverageCase):
    def test_a2_mixed_failures_preserve_issues_order(self):
        cases = ('changed', 'unavailable', 'identity-mismatch', 'normalization-mismatch', 'unreviewed')
        for status in cases:
            with self.subTest(status=status):
                sources = deepcopy(self.sources)
                if status == 'changed':
                    sources['local']['data']['content_sha256'] = 'b' * 64
                elif status == 'unavailable':
                    sources['local'].update(status='failed', data=None)
                elif status == 'identity-mismatch':
                    sources['local']['url'] = 'https://example.org/different'
                elif status == 'normalization-mismatch':
                    sources['local']['data']['normalization'] = 'other-v1'
                else:
                    sources['local']['data']['content_sha256'] = None
                report = self.coverage(self.registry, sources, self.now, ['local'])
                self.assertEqual(report['checks']['local']['status'], status)
                self.assertEqual(report['review_required'], ['local'])
                for group in ('species', 'areas'):
                    self.check_scoped_row(report[group]['mixed'], ['remote-two', 'local', 'remote'],
                                          ['remote-two', 'local', 'remote'], 'partial', ['remote-two', 'remote'])
                    # Evaluated explicitly does not mean passing.
                    self.check_scoped_row(report[group]['local'], ['local'], ['local'], 'evaluated', [])

    def test_a3_empty_full_unknown_and_reordered_scope(self):
        empty_scope = []
        report = self.coverage(self.registry, {}, self.now, empty_scope)
        self.assertEqual(empty_scope, [])
        self.assertEqual(report['source_scope_ids'], [])
        self.assertEqual(report['review_required'], [])
        for group in ('species', 'areas'):
            self.check_scoped_row(report[group]['mixed'], ['remote-two', 'local', 'remote'],
                                  ['remote-two', 'local', 'remote'], 'not-evaluated',
                                  ['remote-two', 'local', 'remote'])
        # The existing real snapshot requires nonempty species dependencies;
        # empty area dependencies are valid and preserve their previous meaning.
        self.check_scoped_row(report['areas']['empty'], [], [], 'evaluated', [])
        with self.assertRaisesRegex(ValueError, 'Unknown regional legal source scope'):
            self.coverage(self.registry, self.sources, self.now, ['not-a-source'])
        for scope in (['remote', 'local', 'remote-two'], ['local', 'remote-two', 'remote', 'local']):
            report = self.coverage(self.registry, self.sources, self.now, scope)
            for group in ('species', 'areas'):
                for row in report[group].values():
                    self.assertEqual(row['assessment_status'], 'evaluated')
                    self.assertEqual(row['out_of_scope_sources'], [])
                    self.assertEqual(row['issues'], [])
        self.registry['species']['local']['source_ids'] = []
        with self.assertRaisesRegex(ValueError, 'Regulations registry is incomplete'):
            self.coverage(self.registry, self.sources, self.now, [])

    def test_a4_inputs_snapshot_dates_and_clearance_unchanged(self):
        before_registry, before_sources = deepcopy(self.registry), deepcopy(self.sources)
        scope = ['local']
        before_scope = list(scope)
        snapshot_before = self.rules.regulatory_snapshot(self.sources, self.now, self.registry, scope)
        report = self.coverage(self.registry, self.sources, self.now, scope)
        self.assertEqual(self.registry, before_registry)
        self.assertEqual(self.sources, before_sources)
        self.assertEqual(scope, before_scope)
        self.assertEqual(self.rules.regulatory_snapshot(self.sources, self.now, self.registry, scope), snapshot_before)
        for key in ('rules_review_status', 'review_required', 'checks', 'checked_at', 'source_scope_ids'):
            self.assertEqual(report[key], snapshot_before[key])
        for key in ('jurisdiction_id', 'revision', 'reviewed_at', 'valid_through'):
            self.assertEqual(report[key], self.registry[key])
        self.assertTrue(report['valid_for_current_date'])
        self.assertTrue(report['areas']['local']['live_clearance_required'])
        self.assertFalse(report['areas']['elsewhere']['live_clearance_required'])
        self.assertFalse(report['areas']['mixed']['live_clearance_required'])
        expired = self.coverage(self.registry, self.sources, self.now + timedelta(days=366), scope)
        self.assertFalse(expired['valid_for_current_date'])
        self.assertNotIn('permission_to_fish', report)
        self.assertEqual(self.rules.content_hash(self.registry), before_registry['approved_rules_content_sha256'])


if __name__ == '__main__':
    unittest.main()
