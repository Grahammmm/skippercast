"""Landing-report ports come from configuration and parse exactly as the hard-coded version did."""
import json
import unittest
from unittest.mock import patch

from skippercast import validate
from skippercast.pipeline import collect as daily, parsers
from skippercast.pipeline.settings import region_report_ports, settings
from skippercast.platform.contracts import REPO, ContractError, load_catalogs
from tests._support import FIXTURES, NOW

FIXTURE = FIXTURES / 'charter-reports'
URL = 'https://www.socalfishreports.com/dock_totals/boats.php?date=2026-09-20'


class CharterPortTests(unittest.TestCase):
    def test_configured_ports_equal_the_previous_constants(self):
        # Previously hard-coded in parsers.charter_reports: these labels, this order, these names.
        self.assertEqual(list(settings('morro-bay')['report_ports'].items()),
                         [('Morro Bay, CA', 'Morro Bay'), ('Avila Beach, CA', 'Avila Beach')])

    def test_every_region_reads_only_its_own_landing_ports(self):
        # A region reads only the publisher ports that are its own landings, so a
        # non-Morro coast never carries Morro Bay/Avila trips (formerly P2-08).
        ports = load_catalogs()[1]['landing-reports']['report_ports']
        seen = {}
        for path in sorted((REPO / 'regions').glob('*/region.json')):
            with self.subTest(region=path.parent.name):
                region = json.loads(path.read_text())
                rules = json.loads((REPO / 'dist' / region['assets']['regulations']).read_text())
                if region['status'] == 'draft' and region['id'] not in {r['id'] for r in rules['reviewed_regions']}:
                    # A draft footprint outside its jurisdiction's legal review is never collected.
                    with self.assertRaisesRegex(ValueError, 'need a regulatory review'):
                        settings(path.parent.name)
                    continue
                own = settings(path.parent.name)['report_ports']
                self.assertEqual(own, region_report_ports(ports, region['landing_names']))
                seen[region['id']] = own
        self.assertEqual(seen.pop('morro-bay'), ports)
        for region in ('big-sur-coast', 'crescent-city', 'monterey-point-sur', 'santa-cruz-monterey-bay'):
            self.assertIn(region, seen)
        self.assertEqual({r: p for r, p in seen.items() if p}, {})

    def test_region_ports_match_whole_landing_words_in_publisher_order(self):
        ports = {'Morro Bay, CA': 'Morro Bay', 'Avila Beach, CA': 'Avila Beach', 'Crescent City, CA': 'Crescent City'}
        self.assertEqual(list(region_report_ports(ports, ['Avila', 'Morro Bay']).items()),
                         [('Morro Bay, CA', 'Morro Bay'), ('Avila Beach, CA', 'Avila Beach')])
        self.assertEqual(region_report_ports(ports, ['Crescent City']), {'Crescent City, CA': 'Crescent City'})
        self.assertEqual(region_report_ports(ports, ['Avil', 'Morro Bay Estuary', 'City', 'Bay']), {})
        self.assertEqual(region_report_ports(ports, []), {})

    def collect_offline(self, region_id, catches_ok):
        # Every network read is stubbed (grid loaders too, so the no-GIS lane never imports
        # scipy); only the port filtering and the charter jobs run for real.
        requested = []
        def read(ident, name, kind, url, *args, **kwargs):
            requested.append(ident)
            if catches_ok and ident.startswith('catches-'):
                return {'id': ident, 'name': name, 'kind': kind, 'url': url, 'status': 'ok',
                        'data': {'reports': []}, 'data_retrieved_at': '2026-09-28T12:00:00Z'}
            return {'id': ident, 'name': name, 'kind': kind, 'url': url, 'status': 'failed', 'data': None}
        with patch.object(daily, 'source', side_effect=read), patch.object(daily, 'grid_loader', return_value=None), \
             patch.object(daily, 'regulatory_snapshot', return_value={}):
            feed = daily.collect(NOW, days=7, region_id=region_id)
        return feed, [i for i in requested if i.startswith('catches-')]

    def test_region_without_own_landing_says_it_has_no_coverage(self):
        # Big Sur has landing names but no publisher port of its own: no dock-total page is
        # requested, no trips, no stale flag, and the feed says plainly that it covers no port.
        for catches_ok in (True, False):
            with self.subTest(catches_ok=catches_ok):
                feed, catches = self.collect_offline('big-sur-coast', catches_ok)
                self.assertEqual(catches, [])
                self.assertEqual((feed['reports'], feed['report_ports']), ([], []))
                self.assertNotIn('charter_reports', feed)
                self.assertNotIn('degraded_reasons', feed['health'])

    def test_covered_port_with_no_trips_stays_distinct_from_no_coverage(self):
        # Morro Bay's pages were all read and simply held no trips: same empty reports,
        # but the feed names its covered ports, so readers can say "no trips reported".
        feed, catches = self.collect_offline('morro-bay', catches_ok=True)
        self.assertEqual(len(catches), 7)
        self.assertEqual(feed['reports'], [])
        self.assertEqual(feed['report_ports'], ['Morro Bay', 'Avila Beach'])
        self.assertNotIn('charter_reports', feed)
        # Pages that failed are still the stale flag, not "no coverage".
        stale, _ = self.collect_offline('morro-bay', catches_ok=False)
        self.assertEqual(stale['report_ports'], ['Morro Bay', 'Avila Beach'])
        self.assertEqual(stale['charter_reports']['reason'], 'source_stale')

    def test_feed_without_coverage_cannot_carry_trips(self):
        feed, _ = self.collect_offline('big-sur-coast', catches_ok=False)
        daily.validate(feed)
        # The writer checks the published schema before writing: a real feed with either
        # coverage value must still pass it (the offline stubs above are not full feeds).
        sample = json.loads((FIXTURES / 'feeds' / 'daily-latest.json').read_text())
        for ports in ([], ['Morro Bay', 'Avila Beach']):
            validate.check('daily-feed', {**sample, 'report_ports': ports, **({} if ports else {'reports': []})})
        with self.assertRaises(ContractError):
            validate.check('daily-feed', {**sample, 'report_ports': ['Morro Bay', '']})
        with self.assertRaisesRegex(ValueError, 'without landing-report coverage'):
            daily.validate({**feed, 'reports': [{'id': 'x', 'date': '2026-09-27'}]})
        with self.assertRaisesRegex(ValueError, 'list of port names'):
            daily.validate({**feed, 'report_ports': 'Morro Bay'})
        legacy = {k: v for k, v in feed.items() if k != 'report_ports'}
        daily.validate(legacy)   # feeds written before report_ports still validate

    def test_output_matches_the_hard_coded_parser_byte_for_byte(self):
        # Expected output was produced by the pre-change parser from the same page: other
        # landings skipped, a row naming both landings takes Morro Bay, duplicates dropped.
        page = (FIXTURE / 'dock-totals-2026-09-20.html').read_text()
        expected = json.loads((FIXTURE / 'dock-totals-2026-09-20.expected.json').read_text())
        result = parsers.charter_reports(page, '2026-09-20', URL, ports=settings('morro-bay')['report_ports'])
        self.assertEqual(json.loads(json.dumps(result)), expected)
        self.assertEqual([(r['boat'], r['port']) for r in result['reports']],
                         [('Example Boat', 'Morro Bay'), ('Other Boat', 'Avila Beach'),
                          ('Twin Port Boat', 'Morro Bay'), ('Example Boat', 'Morro Bay')])

    def test_ports_are_parameters_not_constants(self):
        page = (FIXTURE / 'dock-totals-2026-09-20.html').read_text()
        rows = parsers.charter_reports(page, '2026-09-20', URL, ports={'Crescent City, CA': 'Crescent City'})['reports']
        self.assertEqual([(r['boat'], r['port']) for r in rows], [('North Boat', 'Crescent City')])
        with self.assertRaises(ValueError):
            parsers.charter_reports(page, '2026-09-20', URL, ports={})
        self.assertNotIn('Morro Bay, CA', (REPO / 'src/skippercast/pipeline/parsers.py').read_text())


class RegionDefaultTests(unittest.TestCase):
    def test_build_uses_the_single_default_constant(self):
        from skippercast.platform.contracts import DEFAULT_REGION
        index = json.loads((REPO / 'dist/regions/index.json').read_text())
        self.assertEqual(index['default_region'], DEFAULT_REGION)
        self.assertEqual((REPO / 'dist/region-default.js').read_text().split('\n', 1)[0],
                         f'// Generated by skippercast.platform.build; edit regions/{DEFAULT_REGION}/region.json.')
        self.assertNotIn('"morro-bay"', (REPO / 'src/skippercast/platform/build.py').read_text())

    def test_dead_buoy_constant_is_gone(self):
        from skippercast.pipeline import live
        self.assertFalse(hasattr(live, 'BUOYS'))


if __name__ == '__main__':
    unittest.main()
