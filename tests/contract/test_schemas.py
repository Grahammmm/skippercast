"""JSON Schema contracts in schemas/ against every committed config and generated file.

Live feeds are covered by small trimmed samples of the public branches in
tests/fixtures/feeds/ (data, conditions and forecasts, fetched 2026-09-28):
sources, reports and long arrays were cut, and the forecast tile keeps two
decodable time steps. Nothing here reads the network or var/.

jsonschema is an optional test dependency (requirements-test.txt). The core CI
job does not install it, so the schema checks skip there; the survey-science
job installs it and runs them. The command-line fallback is tested everywhere.
"""
from base64 import b64decode
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

from skippercast import validate
from tests._support import ROOT

try:
    import jsonschema  # noqa: F401
except ImportError:
    HAVE_JSONSCHEMA = False
else:
    HAVE_JSONSCHEMA = True


FEEDS = ROOT / 'tests/fixtures/feeds'
NEEDS_JSONSCHEMA = 'jsonschema not installed (pip install -r requirements-test.txt); the survey-science CI job runs these'


def load(path):
    return json.loads(Path(path).read_text())


@unittest.skipUnless(HAVE_JSONSCHEMA, NEEDS_JSONSCHEMA)
class SchemaFiles(unittest.TestCase):
    def test_every_schema_is_draft_2020_12_with_a_matching_id(self):
        from jsonschema import Draft202012Validator
        files = sorted((ROOT / 'schemas').glob('*.schema.json'))
        self.assertGreaterEqual(len(files), 15)
        for path in files:
            schema = load(path)
            Draft202012Validator.check_schema(schema)
            self.assertEqual(schema['$schema'], 'https://json-schema.org/draft/2020-12/schema', path.name)
            self.assertEqual(schema['$id'], 'https://skippercast.com/schemas/' + path.name)
        kinds = {name for name in validate.KINDS.values()}
        self.assertEqual(kinds | {'common.schema.json'}, {p.name for p in files})

    def test_every_reference_resolves_locally(self):
        def refs(node):
            if isinstance(node, dict):
                if isinstance(node.get('$ref'), str):
                    yield node['$ref']
                for value in node.values():
                    yield from refs(value)
            elif isinstance(node, list):
                for value in node:
                    yield from refs(value)
        for kind in validate.KINDS:
            schema = validate.validator(kind).schema
            resolver = validate.validator(kind)._resolver
            found = list(refs(schema))
            for ref in found:
                resolver.lookup(ref)  # raises Unresolvable; the registry never fetches remote schemas


@unittest.skipUnless(HAVE_JSONSCHEMA, NEEDS_JSONSCHEMA)
class CommittedFiles(unittest.TestCase):
    def assertValid(self, kind, path):
        problems = validate.errors(kind, load(path))
        self.assertEqual(problems, [], f'{path.relative_to(ROOT)} is not a valid {kind}')

    def test_region_configs(self):
        paths = sorted((ROOT / 'regions').glob('*/region.json'))
        self.assertGreaterEqual(len(paths), 15)
        for path in paths:
            self.assertValid('region', path)

    def test_catalogs(self):
        self.assertValid('sources-catalog', ROOT / 'catalog/sources.json')
        self.assertValid('data-needs', ROOT / 'catalog/data-needs.json')

    def test_jurisdictions_excluding_reviews(self):
        paths = sorted((ROOT / 'jurisdictions').glob('*.json'))
        self.assertGreaterEqual(len(paths), 5)
        for path in paths:
            self.assertValid('jurisdiction', path)

    def test_generated_region_packages(self):
        self.assertValid('published-regions', ROOT / 'dist/regions/index.json')
        listed = {row['id'] for row in load(ROOT / 'dist/regions/index.json')['regions']}
        packages = sorted(p for p in (ROOT / 'dist/regions').iterdir() if p.is_dir())
        self.assertEqual({p.name for p in packages}, listed)
        for package in packages:
            self.assertValid('region', package / 'region.json')
            self.assertValid('coverage', package / 'coverage.json')
            self.assertValid('region-manifest', package / 'manifest.json')
            if (package / 'intelligence.json').exists():
                self.assertValid('intelligence-feed', package / 'intelligence.json')

    def test_live_feed_samples(self):
        for kind, name in [('daily-feed', 'daily-latest.json'), ('live-feed', 'live-latest.json'),
                           ('intelligence-feed', 'intelligence.json'), ('regions-index', 'regions-index.json'),
                           ('forecast-index', 'forecast-index.json'), ('forecast-manifest', 'forecast-manifest.json'),
                           ('forecast-tile', 'forecast-tile.json')]:
            self.assertValid(kind, FEEDS / name)

    def test_forecast_tile_sample_decodes_to_its_declared_shape(self):
        tile = load(FEEDS / 'forecast-tile.json')
        manifest = load(FEEDS / 'forecast-manifest.json')
        cells = tile['nlat'] * tile['nlon']
        self.assertEqual(len(b64decode(tile['sea'])), (cells + 7) // 8)
        self.assertEqual(set(tile['fields']), set(manifest['fields']))
        for field in tile['fields'].values():
            self.assertEqual(len(b64decode(field['data'])), 2 * len(tile['times']) * cells)
        self.assertTrue(set(tile['times']) <= set(manifest['times']))


@unittest.skipUnless(HAVE_JSONSCHEMA, NEEDS_JSONSCHEMA)
class ContractsCatchDrift(unittest.TestCase):
    """A renamed key or a weakened fail-closed rule must fail without a schema change."""

    def rejects(self, kind, document):
        self.assertNotEqual(validate.errors(kind, document), [], f'{kind} accepted an invalid document')

    def accepts(self, kind, document):
        self.assertEqual(validate.errors(kind, document), [])

    def test_renamed_feed_keys_fail(self):
        for kind, name, key in [('daily-feed', 'daily-latest.json', 'health'),
                                ('live-feed', 'live-latest.json', 'generated_at'),
                                ('intelligence-feed', 'intelligence.json', 'completed_at'),
                                ('forecast-manifest', 'forecast-manifest.json', 'tiles'),
                                ('forecast-tile', 'forecast-tile.json', 'nlat')]:
            document = load(FEEDS / name)
            document[key + '_v2'] = document.pop(key)
            self.rejects(kind, document)

    def test_daily_feed_fail_closed_rules(self):
        base = load(FEEDS / 'daily-latest.json')
        for mutate in (lambda d: d.__setitem__('catch_probability', 0.4),
                       lambda d: d.__setitem__('bite_score', 7),
                       lambda d: d['reports'][0].__setitem__('coordinates', [35.3, -120.9]),
                       lambda d: d['reports'][0].__setitem__('depth_ft', 180),
                       lambda d: next(iter(d['sources'].values())).update(status='ok', data=None),
                       lambda d: next(iter(d['sources'].values())).update(status='fresh'),
                       lambda d: d['health'].update(status='good')):
            document = deepcopy(base)
            mutate(document)
            self.rejects('daily-feed', document)

    def test_publication_fields_from_pr_30_are_optional_but_paired(self):
        for kind, name in [('daily-feed', 'daily-latest.json'), ('live-feed', 'live-latest.json')]:
            document = load(FEEDS / name)
            self.assertNotIn('run_id', document)
            self.accepts(kind, document)
            self.accepts(kind, {**document, 'published_at': '2026-09-28T23:24:19Z', 'run_id': '12345678901'})
            self.rejects(kind, {**document, 'published_at': '2026-09-28T23:24:19Z'})
            self.rejects(kind, {**document, 'run_id': 'local'})
            self.rejects(kind, {**document, 'published_at': 'yesterday', 'run_id': 'local'})

    def test_failed_region_rows_from_pr_34(self):
        index = load(FEEDS / 'regions-index.json')
        failed = {'region_id': 'crescent-city', 'status': 'failed', 'error_class': 'ValueError',
                  'error': 'Unknown regional data need', 'completed_at': None, 'issues': ['refresh-failed']}
        self.accepts('regions-index', {**index, 'regions': index['regions'] + [failed]})
        self.rejects('regions-index', {**index, 'regions': [{**failed, 'completed_at': '2026-09-28T23:24:18Z'}]})
        self.rejects('regions-index', {**index, 'regions': [{**failed, 'status': 'degraded'}]})
        unhealthy = {**index['regions'][0], 'status': 'failed'}  # collection finished but critical data missing
        self.accepts('regions-index', {**index, 'regions': [unhealthy]})

    def test_catalog_rights_from_pr_33(self):
        catalog = load(ROOT / 'catalog/sources.json')
        source = deepcopy(catalog['sources'][0])
        source['rights'].update(commercial_use='permission-required', attribution_required=True,
                                commercial_note='Confirm with the co-producer before paid launch.')
        self.accepts('source', source)
        self.rejects('source', {**source, 'rights': {**source['rights'], 'commercial_use': 'maybe'}})
        self.rejects('source', {**source, 'rights': {**source['rights'], 'attribution_required': 'yes'}})
        approved = {**source, 'review_status': 'approved', 'rights': {**source['rights'], 'license': 'unresolved'}}
        self.rejects('source', approved)
        self.rejects('source', {**source, 'review_status': 'maybe'})

    def test_region_contract(self):
        region = load(ROOT / 'regions/morro-bay/region.json')
        for mutate in (lambda r: r.pop('stations'),
                       lambda r: r['marine_zones'].update(coastal='PZZ67'),
                       lambda r: r.update(status='beta'),
                       lambda r: r.update(bounds=[-121.2, 35.0, -120.5]),
                       lambda r: r['intelligence'].update(regional_current_model='hycom'),
                       lambda r: r['boat'].update(bottom_depth_limit_ft=5000),
                       lambda r: r.pop('intelligence')):
            document = deepcopy(region)
            mutate(document)
            self.rejects('region', document)
        draft = deepcopy(region)
        draft.pop('intelligence')
        self.accepts('region', {**draft, 'status': 'draft'})  # drafts may omit intelligence (validate_region)

    def test_forecast_contract(self):
        manifest = load(FEEDS / 'forecast-manifest.json')
        self.rejects('forecast-manifest', {**manifest, 'model': 'icon_global'})
        self.rejects('forecast-manifest', {**manifest, 'tiles': ['35-121']})
        tile = load(FEEDS / 'forecast-tile.json')
        name = next(iter(tile['fields']))
        broken = deepcopy(tile)
        broken['fields'][name]['scale'] = 0
        self.rejects('forecast-tile', broken)
        index = load(FEEDS / 'forecast-index.json')
        failed = {'status': 'failed', 'issue': 'no complete cycle published in the last 48 hours', 'kept_previous': True}
        self.accepts('forecast-index', {**index, 'models': {**index['models'], 'ecmwf_wam': failed}})
        self.rejects('forecast-index', {**index, 'models': {'ecmwf_wam': {**failed, 'status': 'ok'}}})


class CommandLine(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = validate.main([str(a) for a in args])
        return status, out.getvalue(), err.getvalue()

    def test_missing_jsonschema_prints_install_hint_and_exits_2(self):
        with mock.patch.dict(sys.modules, {'jsonschema': None}):
            status, _, err = self.run_cli('feed', FEEDS / 'live-latest.json')
        self.assertEqual(status, 2)
        self.assertIn('pip install -r requirements-test.txt', err)

    def test_feed_kind_is_detected_from_shape(self):
        self.assertEqual(validate.detect_feed(load(FEEDS / 'daily-latest.json')), 'daily-feed')
        self.assertEqual(validate.detect_feed(load(FEEDS / 'live-latest.json')), 'live-feed')
        self.assertEqual(validate.detect_feed(load(FEEDS / 'intelligence.json')), 'intelligence-feed')
        with self.assertRaises(ValueError):
            validate.detect_feed({'schema_version': 1})

    @unittest.skipUnless(HAVE_JSONSCHEMA, NEEDS_JSONSCHEMA)
    def test_exit_status_reports_validity(self):
        status, out, _ = self.run_cli('feed', FEEDS / 'live-latest.json', FEEDS / 'daily-latest.json')
        self.assertEqual(status, 0)
        self.assertIn('valid live-feed', out)
        self.assertIn('valid daily-feed', out)
        status, _, err = self.run_cli('region', FEEDS / 'live-latest.json')
        self.assertEqual(status, 1)
        self.assertIn('schema error', err)


if __name__ == '__main__':
    unittest.main()
