"""Full-module offline tests for SP-18-v1 / SP1807-SECTOR-ENDPOINT.

The fixture projects the catalog, published-region index, region assets and atlas
fields consumed by compile_sectors; it is not a complete publishable package.
No public URL in these synthetic documents is fetched.
"""
from contextlib import ExitStack
from copy import deepcopy
import importlib
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/sp1807_sector_endpoint/scenario.json'


def forbidden(*args, **kwargs):
    raise RuntimeError('SP1807 offline sentinel: network/model/child execution forbidden')


class FixtureCase(TestCase):
    def setUp(self):
        # Every patch belongs to this test, including discovery in a peer process.
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ('connect', 'connect_ex'):
            self.stack.enter_context(patch.object(socket.socket, name, forbidden))
        for name in ('create_connection', 'getaddrinfo'):
            self.stack.enter_context(patch.object(socket, name, forbidden))
        self.stack.enter_context(patch.object(subprocess, 'Popen', forbidden))
        out = ROOT.parent / 'out'
        out.mkdir(exist_ok=True)
        temporary = self.stack.enter_context(TemporaryDirectory(prefix='sp1807-fixture-', dir=out))
        self.root = Path(temporary)
        self.data = json.loads(FIXTURE.read_text())
        # Anchor imports to the staged product, not an editable install elsewhere.
        original_path = sys.path[:]
        self.stack.callback(lambda: sys.path.__setitem__(slice(None), original_path))
        sys.path.insert(0, str(ROOT / 'src'))
        from skippercast import paths
        # contracts has no import-time I/O. Keep its other bound defaults on the
        # staged static checkout, while redirecting the compiler before import.
        self.stack.enter_context(patch.object(paths, 'repo_root', lambda: ROOT))
        contracts_new = 'skippercast.platform.contracts' not in sys.modules
        sectors_new = 'skippercast.platform.sectors' not in sys.modules
        from skippercast.platform import contracts
        if contracts_new:
            self.stack.callback(setattr, contracts, 'REPO', ROOT)
        self.stack.enter_context(patch.object(contracts, 'REPO', self.root))
        self.sectors = importlib.import_module('skippercast.platform.sectors')
        if sectors_new:
            self.stack.callback(setattr, self.sectors, 'REPO', ROOT)
            self.stack.callback(setattr, self.sectors.compile_sectors, '__defaults__', (ROOT,))
        self.assertEqual(Path(self.sectors.__file__ or '').resolve(), ROOT / 'src/skippercast/platform/sectors.py')
        self.stack.enter_context(patch.object(self.sectors, 'REPO', self.root))
        self.stack.enter_context(patch.object(self.sectors.compile_sectors, '__defaults__', (self.root,)))
        read, write = contracts.read_json, contracts.atomic_json

        def checked(path):
            path = Path(path).resolve()
            if not path.is_relative_to(self.root):
                raise RuntimeError('SP1807 live-store sentinel: path outside fixture')
            return path

        self.stack.enter_context(patch.object(self.sectors, 'read_json', lambda p: read(checked(p))))
        self.stack.enter_context(patch.object(self.sectors, 'atomic_json', lambda p, v: write(checked(p), v)))

    def compile(self, data=None, *, latitudes=None, longitude=-121):
        data = deepcopy(self.data if data is None else data)
        if latitudes is not None:
            data['atlas']['targets'] = [dict(id=f'point-{i}', latitude=lat, longitude=longitude)
                                        for i, lat in enumerate(latitudes)]
        documents = {
            'catalog/coastal-sectors.json': data['source'],
            'catalog/coasts.json': data['coasts'],
            'dist/regions/index.json': data['packages'],
            'regions/synthetic-package/region.json': data['region'],
            'dist/regions/synthetic-package/atlas.json': data['atlas'],
        }
        for relative, document in documents.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document))
        packet = self.sectors.compile_sectors()  # also exercises redirected bound default
        self.assertEqual(packet, json.loads((self.root / 'dist/data/coastal-sectors.json').read_text()))
        return packet

    def counts(self, **kwargs):
        return [s['published_candidate_points'] for s in self.compile(**kwargs)['sectors']]

    def adjacent(self):
        data = deepcopy(self.data)
        data['coasts']['regions'].append({
            'id': 'northern-coast', 'name': 'Synthetic northern coast',
            'latitude': [36, 37], 'bounds': [-122, 36, -120, 37],
            'packages': ['synthetic-package'], 'rules_url': 'https://example.org/north-rules'})
        data['source']['sectors'].append({
            'id': 'northern-owner', 'name': 'Synthetic northern owner',
            'coast': 'northern-coast', 'latitude': [36, 37]})
        return data


class BaselineTests(FixtureCase):
    def test_primary_regression(self):
        self.assertEqual(self.counts(), [1, 2], 'A1 terminal northern target must not disappear')

    def test_healthy_control(self):
        self.assertEqual(self.counts(latitudes=[34]), [1, 0])
        self.assertEqual(self.counts(latitudes=[35]), [0, 1])


class FocusedTests(FixtureCase):
    def test_a1_counts_and_metadata(self):
        packet = self.compile()
        self.assertEqual([s['published_candidate_points'] for s in packet['sectors']], [1, 2])
        self.assertEqual(sum(s['published_candidate_points'] for s in packet['sectors']), 3)
        for field in ('schema_version', 'reviewed_at', 'scope', 'survey_feed_url',
                      'survey_product_feed_url', 'survey_discovery'):
            self.assertEqual(packet[field], self.data['source'][field])
        self.assertEqual([s['id'] for s in packet['sectors']], ['south-band', 'north-band'])
        for sector in packet['sectors']:
            self.assertEqual(sector['status'], 'discovery')
            self.assertEqual(sector['partial_package_ids'], ['synthetic-package'])
            self.assertEqual(sector['rules_url'], 'https://example.org/rules')
            self.assertEqual(sector['note'], 'Browse area only. Survey coverage, current fish presence and date-specific legal access have not been established by this sector.')

    def test_a2_exact_neighbors(self):
        for latitude, expected in (
                (math.nextafter(34, -math.inf), [0, 0]), (34, [1, 0]),
                (math.nextafter(34, math.inf), [1, 0]),
                (math.nextafter(35, -math.inf), [1, 0]), (35, [0, 1]),
                (math.nextafter(35, math.inf), [0, 1]),
                (math.nextafter(36, -math.inf), [0, 1]), (36, [0, 1]),
                (math.nextafter(36, math.inf), [0, 0])):
            with self.subTest(latitude=latitude):
                self.assertEqual(self.counts(latitudes=[latitude]), expected)

    def test_a2_longitude_edges(self):
        for longitude, expected in ((-122, [0, 1]), (-120, [0, 1]),
                (math.nextafter(-122, -math.inf), [0, 0]),
                (math.nextafter(-120, math.inf), [0, 0])):
            with self.subTest(longitude=longitude):
                self.assertEqual(self.counts(latitudes=[36], longitude=longitude), expected)

    def test_a3_shared_northern_owner_and_order(self):
        data = self.adjacent()
        self.assertEqual(self.counts(data=data, latitudes=[36]), [0, 0, 1])
        data['coasts']['regions'].reverse()
        data['source']['sectors'].reverse()
        self.assertEqual(self.counts(data=data, latitudes=[36]), [1, 0, 0])

    def test_a3_northern_package_absent(self):
        data = self.adjacent()
        data['coasts']['regions'][1]['packages'] = []
        self.assertEqual(self.counts(data=data, latitudes=[36]), [0, 1, 0])

    def test_a3_northern_longitude_ineligible(self):
        for west in (-121, math.nextafter(-121, math.inf)):
            data = self.adjacent()
            data['coasts']['regions'][1]['bounds'][0] = west
            expected = [0, 0, 1] if west == -121 else [0, 1, 0]
            with self.subTest(west=west):
                self.assertEqual(self.counts(data=data, latitudes=[36]), expected)

    def test_a3_northern_package_overlap_required(self):
        data = self.adjacent()
        data['packages']['regions'][0]['fishing_bounds'][3] = 36
        self.assertEqual(self.counts(data=data, latitudes=[36]), [0, 1, 0])

    def test_a3_no_unrelated_interior_deduplication(self):
        data = self.adjacent()
        data['coasts']['regions'][1]['latitude'] = [35, 37]
        data['coasts']['regions'][1]['bounds'][1] = 35
        data['source']['sectors'][-1]['latitude'] = [35, 37]
        self.assertEqual(self.counts(data=data, latitudes=[35.5]), [0, 1, 1])

    def test_a4_one_band_both_edges(self):
        data = deepcopy(self.data)
        data['source']['sectors'] = [dict(data['source']['sectors'][0], latitude=[34, 36])]
        self.assertEqual(self.counts(data=data, latitudes=[34, 36]), [2])

    def test_a4_unchanged_validation_failures(self):
        cases = []
        for seam in (35.25, 34.75):
            data = deepcopy(self.data)
            data['source']['sectors'][1]['latitude'][0] = seam
            cases.append((data, 'Sector bands must meet without gaps or overlaps'))
        data = deepcopy(self.data)
        data['source']['sectors'][0]['latitude'][0] = 33
        cases.append((data, 'Sector bands must cover their parent coast'))
        data = deepcopy(self.data)
        data['source']['sectors'].append(dict(data['source']['sectors'][0], id='unknown', coast='missing'))
        cases.append((data, 'Sector references an unknown coast'))
        data = deepcopy(self.data)
        data['source']['schema_version'] = 2
        cases.append((data, 'Invalid coastal sector catalog'))
        data = deepcopy(self.data)
        data['source']['reviewed_at'] = ''
        cases.append((data, 'Invalid coastal sector catalog'))
        data = deepcopy(self.data)
        data['source']['sectors'][1]['id'] = 'south-band'
        cases.append((data, 'Invalid or duplicate sector identity'))
        for data, message in cases:
            with self.subTest(message=message):
                self.assertFalse((self.root / 'dist/data/coastal-sectors.json').exists())
                with self.assertRaisesRegex(ValueError, message):
                    self.compile(data)
                self.assertFalse((self.root / 'dist/data/coastal-sectors.json').exists())

    def test_sentinels_and_bound_default(self):
        with self.assertRaisesRegex(RuntimeError, 'offline sentinel'):
            socket.create_connection(('example.org', 443))
        with self.assertRaisesRegex(RuntimeError, 'live-store sentinel'):
            self.sectors.compile_sectors(ROOT)
        self.assertEqual(self.sectors.compile_sectors.__defaults__, (self.root,))
