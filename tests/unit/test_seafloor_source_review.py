"""Discovery checkpoints suppress repeat work, never qualify or publish data."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.platform.contracts import atomic_json
from skippercast.seafloor import source_review as review, state_cache
from tests._support import NOW


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = {'surveys': [{'id': 'tested', 'status': 'candidate'},
                                     {'id': 'untested', 'status': 'candidate'}]}
        for name in ('catalog/habitat-rules.json', 'dist/data/atlas.json',
                     'var/seafloor/reference/cells.json'):
            atomic_json(self.root/name, {'version': 1})
        (self.root/'requirements-survey.txt').write_text('pinned science\n')
        atomic_json(self.root/'catalog/reaches.json', {'reaches': [{'id': 'r01'}, {'id': 'r02'}]})
        self.evidence = 'var/seafloor/tested/proof.json'
        atomic_json(self.root/self.evidence, {'before_km2': 1, 'after_km2': 1,
                                            'new_candidate_count': 0})
        self.queue = [{'id': 'tested'}, {'id': 'untested'}]

    def record(self, reaches=('r01',)):
        return review.record(self.root, self.manifest, 'tested', reaches,
            'no-incremental-support', self.evidence, now=NOW,
            note='Complete original grid compared against the current source set.')

    def partition(self, manifest=None, reaches=('r01',), now=NOW):
        return review.partition(self.root, manifest or self.manifest,
                                self.queue, reaches, now=now)

    def test_unchanged_tested_lead_is_deferred_without_losing_untested_lead(self):
        self.record()
        active, deferred, warnings = self.partition()
        self.assertEqual(active, [{'id': 'untested'}])
        self.assertEqual([r['id'] for r in deferred], ['tested'])
        self.assertEqual(warnings, [])
        state = review.load(self.root)
        self.assertIs(state['reviews'][0]['fishing_target'], False)
        self.assertIs(state['reviews'][0]['exportable'], False)
        self.assertEqual(state['reviews'][0]['coverage_credit_km2'], 0)
        # Evidence travels in the private checkpoint, so recovery needs no raw archive.
        (self.root/self.evidence).unlink()
        self.assertEqual(self.partition()[0], [{'id': 'untested'}])

    def test_changed_source_reopens_the_lead(self):
        self.record()
        changed = deepcopy(self.manifest)
        changed['surveys'][0]['sha256'] = 'new original bytes'
        self.assertEqual(self.partition(changed)[0], self.queue)

    def test_rules_reference_and_requirements_changes_reopen_the_lead(self):
        for name in ('catalog/habitat-rules.json', 'var/seafloor/reference/cells.json',
                     'requirements-survey.txt'):
            with self.subTest(name=name):
                self.record()
                (self.root/name).write_text('changed input')
                self.assertEqual(self.partition()[0], self.queue)

    def test_separate_scope_expiry_and_future_review_do_not_hide_the_lead(self):
        self.record()
        self.assertEqual(self.partition(reaches=('r02',))[0], self.queue)
        self.assertEqual(self.partition(now=NOW+timedelta(days=7))[0], self.queue)
        self.assertEqual(self.partition(now=NOW-timedelta(seconds=1))[0], self.queue)

    def test_legal_only_refresh_does_not_reopen_physical_discovery(self):
        self.record()
        atomic_json(self.root/'var/seafloor/screen/snapshot.json', {'changed': True})
        self.assertEqual(self.partition()[0], [{'id': 'untested'}])

    def test_corrupt_or_incomplete_evidence_remains_actionable(self):
        for change in ('evidence', 'credit', 'note', 'expiry'):
            with self.subTest(change=change):
                self.record()
                state = review.load(self.root)
                row = state['reviews'][0]
                if change == 'evidence':
                    row['evidence']['document']['after_km2'] = 2
                elif change == 'credit':
                    row['coverage_credit_km2'] = 1
                elif change == 'note':
                    row.pop('note')
                else:
                    row['expires_at'] = (NOW+timedelta(days=90)).isoformat()
                atomic_json(self.root/review.RELATIVE, state)
                self.assertEqual(self.partition()[0], self.queue)
        (self.root/review.RELATIVE).write_text('not JSON')
        active, _, warnings = self.partition()
        self.assertEqual(active, self.queue)
        self.assertTrue(warnings)

    def test_recorder_rejects_unknown_scope_and_evidence_path_escape(self):
        for source, reaches, evidence in [('unknown', ['r01'], self.evidence),
                    ('tested', ['unknown'], self.evidence), ('tested', ['r01'], '../outside.json')]:
            with self.subTest(source=source, reaches=reaches, evidence=evidence), self.assertRaises(ValueError):
                review.record(self.root, self.manifest, source, reaches, 'no-incremental-support',
                              evidence, now=NOW, note='Bounded source test.')

    def test_malformed_checkpoint_shapes_keep_leads_actionable(self):
        for document in ([], {'version': 1, 'reviews': ['bad row']},
                {'version': 1, 'reviews': [{'source_id': []}]}):
            with self.subTest(document=document):
                atomic_json(self.root/review.RELATIVE, document)
                self.assertEqual(self.partition()[0], self.queue)
        # A recorder may replace malformed rows, but not approve them.
        self.record()
        self.assertEqual(len(review.load(self.root)['reviews']), 1)

    def test_checkpoint_directory_stays_actionable(self):
        path = self.root/review.RELATIVE
        path.mkdir(parents=True)
        active, deferred, warnings = self.partition()
        self.assertEqual(active, self.queue)
        self.assertEqual(deferred, [])
        self.assertTrue(warnings)

    def test_nested_adapter_change_invalidates_discovery_context(self):
        original = review.sha256
        def changed_adapter(path):
            return 'changed reader' if Path(path).name == 'arcgrid.py' else original(path)
        self.record()
        with patch.object(review, 'sha256', side_effect=changed_adapter):
            self.assertEqual(self.partition()[0], self.queue)

    def test_isolated_recovery_admits_only_the_fixed_private_checkpoint(self):
        self.record()
        self.assertNotIn(self.root/review.RELATIVE, state_cache.shared_paths(self.root))
        self.assertTrue(state_cache.allowed('source-review', 'source-review/checkpoint.json'))
        self.assertFalse(state_cache.allowed('shared', 'source-review/checkpoint.json'))
        self.assertFalse(state_cache.allowed('r01', 'source-review/checkpoint.json'))
        self.assertFalse(state_cache.allowed('shared', 'source-review/raw-survey.json'))
        self.assertFalse(state_cache.allowed('shared', 'source-review/../secrets.json'))

        self.assertFalse(state_cache.allowed('source-review', 'cache/'+'a'*64+'/source.tif'))
        self.assertFalse(state_cache.allowed('source-review', 'reaches/source-review/run.json'))
