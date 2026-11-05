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
from unittest import mock

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
        x0 = site['lon'][0] + 0.001 if 'lon' in site else -121.0 + n * 0.1
        step = 0.0003 if 'lon' in site else 0.01
        for k, ident in enumerate(site['objects']):
            x = x0 + k * step
            line = [[x, low], [x + 0.001, (low + high) / 2], [x + 0.002, high], [x + 0.003, high + 0.01]]
            shore.append({'type': 'Feature', 'properties': {'OBJECTID': ident, 'ESI': site.get('classes', {}).get(ident, '3A')},
                          'geometry': {'type': 'LineString', 'coordinates': line}})
        for ident in site['access']:
            access.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [x0, low]},
                           'properties': {'OBJECTID': ident, 'Name': f'Synthetic approach {ident}', 'O_PUBLIC': 'Yes',
                                          'AccessType': 'Beach Access', 'Archived': 'No', 'Date_Closd': None, 'ClosureCom': ' ',
                                          'Description': 'SYNTHETIC-DESCRIPTION', 'Photo_1': 'https://example.org/synthetic.jpg',
                                          'PHONE_NMBR': '805-555-0100'}})
    return {'type': 'FeatureCollection', 'features': shore}, {'type': 'FeatureCollection', 'features': access}


def synthetic_bodies(fetched_at):
    shore, access = synthetic_sources()
    data = {'noaa': shore, 'access': access, 'terms': {'licenseInfo': '<div>Synthetic <b>terms</b></div>'}}
    bodies = {k: json.dumps(v).encode() for k, v in data.items()}
    urls = importer.source_urls('morro-bay')
    receipts = {k: importer.receipt(urls[k], body, fetched_at) for k, body in bodies.items()}
    return bodies, receipts


def write_saved_sources(directory, bodies, receipts):
    for key, name in importer.SOURCE_FILES.items():
        (Path(directory) / name).write_bytes(bodies[key])
    (Path(directory) / 'receipts.json').write_text(json.dumps(receipts))


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
                self.assertEqual(importer.parse_time(p[stamp]) is None, p['substrate'] == 'rocky', stamp)
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
        for feature in self.asset['features'][:5]:
            p = feature['properties']
            self.assertEqual((p['checkedAt'], p['reviewExpiresAt']), (review['source']['reviewedAt'], review['source']['expiresAt']))
            self.assertEqual((p['accessReviewedAt'], p['accessReviewExpiresAt']), (review['access']['reviewedAt'], review['access']['expiresAt']))
            self.assertEqual((p['legalReviewedAt'], p['legalReviewExpiresAt']), (review['legal']['reviewedAt'], review['legal']['expiresAt']))
            self.assertTrue(all(a['checkedAt'] == review['access']['reviewedAt'] for a in p['access']))
        for kind in review.values():
            self.assertLess(importer.parse_time(kind['reviewedAt']), importer.parse_time(kind['expiresAt']))

    def test_estero_bluffs_is_added_unreviewed_with_its_own_receipts(self):
        runs = {f['id']: f['properties'] for f in self.asset['features']}
        p = runs['estero-bluffs']
        self.assertEqual(list(runs)[-1], 'estero-bluffs')
        self.assertEqual((p['substrate'], p['sourceObjectIds'], [a['id'] for a in p['access']]),
                         ('rocky', [2234, 2237, 2242, 2244, 2246, 2250, 2251, 2253, 2255, 2259, 2274, 2276, 2277], ['ccc-792', 'ccc-793', 'ccc-794', 'ccc-795']))
        clocks = ('checkedAt', 'reviewExpiresAt', 'accessReviewedAt', 'accessReviewExpiresAt', 'legalReviewedAt', 'legalReviewExpiresAt')
        self.assertEqual([p[k] for k in clocks], [None] * 6)
        self.assertEqual([a['checkedAt'] for a in p['access']], [None] * 4)
        self.assertEqual(set(p['sourceAcquisitions']), {'noaa', 'access', 'terms'})
        self.assertEqual(sum(len(line) for line in next(f for f in self.asset['features'] if f['id'] == 'estero-bluffs')['geometry']['coordinates']), 490)
        for other in list(runs.values())[:5]:
            self.assertNotIn('sourceAcquisitions', other)

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
        self.assertEqual(late['features'][:5], early['features'][:5])
        # The unreviewed run differs only by the receipts of the fetch it was built from.
        strip = lambda f: {**f, 'properties': {k: v for k, v in f['properties'].items() if k != 'sourceAcquisitions'}}
        self.assertEqual(strip(late['features'][5]), strip(early['features'][5]))
        self.assertNotEqual(late['features'][5]['properties']['sourceAcquisitions'], early['features'][5]['properties']['sourceAcquisitions'])
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

    def test_estero_named_rocky_classes_only(self):
        site = next(s for s in importer.SITES['morro-bay']['sites'] if s['id'] == 'estero-bluffs')
        for ident, code in site['classes'].items():
            shore, access = synthetic_sources()
            feature = next(f for f in shore['features'] if f['properties']['OBJECTID'] == ident)
            self.assertEqual(feature['properties']['ESI'], code)
            self.assertEqual(importer.extract('morro-bay', shore, access)[-1]['properties']['substrate'], 'rocky')
            for wrong in ('3A', '5/2A', '6A/2A', '2A, 1A', '1A' if code == '2A' else '2A', '', None):
                shore, access = synthetic_sources()
                next(f for f in shore['features'] if f['properties']['OBJECTID'] == ident)['properties']['ESI'] = wrong
                with self.assertRaisesRegex(ValueError, 'Reviewed rocky source feature changed: %d' % ident):
                    importer.extract('morro-bay', shore, access)
        shore, access = synthetic_sources()
        next(f for f in shore['features'] if f['properties']['OBJECTID'] == 2094)['properties']['ESI'] = '2A'
        with self.assertRaisesRegex(ValueError, 'Reviewed sandy source feature changed: 2094'):
            importer.extract('morro-bay', shore, access)
        with mock.patch.dict(site, {'classes': {**site['classes'], 2234: '5'}}):
            with self.assertRaisesRegex(ValueError, 'Rocky site needs one named ESI code'):
                importer.extract('morro-bay', *synthetic_sources())

    def test_original_vertices_and_gaps_preserved(self):
        low, high = (-120.97380, -120.91612)
        inside, out = [low + 0.01, 35.45], [high + 0.01, 35.45]
        line = {'type': 'LineString', 'coordinates': [[low + 0.01, 35.45], [low + 0.02, 35.451], out, [low + 0.03, 35.452],
                                                          [low + 0.04, 35.453], [high + 0.02, 35.46], [low + 0.05, 35.454]]}
        paths = importer.run_paths({'geometry': line}, 35.44610, 35.46514, low, high)
        self.assertEqual(paths, [line['coordinates'][:2], line['coordinates'][3:5]])
        self.assertNotIn(out, [p for path in paths for p in path])
        self.assertEqual(importer.run_paths({'geometry': {'type': 'LineString', 'coordinates': [inside, out]}}, 35.44610, 35.46514, low, high), [])
        for bad in ([low, None], [low, float('nan')], [float('inf'), 35.45], [low]):
            with self.assertRaisesRegex(ValueError, 'Invalid coordinate'):
                importer.run_paths({'geometry': {'type': 'LineString', 'coordinates': [inside, bad]}}, 35.44610, 35.46514, low, high)

    def test_addition_keeps_legacy_feature_bytes(self):
        raw = ASSET.read_bytes()
        asset = json.loads(raw)
        legacy = asset['features'][:5]
        self.assertEqual([f['id'] for f in legacy], list(importer.LEGACY_FEATURE_SHA256))
        for feature in legacy:
            blob = importer.feature_bytes(feature)
            self.assertIn(blob, raw)
            self.assertEqual(hashlib.sha256(blob).hexdigest(), importer.LEGACY_FEATURE_SHA256[feature['id']], feature['id'])
        self.assertEqual(PUBLISHED.read_bytes(), raw)
        self.assertEqual(asset['reviews'], importer.REVIEWS['morro-bay'])
        self.assertEqual(asset['sourceChecks']['acquisitions']['access']['responseSha256'], '4925eff242f1c841d8035ccbefe851b0251e75063e39826f02cd1031d17cacc3')

    def test_add_site_refuses_a_changed_baseline_and_never_duplicates(self):
        bodies, receipts = synthetic_bodies('2026-11-04T00:00:00.000Z')
        baseline = json.loads(ASSET.read_text())
        again = importer.add_site('morro-bay', 'estero-bluffs', baseline, bodies, receipts)
        twice = importer.add_site('morro-bay', 'estero-bluffs', again, bodies, receipts)
        self.assertEqual(twice, again)
        self.assertEqual([f['id'] for f in twice['features']].count('estero-bluffs'), 1)
        for change in (lambda d: d['features'][0]['properties'].update(name='Edited'), lambda d: d['features'].pop(1),
                       lambda d: d['features'].reverse() or None):
            changed = copy.deepcopy(baseline)
            change(changed)
            with self.assertRaisesRegex(ValueError, 'Baseline legacy run'):
                importer.add_site('morro-bay', 'estero-bluffs', changed, bodies, receipts)
        with self.assertRaisesRegex(ValueError, 'Unknown site'):
            importer.add_site('morro-bay', 'morro-strand', baseline, bodies, receipts)

    def test_estero_is_never_reviewed_by_download(self):
        early = importer.build_asset('morro-bay', *synthetic_bodies('2026-10-03T00:00:00.000Z'))
        late = importer.build_asset('morro-bay', *synthetic_bodies('2027-06-01T00:00:00.000Z'))
        for asset in (early, late):
            p = asset['features'][-1]['properties']
            self.assertEqual((asset['features'][-1]['id'], p['checkedAt'], p['reviewExpiresAt'], p['accessReviewedAt'], p['legalReviewExpiresAt']),
                             ('estero-bluffs', None, None, None, None))
            self.assertEqual([a['checkedAt'] for a in p['access']], [None] * 4)
            self.assertEqual(set(p['sourceAcquisitions']), {'noaa', 'access', 'terms'})
        def first(collection, ident):
            return next(f for f in collection['features'] if f['properties']['OBJECTID'] == ident)
        for corrupt in (lambda a: first(a, 792)['properties'].update(O_PUBLIC='No'), lambda a: first(a, 793)['properties'].update(Archived='Yes'),
                        lambda a: first(a, 794)['properties'].update(Date_Closd='2026-11-01'), lambda a: first(a, 795)['properties'].update(ClosureCom='Closed'),
                        lambda a: a['features'].remove(first(a, 795))):
            shore, access = synthetic_sources()
            corrupt(access)
            with self.assertRaisesRegex(ValueError, 'Unverified public beach approach'):
                importer.extract('morro-bay', shore, access)

    def test_truncated_or_failed_responses_are_rejected(self):
        for body in (b'{"exceededTransferLimit": true, "features": []}', b'{"error": {"code": 400}}', b'[]'):
            with self.assertRaisesRegex(ValueError, 'Source error'):
                importer.parse(body)

    def test_offline_rebuild_checks_saved_receipts_and_keeps_their_clock(self):
        bodies, receipts = synthetic_bodies('2026-10-03T00:00:00.000Z')
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            write_saved_sources(tmp, bodies, receipts)
            receipt_bytes = (Path(tmp) / 'receipts.json').read_bytes()
            loaded, kept = importer.load_saved(tmp, 'morro-bay', now)
            self.assertEqual((loaded, kept), (bodies, receipts))
            self.assertEqual((Path(tmp) / 'receipts.json').read_bytes(), receipt_bytes)
            self.assertEqual(importer.build_asset('morro-bay', loaded, kept),
                             importer.build_asset('morro-bay', bodies, receipts))
            for corrupt in (lambda r: r.pop('noaa'), lambda r: r['access'].update(fetchedAt='invalid'),
                            lambda r: r['terms'].update(fetchedAt='2099-01-01T00:00:00Z'),
                            lambda r: r['access'].update(responseSha256=hashlib.sha256(b'other').hexdigest())):
                changed = copy.deepcopy(receipts)
                corrupt(changed)
                (Path(tmp) / 'receipts.json').write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'saved source receipt'):
                    importer.load_saved(tmp, 'morro-bay', now)

    def test_offline_rebuild_rejects_missing_or_tampered_source_urls(self):
        bodies, receipts = synthetic_bodies('2026-10-03T00:00:00.000Z')
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            for key in importer.SOURCE_FILES:
                for url in (None, '', 42, 'https://example.org/other', receipts[key]['url'] + '&other=1'):
                    with self.subTest(key=key, url=url):
                        changed = copy.deepcopy(receipts)
                        if url is None:
                            changed[key].pop('url')
                        else:
                            changed[key]['url'] = url
                        write_saved_sources(tmp, bodies, changed)
                        with self.assertRaisesRegex(ValueError, 'saved source receipt: ' + key):
                            importer.load_saved(tmp, 'morro-bay', now)

    def test_offline_rebuild_rejects_source_key_url_swaps(self):
        bodies, receipts = synthetic_bodies('2026-10-03T00:00:00.000Z')
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            for key in importer.SOURCE_FILES:
                for other in importer.SOURCE_FILES:
                    if key == other:
                        continue
                    with self.subTest(key=key, other=other):
                        changed = copy.deepcopy(receipts)
                        changed[key]['url'] = receipts[other]['url']
                        write_saved_sources(tmp, bodies, changed)
                        with self.assertRaisesRegex(ValueError, 'saved source receipt: ' + key):
                            importer.load_saved(tmp, 'morro-bay', now)

    def test_offline_rebuild_binds_urls_to_the_selected_region(self):
        bodies, receipts = synthetic_bodies('2026-10-03T00:00:00.000Z')
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        # A second synthetic region exercises the bbox without adding a real source.
        with mock.patch.dict(importer.SITES, {'synthetic-other': {'bbox': (-122, 36, -121, 37)}}):
            urls = importer.source_urls('synthetic-other')
            with tempfile.TemporaryDirectory() as tmp:
                for key in ('noaa', 'access'):
                    with self.subTest(key=key):
                        changed = copy.deepcopy(receipts)
                        changed[key]['url'] = urls[key]
                        write_saved_sources(tmp, bodies, changed)
                        with self.assertRaisesRegex(ValueError, 'saved source receipt: ' + key):
                            importer.load_saved(tmp, 'morro-bay', now)
                selected = copy.deepcopy(receipts)
                for key in selected:
                    selected[key]['url'] = urls[key]
                write_saved_sources(tmp, bodies, selected)
                self.assertEqual(importer.load_saved(tmp, 'synthetic-other', now), (bodies, selected))


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


class Substrate(unittest.TestCase):
    """FSC-03: a run may be sand or rocky; the committed sand runs keep their bytes."""
    # Before SC1952-08 the whole all-sand asset hashed to 09a91f7616b761236a9065d0529e3065d5b9b4a2f94b5bb985ca1a3ba090c4b6;
    # the five legacy feature digests now live in importer.LEGACY_FEATURE_SHA256.

    def test_both_schema_copies_are_byte_identical(self):
        self.assertEqual((ROOT / 'schemas/shore-habitat.schema.json').read_bytes(),
                         (ROOT / 'src/skippercast/coastal/resources/shore-habitat.schema.json').read_bytes())

    @unittest.skipUnless(validate.available(), NEEDS_JSONSCHEMA)
    def test_rocky_validates_and_other_substrates_are_refused(self):
        asset = json.loads(ASSET.read_text())
        for value, ok in (('sand', True), ('rocky', True), ('Rock', False), ('gravel', False), ('', False), ('ROCKY', False),
                          (None, False), ('missing', False)):
            with self.subTest(substrate=value):
                doc = copy.deepcopy(asset)
                p = doc['features'][0]['properties']
                if value == 'missing':
                    del p['substrate']
                else:
                    p['substrate'] = value
                self.assertEqual(validate.errors('shore-habitat', doc) == [], ok)

    @unittest.skipUnless(validate.available(), NEEDS_JSONSCHEMA)
    def test_null_dates_validate_but_malformed_or_mixed_pairs_fail(self):
        asset = json.loads(ASSET.read_text())
        pairs = (('checkedAt', 'reviewExpiresAt'), ('accessReviewedAt', 'accessReviewExpiresAt'), ('legalReviewedAt', 'legalReviewExpiresAt'))
        def check(mutate, ok, index=-1):
            doc = copy.deepcopy(asset)
            mutate(doc['features'][index]['properties'])
            self.assertEqual(validate.errors('shore-habitat', doc) == [], ok)
        check(lambda p: None, True)
        for a, b in pairs:
            check(lambda p: p.update({b: '2026-11-01T00:00:00Z'}), False)  # one side dated on the unreviewed run
            check(lambda p: p.update({a: '2026-11-01T00:00:00Z', b: None}), False)
            check(lambda p: p.update({a: 'not a date', b: 'not a date'}), False)
            check(lambda p: p.update({a: '', b: ''}), False)
            check(lambda p: p.update({a: None}), False, 0)  # a dated sand run cannot lose one side either
            check(lambda p: p.update({a: None, b: None}), True, 0)
        check(lambda p: p['access'][0].update(checkedAt='bad'), False)
        doc = copy.deepcopy(asset)
        doc['reviews']['source']['reviewedAt'] = None
        self.assertNotEqual(validate.errors('shore-habitat', doc), [])  # root reviews stay dated

    def test_access_checked_state_agrees_with_the_run(self):
        for f in json.loads(ASSET.read_text())['features']:
            p = f['properties']
            for point in p['access']:
                self.assertEqual(point['checkedAt'] is None, p['accessReviewedAt'] is None, f['id'])

    def test_legacy_sand_runs_and_published_copy_are_unchanged(self):
        asset = json.loads(ASSET.read_text())
        self.assertTrue(all(f['properties']['substrate'] == 'sand' for f in asset['features'][:5]))
        self.assertEqual([f['properties']['substrate'] for f in asset['features'][5:]], ['rocky'])
        self.assertEqual(PUBLISHED.read_bytes(), ASSET.read_bytes())


if __name__ == '__main__':
    unittest.main()
