"""RF0310-12: source-issue text cannot start a workflow command or break a Markdown list line."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import report_conditions
from scripts.report_conditions import annotation

INJECTED = 'buoy 46011: HTTP 503\n::error::fake'
PREFIX = '::warning title=Degraded source::'


def run_main(region_issues, health_issues=(), gaps=()):
    """Run main() on four valid products; return (stdout lines, summary text)."""
    latest = {'completed_at': '2026-11-02T04:00Z', 'health': {'issues': list(health_issues)},
              'sources': {'b1': {'name': 'Buoy 46011', 'status': 'ok'}}}
    index = {'regions': [{'region_id': 'morro-bay', 'status': 'degraded', 'issues': list(region_issues),
                          'coverage_gaps': list(gaps)}]}
    empty = {'regions': []}
    products = {'latest.json': latest, 'regions/index.json': index, 'intelligence-health.json': empty,
                'habitat-health.json': empty}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / 'out'
        (root / 'regions').mkdir(parents=True)
        for name, data in products.items():
            (root / name).write_text(json.dumps(data), encoding='utf-8')
        summary = Path(directory) / 'summary.md'
        argv = ['report_conditions.py', '--output', str(root), '--outcome', 'success']
        with mock.patch('sys.argv', argv), mock.patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            report_conditions.main()
        return out.getvalue().splitlines(), summary.read_text(encoding='utf-8')


class AnnotationTests(unittest.TestCase):
    def test_injected_newline_stays_inside_one_warning_line(self):
        out, _ = run_main([INJECTED])
        self.assertEqual(out, [PREFIX + 'buoy 46011: HTTP 503%0A::error::fake', 'Published; 1 degraded source(s).'])
        self.assertEqual([line for line in out if line.startswith('::warning')], [out[0]])
        self.assertFalse([line for line in out if line.startswith('::error')])

    def test_percent_cr_and_lf_use_the_data_encoding(self):
        self.assertEqual(annotation('50% missing\r\n'), '50%25 missing%0D%0A')
        self.assertEqual(annotation('a\rb'), 'a%0Db')
        # Text that is already encoded cannot decode back into a line break.
        self.assertEqual(annotation('x%0A::error::y'), 'x%250A::error::y')
        self.assertEqual(annotation('plain issue'), 'plain issue')

    def test_long_issue_is_cut_to_300_characters_before_escaping(self):
        self.assertEqual(annotation('a' * 1000), 'a' * 300 + '…')
        self.assertEqual(len(annotation('a' * 1000)), 301)
        self.assertEqual(annotation('a' * 300), 'a' * 300)
        self.assertEqual(annotation('a' * 299 + '%\n' + 'b' * 50), 'a' * 299 + '%25…')
        # A line break after the cut is dropped, never printed.
        self.assertEqual(annotation('a' * 300 + '\n::error::late'), 'a' * 300 + '…')

    def test_long_issue_in_main_prints_one_capped_line(self):
        out, _ = run_main(['z' * 1000 + '\n::error::x'])
        self.assertEqual(out, [PREFIX + 'z' * 300 + '…', 'Published; 1 degraded source(s).'])

    def test_summary_keeps_each_issue_and_gap_on_one_markdown_line(self):
        _, summary = run_main([INJECTED, 'a\r\n\tb'], gaps=['day-6\nday-7'])
        lines = summary.splitlines()
        self.assertIn('  - Source issue: buoy 46011: HTTP 503 ::error::fake', lines)
        self.assertIn('  - Source issue: a b', lines)
        self.assertIn('  - Coverage gap: day-6 day-7', lines)
        self.assertFalse([line for line in lines if line.startswith('::')])
        self.assertIn('- morro-bay: degraded', lines)

    def test_published_count_is_the_number_of_distinct_issues(self):
        out, summary = run_main([INJECTED, INJECTED, 'sst-analysis'], health_issues=['sst-analysis', 'buoy-spectrum'])
        self.assertEqual(out[-1], 'Published; 3 degraded source(s).')
        self.assertEqual(len([line for line in out if line.startswith(PREFIX)]), 3)
        self.assertIn('\n5 source(s) degraded this cycle;', summary)

    def test_non_string_issue_is_printed_as_text(self):
        self.assertEqual(annotation(7), '7')
        out, summary = run_main([7, '7'])
        self.assertEqual(out, [PREFIX + '7', 'Published; 1 degraded source(s).'])
        self.assertEqual(summary.splitlines().count('  - Source issue: 7'), 2)


if __name__ == '__main__':
    unittest.main()
