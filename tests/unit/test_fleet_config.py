"""skippercast.fleet.config: load_region, its cross-reference checks and the geometry helpers.

Each test builds a throwaway repository root with the real fleet catalogs and
home ports and a small synthetic state region ``ZZ`` (two drawn ports, one
landing), then breaks one rule and expects FleetConfigError to name it.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from skippercast import validate
from skippercast.fleet import config
from skippercast.fleet.config import FleetConfigError, load_region
from tests._support import ROOT

NEEDS_JSONSCHEMA = 'jsonschema not installed (pip install -r requirements-test.txt); the survey-science CI job runs these'


def box(west, south, east, north):
    return {'type': 'Polygon', 'coordinates': [[[west, south], [east, south], [east, north], [west, north], [west, south]]]}


BASE = {
    'schema_version': 1, 'id': 'ZZ', 'name': 'Example State', 'timezone': 'America/Los_Angeles', 'status': 'dry-run',
    'ports': [
        {'id': 'north-harbor', 'name': 'North Harbor', 'point': [35.37, -120.86], 'home_port': 'morro-bay',
         'region': 'morro-bay', 'waters': ['ocean', 'bay'], 'geofence': box(-120.88, 35.35, -120.84, 35.39),
         'geofence_source': 'drawn'},
        {'id': 'south-cove', 'name': 'South Cove', 'point': [35.17, -120.75], 'home_port': None, 'region': None,
         'waters': ['ocean'], 'geofence': box(-120.77, 35.16, -120.73, 35.18), 'geofence_source': 'drawn'},
    ],
    'landings': [{'id': 'example-landing', 'name': 'Example Landing', 'port': 'north-harbor',
                  'point': [35.372, -120.858], 'website': 'https://landing.example/'}],
    'ais': {'source': 'aisstream', 'bbox': [[34.0, -122.0], [36.0, -119.0]],
            'message_types': ['PositionReport', 'ShipStaticData'], 'mmsi_filter': False},
    'agencies': [{'id': 'licensing-agency', 'name': 'Example licensing agency', 'kind': 'licensing',
                  'notes': 'synthetic', 'records_request_url': None}],
    'sources': [
        {'id': 'registry', 'adapter': 'fcc-uls', 'enabled': True, 'rights': 'public-domain', 'params': {'state': 'ZZ'}},
        {'id': 'example-landing', 'adapter': 'landing-pages', 'enabled': True, 'rights': 'facts-only',
         'params': {'landing': 'example-landing', 'template': 'generic', 'url': 'https://landing.example/fleet'}},
    ],
    'thresholds': {
        'activity': {'in_port_debounce_min': 3, 'min_trip_minutes': 20, 'min_trip_offshore_nm': 0.5,
                     'gap_unknown_min': 30, 'gap_split_hours': 12,
                     'max_open_trip_hours': {'six-pack': 18, 'inspected-party': 40, 'long-range': 480},
                     'window_min': 20, 'min_segment_minutes': 5, 'simplify_tolerance_m': 25,
                     'drift': {'max_sog_kn': 2.0, 'min_minutes': 15},
                     'troll': {'min_sog_kn': 4.0, 'max_sog_kn': 9.0, 'max_straightness': 0.6,
                               'min_heading_variance': 0.35, 'min_minutes': 15}},
        'match': {'auto_merge': 0.9, 'review_min': 0.6, 'mmsi_auto': 0.85},
        'refresh': {'vanished_after_runs': 3, 'vanished_after_days': 45, 'osint_stale_days': 60, 'fact_stale_days': 120},
        'retention': {'raw_days': 30, 'discovery_days': 7, 'static_days': 90},
        'aggregate': {'module': 'grid', 'resolution_m': 1000, 'min_distinct_vessels': None, 'delay_hours': None},
    },
    'seasons': {'parts': [{'id': 'cool', 'months': [11, 12, 1, 2, 3, 4]}, {'id': 'warm', 'months': [5, 6, 7, 8, 9, 10]}]},
    'resolver_overrides': {'mmsi': {'priority': ['admin', 'ais-static', 'fcc-uls']}},
}


@unittest.skipUnless(validate.available(), NEEDS_JSONSCHEMA)
class LoadRegion(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        shutil.copytree(ROOT / 'catalog/fleet', self.root / 'catalog/fleet')
        shutil.copy(ROOT / 'catalog/home-ports.json', self.root / 'catalog/home-ports.json')
        (self.root / 'regions/morro-bay').mkdir(parents=True)
        shutil.copy(ROOT / 'regions/morro-bay/region.json', self.root / 'regions/morro-bay/region.json')

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, doc, ident='ZZ'):
        (self.root / 'regions' / ident).mkdir(parents=True, exist_ok=True)
        (self.root / 'regions' / ident / 'fleet.json').write_text(json.dumps(doc))

    def problems(self, mutate, ident='ZZ'):
        doc = deepcopy(BASE)
        mutate(doc)
        self.write(doc, ident)
        with self.assertRaises(FleetConfigError) as caught:
            load_region(ident, self.root)
        return ' | '.join(caught.exception.problems)

    def test_valid_region_returns_typed_frozen_objects(self):
        self.write(BASE)
        region = load_region('ZZ', self.root)
        self.assertEqual(region.id, 'ZZ')
        self.assertEqual([p.id for p in region.ports], ['north-harbor', 'south-cove'])
        self.assertTrue(region.port('north-harbor').contains(35.372, -120.858))
        self.assertFalse(region.port('south-cove').contains(35.372, -120.858))
        self.assertEqual(region.ais.south, 34.0)
        self.assertEqual(region.binding('example-landing').params['landing'], 'example-landing')
        self.assertEqual(region.resolver['mmsi'].priority, ('admin', 'ais-static', 'fcc-uls'))
        self.assertEqual(region.resolver['mmsi'].min_confidence, 0.7)  # catalog value kept where not overridden
        self.assertEqual(region.seasons['warm'], (5, 6, 7, 8, 9, 10))
        self.assertAlmostEqual(sum(region.lead_score.values()), 1.0)
        self.assertTrue(region.is_off_limits('https://www.fishingbooker.com/charters/x'))
        self.assertFalse(region.is_off_limits('https://landing.example/'))
        with self.assertRaises(TypeError):
            region.thresholds['match']['auto_merge'] = 0.1
        self.assertEqual(config.region_ids(self.root), ['ZZ'])

    def test_missing_geofence(self):
        self.assertIn("'geofence' is a required property", self.problems(lambda d: d['ports'][0].pop('geofence')))

    def test_unknown_adapter(self):
        def mutate(doc):
            doc['sources'][0]['adapter'] = 'fishing-marketplace'
        self.assertIn("adapter 'fishing-marketplace' is not registered", self.problems(mutate))

    def test_off_limits_host_in_a_binding_including_subdomains(self):
        for url in ('https://fishingbooker.com/destinations', 'https://www.instagram.com/example',
                    'https://book.fareharbor.com/embeds/x'):
            with self.subTest(url=url):
                def mutate(doc, url=url):
                    doc['sources'][1]['params']['url'] = url
                self.assertIn('off-limits host', self.problems(mutate))

    def test_off_limits_host_as_a_landing_website(self):
        def mutate(doc):
            doc['landings'][0]['website'] = 'https://m.facebook.com/example'
        self.assertIn('off-limits host facebook.com', self.problems(mutate))

    def test_binding_urls_must_be_https(self):
        def mutate(doc):
            doc['sources'][1]['params']['url'] = 'http://landing.example/fleet'
        self.assertIn('is not https', self.problems(mutate))

    def test_geofence_must_contain_its_port(self):
        def mutate(doc):
            doc['ports'][0]['geofence'] = box(-121.0, 35.0, -120.95, 35.05)
        self.assertIn('geofence does not contain the port point', self.problems(mutate))

    def test_geofence_must_be_simple_and_closed(self):
        bowtie = {'type': 'Polygon', 'coordinates': [[[-120.88, 35.35], [-120.84, 35.39], [-120.84, 35.35],
                                                      [-120.88, 35.39], [-120.88, 35.35]]]}
        open_ring = {'type': 'Polygon', 'coordinates': [[[-120.88, 35.35], [-120.84, 35.35], [-120.84, 35.39],
                                                         [-120.88, 35.39]]]}
        for fence in (bowtie, open_ring):
            with self.subTest(fence=fence):
                def mutate(doc, fence=fence):
                    doc['ports'][0]['geofence'] = fence
                self.assertIn('not a closed simple polygon', self.problems(mutate))

    def test_landing_outside_its_port_geofence(self):
        def mutate(doc):
            doc['landings'][0]['point'] = [35.17, -120.75]
        self.assertIn("outside the geofence of port 'north-harbor'", self.problems(mutate))

    def test_port_inside_another_ports_geofence(self):
        def mutate(doc):
            doc['ports'][1]['geofence'] = box(-120.90, 35.15, -120.70, 35.40)
        self.assertIn("inside the geofence of port 'south-cove'", self.problems(mutate))

    def test_unknown_home_port_and_region(self):
        def mutate(doc):
            doc['ports'][1]['home_port'] = 'atlantis'
            doc['ports'][1]['region'] = 'atlantis-coast'
        found = self.problems(mutate)
        self.assertIn("home_port 'atlantis' is not in catalog/home-ports.json", found)
        self.assertIn("region 'atlantis-coast' has no regions/<id>/region.json", found)

    def test_port_outside_its_coastal_region(self):
        def mutate(doc):
            doc['ports'][1]['region'] = 'morro-bay'
            doc['ports'][1]['point'] = [34.5, -120.75]
            doc['ports'][1]['geofence'] = box(-120.77, 34.49, -120.73, 34.51)
        self.assertIn("outside the bounds of region 'morro-bay'", self.problems(mutate))

    def test_ais_bbox_must_contain_every_port(self):
        def mutate(doc):
            doc['ais']['bbox'] = [[35.3, -122.0], [36.0, -119.0]]
        self.assertIn('ports/south-cove: point lies outside ais.bbox', self.problems(mutate))

    def test_seasons_cover_each_month_once(self):
        def mutate(doc):
            doc['seasons']['parts'][1]['months'] = [5, 6, 7]
        self.assertIn('months must cover 1-12 exactly once', self.problems(mutate))

    def test_threshold_ordering(self):
        def mutate(doc):
            doc['thresholds']['match']['review_min'] = 0.95
            doc['thresholds']['activity']['drift']['max_sog_kn'] = 5.0
        found = self.problems(mutate)
        self.assertIn('review_min is above auto_merge', found)
        self.assertIn('drift max_sog_kn must be below troll min_sog_kn', found)

    def test_resolver_override_must_name_a_catalog_field_and_known_sources(self):
        def mutate(doc):
            doc['resolver_overrides'] = {'favourite_colour': {'min_confidence': 0.5},
                                         'mmsi': {'priority': ['admin', 'scraper']}}
        found = self.problems(mutate)
        self.assertIn('resolver_overrides/favourite_colour: not a field', found)
        self.assertIn("unknown source kind(s) ['scraper']", found)

    def test_landing_binding_must_reference_a_landing(self):
        def mutate(doc):
            doc['sources'][1]['params']['landing'] = 'missing-landing'
        self.assertIn("params.landing 'missing-landing' is not a landing id", self.problems(mutate))

    def test_duplicate_ids(self):
        self.assertIn("ports: duplicate id 'north-harbor'",
                      self.problems(lambda d: d['ports'].append(deepcopy(d['ports'][0]))))

    def test_lower_case_and_unknown_ids_are_rejected(self):
        with self.assertRaises(FleetConfigError):
            load_region('morro-bay', self.root)
        with self.assertRaises(FleetConfigError) as caught:
            load_region('QQ', self.root)
        self.assertIn('file not found', caught.exception.problems)

    def test_id_must_match_directory(self):
        self.write(BASE, 'YY')
        with self.assertRaises(FleetConfigError) as caught:
            load_region('YY', self.root)
        self.assertIn("id 'ZZ' does not match its directory", caught.exception.problems)

    def test_catalog_errors_name_the_catalog(self):
        path = self.root / 'catalog/fleet/lead-score.json'
        lead = json.loads(path.read_text())
        lead['weights']['ais_seen_30d'] = 0.5
        path.write_text(json.dumps(lead))
        self.write(BASE)
        with self.assertRaises(FleetConfigError) as caught:
            load_region('ZZ', self.root)
        self.assertEqual(caught.exception.source, 'catalog/fleet/lead-score.json')

    def test_resolver_catalog_rejects_unknown_source_kinds(self):
        path = self.root / 'catalog/fleet/resolver.json'
        resolver = json.loads(path.read_text())
        resolver['fields']['mmsi']['priority'].append('marketplace')
        path.write_text(json.dumps(resolver))
        self.write(BASE)
        with self.assertRaises(FleetConfigError) as caught:
            load_region('ZZ', self.root)
        self.assertEqual(caught.exception.source, 'catalog/fleet/resolver.json')

    def test_check_document_reports_without_raising(self):
        doc = deepcopy(BASE)
        doc['sources'][0]['adapter'] = 'nope'
        self.assertTrue(any('not registered' in p for p in config.check_document(doc, self.root)))
        self.assertEqual(config.check_document(deepcopy(BASE), self.root), [])


class Geometry(unittest.TestCase):
    SQUARE = [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]

    def test_point_in_polygon(self):
        self.assertTrue(config.point_in_polygon(1, 1, self.SQUARE))
        self.assertFalse(config.point_in_polygon(3, 1, self.SQUARE))
        concave = [(0, 0), (4, 0), (4, 4), (2, 1), (0, 4), (0, 0)]
        self.assertFalse(config.point_in_polygon(2, 3, concave))
        self.assertTrue(config.point_in_polygon(1, 1, concave))

    def test_ring_is_simple(self):
        self.assertTrue(config.ring_is_simple(self.SQUARE))
        self.assertFalse(config.ring_is_simple([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)]))  # bow tie
        self.assertFalse(config.ring_is_simple([(0, 0), (2, 0), (2, 2), (0, 2)]))          # not closed
        self.assertFalse(config.ring_is_simple([(0, 0), (1, 0), (2, 0), (0, 0)]))          # zero area
        self.assertFalse(config.ring_is_simple([(0, 0), (2, 0), (0, 0), (0, 2), (0, 0)]))  # repeated vertex

    def test_off_limits_host_matches_host_and_subdomains_only(self):
        hosts = ['fishingbooker.com', 'fb.com']
        self.assertEqual(config.off_limits_host('https://fishingbooker.com/x', hosts), 'fishingbooker.com')
        self.assertEqual(config.off_limits_host('https://WWW.FishingBooker.com./x', hosts), 'fishingbooker.com')
        self.assertIsNone(config.off_limits_host('https://notfishingbooker.com/x', hosts))
        self.assertIsNone(config.off_limits_host('https://fb.com.example/x', hosts))
        self.assertIsNone(config.off_limits_host('not a url', hosts))


if __name__ == '__main__':
    unittest.main()
