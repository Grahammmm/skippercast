"""SC111: qualify_row requires integer native evidence counts.

Import is inert: no guards, roots, environment or tempfile settings change here.
The standalone runner (tools/run_sc111_qualify_counts.py) selects these methods
by explicit name under its offline guards; ordinary unittest/pytest discovery
runs the same methods against the importable candidate package.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests._support import ROOT as REPO
FIXTURE = REPO / 'tests/fixtures/sc111-qualify-counts/qualification.json'
RUNNER = REPO / 'tools/run_sc111_qualify_counts.py'
CATALOG = REPO / 'catalog/surveys.json'
TOKEN = 'native_receipt_counts_invalid'
SOURCE_BYTES = 'source_bytes'
VALID = 'valid_pixels_in_requested_bounds'
SHALLOW = 'nominal_0_300ft_pixels_in_requested_bounds'
COUNT_FIELDS = (SOURCE_BYTES, VALID, SHALLOW)
MISSING = object()
REVIEW_KEYS = ('adapter_version', 'source_sha256', 'cog_sha256', 'requested_bounds_wgs84',
               VALID, SHALLOW, 'native_resolution_m', 'vertical_datum', 'uncertainty_type',
               'interpolation_mask')
GRID_KEYS = ('native_sampling', 'grid_spacing_m', 'preparation_receipt_sha256')


def malformed(value):
    """Every malformed spelling of one otherwise-valid integer count."""
    return (('missing', MISSING), ('null', None), ('bool-true', True), ('bool-false', False),
            ('integral-float', float(value)), ('fractional-float', value + 0.5),
            ('string', str(value)), ('negative', -value), ('nan', float('nan')),
            ('infinity', float('inf')), ('negative-infinity', -float('inf')))


def snapshot(value):
    return repr(value)


def load_runner():
    spec = importlib.util.spec_from_file_location('sc111_runner_for_tests', RUNNER)
    if spec is None or spec.loader is None:
        raise ImportError('SC111 runner is not loadable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QualifyCountsTests(unittest.TestCase):
    # The runner assigns a list to collect evidence; ordinary discovery records nothing.
    events = None

    @classmethod
    def setUpClass(cls):
        from skippercast.seafloor import manifest
        cls.manifest = manifest
        cls.data = json.loads(FIXTURE.read_text())

    def record(self, **event):
        if self.events is not None:
            self.events.append({'test_id': self.id(), **event})

    # ---- fixture constructors -------------------------------------------------
    def variants(self):
        d = deepcopy(self.data)
        private = dict(deepcopy(d['government_row']), license='unknown')
        return [('public-original', d['government_row'], d['original_receipt'], False),
                ('physical-original', private, deepcopy(d['original_receipt']), True),
                ('physical-grid', d['grid_row'], d['grid_receipt'], True)]

    def qualify(self, row, receipt, physical_only=False, rights_url=None):
        """Call the real API and prove caller inputs are never mutated."""
        rights_url = rights_url or self.data['rights_url']
        before = (snapshot(row), snapshot(receipt))
        try:
            return self.manifest.qualify_row(row, receipt, rights_url=rights_url,
                                             physical_only=physical_only)
        finally:
            after = (snapshot(row), snapshot(receipt))
            self.record(inputs_unchanged=before == after)
            self.assertEqual(before, after, 'caller inputs mutated')

    def refused(self, row, receipt, physical_only=False, pattern=TOKEN, rights_url=None):
        with self.assertRaisesRegex(ValueError, pattern):
            self.qualify(row, receipt, physical_only, rights_url)

    def expected(self, row, receipt, physical_only):
        grid = row.get('format') == 'measured-multibeam-grid'
        result = deepcopy(row)
        result.update(status='physical-only' if physical_only else 'usable', hold_reason='unknown',
                      bytes=receipt[SOURCE_BYTES], horizontal_crs=receipt['horizontal_crs'],
                      vertical_datum=receipt['vertical_datum'],
                      resolution_m=max(receipt['grid_spacing_m'] if grid else receipt['native_resolution_m']))
        review = {key: receipt[key] for key in REVIEW_KEYS + (GRID_KEYS if grid else ())}
        review['rights_source_url'] = self.data['rights_url']
        if 'raster_identity' in receipt:
            review['raster_identity'] = receipt['raster_identity']
        result['adapter_review'] = review
        return result

    def assert_qualified(self, row, receipt, physical_only=False):
        result = self.qualify(row, receipt, physical_only)
        expected = self.expected(row, receipt, physical_only)
        notes = result.pop('notes')
        expected.pop('notes')
        self.assertEqual(result, expected)
        for field in COUNT_FIELDS[1:]:
            self.assertIs(type(result['adapter_review'][field]), int)
        self.assertIs(type(result['bytes']), int)
        grid = row.get('format') == 'measured-multibeam-grid'
        self.assertTrue(notes.startswith('Reviewed measured-support bins' if grid
                                         else 'Opened through original-native-adapters-v1'))
        self.assertEqual(notes.endswith('publication/export remain prohibited.'), physical_only)
        return result

    # ---- A1 regression: positives and boundaries ------------------------------
    def test_regression_minimum_counts_of_one_qualify(self):
        for name, row, receipt, physical in self.variants():
            with self.subTest(variant=name):
                minimum = dict(receipt, **{SOURCE_BYTES: 1, VALID: 1, SHALLOW: 1})
                self.assert_qualified(row, minimum, physical)

    def test_regression_equal_shallow_and_valid_counts_qualify(self):
        for name, row, receipt, physical in self.variants():
            with self.subTest(variant=name):
                equal = dict(receipt, **{SHALLOW: receipt[VALID]})
                result = self.assert_qualified(row, equal, physical)
                self.assertEqual(result['adapter_review'][SHALLOW], result['adapter_review'][VALID])

    def test_regression_larger_valid_counts_preserve_source_and_review_fields(self):
        for name, row, receipt, physical in self.variants():
            with self.subTest(variant=name):
                result = self.assert_qualified(row, receipt, physical)
                self.assertEqual((result['id'], result['sha256'], result['url']),
                                 (row['id'], row['sha256'], row['url']))
                self.assertEqual(result['adapter_review']['cog_sha256'], receipt['cog_sha256'])
                huge = dict(receipt, **{SOURCE_BYTES: 2**63, VALID: 2**62, SHALLOW: 2**61})
                self.assert_qualified(row, huge, physical)

    def test_regression_public_and_physical_only_construction(self):
        d = self.data
        public = self.assert_qualified(d['government_row'], d['original_receipt'])
        self.assertEqual((public['status'], public['license']), ('usable', 'public-domain-us-gov'))
        private_row = dict(deepcopy(d['government_row']), license='unknown')
        private = self.assert_qualified(private_row, d['original_receipt'], True)
        self.assertEqual((private['status'], private['license']), ('physical-only', 'unknown'))
        self.assertTrue(self.manifest.physical_source(private, physical_only=True))
        self.assertFalse(self.manifest.physical_source(private))
        csumb_receipt = dict(d['original_receipt'], source_id=d['csumb_row']['id'],
                             source_sha256=d['csumb_row']['sha256'], source_bytes=d['csumb_row']['bytes'])
        csumb = self.qualify(d['csumb_row'], csumb_receipt,
                             rights_url=d['csumb_row']['rights_review']['policy_url'])
        self.assertEqual(csumb['status'], 'usable')
        self.assertEqual(csumb['adapter_review']['rights_source_url'],
                         d['csumb_row']['rights_review']['policy_url'])
        grid = self.assert_qualified(d['grid_row'], d['grid_receipt'], True)
        self.assertEqual(grid['resolution_m'], 5)
        self.assertNotIn('sparse_bins_excluded_in_requested_bounds', grid['adapter_review'])

    def test_regression_caller_inputs_unchanged_on_success_and_refusal(self):
        d = self.data
        row, receipt = deepcopy(d['government_row']), deepcopy(d['original_receipt'])
        frozen = (json.dumps(row, sort_keys=True), json.dumps(receipt, sort_keys=True))
        result = self.qualify(row, receipt)
        result['adapter_review'][VALID] = -5
        result['raster_identity_probe'] = True
        self.assertEqual((json.dumps(row, sort_keys=True), json.dumps(receipt, sort_keys=True)), frozen)
        bad = dict(receipt, **{SHALLOW: True})
        self.refused(row, bad)
        self.assertIs(bad[SHALLOW], True)
        self.assertEqual((json.dumps(row, sort_keys=True), json.dumps(receipt, sort_keys=True)), frozen)

    def test_regression_existing_source_hash_and_rights_refusals_preserved(self):
        d = self.data
        row, receipt = d['government_row'], d['original_receipt']
        receipt_message = 'matching native adapter receipt'
        for changes in ({'source_id': 'other-source'}, {'source_sha256': '0' * 64},
                        {'adapter_version': 'measured-multibeam-grid-v1'}):
            with self.subTest(changes=changes):
                self.refused(row, dict(receipt, **changes), pattern=receipt_message)
                self.refused(dict(row, license='unknown'), dict(receipt, **changes), True,
                             pattern=receipt_message)
        with self.subTest(case='public-rights-unqualified'):
            self.refused(dict(row, license='unknown'), receipt, pattern='rights')
        with self.subTest(case='producer-policy-url-conflict'):
            csumb_receipt = dict(receipt, source_id=d['csumb_row']['id'],
                                 source_sha256=d['csumb_row']['sha256'], source_bytes=8192)
            self.refused(d['csumb_row'], csumb_receipt, pattern='Producer policy URL conflicts')
        with self.subTest(case='non-public-rights-url'):
            self.refused(row, receipt, pattern='public HTTPS', rights_url='http://rights.example.invalid/x')
        with self.subTest(case='grid-public-refused'):
            self.refused(d['grid_row'], d['grid_receipt'], pattern='private-only')
        with self.subTest(case='grid-receipt-adapter-mismatch'):
            self.refused(d['grid_row'], dict(d['grid_receipt'], adapter_version='original-native-adapters-v1'),
                         True, pattern=receipt_message)

    # ---- A1 regression: malformed counts, one field at a time ------------------
    def malformed_field(self, field):
        for name, row, receipt, physical in self.variants():
            self.assert_qualified(row, receipt, physical)  # unrelated fields are valid
            for label, value in malformed(receipt[field]):
                with self.subTest(variant=name, field=field, value=label):
                    bad = deepcopy(receipt)
                    if value is MISSING:
                        bad.pop(field)
                    else:
                        bad[field] = value
                    self.refused(row, bad, physical)
                    self.record(field=field, value=label, variant=name, refused=True)

    def test_regression_source_bytes_malformed_refused(self):
        self.malformed_field(SOURCE_BYTES)

    def test_regression_valid_pixels_malformed_refused(self):
        self.malformed_field(VALID)

    def test_regression_shallow_pixels_malformed_refused(self):
        self.malformed_field(SHALLOW)

    def test_regression_zero_source_bytes_refused(self):
        for name, row, receipt, physical in self.variants():
            with self.subTest(variant=name):
                self.refused(row, dict(receipt, **{SOURCE_BYTES: 0}), physical)

    def test_regression_zero_shallow_count_refused(self):
        for name, row, receipt, physical in self.variants():
            with self.subTest(variant=name):
                self.refused(row, dict(receipt, **{SHALLOW: 0}), physical)

    def test_regression_shallow_greater_than_valid_refused(self):
        for name, row, receipt, physical in self.variants():
            with self.subTest(variant=name):
                self.refused(row, dict(receipt, **{SHALLOW: receipt[VALID] + 1}), physical)

    def deciding_boolean_refusal(self):
        """The deciding regression: a boolean shallow count with every other field valid."""
        row, receipt = self.data['government_row'], dict(self.data['original_receipt'], **{SHALLOW: True})
        with self.assertRaisesRegex(ValueError, TOKEN):
            self.manifest.qualify_row(row, receipt, rights_url=self.data['rights_url'])

    def test_regression_boolean_shallow_count_refused(self):
        self.deciding_boolean_refusal()

    # ---- A1 regression: evidence log sealing ----------------------------------
    def test_regression_seal_rejects_missing_changed_and_late_append_logs(self):
        runner = load_runner()
        root = Path(tempfile.mkdtemp(prefix='sc111-seal-'))
        created = []

        def cleanup():
            # Explicit absolute removal of only the inert files this test created.
            for path in reversed(created):
                if path.is_dir():
                    path.rmdir()
                elif path.exists():
                    path.unlink()
            root.rmdir()
        self.addCleanup(cleanup)

        def complete(name):
            run = root / name
            run.mkdir()
            created.append(run)
            (run / 'stdout.txt').write_text('inert synthetic stdout\n')
            (run / 'stderr.txt').write_text('inert synthetic stderr\n')
            (run / 'receipt.json').write_text('{"inert": true}\n')
            runner.seal(run)
            created.extend(run / leaf for leaf in ('stdout.txt', 'stderr.txt', 'receipt.json', 'seal.json'))
            return run

        runner.verify_seal(complete('positive'))
        missing = complete('missing')
        (missing / 'stderr.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'sealed log missing'):
            runner.verify_seal(missing)
        changed = complete('changed')
        (changed / 'stdout.txt').write_text('inert synthetic stdouT\n')
        with self.assertRaisesRegex(ValueError, 'sealed log changed'):
            runner.verify_seal(changed)
        late = complete('late-append')
        with (late / 'receipt.json').open('a') as handle:
            handle.write('late\n')
        with self.assertRaisesRegex(ValueError, 'sealed log changed'):
            runner.verify_seal(late)
        with self.assertRaisesRegex(ValueError, 'seal already exists'):
            runner.seal(late)
        unsealed = root / 'unsealed'
        unsealed.mkdir()
        created.append(unsealed)
        with self.assertRaisesRegex(ValueError, 'seal missing'):
            runner.verify_seal(unsealed)
        self.record(seal_positive=True, missing_rejected=True, changed_rejected=True,
                    late_append_rejected=True)

    # ---- A2 compatibility -----------------------------------------------------
    def test_compatibility_producer_shaped_receipts_drop_unreviewed_extras(self):
        d = self.data
        result = self.assert_qualified(d['government_row'], d['original_receipt'])
        for extra in ('inputs', 'cog_bytes', 'seam_margin_m', 'depth_basis', 'metadata', 'note',
                      'source_id', SOURCE_BYTES, 'horizontal_crs'):
            self.assertNotIn(extra, result['adapter_review'])
        grid = self.assert_qualified(d['grid_row'], d['grid_receipt'], True)
        self.assertEqual({k: grid['adapter_review'][k] for k in GRID_KEYS},
                         {k: d['grid_receipt'][k] for k in GRID_KEYS})

    def test_compatibility_committed_catalog_rows_requalify_unchanged(self):
        rows = json.loads(CATALOG.read_text())['surveys']
        reviewed = [r for r in rows if r['status'] in {'usable', 'physical-only'}]
        self.assertTrue(reviewed)
        for row in reviewed:
            with self.subTest(id=row['id']):
                review = row['adapter_review']
                receipt = dict(review, source_id=row['id'], source_bytes=row['bytes'],
                               horizontal_crs=row['horizontal_crs'])
                for field in COUNT_FIELDS:
                    self.assertIs(type(receipt[field]), int)
                result = self.manifest.qualify_row(row, receipt, rights_url=review['rights_source_url'],
                                                   physical_only=True)
                for field in (VALID, SHALLOW):
                    self.assertEqual(result['adapter_review'][field], review[field])
                self.assertEqual(result['bytes'], row['bytes'])
                self.assertEqual(result['resolution_m'], row['resolution_m'])
        self.record(catalog_reviewed_rows=len(reviewed))

    # ---- A3 negative control --------------------------------------------------
    def test_negative_control_count_predicate_seam(self):
        manifest = self.manifest
        original = manifest._require_native_counts
        d = self.data

        def positive():
            self.assert_qualified(d['government_row'], d['original_receipt'])

        positive()
        self.deciding_boolean_refusal()
        accepted_by_mutant = inner = None
        with patch.object(manifest, '_require_native_counts', lambda receipt: None):
            self.assertIsNot(manifest._require_native_counts, original)
            bad = dict(d['original_receipt'], **{SHALLOW: True})
            accepted_by_mutant = manifest.qualify_row(d['government_row'], bad, rights_url=d['rights_url'])
            self.assertIs(accepted_by_mutant['adapter_review'][SHALLOW], True)
            with self.assertRaises(AssertionError) as caught:
                self.deciding_boolean_refusal()
            inner = str(caught.exception)
            self.assertEqual(inner, 'ValueError not raised')
            positive()
        self.assertIs(manifest._require_native_counts, original)
        self.deciding_boolean_refusal()
        positive()
        self.record(mutant_detected=True, positive_passed=True, restored=True,
                    mutant_returned_boolean_count=True, expected_inner_failure=inner)


if __name__ == '__main__':
    unittest.main()
