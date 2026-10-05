"""Every committed charter fleet region (regions/<STATE>/fleet.json) meets design section 3.

The rules listed at the end of design section 3 are each asserted here against
the committed files, independently of the loader, and then the loader itself
must accept every region. The fleet package must stay state-agnostic, and the
state-level directories must stay invisible to the coastal-region enumeration
(regions/*/region.json) used by the platform build and the region contract.
"""
import json
import re
import unittest

from skippercast import validate
from skippercast.fleet import config
from tests._support import ROOT

NEEDS_JSONSCHEMA = 'jsonschema not installed (pip install -r requirements-test.txt); the survey-science CI job runs these'
FLEET_FILES = sorted((ROOT / 'regions').glob('*/fleet.json'))


def load(path):
    return json.loads(path.read_text())


def off_limits():
    return [row['host'] for row in load(ROOT / 'catalog/fleet/off-limits.json')['hosts']]


class FleetRegionFiles(unittest.TestCase):
    def test_at_least_one_fleet_region_and_only_in_state_directories(self):
        self.assertTrue(FLEET_FILES)
        for path in FLEET_FILES:
            self.assertRegex(path.parent.name, r'^[A-Z]{2}$', path)
            self.assertEqual(load(path)['id'], path.parent.name)
        self.assertEqual(config.region_ids(ROOT), [p.parent.name for p in FLEET_FILES])

    @unittest.skipUnless(validate.available(), NEEDS_JSONSCHEMA)
    def test_schema_valid(self):
        for path in FLEET_FILES:
            self.assertEqual(validate.errors('fleet-region', load(path)), [], path)

    def test_geofences_are_closed_simple_polygons_holding_port_and_landing_points(self):
        for path in FLEET_FILES:
            doc = load(path)
            rings = {}
            for port in doc['ports']:
                ring = [tuple(p) for p in port['geofence']['coordinates'][0]]
                self.assertEqual(ring[0], ring[-1], port['id'])
                self.assertTrue(config.ring_is_simple(ring), port['id'])
                lat, lon = port['point']
                self.assertTrue(config.point_in_polygon(lon, lat, ring), f"{port['id']} point outside its geofence")
                self.assertIn(port['geofence_source'], {'drawn', 'chart'})
                rings[port['id']] = ring
            for landing in doc['landings']:
                lat, lon = landing['point']
                self.assertIn(landing['port'], rings, landing['id'])
                self.assertTrue(config.point_in_polygon(lon, lat, rings[landing['port']]),
                                f"{landing['id']} outside the geofence of {landing['port']}")
            for port in doc['ports']:
                lat, lon = port['point']
                inside = [other for other, ring in rings.items()
                          if other != port['id'] and config.point_in_polygon(lon, lat, ring)]
                self.assertEqual(inside, [], f"{port['id']} lies in another port's geofence")

    def test_home_port_and_region_ids_exist(self):
        home_ports = {row['id'] for row in load(ROOT / 'catalog/home-ports.json')['ports']}
        coastal = {p.parent.name for p in (ROOT / 'regions').glob('*/region.json')}
        for path in FLEET_FILES:
            for port in load(path)['ports']:
                if port['home_port'] is not None:
                    self.assertIn(port['home_port'], home_ports, port['id'])
                if port['region'] is not None:
                    self.assertIn(port['region'], coastal, port['id'])

    def test_every_adapter_is_registered(self):
        for path in FLEET_FILES:
            for binding in load(path)['sources']:
                self.assertIn(binding['adapter'], config.ADAPTERS, binding['id'])

    def test_no_binding_or_url_names_an_off_limits_host(self):
        hosts = off_limits()
        for path in FLEET_FILES:
            text = path.read_text().lower()
            for host in hosts:
                self.assertNotRegex(text, r'(?<![a-z0-9.-])(?:[a-z0-9-]+\.)*' + re.escape(host) + r'\b',
                                    f'{path.relative_to(ROOT)} names off-limits host {host}')

    def test_ais_bbox_contains_every_port_and_landing(self):
        for path in FLEET_FILES:
            doc = load(path)
            (south, west), (north, east) = doc['ais']['bbox']
            self.assertLess(south, north)
            self.assertLess(west, east)
            for row in doc['ports'] + doc['landings']:
                lat, lon = row['point']
                self.assertTrue(south <= lat <= north and west <= lon <= east, row['id'])

    def test_no_contact_details_in_region_config(self):
        phone = re.compile(r'\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b')
        for path in FLEET_FILES:
            text = path.read_text()
            self.assertIsNone(phone.search(text), path)
            self.assertNotIn('@', text, path)
            self.assertNotIn('mailto:', text, path)

    @unittest.skipUnless(validate.available(), NEEDS_JSONSCHEMA)
    def test_loader_accepts_every_committed_region(self):
        for ident in config.region_ids(ROOT):
            region = config.load_region(ident, ROOT)
            self.assertEqual(region.id, ident)


class StateAgnosticCode(unittest.TestCase):
    def test_no_state_port_or_landing_literal_in_the_fleet_package(self):
        literals = set()
        for path in FLEET_FILES:
            doc = load(path)
            literals.add(doc['id'])
            literals.update(row['id'] for row in doc['ports'] + doc['landings'])
        sources = sorted((ROOT / 'src/skippercast/fleet').rglob('*.py'))
        self.assertTrue(sources)
        for source in sources:
            text = source.read_text()
            for literal in literals:
                for quoted in (f'"{literal}"', f"'{literal}'"):
                    self.assertNotIn(quoted, text, f'{source.relative_to(ROOT)} hard-codes {quoted}')


class CoastalRegionEnumeration(unittest.TestCase):
    """CF-04 acceptance 3: state-level fleet directories hold no region.json and never shadow a coastal id."""

    def test_state_directories_hold_only_fleet_config(self):
        for path in FLEET_FILES:
            self.assertFalse((path.parent / 'region.json').exists(), path.parent)
        for path in (ROOT / 'regions').glob('*/region.json'):
            self.assertRegex(path.parent.name, r'^[a-z][a-z0-9-]{1,63}$')
            self.assertFalse((path.parent / 'fleet.json').exists(), path.parent)

    def test_worker_build_skips_directories_without_region_json(self):
        script = (ROOT / 'scripts/build-worker.mjs').read_text()
        self.assertIn("existsSync(`regions/${id}/region.json`)", script)


if __name__ == '__main__':
    unittest.main()
