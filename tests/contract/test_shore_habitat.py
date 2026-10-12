"""Shore runs and beach approaches (FE-43): the importer, its committed asset and the build copy.

The asset must stay readable by packages/coast's shore consumer (MultiLineString runs,
properties.reviewExpiresAt, access[].coordinates), keep only factual Coastal Commission
fields, and carry review dates that no import or build can renew. Fixtures here are
synthetic; nothing reads the network or var/.
"""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from skippercast import validate
from skippercast.platform.build import compile_shore_habitat
from skippercast.platform.contracts import load_region
from tests._support import ROOT

SPEC = importlib.util.spec_from_file_location('collect_shore_habitat', ROOT / 'scripts/collect_shore_habitat.py')
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)

ASSET = ROOT / 'catalog/shore-habitat/morro-bay.geojson'
PUBLISHED = ROOT / 'dist/regions/morro-bay/shore-habitat.geojson'
NEEDS_JSONSCHEMA = 'jsonschema not installed (pip install -r requirements-test.txt); the survey-science CI job runs these'
FORBIDDEN = ('photo', 'description', 'phone', 'video', 'googlemaps', 'applemaps', 'directions')
ACCESS_KEYS = {'id', 'name', 'coordinates', 'sourceUrl', 'publicAccess', 'checkedAt', 'note'}


def keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from keys(value)


def synthetic_sources(region='morro-bay'):
    """One synthetic line per reviewed object, with one vertex outside its beach window."""
    shore, access = [], []
    for n, site in enumerate(importer.SITES[region]['sites']):
        low, high = site['lat']
        for k, ident in enumerate(site['objects']):
            x = -121.0 + n * 0.1 + k * 0.01
            line = [[x, low], [x + 0.001, (low + high) / 2], [x + 0.002, high], [x + 0.003, high + 0.01]]
            shore.append({'type': 'Feature', 'properties': {'OBJECTID': ident, 'ESI': '3A'}, 'geometry': {'type': 'LineString', 'coordinates': line}})
        for ident in site['access']:
            access.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-121.0 + n * 0.1, low]},
                           'properties': {'OBJECTID': ident, 'Name': f'Synthetic approach {ident}', 'O_PUBLIC': 'Yes',
                                          'AccessType': 'Beach Access', 'Archived': 'No', 'Date_Closd': None, 'ClosureCom': ' ',
                                          'Description': 'SYNTHETIC-DESCRIPTION', 'Photo_1': 'https://example.org/synthetic.jpg',
                                          'PHONE_NMBR': '805-555-0100'}})
    return {'type': 'FeatureCollection', 'features': shore}, {'type': 'FeatureCollection', 'features': access}


def synthetic_bodies(fetched_at):
    shore, access = synthetic_sources()
    data = {'noaa': shore, 'access': access, 'terms': {'licenseInfo': '<div>Synthetic <b>terms</b></div>'}}
    bodies = {k: json.dumps(v).encode() for k, v in data.items()}
    receipts = {k: importer.receipt(f'https://example.org/{k}', body, fetched_at) for k, body in bodies.items()}
    return bodies, receipts


class CommittedAsset(unittest.TestCase):
    def setUp(self):
        self.asset = json.loads(ASSET.read_text())

    @unittest.skipUnless(validate.available(), NEEDS_JSONSCHEMA)
    def test_asset_matches_its_schema(self):
        self.assertEqual(validate.errors('shore-habitat', self.asset), [])

    def test_asset_keeps_the_shape_the_coast_reader_uses(self):
        self.assertEqual(self.asset['type'], 'FeatureCollection')
        self.assertEqual(self.asset['sourceYear'], 2006)
        for feature in self.asset['features']:
            p = feature['properties']
            self.assertEqual(feature['geometry']['type'], 'MultiLineString')
            self.assertEqual(feature['id'], p['id'])
            self.assertIn(p['areaId'], {'north', 'central', 'south'})
            self.assertEqual(p['sourceYear'], 2006)
            for stamp in ('checkedAt', 'reviewExpiresAt', 'accessReviewExpiresAt', 'legalReviewExpiresAt'):
                self.assertIsNotNone(importer.parse_time(p[stamp]), stamp)
            self.assertTrue(p['access'] and all(len(a['coordinates']) == 2 for a in p['access']))
            self.assertTrue(all(len(line) >= 2 for line in feature['geometry']['coordinates']))

    def test_access_points_carry_ids_and_links_only(self):
        for key in keys(self.asset):
            self.assertFalse(any(word in key.lower() for word in FORBIDDEN), key)
        for feature in self.asset['features']:
            for point in feature['properties']['access']:
                self.assertEqual(set(point), ACCESS_KEYS)
                self.assertRegex(point['id'], r'^ccc-\d+$')
                self.assertTrue(point['sourceUrl'].startswith(importer.ACCESS + '/0/query?objectIds=' + point['id'][4:] + '&'))

    def test_review_dates_are_the_dated_review_not_the_import_clock(self):
        review = importer.REVIEWS['morro-bay']
        self.assertEqual(self.asset['reviews'], review)
        for feature in self.asset['features']:
            p = feature['properties']
            self.assertEqual((p['checkedAt'], p['reviewExpiresAt']), (review['source']['reviewedAt'], review['source']['expiresAt']))
            self.assertEqual((p['accessReviewedAt'], p['accessReviewExpiresAt']), (review['access']['reviewedAt'], review['access']['expiresAt']))
            self.assertEqual((p['legalReviewedAt'], p['legalReviewExpiresAt']), (review['legal']['reviewedAt'], review['legal']['expiresAt']))
            self.assertTrue(all(a['checkedAt'] == review['access']['reviewedAt'] for a in p['access']))
        for kind in review.values():
            self.assertLess(importer.parse_time(kind['reviewedAt']), importer.parse_time(kind['expiresAt']))

    def test_build_publishes_the_catalog_file_unchanged(self):
        self.assertEqual(PUBLISHED.read_bytes(), ASSET.read_bytes())


class Importer(unittest.TestCase):
    def test_runs_keep_only_source_vertices_inside_each_beach(self):
        shore, access = synthetic_sources()
        features = importer.extract('morro-bay', shore, access)
        self.assertEqual([f['id'] for f in features], [s['id'] for s in importer.SITES['morro-bay']['sites']])
        sources = {f['properties']['OBJECTID']: f['geometry']['coordinates'] for f in shore['features']}
        for feature, site in zip(features, importer.SITES['morro-bay']['sites']):
            self.assertEqual(feature['geometry']['coordinates'], [sources[i][:3] for i in site['objects']])

    def test_inventory_photos_descriptions_and_phones_are_dropped(self):
        bodies, receipts = synthetic_bodies('2026-10-03T00:00:00.000Z')
        text = json.dumps(importer.build_asset('morro-bay', bodies, receipts))
        for leaked in ('SYNTHETIC-DESCRIPTION', 'synthetic.jpg', '555-0100', 'Photo_1', 'Description'):
            self.assertNotIn(leaked, text)
        self.assertIn('Synthetic terms', text)

    def test_a_later_import_cannot_renew_any_review(self):
        early = importer.build_asset('morro-bay', *synthetic_bodies('2026-10-03T00:00:00.000Z'))
        late = importer.build_asset('morro-bay', *synthetic_bodies('2027-06-01T00:00:00.000Z'))
        self.assertEqual(late['reviews'], early['reviews'])
        self.assertEqual(late['features'], early['features'])
        self.assertEqual(late['builtAt'], '2027-06-01T00:00:00.000Z')

    def test_reclassification_withdrawal_or_bad_geometry_stops_the_import(self):
        def first(collection, ident):
            return next(f for f in collection['features'] if f['properties']['OBJECTID'] == ident)
        cases = [
            lambda s, a: first(s, 2094)['properties'].update(ESI='6A'),
            lambda s, a: s['features'].remove(first(s, 2294)),
            lambda s, a: first(s, 2294)['geometry'].update(coordinates=[[-121.0, None], [-121.0, 35.39]]),
            lambda s, a: first(a, 770)['properties'].update(O_PUBLIC='No'),
            lambda s, a: first(a, 770)['properties'].update(AccessType='Visual Access'),
            lambda s, a: first(a, 804)['properties'].update(Archived='Yes'),
            lambda s, a: first(a, 875)['properties'].update(Date_Closd='2026-10-01'),
            lambda s, a: first(a, 797)['properties'].update(ClosureCom='Closed pending repair'),
            lambda s, a: a['features'].remove(first(a, 868)),
        ]
        for corrupt in cases:
            shore, access = synthetic_sources()
            corrupt(shore, access)
            with self.assertRaisesRegex(ValueError, 'Reviewed sandy source|Unverified public beach approach|Invalid coordinate'):
                importer.extract('morro-bay', shore, access)

    def test_truncated_or_failed_responses_are_rejected(self):
        for body in (b'{"exceededTransferLimit": true, "features": []}', b'{"error": {"code": 400}}', b'[]'):
            with self.assertRaisesRegex(ValueError, 'Source error'):
                importer.parse(body)

    def test_offline_rebuild_checks_saved_receipts_and_keeps_their_clock(self):
        bodies, receipts = synthetic_bodies('2026-10-03T00:00:00.000Z')
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            for key, name in importer.SOURCE_FILES.items():
                (Path(tmp) / name).write_bytes(bodies[key])
            (Path(tmp) / 'receipts.json').write_text(json.dumps(receipts))
            loaded, kept = importer.load_saved(tmp, now)
            self.assertEqual((loaded, kept), (bodies, receipts))
            for corrupt in (lambda r: r.pop('noaa'), lambda r: r['access'].update(fetchedAt='invalid'),
                            lambda r: r['terms'].update(fetchedAt='2099-01-01T00:00:00Z'),
                            lambda r: r['access'].update(responseSha256=hashlib.sha256(b'other').hexdigest())):
                changed = copy.deepcopy(receipts)
                corrupt(changed)
                (Path(tmp) / 'receipts.json').write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'saved source receipt'):
                    importer.load_saved(tmp, now)


class BuildCopy(unittest.TestCase):
    def check(self, mutate):
        region = load_region('morro-bay')
        data = json.loads(ASSET.read_text())
        mutate(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'catalog/shore-habitat').mkdir(parents=True)
            (root / 'dist/regions/morro-bay').mkdir(parents=True)
            (root / 'catalog/shore-habitat/morro-bay.geojson').write_text(json.dumps(data))
            compile_shore_habitat(root, [region])
            return (root / 'dist/regions/morro-bay/shore-habitat.geojson').read_text()

    def test_build_copies_a_valid_asset(self):
        self.assertEqual(json.loads(self.check(lambda d: None)), json.loads(ASSET.read_text()))

    def test_build_refuses_another_region_or_an_outside_point(self):
        with self.assertRaisesRegex(ValueError, 'another region'):
            self.check(lambda d: d['features'][0]['properties'].update(region='cambria-san-simeon'))
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.check(lambda d: d['features'][0]['properties']['access'][0].update(coordinates=[-118.0, 34.0]))

    def test_build_refuses_a_region_without_a_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'catalog/shore-habitat').mkdir(parents=True)
            shutil.copyfile(ASSET, Path(tmp) / 'catalog/shore-habitat/not-a-region.geojson')
            with self.assertRaisesRegex(ValueError, 'unknown or draft region'):
                compile_shore_habitat(Path(tmp), [load_region('morro-bay')])


if __name__ == '__main__':
    unittest.main()
