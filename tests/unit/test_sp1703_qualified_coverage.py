"""SP1703: a qualified bottom view's coverage claim must match its decoded raster.

Every case runs through the real ``validate_qualified_scope`` against a wholly
synthetic release written to a temporary directory, patterned after
tests/integration/test_qualified_scope.py. Artifact and receipt hashes are
recomputed after every change, so a rejection names the decoded-coverage gate
rather than an integrity or other prerequisite failure. Raster bytes come from
literal little-endian hex in tests/fixtures/sp1703_qualified_coverage, with
valid-sample counts stated independently of the decoder under test.

A passing case is a scoped coverage check only, never publication, survey,
legal or navigation acceptance.
"""
import base64
import binascii
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from skippercast.platform.bottom_targets import VERSION
from skippercast.platform.qualified_scope import validate_qualified_scope
from tests._support import FIXTURES

FIXTURE = FIXTURES / 'sp1703_qualified_coverage'
RELEASE = json.loads((FIXTURE / 'release.json').read_text(encoding='utf-8'))
RASTERS = json.loads((FIXTURE / 'rasters.json').read_text(encoding='utf-8'))
COVERAGE_REASON = 'Bottom view coverage differs from its decoded valid samples'
CONTRACT_REASON = 'Unsupported bottom-view raster contract'
INCOMPLETE_REASON = 'Bottom view raster is incomplete'
NODATA_HEX = '0080'  # -32768 as int16 little-endian


def polygon(west, south, east, north):
    return {'type': 'Polygon', 'coordinates': [[[west, south], [east, south],
            [east, north], [west, north], [west, south]]]}


def raster(case):
    """Raw bytes plus an independent valid count from the literal hex tokens."""
    text = case['hex']
    tokens = [text[i:i + 4] for i in range(0, len(text), 4)]
    if len(tokens) != case['width'] * case['height'] or sum(t != NODATA_HEX for t in tokens) != case['valid']:
        raise ValueError(f'Inconsistent synthetic raster fixture: {case}')
    return bytes.fromhex(text)


class SyntheticRelease:
    """One complete qualified-subset release with N targets and their bottom views."""

    def __init__(self, test, views):
        temporary = tempfile.TemporaryDirectory()
        test.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.rid = RELEASE['region_id']
        self.base = f'regions/{self.rid}/'
        self.folder = Path('dist') / self.base / 'qualified-bottom'
        prefix = RELEASE['target_prefix']
        self.write_holds([])
        self.spec = {**RELEASE['spec'], 'sha256': 'a' * 64}
        self.catalog = {'noaa-test': {'review_status': 'approved', 'adapter': 'noaa-native-vr-bag',
                                      'pinned_sha256': self.spec['sha256'], 'access_url': self.spec['url'],
                                      'vertical_datum': 'MLLW', 'qualified_resolution_limit_m': 4,
                                      'bounds': RELEASE['source_bounds']},
                        'mpa': {'review_status': 'approved'}}
        self.region = {'id': self.rid,
                       'assets': {'target_qualification': self.base + 'qualified-bottom/manifest.json',
                                  'bottom_index': self.base + 'bottom-index.json',
                                  'protected_areas': self.base + 'protected.geojson',
                                  'closures': self.base + 'closures.geojson'},
                       'source_bindings': {'bathymetry': ['noaa-test'], 'protected-areas': ['mpa']},
                       'coverage': {'protected-areas': {'status': 'ready'}},
                       'boat': {'bottom_depth_limit_ft': RELEASE['boat_bottom_depth_limit_ft']},
                       'fishing_bounds': RELEASE['fishing_bounds']}
        habitat_path = 'dist/' + self.base + 'habitat.geojson'
        habitat = self.write(habitat_path, {'schema_version': 1, 'region_id': self.rid,
                                            'type': 'FeatureCollection', 'features': []})
        closure_receipts = []
        for closure in RELEASE['closures']:
            path = 'dist/' + self.region['assets'][closure['asset']]
            value = {'region_id': self.rid, 'type': 'FeatureCollection', 'checked_at': RELEASE['checked_at'],
                     'source_url': 'https://official.example/' + closure['asset'],
                     'features': [{'type': 'Feature', 'geometry': polygon(
                         closure['west'], closure['south'], closure['east'], closure['north'])}]}
            receipt = self.write(path, value)
            closure_receipts.append({'path': path, 'checked_at': value['checked_at'], 'sha256': receipt['sha256'],
                                     'features': 1, 'source_url': value['source_url']})
        self.config = {'schema_version': 1, 'region_id': self.rid, 'status': 'reviewed', 'target_prefix': prefix,
                       **RELEASE['config'], 'habitat_path': habitat_path, 'habitat_sha256': habitat['sha256'],
                       'sources': [self.spec],
                       'closure_inputs': [{'path': r['path'], 'minimum_features': 1} for r in closure_receipts]}
        config_receipt = self.write_config()
        source = {**self.spec, 'url': self.spec['documentation_url'], 'native_data_url': self.spec['url'],
                  'survey_year': int(self.spec['survey_start'][:4]), 'datum': 'MLLW'}
        qualification = {'policy': VERSION, **RELEASE['qualification']}
        targets, areas = [], []
        self.tids = []
        half = RELEASE['area_half_width_deg']
        for index in range(len(views)):
            suffix = f'a{index:09x}'
            tid, aid = f'{prefix}-{suffix}', f'{prefix}-AREA-{suffix}'
            lon = RELEASE['first_target']['longitude'] + index * RELEASE['target_spacing_deg']
            lat = RELEASE['first_target']['latitude']
            self.tids.append(tid)
            targets.append({'id': tid, 'source_id': self.spec['id'], 'qualification': deepcopy(qualification),
                            'recorded_validation': deepcopy(RELEASE['recorded_validation']),
                            'depth_qualified': True, 'fishing_target': True, 'fishing_export': True,
                            'vertical_datum': 'MLLW', 'drift_id': None,
                            'rating': {'score_type': 'uncalibrated-habitat-rank', 'catch_probability': None},
                            'native_resolution_range_m': [1, 4], 'analysis_cell_m': 4,
                            'longitude': lon, 'latitude': lat, 'area_ids': [aid]})
            areas.append({'id': aid, 'source_id': self.spec['id'], 'target_ids': [tid],
                          'qualification': deepcopy(qualification),
                          'recorded_validation': deepcopy(RELEASE['recorded_validation']),
                          'geometry': polygon(lon - half, lat - half, lon + half, lat + half)})
        self.atlas = {'schema_version': 1, 'region_id': self.rid, 'edition': VERSION,
                      'fishing_depth_limit_ft': RELEASE['config']['depth_limit_ft'],
                      'targets': targets, 'areas': areas, 'drifts': [], 'sources': [source]}
        self.quality = {'schema_version': 1, 'region_id': self.rid, 'status': 'qualified-partial',
                        'transformation_version': VERSION, 'config_sha256': config_receipt['sha256'],
                        'habitat_sha256': habitat['sha256'], 'sources': [source],
                        'closure_receipts': closure_receipts,
                        'source_receipts': [{'url': self.spec['url'], 'sha256': self.spec['sha256'],
                                             'bytes': self.spec['bytes'], 'http_status': 206,
                                             'retrieved_at': RELEASE['checked_at']}],
                        'target_count': len(targets), 'area_count': len(areas), 'bottom_views': len(targets),
                        'claims': {'measured_datum': 'MLLW', 'depth_qualified': True, 'catch_calibrated': False,
                                   'boulder_size_measured': False, 'complete_island_coverage': False}}
        self.views = {'schema_version': 1, 'region_id': self.rid, 'views': {},
                      'sources': {self.spec['id']: {'source_id': self.spec['id'], 'sha256': self.spec['sha256'],
                                                    'url': self.spec['url'],
                                                    'survey_year': int(self.spec['survey_start'][:4]),
                                                    'vertical_datum': 'MLLW'}}}
        self.tiles = {}
        for tid, view in zip(self.tids, views):
            self.set_view(tid, view, publish=False)
        self.manifest = {'schema_version': 1, 'region_id': self.rid, 'status': 'ready',
                         'generated_at': RELEASE['checked_at'], 'transformation_version': VERSION, 'artifacts': {}}
        self.publish()
        mock = patch('skippercast.platform.qualified_scope.load_catalogs',
                     side_effect=lambda root: ({}, self.catalog))
        mock.start()
        test.addCleanup(mock.stop)

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(data, allow_nan=False) + '\n').encode()
        target.write_bytes(raw)
        return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

    def write_holds(self, holds):
        self.write('catalog/noaa-survey-lead-holds.json', {
            'schema_version': 1, 'scope': 'reviewed-noaa-survey-fishing-lead-holds', 'holds': holds})

    def write_config(self):
        return self.write(f'regions/{self.rid}/bottom-sources.reviewed.json', self.config)

    def set_view(self, tid, view, publish=True, **tile_changes):
        """Write one bottom view; ``view`` holds width, height, bytes and declared coverage."""
        tile = {'schema_version': 1, 'region_id': self.rid, 'target_id': tid, 'source_id': self.spec['id'],
                'source_sha256': self.spec['sha256'], 'source_url': self.spec['documentation_url'],
                'vertical_datum': 'MLLW', 'horizontal_crs': self.spec['horizontal_crs'],
                'depth_qualified': True, 'fishing_target': True, 'width': view['width'], 'height': view['height'],
                **RELEASE['tile'], 'coverage_fraction': view['declared'],
                'elevations': base64.b64encode(view['bytes']).decode()}
        tile.update(tile_changes)
        self.tiles[tid] = tile
        path = self.base + 'bottom/' + tid + '.json'
        receipt = self.write('dist/' + path, tile)
        self.views['views'][tid] = {'status': 'surveyed', 'path': path, 'source_id': self.spec['id'],
                                    'coverage_fraction': view.get('index_declared', view['declared']), **receipt}
        if publish:
            self.publish()

    def publish(self):
        """Rehash every artifact so only the semantic content under test can differ."""
        for name, data in (('atlas.json', self.atlas), ('quality.json', self.quality),
                           ('bottom-index-fragment.json', self.views)):
            self.manifest['artifacts'][name] = self.write(self.folder / name, data)
        self.write(self.folder / 'manifest.json', self.manifest)
        self.write('dist/' + self.region['assets']['bottom_index'], self.views)

    def integrity_mismatches(self):
        """Independent check that every hash/size receipt matches the bytes on disk."""
        problems = []
        for name, receipt in self.manifest['artifacts'].items():
            raw = (self.root / self.folder / name).read_bytes()
            if receipt != {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}:
                problems.append(name)
        index = json.loads((self.root / 'dist' / self.region['assets']['bottom_index']).read_text())
        for tid, record in index['views'].items():
            raw = (self.root / 'dist' / record['path']).read_bytes()
            if (record['sha256'], record['bytes']) != (hashlib.sha256(raw).hexdigest(), len(raw)):
                problems.append(tid)
        return problems

    def coverage_claims(self, tid):
        """(published tile claim, published index claim) as read back from disk."""
        index = json.loads((self.root / 'dist' / self.region['assets']['bottom_index']).read_text())
        record = index['views'][tid]
        return json.loads((self.root / 'dist' / record['path']).read_bytes())['coverage_fraction'], \
            record['coverage_fraction']

    def validate(self):
        return validate_qualified_scope(self.region, self.atlas, self.root)


def view(case, declared=None, **extra):
    return {'width': case['width'], 'height': case['height'], 'bytes': raster(case),
            'declared': case['declared'] if declared is None else declared, **extra}


class ReleaseTestCase(unittest.TestCase):
    def assert_ready(self, release):
        self.assertEqual(release.integrity_mismatches(), [])
        result = release.validate()
        self.assertTrue(result['ready'])
        self.assertEqual(result['target_count'], len(release.tids))
        return result

    def assert_rejected(self, release, reason):
        self.assertEqual(release.integrity_mismatches(), [])
        with self.assertRaisesRegex(ValueError, '^' + re.escape(reason) + '$'):
            release.validate()


class BaselineTests(ReleaseTestCase):
    """The frozen diagnostic pair: red on the unchanged validator, green after the repair."""

    def test_primary_regression(self):
        # A1: all-nodata bytes with tile and index both claiming full coverage.
        release = SyntheticRelease(self, [view(RASTERS['all_nodata'])])
        self.assertEqual(release.coverage_claims(release.tids[0]), (1, 1))
        self.assert_rejected(release, COVERAGE_REASON)

    def test_healthy_control(self):
        # Otherwise identical release with valid sample bytes and matching coverage.
        release = SyntheticRelease(self, [view(RASTERS['healthy'])])
        self.assert_ready(release)


class CoverageGateTests(ReleaseTestCase):
    def test_a1_all_nodata_claiming_full_coverage_is_rejected_with_intact_integrity(self):
        for case in (RASTERS['all_nodata'], RASTERS['mismatched'][0]):
            with self.subTest(width=case['width'], height=case['height']):
                release = SyntheticRelease(self, [view(case, declared=1)])
                self.assert_rejected(release, COVERAGE_REASON)
                # Only the raster bytes differ from a passing release.
                release.set_view(release.tids[0], {'width': case['width'], 'height': case['height'],
                                                   'bytes': bytes.fromhex('0001') * case['width'] * case['height'],
                                                   'declared': 1})
                self.assert_ready(release)

    def test_a2_matching_fractions_pass(self):
        for case in RASTERS['matching']:
            with self.subTest(case['name']):
                total = case['width'] * case['height']
                self.assertEqual(case['declared'], round(case['valid'] / total, 4))
                self.assert_ready(SyntheticRelease(self, [view(case)]))

    def test_a2_wrong_nonzero_fraction_fails_even_when_tile_and_index_agree(self):
        for case in RASTERS['mismatched']:
            with self.subTest(case['name']):
                total = case['width'] * case['height']
                self.assertNotEqual(case['declared'], round(case['valid'] / total, 4))
                release = SyntheticRelease(self, [view(case)])
                self.assertEqual(release.coverage_claims(release.tids[0]), (case['declared'], case['declared']))
                self.assert_rejected(release, COVERAGE_REASON)

    def test_a2_zero_actual_coverage_cannot_claim_positive_coverage(self):
        case = RASTERS['zero_actual']
        for claim in case['positive_claims']:
            with self.subTest(claim=claim):
                self.assert_rejected(SyntheticRelease(self, [view(case, declared=claim)]), COVERAGE_REASON)
        # An honest zero claim meets the coverage binding; no new minimum-coverage
        # policy is introduced here and the existing validator has none to relax.
        self.assert_ready(SyntheticRelease(self, [view(case, declared=0)]))

    def test_a2_largest_raster_rounds_like_the_producer(self):
        # 1025 x 1025 with one nodata cell: the producer writes round(1050624 / 1050625, 4) == 1.0.
        width = height = 1025
        data = bytes.fromhex(NODATA_HEX) + bytes.fromhex('0100') * (width * height - 1)
        self.assertEqual(round((width * height - 1) / (width * height), 4), 1.0)
        large = {'width': width, 'height': height, 'bytes': data}
        self.assert_ready(SyntheticRelease(self, [{**large, 'declared': 1.0}]))
        self.assert_rejected(SyntheticRelease(self, [{**large, 'declared': 0.9999}]), COVERAGE_REASON)

    def test_a2_every_target_view_is_bound_independently(self):
        good = view(RASTERS['matching'][1])
        bad = view(RASTERS['mismatched'][1])
        self.assert_ready(SyntheticRelease(self, [good, view(RASTERS['healthy'])]))
        for order in ((good, bad), (bad, good)):
            with self.subTest(first_valid=order[0] is good):
                self.assert_rejected(SyntheticRelease(self, list(order)), COVERAGE_REASON)


class RasterDecodeTests(ReleaseTestCase):
    def test_a3_signed_little_endian_samples_are_decoded(self):
        case = RASTERS['little_endian_signed']
        self.assert_ready(SyntheticRelease(self, [view(case)]))
        for claim in case['misread_claims']:
            with self.subTest(claim=claim):
                self.assert_rejected(SyntheticRelease(self, [view(case, declared=claim)]), COVERAGE_REASON)

    def test_a3_existing_raster_refusals_are_preserved(self):
        healthy = RASTERS['healthy']
        mismatched = view(RASTERS['all_nodata'])  # Would also fail coverage if it were reached.
        contract = [{'encoding': 'base64-int16-be'}, {'encoding': 'base64-float32-le'}, {'nodata': -9999},
                    {'nodata': None}, {'width': 0}, {'width': 1026}, {'height': 0}, {'height': 1026},
                    {'width': 2.0}, {'coverage_fraction': 1.5}, {'coverage_fraction': -0.25},
                    {'coverage_fraction': True}]
        incomplete = [base64.b64encode(raster(healthy)[:7]).decode(),
                      base64.b64encode(raster(healthy) + b'\x00').decode(),
                      base64.b64encode(raster(healthy)[:6]).decode(), '']
        for base in (view(healthy), mismatched):
            for change in contract:
                with self.subTest(change=change, base_valid=base is not mismatched):
                    release = SyntheticRelease(self, [base])
                    release.set_view(release.tids[0], base, **change)
                    self.assert_rejected(release, CONTRACT_REASON)
            with self.subTest('tile and index coverage disagree', base_valid=base is not mismatched):
                release = SyntheticRelease(self, [{**base, 'index_declared': 0.5}])
                self.assert_rejected(release, CONTRACT_REASON)
            for encoded in incomplete:
                with self.subTest(elevations_length=len(encoded), base_valid=base is not mismatched):
                    release = SyntheticRelease(self, [base])
                    release.set_view(release.tids[0], base, elevations=encoded)
                    self.assert_rejected(release, INCOMPLETE_REASON)
            for encoded in ('AAA', 'AAAA=AAA', '@@@@AAAAAAA=', 'AAEAAQABAAE'):
                with self.subTest(malformed=encoded, base_valid=base is not mismatched):
                    release = SyntheticRelease(self, [base])
                    release.set_view(release.tids[0], base, elevations=encoded)
                    self.assertEqual(release.integrity_mismatches(), [])
                    with self.assertRaises(binascii.Error) as caught:
                        release.validate()
                    self.assertNotIn(COVERAGE_REASON, str(caught.exception))


class ValidatorPreservationTests(ReleaseTestCase):
    def test_a4_ready_result_keeps_limited_scope(self):
        result = self.assert_ready(SyntheticRelease(self, [view(RASTERS['healthy'])]))
        self.assertEqual(result, {'ready': True, 'scope': 'Only the explicitly qualified survey footprints',
                                  'target_count': 1, 'complete_region_coverage': False, 'method': VERSION,
                                  'manifest': f"regions/{RELEASE['region_id']}/qualified-bottom/manifest.json",
                                  'current_legal_clearance': False, 'runtime_closure_screen_required': True})

    def test_a4_held_original_survey_still_blocks_before_coverage(self):
        url = 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11967/BAG/H11967_MB_VR_MLLW.bag'
        for case in (RASTERS['healthy'], RASTERS['all_nodata']):
            with self.subTest(valid=case['valid']):
                release = SyntheticRelease(self, [view(case)])
                release.write_holds([{'survey_id': 'H11967', 'disposition': 'withhold_from_fishing_promotion',
                                      'reason': 'Synthetic hold for SP1703.', 'report_sha256': 'b' * 64}])
                release.spec['url'] = url
                release.quality['config_sha256'] = release.write_config()['sha256']
                release.publish()
                self.assert_rejected(release, 'Reviewed original NOAA survey is held from fishing promotion')

    def test_a4_native_depth_and_footprint_checks_still_block(self):
        depth = 'Target exceeds its native depth or source-cell qualification'
        footprint = 'Qualified footprint intersects a protected or excluded area'
        resolution = 'Target overstates native resolution'
        for case in (RASTERS['healthy'], RASTERS['all_nodata']):
            with self.subTest('depth', valid=case['valid']):
                release = SyntheticRelease(self, [view(case)])
                for record in (release.atlas['targets'][0], release.atlas['areas'][0]):
                    record['qualification']['max_depth_including_uncertainty_and_margin_ft'] = 201
                release.publish()
                self.assert_rejected(release, depth)
            with self.subTest('native resolution', valid=case['valid']):
                release = SyntheticRelease(self, [view(case)])
                release.atlas['targets'][0]['native_resolution_range_m'] = [1, 8]
                release.publish()
                self.assert_rejected(release, resolution)
            with self.subTest('footprint', valid=case['valid']):
                release = SyntheticRelease(self, [view(case)])
                closure = RELEASE['closures'][0]
                lon = (closure['west'] + closure['east']) / 2
                lat = (closure['south'] + closure['north']) / 2
                release.atlas['targets'][0].update(longitude=lon, latitude=lat)
                release.atlas['areas'][0]['geometry'] = polygon(lon - .1, lat - .1, lon + .1, lat + .1)
                release.publish()
                self.assert_rejected(release, footprint)

    def test_a4_tile_identity_and_artifact_integrity_still_bound(self):
        release = SyntheticRelease(self, [view(RASTERS['healthy'])])
        release.set_view(release.tids[0], view(RASTERS['healthy']), source_sha256='c' * 64)
        self.assert_rejected(release, 'Bottom view source, target or datum identity mismatch')
        release = SyntheticRelease(self, [view(RASTERS['healthy'])])
        tile_path = release.root / 'dist' / release.views['views'][release.tids[0]]['path']
        # Same size, different bytes, stale receipt: integrity, not coverage, decides.
        tile_path.write_bytes(tile_path.read_bytes().replace(b'"coverage_fraction": 1', b'"coverage_fraction": 0'))
        with self.assertRaisesRegex(ValueError, '^Survey subset artifact integrity mismatch$'):
            release.validate()


if __name__ == '__main__':
    unittest.main()
