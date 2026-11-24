"""Source-rights helpers refuse malformed rows, id lists and deployment policy by name.

Contract: the package refuses with ValueError and a stated reason, never a bare
TypeError/AttributeError/KeyError, and never accepts a bare string as a source list.
Healthy rows stay byte-identical so a guard that rejects a good row is caught too.
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from skippercast.seafloor.rights import (CSUMB_CREDIT, CSUMB_LICENSE, CSUMB_NOTICE, CSUMB_POLICY,
                                         deployment_use, feature_rights, source_rights)

TODAY = date(2026, 9, 28)
UNQUALIFIED = 'Source publication rights are unqualified or conflict with producer review'
USGS = {'id': 'u', 'url': 'https://example.test/u', 'license': 'public-domain-us-gov', 'publisher': 'USGS'}
CSUMB = {'id': 'c', 'url': 'https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/a/b.tif',
         'license': CSUMB_LICENSE, 'publisher': 'CSUMB SFML', 'sha256': 'h',
         'rights_review': {'policy_url': CSUMB_POLICY, 'source_sha256': 'h', 'producer': 'CSUMB SFML',
                           'allowed_use': 'noncommercial', 'attribution': CSUMB_CREDIT,
                           'navigation_use': False, 'for_profit_permission': 'required-not-obtained',
                           'reviewed_on': '2026-01-01'}}


def refusal(call, *args, **kwargs):
    """Return the ValueError message; any other exception type, or none, fails the case."""
    try:
        call(*args, **kwargs)
    except ValueError as error:
        return str(error)
    raise AssertionError('accepted a malformed input without a ValueError')


def without(row, key):
    return {k: v for k, v in row.items() if k != key}


class MalformedSourceRowTests(unittest.TestCase):
    def test_healthy_rows_are_unchanged(self):
        # Bug caught: a new shape guard rejects or reshapes a row the existing contract accepts.
        self.assertEqual(source_rights(USGS), {
            'source_id': 'u', 'license': 'public-domain-us-gov', 'source_url': 'https://example.test/u',
            'policy_url': '', 'attribution': 'USGS',
            'notice': 'Original US government data; retain source attribution and survey limitations.'})
        self.assertEqual(source_rights(CSUMB, today=TODAY), {
            'source_id': 'c', 'license': CSUMB_LICENSE, 'source_url': CSUMB['url'],
            'policy_url': CSUMB_POLICY, 'attribution': CSUMB_CREDIT, 'notice': CSUMB_NOTICE,
            'commercial_use': 'permission-required', 'navigation_use': False, 'reviewed_on': '2026-01-01'})
        # a US-government row with an explicit review object keeps its policy URL
        reviewed = dict(USGS, adapter_review={'rights_source_url': 'https://example.test/policy'})
        self.assertEqual(source_rights(reviewed)['policy_url'], 'https://example.test/policy')
        # a US-government row without a publisher keeps the default credit
        self.assertEqual(source_rights(without(USGS, 'publisher'))['attribution'], 'Original USGS / NOAA survey')

    def test_existing_refusals_are_unchanged(self):
        # Bug caught: the guards loosen the future-date, for-profit or unknown-profile refusals.
        with self.assertRaisesRegex(ValueError, 'cannot be dated in the future'):
            source_rights(CSUMB, today=date(2025, 12, 31))
        with self.assertRaisesRegex(ValueError, 'For-profit publication requires'):
            source_rights(CSUMB, use='for-profit', today=TODAY)
        with self.assertRaisesRegex(ValueError, 'Unknown deployment source-use profile'):
            source_rights(CSUMB, use='other', today=TODAY)
        with self.assertRaisesRegex(ValueError, 'actual dated producer review'):
            source_rights(dict(CSUMB, rights_review=dict(CSUMB['rights_review'], reviewed_on=20260101)), today=TODAY)

    def test_malformed_rows_raise_a_named_value_error(self):
        # Bug caught: a malformed row escapes as TypeError/AttributeError/KeyError, or is accepted.
        review = CSUMB['rights_review']
        cases = (
            ('publisher None', dict(CSUMB, publisher=None), UNQUALIFIED),
            ('publisher int', dict(CSUMB, publisher=7), UNQUALIFIED),
            ('rights_review list', dict(CSUMB, rights_review=[]), UNQUALIFIED),
            ('rights_review None', dict(CSUMB, rights_review=None), UNQUALIFIED),
            ('rights_review string', dict(CSUMB, rights_review='reviewed'), UNQUALIFIED),
            ('usgs adapter_review None', dict(USGS, adapter_review=None), 'adapter_review must be an object'),
            ('usgs adapter_review list', dict(USGS, adapter_review=[]), 'adapter_review must be an object'),
            ('usgs without url', without(USGS, 'url'), 'requires a string id and url'),
            ('usgs without id', without(USGS, 'id'), 'requires a string id and url'),
            ('usgs id None', dict(USGS, id=None), 'requires a string id and url'),
            ('usgs url empty', dict(USGS, url=''), 'requires a string id and url'),
            ('csumb without id', without(CSUMB, 'id'), 'requires a string id and url'),
            ('row list', [], 'Source row must be an object'),
            ('row None', None, 'Source row must be an object'),
        )
        for label, row, reason in cases:
            with self.subTest(label):
                self.assertIn(reason, refusal(source_rights, row, today=TODAY))
        self.assertEqual(review, CSUMB['rights_review'])  # the control row was never mutated

    def test_each_named_reason_is_distinct(self):
        # Bug caught: two different malformed inputs collapse into one unhelpful message.
        reasons = set()
        for row in (dict(USGS, adapter_review=None), without(USGS, 'id'), [], dict(CSUMB, publisher=None)):
            reasons.add(refusal(source_rights, row, today=TODAY))
        self.assertEqual(len(reasons), 4)


class FeatureRightsIdTests(unittest.TestCase):
    SOURCES = {'a': USGS, 'b': USGS}

    def test_list_tuple_and_set_of_ids_still_resolve(self):
        # Bug caught: the type guard rejects the accepted list/tuple/set forms or changes order/dedupe.
        for ids in (['b', 'a', 'a'], ('a', 'b'), {'a', 'b'}, frozenset(('a', 'b'))):
            with self.subTest(ids=ids):
                self.assertEqual([r['source_id'] for r in feature_rights(ids, self.SOURCES)], ['u', 'u'])
        self.assertEqual(len(feature_rights(['a'], self.SOURCES)), 1)

    def test_generator_ids_still_resolve(self):
        # Bug caught: the type guard rejects the one-shot generators tests/unit/test_sc54_regression.py accepts.
        self.assertEqual(len(feature_rights((i for i in ('a', 'b')), self.SOURCES)), 2)

    def test_bare_string_or_non_string_ids_are_refused(self):
        # Bug caught: 'ab' is silently treated as the two source ids 'a' and 'b'.
        for label, ids in (('bare string', 'ab'), ('single id string', 'a'), ('None', None), ('int', 5),
                           ('dict', {'a': 1}), ('generator of non-strings', (i for i in (1, 2))), ('bytes', b'ab'),
                           ('list with None', ['a', None]), ('list with int', ['a', 1]),
                           ('list with list', ['a', ['b']])):
            with self.subTest(label):
                self.assertIn('must be a list, tuple or set of strings',
                              refusal(feature_rights, ids, self.SOURCES))

    def test_empty_and_unknown_ids_keep_their_existing_refusal(self):
        # Bug caught: the new guard shadows the incomplete-attribution refusal.
        for ids in ([], ['a', 'missing']):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, 'attribution is incomplete'):
                feature_rights(ids, self.SOURCES)


class DeploymentPolicyShapeTests(unittest.TestCase):
    def policy_use(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'deployments').mkdir()
            (root / 'deployments/production.json').write_text(text)
            return deployment_use(root)

    def test_healthy_policy_and_missing_policy_are_unchanged(self):
        # Bug caught: shape checks change the healthy result or the missing-file for-profit default.
        self.assertEqual(self.policy_use(json.dumps({'source_use': 'noncommercial', 'monetization': 'none'})),
                         'noncommercial')
        self.assertEqual(self.policy_use(json.dumps({'source_use': 'for-profit', 'monetization': 'paid'})),
                         'for-profit')
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(deployment_use(tmp), 'for-profit')

    def test_non_object_or_invalid_policy_raises_a_named_value_error(self):
        # Bug caught: a list/null policy raises AttributeError; truncated JSON surfaces a bare decode error.
        for label, text, reason in (
                ('list', '[]', 'Deployment policy must be a JSON object'),
                ('null', 'null', 'Deployment policy must be a JSON object'),
                ('string', '"noncommercial"', 'Deployment policy must be a JSON object'),
                ('number', '1', 'Deployment policy must be a JSON object'),
                ('truncated', '{"source_use":', 'Deployment policy is not valid JSON'),
                ('empty', '', 'Deployment policy is not valid JSON')):
            with self.subTest(label):
                self.assertIn(reason, refusal(self.policy_use, text))

    def test_object_policy_without_fields_keeps_its_existing_refusal(self):
        # Bug caught: the object check replaces the explicit source_use/monetization requirement.
        with self.assertRaisesRegex(ValueError, 'requires explicit source_use and monetization'):
            self.policy_use('{}')


if __name__ == '__main__':
    unittest.main()
