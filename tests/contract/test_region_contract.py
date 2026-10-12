"""validate_region: schemas/region.schema.json for shape, imperative checks for cross-references.

The imperative shape checks (contracts._region_shape) now run only when
jsonschema is unavailable or SKIPPERCAST_VALIDATE=off. These tests prove the
two paths agree: both accept every committed region (source and compiled) and
both reject a bad input for every check that moved from code to the schema.
They also cover validate-on-write (validate.check and atomic_json(kind=)).
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfoNotFoundError

from skippercast import validate
from skippercast.platform import contracts
from skippercast.platform.contracts import REPO, ContractError, atomic_json, load_catalogs, read_json, validate_region

HAVE_JSONSCHEMA = validate.available()
NEEDS_JSONSCHEMA = 'jsonschema not installed (pip install -r requirements-test.txt); the survey-science CI job runs these'
REGIONS = sorted((REPO / 'regions').glob('*/region.json'))
COMPILED = sorted((REPO / 'dist/regions').glob('*/region.json'))


def without_jsonschema():
    return mock.patch.object(validate, 'available', return_value=False)


def morro():
    return read_json(REPO / 'regions/morro-bay/region.json')


def with_context(region):
    """morro-bay has no local contexts; borrow a valid one so context checks have something to break."""
    zones = region['marine_zones']
    region['contexts'] = {'harbor-mouth': {'name': 'Harbor mouth',
                                           'marine_zones': {'coastal': zones['coastal'], 'offshore': zones['offshore']},
                                           'stations': deepcopy(region['stations'])}}
    return region


def with_focus(region):
    region['map'].setdefault('focus_areas', []).insert(
        0, {'id': 'test-focus', 'name': 'Test focus', 'bounds': region['fishing_bounds']})
    return region


def with_local_area(region):
    region['map'].setdefault('local_areas', []).append(
        {'id': 'test-area', 'name': 'Test area', 'bounds': region['fishing_bounds'],
         'hidden_targets': [{'id': region['species'][0], 'reason': 'Survey held back',
                             'source_url': 'https://example.org/evidence'}]})
    return region


# One bad input for every check removed from the imperative path because the schema expresses it.
SHAPE_MUTATIONS = {
    'schema_version': lambda r: r.update(schema_version=2),
    'id pattern': lambda r: r.update(id='Morro_Bay'),
    'id trailing newline': lambda r: r.update(id='morro-bay\n'),
    'unknown status': lambda r: r.update(status='beta'),
    'published without intelligence': lambda r: r.pop('intelligence'),
    'depth limit zero': lambda r: r['boat'].update(bottom_depth_limit_ft=0),
    'depth limit too deep': lambda r: r['boat'].update(bottom_depth_limit_ft=2001),
    'depth limit boolean': lambda r: r['boat'].update(bottom_depth_limit_ft=True),
    'cruise zero': lambda r: r['boat'].update(cruise_knots=0),
    'cruise too fast': lambda r: r['boat'].update(cruise_knots=101),
    'cruise boolean': lambda r: r['boat'].update(cruise_knots=True),
    'species empty': lambda r: r.update(species=[]),
    'species duplicate': lambda r: r.update(species=r['species'] + r['species'][:1]),
    'focus area id': lambda r: with_focus(r)['map']['focus_areas'][0].update(id='Bad Id'),
    'focus area name': lambda r: with_focus(r)['map']['focus_areas'][0].update(name=''),
    'local area id': lambda r: with_local_area(r)['map']['local_areas'][-1].update(id='Bad Id'),
    'local area name': lambda r: with_local_area(r)['map']['local_areas'][-1].update(name=''),
    'hidden target reason': lambda r: with_local_area(r)['map']['local_areas'][-1]['hidden_targets'][0].update(reason=''),
    'context id': lambda r: with_context(r)['contexts'].update({'Bad Id': r['contexts'].pop('harbor-mouth')}),
    'context name': lambda r: with_context(r)['contexts']['harbor-mouth'].update(name=''),
    'context marine zone': lambda r: with_context(r)['contexts']['harbor-mouth']['marine_zones'].update(coastal='PZZ67'),
    'context zone trailing newline': lambda r: with_context(r)['contexts']['harbor-mouth']['marine_zones'].update(
        offshore=r['marine_zones']['offshore'] + '\n'),
    'context tide station': lambda r: with_context(r)['contexts']['harbor-mouth']['stations'].update(tide='941'),
    'context airport': lambda r: with_context(r)['contexts']['harbor-mouth']['stations'].update(airport='ksbp'),
    'context buoy': lambda r: with_context(r)['contexts']['harbor-mouth']['stations'].update(nearshore_buoy='4601'),
    'binding duplicate': lambda r: r['source_bindings'].update({'wind-ensemble': ['gefs-wind', 'gefs-wind']}),
    'binding not a list': lambda r: r['source_bindings'].update({'wind-ensemble': 'gefs-wind'}),
    'current model': lambda r: r['intelligence'].update(regional_current_model='hycom'),
    'wind model': lambda r: r['intelligence'].update(wind_ensemble_model='icon'),
    'wave provider': lambda r: r['intelligence'].update(wave_ensemble_provider='ecmwf'),
    'no verification stations': lambda r: r['intelligence'].update(verification_stations=[]),
    'verification station id': lambda r: r['intelligence']['verification_stations'][0].update(id='4601'),
    'verification station latitude': lambda r: r['intelligence']['verification_stations'][0].update(latitude=91),
    'verification station longitude': lambda r: r['intelligence']['verification_stations'][0].update(longitude=-181),
    'unknown base layer': lambda r: r['basemap'].update(relief=r['basemap']['aerial']),
    'aerial without check date': lambda r: r['basemap']['aerial'].pop('checked_at'),
    'aerial empty note': lambda r: r['basemap']['aerial'].update(note=''),
    'aerial undated window': lambda r: r['basemap']['aerial']['acquired'].update(first='May 2022'),
    'aerial source id': lambda r: r['basemap']['aerial'].update(source='USGS NAIP'),
}

# Cross-references the schema cannot express; both paths must still reject them.
CROSS_REFERENCE_MUTATIONS = {
    'bounds ordering': lambda r: r.update(bounds=[r['bounds'][2], r['bounds'][1], r['bounds'][0], r['bounds'][3]]),
    'unknown time zone': lambda r: r.update(timezone='America/Atlantis'),
    'unreviewed species': lambda r: r.update(species=r['species'] + ['kraken']),
    'duplicate forecast point': lambda r: r.update(forecast_points=r['forecast_points'] + r['forecast_points'][:1]),
    'forecast point outside bounds': lambda r: r['forecast_points'][0].update(latitude=r['bounds'][3] + 1),
    'unknown default point': lambda r: r.update(default_forecast_point='nowhere'),
    'unknown need': lambda r: r['source_bindings'].update({'telepathy': []}),
    'unknown source': lambda r: r['source_bindings'].update({'wind-ensemble': ['not-a-source']}),
    'duplicate local area': lambda r: with_local_area(with_local_area(r)),
    'hidden target not a regional species': lambda r: with_local_area(r)['map']['local_areas'][-1]['hidden_targets'][0].update(id='kraken'),
    'private closure url': lambda r: r.update(closure_check={'url': 'https://localhost/closures', 'source_id': 'not-bound'}),
    'context zone not scheduled': lambda r: with_context(r)['contexts']['harbor-mouth']['marine_zones'].update(coastal='PZZ999'),
    'asset escapes dist': lambda r: r['assets'].update(atlas='../secrets.json'),
    'aerial unknown source': lambda r: r['basemap']['aerial'].update(source='not-a-source'),
    'aerial source without live tiles': lambda r: r['basemap']['aerial'].update(source='ndbc-history'),
    'aerial acquired after its check': lambda r: r['basemap']['aerial']['acquired'].update(last='2026-10-09'),
}


def mutated(mutate):
    region = morro()
    mutate(region)
    return region


class ImperativeFallback(unittest.TestCase):
    """Runs everywhere, including the core CI job without jsonschema."""

    def test_every_committed_region_passes_without_jsonschema(self):
        self.assertGreaterEqual(len(REGIONS), 15)
        catalogs = load_catalogs(REPO)
        with without_jsonschema():
            for path in REGIONS + COMPILED:
                region = read_json(path)
                self.assertEqual(contracts.check_region_shape(region), 'imperative', path)
                validate_region(region, *catalogs, root=REPO)

    def test_fallback_rejects_every_shape_mutation(self):
        catalogs = load_catalogs(REPO)
        with without_jsonschema():
            for name, mutate in SHAPE_MUTATIONS.items():
                region = mutated(mutate)  # outside assertRaises: a broken mutation must not pass
                with self.subTest(name), self.assertRaises((ValueError, KeyError, TypeError)):
                    validate_region(region, *catalogs, root=REPO)

    def test_both_paths_reject_every_cross_reference_mutation(self):
        catalogs = load_catalogs(REPO)
        for name, mutate in CROSS_REFERENCE_MUTATIONS.items():
            region = mutated(mutate)
            with self.subTest(name), without_jsonschema(), self.assertRaises((ValueError, ZoneInfoNotFoundError)):
                validate_region(region, *catalogs, root=REPO)
            if HAVE_JSONSCHEMA:
                region = mutated(mutate)
                self.assertEqual(contracts.check_region_shape(region), 'schema', name)  # shape is fine
                with self.subTest(name), self.assertRaises((ValueError, ZoneInfoNotFoundError)):
                    validate_region(region, *catalogs, root=REPO)

    def test_switch_off_uses_the_fallback(self):
        with mock.patch.dict('os.environ', {'SKIPPERCAST_VALIDATE': 'off'}):
            self.assertFalse(validate.enabled())
            self.assertEqual(contracts.check_region_shape(morro()), 'imperative')
            self.assertFalse(validate.check('region', {'not': 'a region'}))
        self.assertTrue(validate.enabled({}))
        self.assertTrue(validate.enabled({'SKIPPERCAST_VALIDATE': 'on'}))

    def test_check_without_jsonschema_writes_anyway(self):
        with without_jsonschema(), tempfile.TemporaryDirectory() as directory:
            self.assertFalse(validate.check('daily-feed', {}))
            atomic_json(Path(directory) / 'latest.json', {}, kind='daily-feed')
            self.assertTrue((Path(directory) / 'latest.json').is_file())


@unittest.skipUnless(HAVE_JSONSCHEMA, NEEDS_JSONSCHEMA)
class SchemaPath(unittest.TestCase):
    def test_every_committed_region_passes_the_schema(self):
        catalogs = load_catalogs(REPO)
        for path in REGIONS + COMPILED:
            region = read_json(path)
            self.assertEqual(validate.errors('region', region), [], path)
            self.assertEqual(contracts.check_region_shape(region), 'schema', path)
            validate_region(region, *catalogs, root=REPO)

    def test_schema_rejects_every_shape_mutation_the_fallback_rejects(self):
        catalogs = load_catalogs(REPO)
        for name, mutate in SHAPE_MUTATIONS.items():
            region = mutated(mutate)
            with self.subTest(name):
                self.assertNotEqual(validate.errors('region', region), [])
                with self.assertRaises(ContractError):
                    validate_region(region, *catalogs, root=REPO)

    def test_schema_errors_keep_the_familiar_message(self):
        region = mutated(SHAPE_MUTATIONS['published without intelligence'])
        with self.assertRaisesRegex(ContractError, 'intelligence configuration') as caught:
            validate_region(region, *load_catalogs(REPO), root=REPO)
        self.assertIn("'intelligence' is a required property", str(caught.exception))

    def test_patterns_use_ecma_end_anchors(self):
        self.assertEqual(validate.ecma_pattern(r'^[a-z]{2}$'), r'^[a-z]{2}\Z')
        self.assertEqual(validate.ecma_pattern(r'^\$[$]$'), r'^\$[$]\Z')
        self.assertEqual(validate.errors('region', mutated(SHAPE_MUTATIONS['id trailing newline']))[:1],
                         ["id: 'morro-bay\\n' does not match '^[a-z][a-z0-9-]{1,63}$'"])


@unittest.skipUnless(HAVE_JSONSCHEMA, NEEDS_JSONSCHEMA)
class ValidateOnWrite(unittest.TestCase):
    FEEDS = REPO / 'tests/fixtures/feeds'

    def sample(self, name):
        return json.loads((self.FEEDS / name).read_text())

    def test_check_accepts_valid_and_detects_feed_kind(self):
        self.assertTrue(validate.check('daily-feed', self.sample('daily-latest.json')))
        self.assertTrue(validate.check('feed', self.sample('live-latest.json')))
        with self.assertRaisesRegex(ContractError, 'Cannot tell'):
            validate.check('feed', {'schema_version': 1})

    def test_bad_shape_raises_and_nothing_is_written(self):
        feed = self.sample('daily-latest.json')
        feed['catch_probability'] = 0.4
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'regions/morro-bay/latest.json'
            with self.assertRaisesRegex(ContractError, r'daily-feed does not match schemas/daily-feed.schema.json'):
                atomic_json(target, feed, kind='daily-feed')
            self.assertFalse(target.exists())
            self.assertFalse(target.parent.exists())

    def test_contract_error_is_a_value_error(self):
        # refresh_regions isolates per region on any exception; existing callers catch ValueError.
        self.assertTrue(issubclass(ContractError, ValueError))

    def test_refresh_records_a_bad_shape_as_a_failed_region(self):
        from unittest.mock import patch
        from scripts.refresh_regions import refresh
        feed = self.sample('live-latest.json')

        def collector(now, prior, region_id):
            document = {**feed, 'region_id': region_id}
            if region_id == 'crescent-city':
                document['schedule_minutes'] = 'thirty'
            return document
        with tempfile.TemporaryDirectory() as directory, \
                patch('scripts.refresh_regions.live', side_effect=collector), patch('builtins.print'):
            output = Path(directory)
            refresh('live', output)
            index = json.loads((output / 'regions/index.json').read_text())
        failed = [r for r in index['regions'] if r['status'] == 'failed']
        self.assertEqual([(r['region_id'], r['error_class']) for r in failed], [('crescent-city', 'ContractError')])

    def test_intelligence_is_checked_before_its_archive_is_written(self):
        from skippercast.pipeline import intelligence
        source = Path(intelligence.__file__).read_text()
        self.assertLess(source.index("validate.check('intelligence-feed',data)"), source.index('write_archive(target'))


if __name__ == '__main__':
    unittest.main()
