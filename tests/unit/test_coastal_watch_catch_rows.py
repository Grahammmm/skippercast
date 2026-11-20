"""RF1940-2: a malformed catch row is skipped alone and never hides later valid catches."""
import copy
from datetime import datetime, timezone
import io
import json
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from skippercast.pipeline import coastal_watch
from skippercast.pipeline.coastal_watch import located_reports

NOW = datetime(2026, 9, 22, 15, tzinfo=timezone.utc)
REAL_COLLECT = coastal_watch.collect
COAST = {'bounds': [-125, 30, -115, 40], 'watch': ['yellowfin', 'bluefin']}
POLICY = {'report_max_age_days': 14, 'minimum_independent_sources': 2, 'minimum_report_dates': 2}
GOOD = {'species': 'yellowfin', 'count': 5}
BAD_ROWS = (None, 7, 'yellowfin', True, [GOOD], {}, {'count': 5}, {'species': None, 'count': 5},
            {'species': 5, 'count': 5}, {'species': ['yellowfin'], 'count': 5})


def rep(day, pub, *catches):
    return {'date': day, 'coordinates': [-121.4, 35.6], 'coordinate_role': 'fishing-observation',
            'location_review': 'reviewed', 'original_publisher_id': pub, 'publisher_review': 'reviewed',
            'source_url': f'https://{pub}.example/r', 'catches': list(catches)}


def target(rows, ident='yellowfin'):
    return next(w for w in located_reports(COAST, rows, NOW, POLICY) if w['target'] == ident)


class CatchRowIsolationTests(TestCase):
    def test_bad_catch_before_good_does_not_lose_publisher(self):
        control = target([rep('2026-09-21', 'one', GOOD), rep('2026-09-20', 'two', GOOD)])
        self.assertEqual(control['status'], 'recent-located-reports')
        for bad in (None, {'count': 5}):
            with self.subTest(bad=bad):
                for order in ((bad, GOOD), (GOOD, bad)):
                    rows = [rep('2026-09-21', 'one', GOOD), rep('2026-09-20', 'two', *order)]
                    before = copy.deepcopy(rows)
                    self.assertEqual(target(rows), control)
                    self.assertEqual(rows, before)

    def test_catch_shape_matrix_is_locally_isolated(self):
        other = {'species': 'bluefin', 'count': 2}
        for bad in BAD_ROWS:
            with self.subTest(bad=bad):
                rows = [rep('2026-09-21', 'one', bad, GOOD, other), rep('2026-09-20', 'two', bad, GOOD, bad, other)]
                self.assertEqual(target(rows)['status'], 'recent-located-reports')
                self.assertEqual(target(rows, 'bluefin')['status'], 'recent-located-reports')
        # the positive-count policy still applies to well-formed rows
        rows = [rep('2026-09-21', 'one', GOOD), rep('2026-09-20', 'two', None, {'species': 'yellowfin', 'count': True})]
        self.assertEqual(target(rows)['status'], 'watch-only')

    def test_invalid_only_catches_cannot_complete_quorum(self):
        for catches in ((None, {'count': 5}, 'x'), ()):
            with self.subTest(catches=catches):
                got = target([rep('2026-09-21', 'one', GOOD), rep('2026-09-20', 'two', *catches)])
                self.assertEqual(got['status'], 'watch-only')
                self.assertEqual([e['publisher'] for e in got['evidence']], ['one'])

    def test_healthy_catch_control_is_identical(self):
        rows = [rep('2026-09-21', 'one', GOOD), rep('2026-09-20', 'two', GOOD)]
        got = target(rows)
        self.assertEqual([e['publisher'] for e in got['evidence']], ['one', 'two'])
        self.assertIsNone(got['catch_probability'])
        self.assertIs(got['auto_add_to_qualified_map'], False)
        missing = rep('2026-09-20', 'two')
        del missing['catches']
        self.assertEqual(target([rows[0], missing])['status'], 'watch-only')

    def test_real_run_retains_valid_catches_in_both_projections(self):
        tmp = Path(tempfile.mkdtemp())
        feed = tmp / 'daily/regions/central/latest.json'
        feed.parent.mkdir(parents=True)
        feed.write_text(json.dumps({'region_id': 'central', 'reports': [
            rep('2026-09-21', 'one', GOOD), rep('2026-09-20', 'two', None, {'count': 1}, GOOD)]}))
        patches = (patch.object(coastal_watch, 'source', return_value={'id': 'x', 'status': 'failed', 'data': None}),
                   patch.object(coastal_watch, 'publication', return_value={'published_at': 'P', 'run_id': 'local'}),
                   patch.object(coastal_watch, 'collect', side_effect=lambda **kw: REAL_COLLECT(now=NOW, **kw)))
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        with redirect_stderr(io.StringIO()) as err:
            data = coastal_watch.run(tmp / 'out', tmp / 'prev', tmp / 'daily')
        self.assertEqual(err.getvalue(), '')
        self.assertNotIn('skipped_report_feeds', data['health'])
        for name in ('latest', 'status'):
            watch = json.loads((tmp / f'out/coastal/{name}.json').read_text())['regions']['central']['watch']
            got = next(w for w in watch if w['target'] == 'yellowfin')
            self.assertEqual(got['status'], 'recent-located-reports')
            self.assertEqual([e['publisher'] for e in got['evidence']], ['one', 'two'])
            self.assertIsNone(got['catch_probability'])
            self.assertIs(got['auto_add_to_qualified_map'], False)
