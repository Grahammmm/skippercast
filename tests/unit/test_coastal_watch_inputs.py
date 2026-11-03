"""RF2330-1: an unusable previous snapshot or region report feed never stops the coastal watch."""
from contextlib import redirect_stderr
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from skippercast.pipeline import coastal_watch
from skippercast.platform.contracts import atomic_json

NOW = datetime(2026, 9, 22, 15, tzinfo=timezone.utc)
REAL_COLLECT = coastal_watch.collect
REPORT = {'date': '2026-09-21', 'coordinates': [-122.0, 36.5], 'source_url': 'https://example.org/r'}


class CoastalWatchInputTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.prev_root, self.report_root, self.out = self.tmp / 'prev', self.tmp / 'daily', self.tmp / 'out'
        self.priors, self.seen = [], []

        def fake_source(ident, name, kind, url, max_age, loader, now, previous, factory):
            self.priors.append(previous)
            return {'id': ident, 'status': 'failed', 'data': None}

        def fixed_collect(**kw):
            self.seen.append(kw)
            return REAL_COLLECT(now=NOW, **kw)
        for p in (patch.object(coastal_watch, 'source', side_effect=fake_source),
                  patch.object(coastal_watch, 'publication', return_value={'published_at': 'P', 'run_id': 'local'}),
                  patch.object(coastal_watch, 'collect', side_effect=fixed_collect)):
            p.start(); self.addCleanup(p.stop)

    def write(self, rel, raw):
        path = self.report_root / rel if rel.startswith('regions') else self.prev_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw if isinstance(raw, bytes) else json.dumps(raw).encode())

    def run_watch(self):
        err = io.StringIO()
        with redirect_stderr(err):
            data = coastal_watch.run(self.out, self.prev_root, self.report_root)
        self.assertTrue((self.out / 'coastal/latest.json').is_file())
        self.assertTrue((self.out / 'coastal/status.json').is_file())
        return data, err.getvalue().splitlines()

    def test_unusable_previous_is_ignored_with_one_line(self):
        for raw in (b'{"scope": "califo', b'\xff\xfe{}', b'{"a": 1, "a": 2}', b'{"a": NaN}', b'[]', b'"x"',
                    b'[' * 100000):
            with self.subTest(raw=raw[:20]):
                self.priors.clear()
                self.write('coastal/latest.json', raw)
                data, lines = self.run_watch()
                reason = 'not an object' if raw in (b'[]', b'"x"') else 'unreadable JSON'
                self.assertEqual(lines, [f'coastal-watch: previous snapshot ignored: {reason}'])
                self.assertIsNone(self.seen[-1]['previous'])
                self.assertTrue(self.priors and not any(self.priors))
                self.assertNotIn('skipped_report_feeds', data['health'])

    def test_previous_with_other_scope_is_silently_unused(self):
        self.write('coastal/latest.json', {'scope': 'elsewhere', 'sources': {'enso': {'data': {'k': 1}}}})
        _, lines = self.run_watch()
        self.assertEqual(lines, [])
        self.assertTrue(self.priors and not any(self.priors))
        self.priors.clear()
        self.write('coastal/latest.json', {'scope': 'california-coast-directory', 'sources': {'enso': {'data': {'k': 1}}}})
        _, lines = self.run_watch()
        self.assertEqual(lines, [])
        self.assertIn({'data': {'k': 1}}, self.priors)

    def test_bad_region_feeds_are_skipped_named_and_counted(self):
        self.write('regions/good/latest.json', {'region_id': 'good', 'reports': [REPORT, 'junk']})
        self.write('regions/trunc/latest.json', b'{"region_id": "trunc", "rep')
        self.write('regions/listy/latest.json', [REPORT])
        self.write('regions/stringy/latest.json', {'region_id': 'stringy', 'reports': 'abc'})
        self.write('regions/numbery/latest.json', {'reports': 5})
        self.write('regions/other/latest.json', {'region_id': 'not-other', 'reports': [REPORT]})
        self.write('regions/Bad..Name/latest.json', b'nope')
        data, lines = self.run_watch()
        self.assertEqual(sorted(lines), sorted([
            'coastal-watch: region feed skipped: trunc: unreadable JSON',
            'coastal-watch: region feed skipped: listy: not an object',
            'coastal-watch: region feed skipped: stringy: not an object',
            'coastal-watch: region feed skipped: numbery: not an object',
            'coastal-watch: region feed skipped: ?: unreadable JSON']))
        self.assertEqual(data['health']['skipped_report_feeds'], 5)
        self.assertEqual(self.seen[-1]['reports'], [REPORT, 'junk'])
        saved = json.loads((self.out / 'coastal/latest.json').read_text())
        self.assertEqual(saved['health']['skipped_report_feeds'], 5)
        self.assertEqual(json.loads((self.out / 'coastal/status.json').read_text())['health'], saved['health'])

    def test_unsafe_folder_names_print_as_question_mark(self):
        for name in ('a\nb', 'UPPER', 'x' * 70, '-lead', 'a b'):
            with self.subTest(name=name):
                self.report_root = Path(tempfile.mkdtemp(dir=self.tmp))
                self.write(f'regions/{name}/latest.json', b'[1]')
                _, lines = self.run_watch()
                self.assertEqual(lines, ['coastal-watch: region feed skipped: ?: not an object'])

    def test_clean_inputs_give_identical_output(self):
        previous = {'scope': 'california-coast-directory', 'sources': {'enso': {'data': {'k': 1}}}}
        self.write('coastal/latest.json', previous)
        self.write('regions/central/latest.json', {'region_id': 'central', 'reports': [REPORT]})
        self.write('regions/north/latest.json', {'region_id': 'north'})
        data, lines = self.run_watch()
        self.assertEqual(lines, [])
        self.assertNotIn('skipped_report_feeds', data['health'])
        atomic_json(self.tmp / 'expected.json', REAL_COLLECT(now=NOW, previous=previous, reports=[REPORT]))
        self.assertEqual((self.out / 'coastal/latest.json').read_bytes(), (self.tmp / 'expected.json').read_bytes())
