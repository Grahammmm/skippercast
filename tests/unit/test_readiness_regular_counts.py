"""RF1741-6: the compiler refuses regular-depth sector counts its source rows do not support.

Uses the committed synthetic SP1701 bundle and its scoped import helper; the full
real compiler runs against real JSON files in per-test temporary roots.
"""
import json
import unittest

from tests.unit import test_sp1701_readiness_spacing as sp

REGULAR = 'dist/data/noaa-regular-native-depth-review.json'
VARIABLE = 'dist/data/noaa-vr-native-depth-expanded-review.json'
OUTPUT = 'dist/data/california-atlas-readiness.json'
MISMATCH = 'Regular-depth sector file count does not match source rows'
OTHER = 'synthetic-sector-01'
SENTINEL = b'{"sentinel": "previous report"}\n'


def source_file(name, survey, sectors, status='ok'):
    return {'survey_id': survey, 'bag_url': f'https://example.invalid/{survey}/{name}.bag',
            'status': status,
            'sectors': {key: {'depth_uncertainty_eligible_cells': cells} for key, cells in sectors.items()}}


class RegularCountTests(sp.FixtureCase):
    def configure(self, files, counts):
        packet = self.inputs[REGULAR]
        packet['files'] = files
        for row in packet['sectors']:
            row['source_files_with_eligible_cells'] = counts.get(row['sector_id'], 0)

    def run_compile(self, preseed=False):
        """Return (report-or-None, error-or-None, root)."""
        root = self.materialize()
        output = root / OUTPUT
        if preseed:
            output.write_bytes(SENTINEL)
        with sp.isolated_readiness(root) as module:
            try:
                module.compile_readiness()
            except ValueError as error:
                return None, error, root
        return json.loads(output.read_text()), None, root

    def assert_refused(self, files, counts):
        for preseed in (True, False):
            with self.subTest(preseed=preseed, counts=counts):
                report, error, root = self.run_compile(preseed)
                self.assertIsNone(report)
                self.assertEqual(str(error), MISMATCH)
                output = root / OUTPUT
                if preseed:
                    self.assertEqual(output.read_bytes(), SENTINEL)
                else:
                    self.assertFalse(output.exists())

    def assert_compiles(self):
        report, error, _ = self.run_compile()
        self.assertIsNone(error)
        return self.first(report)

    def test_regular_summary_overcounts_empty_sources_refuse(self):
        for count in (1, 7):
            self.configure([], {sp.SECTOR: count})
            self.assert_refused([], {sp.SECTOR: count})

    def test_regular_summary_undercounts_actual_contributors_refuse(self):
        for rows, summary in ((1, 0), (2, 1)):
            files = [source_file(f'f{i}', f'S{i}', {sp.SECTOR: 5}) for i in range(rows)]
            self.configure(files, {sp.SECTOR: summary})
            self.assert_refused(files, {sp.SECTOR: summary})

    def test_regular_count_is_sector_local_and_not_substrate_subset(self):
        # Cells only in another sector, or zero cells here, support nothing here.
        files = [source_file('a', 'S1', {OTHER: 4}), source_file('b', 'S2', {sp.SECTOR: 0, OTHER: 3})]
        self.configure(files, {OTHER: 2})
        self.assertEqual(self.assert_compiles()['native_regular_depth_file_leads'], 0)
        self.configure(files, {OTHER: 2, sp.SECTOR: 1})
        self.assert_refused(files, {sp.SECTOR: 1})
        # A qualifying file outside the substrate-screen URL subset still counts.
        files = [source_file('c', 'S3', {sp.SECTOR: 6})]
        self.configure(files, {sp.SECTOR: 1})
        first = self.assert_compiles()
        self.assertEqual(first['native_regular_depth_file_leads'], 1)
        self.assertEqual(first['native_substrate_screen_files_with_eligible_sector_cells'], 0)

    def test_regular_file_identity_not_survey_identity(self):
        two = [source_file('a', 'S1', {sp.SECTOR: 2}), source_file('b', 'S1', {sp.SECTOR: 3})]
        self.configure(two, {sp.SECTOR: 1})
        self.assert_refused(two, {sp.SECTOR: 1})
        self.configure(two, {sp.SECTOR: 2})
        self.assertEqual(self.assert_compiles()['native_regular_depth_file_leads'], 2)
        both = [source_file('a', 'S1', {sp.SECTOR: 2, OTHER: 2})]
        self.configure(both, {sp.SECTOR: 1, OTHER: 1})
        report, error, _ = self.run_compile()
        self.assertIsNone(error)
        self.assertEqual([r['native_regular_depth_file_leads'] for r in report['sectors'][:2]], [1, 1])
        bad = [source_file('a', 'S1', {sp.SECTOR: 2}, status='failed')]
        self.configure(bad, {sp.SECTOR: 1})
        self.assert_refused(bad, {sp.SECTOR: 1})
        self.configure(bad, {})
        self.assertEqual(self.assert_compiles()['native_regular_depth_file_leads'], 0)
        duplicate = [source_file('a', 'S1', {sp.SECTOR: 2}), source_file('a', 'S1', {sp.SECTOR: 2})]
        self.configure(duplicate, {sp.SECTOR: 2})
        _, error, _ = self.run_compile()
        self.assertRegex(str(error), 'missing from original-cell audit')

    def test_consistent_inputs_preserve_report_and_other_gates(self):
        self.configure([], {})
        report, error, _ = self.run_compile()
        self.assertIsNone(error)
        zero = next(row for row in report['sectors'] if row['sector_id'] == OTHER)
        self.assertEqual(zero['native_regular_depth_file_leads'], 0)
        self.assertIn('sampled files yielded no eligible cells', zero['next_source_step'])
        self.configure([source_file('a', 'S1', {sp.SECTOR: 2})], {sp.SECTOR: 1})
        report, error, _ = self.run_compile()
        self.assertIsNone(error)
        self.assertEqual(len(report['sectors']), 19)
        first = self.first(report)
        self.assertTrue(first['next_source_step'].startswith('Find independent original substrate overlap'))
        for row in report['sectors']:
            self.assertEqual(row['status'], 'source-review-only')
            self.assertEqual(row['published_candidate_points_in_band'], 0)
            self.assertTrue(row['nbs_original_hard_footprint_screen']['research_only'])
        # Other input gates still refuse.
        self.configure([], {})
        self.inputs[VARIABLE]['sectors'][0]['source_files_with_eligible_cells'] = 1
        _, error, _ = self.run_compile()
        self.assertEqual(str(error), 'Variable-depth sector file count does not match source rows')
        self.inputs[VARIABLE]['sectors'][0]['source_files_with_eligible_cells'] = 0
        self.inputs[REGULAR]['sectors'].pop()
        _, error, _ = self.run_compile()
        self.assertRegex(str(error), 'missing or has duplicate sectors')


if __name__ == '__main__':
    unittest.main()
