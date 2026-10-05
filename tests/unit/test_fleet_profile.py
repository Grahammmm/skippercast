"""The charter fleet profile contract: schemas/fleet-profile.schema.json plus policy (CF-05).

docs/plans/charter-fleet/design.md section 8. The fixtures in
tests/fixtures/fleet/profiles/ are synthetic: invented boats, 555-01XX phones,
handles from catalog/advisor/fixture-handles.json and 999xxxxxx MMSIs. The
policy checks run everywhere; the schema checks need the optional jsonschema
package, which the survey-science CI job installs.
"""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import unittest
from unittest import mock

from skippercast import validate
from skippercast.fleet import profile
from tests._support import FIXTURES, ROOT

PROFILES = FIXTURES / 'fleet/profiles'
NEEDS_JSONSCHEMA = 'jsonschema not installed (pip install -r requirements-test.txt); the survey-science CI job runs these'
SEEDED = [
    'boat.passengers_max: source_url on an off-limits host (www.fishingbooker.com)',
    'boat.mmsi: disagrees with boat.ais.mmsi and no conflicts[] entry names the MMSI',
    'boat.reputation.other[0]: numbers only (a rating or a count), never review text',
]


def load(name):
    return json.loads((PROFILES / name).read_text(encoding='utf-8'))


def prov(value, source='https://operator.example/', method='page'):
    return {'value': value, 'source_url': source, 'retrieved_at': '2026-10-04T10:20:00Z', 'method': method, 'confidence': 0.8}


class PolicyTests(unittest.TestCase):
    def test_valid_fixtures_have_no_policy_errors(self):
        for name in ('party.json', 'six-pack.json'):
            with self.subTest(name):
                self.assertEqual(profile.policy_errors(load(name)), [])

    def test_the_invalid_fixture_reports_each_seeded_error(self):
        self.assertEqual(profile.policy_errors(load('invalid.json')), SEEDED)

    def test_off_limits_hosts_match_subdomains_only(self):
        doc = load('party.json')
        for source, bad in (('https://m.facebook.com/x', True), ('https://fb.com/x', True), ('https://www.threads.net/x', True),
                            ('https://notfacebook.com/x', False), ('https://fb.community.example/x', False)):
            with self.subTest(source):
                doc['boat']['year_built'] = prov(1979, source)
                errors = profile.policy_errors(doc)
                self.assertEqual(bool(errors), bad, errors)

    def test_off_limits_source_url_in_a_conflict_fails(self):
        doc = load('six-pack.json')
        doc['conflicts'][0]['values'][1]['source_url'] = 'https://fareharbor.com/embeds/book/placeholder-example/'
        self.assertEqual(profile.policy_errors(doc), ['conflicts[0].values[1]: source_url on an off-limits host (fareharbor.com)'])

    def test_off_limits_values_need_a_page_source(self):
        doc = load('party.json')
        self.assertEqual(profile.policy_errors(doc), [], 'a booking link and Instagram read off the operator site pass')
        doc['boat']['booking_url'] = prov('https://fareharbor.com/embeds/book/placeholder-example/', method='search')
        doc['boat']['social']['instagram']['handle'] = prov('sea.example', method='inference')
        doc['boat']['website'] = prov('www.instagram.com/sea.example', method='search')
        errors = profile.policy_errors(doc)
        self.assertEqual([e.split(':')[0] for e in errors],
                         ['boat.website', 'boat.booking_url', 'boat.social.instagram.handle'])
        self.assertTrue(all("(method 'page')" in e for e in errors))

    def test_an_mmsi_conflict_entry_allows_a_disagreement(self):
        doc = load('party.json')
        doc['boat']['ais']['mmsi'] = prov('999000199')
        self.assertEqual(profile.policy_errors(doc), [SEEDED[1]])
        for field in ('mmsi', 'boat.mmsi', 'ais.mmsi'):
            with self.subTest(field):
                doc['conflicts'] = [{'field': field, 'note': 'listener statics disagree with the registry',
                                     'values': [{'value': '999000101', 'source_url': 'https://registry.example/'},
                                                {'value': '999000199', 'source_url': 'https://ais.example/'}]}]
                self.assertEqual(profile.policy_errors(doc), [])

    def test_reputation_other_is_numbers_only(self):
        doc = load('party.json')
        for value, ok in ((4.5, True), (37, True), ('4.5 stars', False), (True, False)):
            with self.subTest(value):
                doc['boat']['reputation']['other'] = [prov(value)]
                self.assertEqual(profile.policy_errors(doc) == [], ok)

    def test_notes_are_capped(self):
        doc = load('party.json')
        doc['notes'] = 'x' * profile.MAX_NOTES
        doc['boat']['ais']['notes'] = prov('y' * profile.MAX_NOTES)
        self.assertEqual(profile.policy_errors(doc), [])
        doc['notes'] += 'x'
        doc['boat']['ais']['notes'] = prov('y' * (profile.MAX_NOTES + 5))
        self.assertEqual(profile.policy_errors(doc), ['notes: 2001 characters; at most 2000',
                                                      'boat.ais.notes: 2005 characters; at most 2000'])

    def test_a_malformed_document_does_not_crash_the_policy(self):
        for doc in (None, [], {}, {'boat': []}, {'boat': {'ais': None, 'reputation': {'other': 'text'}}, 'conflicts': {}},
                    {'boat': {'mmsi': 'x'}, 'conflicts': [None, {'values': 'x'}, {'values': [None, {'source_url': 5}]}]}):
            with self.subTest(doc):
                self.assertIsInstance(profile.policy_errors(doc), list)

    def test_webmail_is_flagged_not_refused(self):
        doc = load('party.json')
        self.assertEqual(profile.review_flags(doc), [])
        doc['boat']['email_business'] = prov('sea.example' + '@' + 'Gmail.com')
        self.assertEqual(profile.policy_errors(doc), [])
        self.assertEqual(profile.review_flags(doc),
                         ['boat.email_business: webmail address; confirm it is published as the business contact'])


class OffLimitsListTests(unittest.TestCase):
    def test_the_d7_list(self):
        self.assertTrue({'fishingbooker.com', 'fareharbor.com', 'xola.com', 'fishdope.com', 'fishcity.app',
                         'instagram.com', 'facebook.com'} <= set(profile.OFF_LIMITS_HOSTS))

    def test_the_catalog_list_is_used_when_present(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'off-limits.json'
            self.assertEqual(profile.load_off_limits(path), profile.OFF_LIMITS_HOSTS)
            path.write_text(json.dumps({'hosts': ['Example-Booking.test', {'host': 'other.test', 'reason': 'terms'}]}))
            self.assertEqual(profile.load_off_limits(path), ('example-booking.test', 'other.test'))
            path.write_text(json.dumps(['one.test']))
            self.assertEqual(profile.load_off_limits(path), ('one.test',))
            path.write_text(json.dumps({'hosts': []}))
            with self.assertRaises(ValueError):
                profile.load_off_limits(path)

    def test_a_custom_list_applies(self):
        doc = load('six-pack.json')
        self.assertEqual(profile.policy_errors(doc, off_limits=['directory.example']),
                         ['boat.website: source_url on an off-limits host (directory.example)',
                          'conflicts[0].values[1]: source_url on an off-limits host (directory.example)'])


@unittest.skipUnless(validate.available(), NEEDS_JSONSCHEMA)
class SchemaTests(unittest.TestCase):
    def test_every_fixture_through_the_validator(self):
        results = {path.name: profile.validate_profile(json.loads(path.read_text(encoding='utf-8')))
                   for path in sorted(PROFILES.glob('*.json'))}
        self.assertEqual(results, {'invalid.json': SEEDED, 'party.json': [], 'six-pack.json': []})

    def test_section_8_changes(self):
        schema = json.loads((ROOT / 'schemas/fleet-profile.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(schema['properties']['schema_version'], {'const': '1.0.0'})
        self.assertTrue({'vessel_id', 'run_id', 'batch_id'} <= set(schema['required']))
        self.assertIn('waters', schema['properties']['boat']['required'])
        doc = load('party.json')
        for path, value in ((('schema_version',), '0.1.0'), (('region',), 'California'), (('region',), 'ca'),
                            (('vessel_id',), 'not-hex'), (('batch_id',), 'b1'), (('run_id',), ''),
                            (('boat', 'waters', 0, 'value'), 'lake'), (('boat', 'vessel_class', 'value'), 'kayak'),
                            (('boat', 'mmsi', 'value'), '12345'), (('boat', 'phone_business', 'value'), '(805) 555-0123'),
                            (('boat', 'name', 'source_url'), 'ftp://x.example/'), (('boat', 'name', 'method'), 'guess'),
                            (('boat', 'name', 'confidence'), 1.5)):
            with self.subTest(path):
                broken = deepcopy(doc)
                node = broken
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                self.assertNotEqual(validate.errors(profile.KIND, broken), [])
        for key in ('vessel_id', 'run_id', 'batch_id'):
            with self.subTest(missing=key):
                broken = deepcopy(doc)
                del broken[key]
                self.assertNotEqual(validate.errors(profile.KIND, broken), [])
        self.assertEqual(validate.errors(profile.KIND, doc), [])

    def test_cli_exit_status(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(profile.main([str(PROFILES / 'party.json'), str(PROFILES / 'six-pack.json')]), 0)
            self.assertEqual(profile.main([str(PROFILES / 'invalid.json')]), 1)
        self.assertIn('party.json: valid fleet-profile', out.getvalue())
        self.assertIn('invalid.json: 3 error(s)', err.getvalue())


class MissingDependencyTests(unittest.TestCase):
    def test_validate_profile_never_passes_on_policy_alone(self):
        with mock.patch.object(validate, 'validator', side_effect=validate.MissingDependency(validate.INSTALL_HINT)):
            with self.assertRaises(validate.MissingDependency):
                profile.validate_profile(load('party.json'))
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                self.assertEqual(profile.main([str(PROFILES / 'party.json')]), 2)
        self.assertIn('jsonschema', err.getvalue())


if __name__ == '__main__':
    unittest.main()
