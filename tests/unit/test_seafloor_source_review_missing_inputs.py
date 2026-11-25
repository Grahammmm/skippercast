"""Source-review checkpoint names missing evidence and keeps leads actionable.

Contract: record() refuses evidence that is absent, not a regular file or not
JSON with the module's named ValueError and writes nothing; partition() treats
an unreadable catalog/context file like a corrupt checkpoint (queue untouched,
one warning) instead of aborting the rollout plan or deferring a lead.
"""
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from skippercast.platform.contracts import atomic_json
from skippercast.seafloor import source_review as review
from tests._support import NOW

UNSAFE = 'Unsafe source-review evidence'
CONTEXT_FILES = ('catalog/reaches.json', 'catalog/habitat-rules.json',
                 'requirements-survey.txt', 'dist/data/atlas.json',
                 'var/seafloor/reference/cells.json')


class SourceReviewMissingInputTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.manifest = {'surveys': [{'id': 'tested', 'status': 'candidate'}]}
        self.queue = [{'id': 'tested'}]
        for name in ('catalog/habitat-rules.json', 'dist/data/atlas.json',
                     'var/seafloor/reference/cells.json'):
            atomic_json(self.root/name, {'version': 1})
        (self.root/'requirements-survey.txt').write_text('pinned science\n')
        atomic_json(self.root/'catalog/reaches.json', {'reaches': [{'id': 'r01'}]})
        self.evidence = 'var/seafloor/tested/proof.json'
        atomic_json(self.root/self.evidence, {'before_km2': 1, 'after_km2': 1})

    def record(self, evidence=None):
        return review.record(self.root, self.manifest, 'tested', ['r01'],
                             'no-incremental-support', evidence or self.evidence,
                             now=NOW, note='Complete original grid compared.')

    def partition(self):
        return review.partition(self.root, self.manifest, self.queue, ['r01'],
                                now=NOW + timedelta(hours=1))

    def assert_refused_without_checkpoint(self, evidence):
        with self.assertRaisesRegex(ValueError, UNSAFE):
            self.record(evidence)
        self.assertFalse((self.root/review.RELATIVE).exists())

    # Bug caught: a missing evidence file leaks FileNotFoundError from stat().
    def test_missing_evidence_is_refused_by_name(self):
        self.assert_refused_without_checkpoint('var/seafloor/tested/absent.json')

    # Bug caught: a directory named *.json leaks IsADirectoryError from the read.
    def test_directory_evidence_is_refused_by_name(self):
        (self.root/'var/seafloor/tested/dir.json').mkdir()
        self.assert_refused_without_checkpoint('var/seafloor/tested/dir.json')

    # Bug caught: a read/JSON failure surfaces as a bare JSONDecodeError/UnicodeDecodeError
    # message instead of the module's named refusal.
    def test_unreadable_or_non_json_evidence_is_refused_by_name(self):
        for name, data in (('bad.json', b'not json'), ('binary.json', b'\xff\xfe\x00')):
            with self.subTest(name=name):
                (self.root/'var/seafloor/tested'/name).write_bytes(data)
                self.assert_refused_without_checkpoint('var/seafloor/tested/'+name)

    # Unaffected control: valid evidence still records, so the refusals above are not blanket.
    def test_valid_evidence_still_records(self):
        self.assertEqual(self.record()['source_id'], 'tested')
        self.assertEqual(self.partition(), ([], [{'id': 'tested', 'review_outcome': 'no-incremental-support',
                         'review_note': 'Complete original grid compared.',
                         'expires_at': (NOW+review.TTL).isoformat()}], []))

    # Bug caught: a missing catalog file aborts the plan (OSError) or is swallowed without
    # the warning so the lead is silently deferred or silently kept.
    def test_stored_decision_with_missing_context_file_keeps_lead_actionable(self):
        for name in CONTEXT_FILES:
            with self.subTest(missing=name):
                self.record()
                (self.root/name).unlink()
                active, deferred, warnings = self.partition()
                self.assertEqual((active, deferred), (self.queue, []))
                self.assertEqual(len(warnings), 1)
                self.assertIn('context is unreadable', warnings[0])
                self.assertIn('all leads remain actionable', warnings[0])
                self.restore(name)

    def restore(self, name):
        path = self.root/name
        if name == 'requirements-survey.txt':
            path.write_text('pinned science\n')
        elif name == 'catalog/reaches.json':
            atomic_json(path, {'reaches': [{'id': 'r01'}]})
        else:
            atomic_json(path, {'version': 1})

    def test_stored_decision_with_no_catalog_files_keeps_lead_actionable(self):
        self.record()
        for name in CONTEXT_FILES:
            (self.root/name).unlink()
        self.assertEqual(self.partition(),
                         (self.queue, [], ['Source-review context is unreadable; '
                                           'all leads remain actionable.']))

    # Controls: these already held on main and must stay identical.
    def test_empty_checkpoint_control(self):
        atomic_json(self.root/review.RELATIVE, {'version': 1, 'reviews': []})
        for name in CONTEXT_FILES:
            (self.root/name).unlink()  # no stored decision: context is never consulted
        self.assertEqual(self.partition(), (self.queue, [], []))

    def test_corrupt_checkpoint_control(self):
        (self.root/review.RELATIVE).parent.mkdir(parents=True)
        (self.root/review.RELATIVE).write_text('{"version": 1, "reviews": [')
        self.assertEqual(self.partition(), (self.queue, [],
                         ['Invalid source-review checkpoint; all leads remain actionable.']))
