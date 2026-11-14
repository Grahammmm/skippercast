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

    # Exact serialized-byte admission: record must never write what load refuses.
    NOTE = 'Complete original grid compared against the current source set.'

    def record_as(self, source, note=None):
        return review.record(self.root, self.manifest, source, ('r01',),
                             'no-incremental-support', self.evidence, now=NOW,
                             note=note or self.NOTE)

    def checkpoint(self):
        return self.root/review.RELATIVE

    def inventory(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*'))

    def seed_padded(self, pad=0, *, compact=False):
        """Readable checkpoint: one real prior review ('untested') plus pad ASCII bytes."""
        self.checkpoint().unlink(missing_ok=True)
        self.record_as('untested')
        state = review.load(self.root)
        state['reviews'][0]['pad'] = 'x'*pad
        atomic_json(self.checkpoint(), state, indent=None if compact else 2)

    def final_size(self, note=None, *, replace=False):
        """Bytes the writer produces when 'tested' is recorded on the seeded checkpoint."""
        self.seed_padded()
        if replace:
            self.record_as('tested')
        self.record_as('tested', note)
        return self.checkpoint().stat().st_size

    def assert_refused_untouched(self, *, writer, **kw):
        before, files = self.checkpoint().read_bytes(), self.inventory()
        with self.assertRaisesRegex(ValueError, 'exceeds bounded size'):
            self.record_as('tested', **kw)
        writer.assert_not_called()
        self.assertEqual(self.checkpoint().read_bytes(), before)
        self.assertEqual(self.inventory(), files)

    def test_newline_over_cap_preserves_checkpoint(self):
        base = self.final_size()
        self.seed_padded(review.MAX_BYTES + 1 - base)
        self.assertLessEqual(self.checkpoint().stat().st_size, review.MAX_BYTES)
        with patch.object(review, 'atomic_json', wraps=review.atomic_json) as writer:
            self.assert_refused_untouched(writer=writer)
        self.assertEqual(len(review.load(self.root)['reviews']), 1)
        active, deferred, warnings = self.partition()
        self.assertEqual(([r['id'] for r in active], [r['id'] for r in deferred], warnings),
                         (['tested'], ['untested'], []))

    def test_exact_final_cap_is_readable(self):
        base = self.final_size()
        self.seed_padded(review.MAX_BYTES - base)
        self.record_as('tested')
        self.assertEqual(self.checkpoint().stat().st_size, review.MAX_BYTES)
        self.assertEqual(len(review.load(self.root)['reviews']), 2)
        active, deferred, warnings = self.partition()
        self.assertEqual((active, [r['id'] for r in deferred], warnings),
                         ([], ['tested', 'untested'], []))

    def test_final_bytes_below_cap_pass_and_over_cap_refuse(self):
        for replace in (False, True):
            note = self.NOTE + ' Rechecked.' if replace else None
            final = self.final_size(note, replace=replace)
            for cap, ok in ((final+1, True), (final, True), (final-1, False)):
                with self.subTest(replace=replace, cap=cap):
                    self.seed_padded()
                    if replace:
                        self.record_as('tested')
                    with patch.object(review, 'MAX_BYTES', cap), \
                            patch.object(review, 'atomic_json', wraps=review.atomic_json) as writer:
                        if ok:
                            self.record_as('tested', note)
                            self.assertEqual(self.checkpoint().stat().st_size, final)
                            self.assertEqual(len(review.load(self.root)['reviews']), 2)
                        else:
                            self.assert_refused_untouched(writer=writer, note=note)
                            self.assertEqual(len(review.load(self.root)['reviews']),
                                             2 if replace else 1)

    def test_compact_input_expansion_is_preflighted(self):
        final = self.final_size(replace=True)
        self.seed_padded(compact=True)
        self.record_as('tested')
        self.checkpoint().write_bytes(json.dumps(review.load(self.root), separators=(',', ':')).encode())
        self.assertLess(self.checkpoint().stat().st_size, final - 1)
        with patch.object(review, 'MAX_BYTES', final - 1), \
                patch.object(review, 'atomic_json', wraps=review.atomic_json) as writer:
            self.assert_refused_untouched(writer=writer)
            self.assertEqual(len(review.load(self.root)['reviews']), 2)
        with patch.object(review, 'MAX_BYTES', final):
            self.record_as('tested')
        self.assertEqual(self.checkpoint().stat().st_size, final)

    def test_utf8_bytes_not_ascii_escapes_set_the_budget(self):
        note = 'é'*200 + ' café ☃ 海'
        self.record_as('tested', note)
        raw = self.checkpoint().read_bytes()
        final = len(raw)
        self.assertTrue(raw.endswith(b'}\n'))
        self.assertIn('é'.encode(), raw)
        self.assertNotIn(b'\\u00e9', raw)
        state = review.load(self.root)
        self.assertEqual(raw, (json.dumps(state, ensure_ascii=False, indent=2) + '\n').encode())
        self.checkpoint().unlink()
        for cap, ok in ((final, True), (final-1, False)):
            with self.subTest(cap=cap), patch.object(review, 'MAX_BYTES', cap), \
                    patch.object(review, 'atomic_json', wraps=review.atomic_json) as writer:
                if ok:
                    self.record_as('tested', note)
                    self.assertEqual(self.checkpoint().read_bytes(), raw)
                else:
                    self.checkpoint().unlink(missing_ok=True)
                    files = self.inventory()
                    with self.assertRaisesRegex(ValueError, 'exceeds bounded size'):
                        self.record_as('tested', note)
                    writer.assert_not_called()
                    self.assertEqual(self.inventory(), files)

    def test_oversized_evidence_still_refused_before_any_checkpoint_write(self):
        atomic_json(self.root/self.evidence, {'pad': 'x'*review.MAX_EVIDENCE_BYTES})
        with self.assertRaisesRegex(ValueError, 'Unsafe source-review evidence'):
            self.record_as('tested')
        self.assertFalse(self.checkpoint().exists())
