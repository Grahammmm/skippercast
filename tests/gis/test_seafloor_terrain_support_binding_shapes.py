"""A malformed terrain-support binding is refused by name, never by a raw Python error.

Contract: ``validate_binding``, ``binding_digest`` and ``feature_evidence`` bind the
CSUMB rough/smooth interpretation to its reviewed depth product. A binding of the
wrong shape raises ``ValueError('Terrain support binding is malformed: ...')``; a
well-formed one keeps the pre-existing refusals, their messages and their order.
"""
from copy import deepcopy
import unittest

from skippercast.seafloor import terrain_support as support

MALFORMED = 'Terrain support binding is malformed'
# Written out here, not imported, so a dropped key in the source cannot hide itself.
BINDING_KEYS = ('depth_source_id', 'source_sha256', 'depth_archive_member', 'depth_cog_sha256',
                'profile', 'rough_codes', 'smooth_codes', 'reviewed_on', 'evidence',
                'archive_member')
EVIDENCE_KEYS = ('profile', 'source_sha256', 'archive_member', 'metadata_sha256', 'evidence')


def make_row():
    return {
        'id': 'src', 'kind': 'bathymetry', 'format': 'arcgrid', 'sha256': 'a' * 64,
        'archive_member': 'native/depth', 'evidence': ['e1'],
        'adapter_review': {'cog_sha256': 'b' * 64},
        'terrain_support': {
            'profile': 'csumb-native-rough-v1', 'rough_codes': list(support.ROUGH_CODES),
            'smooth_codes': list(support.SMOOTH_CODES), 'reviewed_on': '2020-01-01',
            'evidence': ['e1'], 'depth_source_id': 'src', 'source_sha256': 'a' * 64,
            'depth_archive_member': 'native/depth', 'depth_cog_sha256': 'b' * 64,
            'archive_member': 'native/classes', 'metadata_sha256': 'c' * 64},
    }


def with_binding(**changes):
    row = make_row()
    row['terrain_support'].update(changes)
    return row


def without_key(key):
    row = make_row()
    del row['terrain_support'][key]
    return row


class MalformedBindingTests(unittest.TestCase):
    def test_healthy_binding_and_absent_binding_are_unchanged(self):
        # Bug caught: the new shape guard rejects a good binding or an unbound row.
        row = make_row()
        before = deepcopy(row)
        self.assertIsNone(support.validate_binding(row))
        self.assertEqual(len(support.binding_digest(row)), 64)
        self.assertEqual(set(support.feature_evidence(row)), {
            'profile', 'binding_sha256', 'depth_source_id', 'source_sha256', 'archive_member',
            'metadata_sha256', 'same_survey_as_depth', 'independent_confirmation', 'meaning',
            'evidence'})
        self.assertEqual(row, before)
        absent = {k: v for k, v in row.items() if k != 'terrain_support'}
        for label, unbound in (('absent', absent), ('null', dict(row, terrain_support=None))):
            with self.subTest(unbound=label):
                self.assertIsNone(support.validate_binding(unbound))
                self.assertIsNone(support.feature_evidence(unbound))
        # adapter_review may be absent entirely: that is the old "no cog hash" mismatch.
        no_review = make_row()
        del no_review['adapter_review']
        with self.assertRaisesRegex(ValueError, 'must bind the exact reviewed native depth'):
            support.validate_binding(no_review)

    def test_each_missing_key_is_refused_by_name(self):
        # Bug caught: a missing key leaks KeyError (e.g. KeyError: 'profile').
        for key in BINDING_KEYS:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, MALFORMED + '.*' + key):
                support.validate_binding(without_key(key))

    def test_non_object_binding_is_refused_by_name(self):
        # Bug caught: a string/list binding leaks TypeError: string indices must be integers.
        for bad in ('csumb-native-rough-v1', ['profile'], 7, True, ''):
            row = dict(make_row(), terrain_support=bad)
            with self.subTest(binding=bad):
                with self.assertRaisesRegex(ValueError, MALFORMED):
                    support.validate_binding(row)
                with self.assertRaisesRegex(ValueError, MALFORMED):
                    support.binding_digest(row)
        for bad in ('csumb-native-rough-v1', ['profile'], 7, True):
            with self.subTest(feature_evidence=bad), self.assertRaisesRegex(ValueError, MALFORMED):
                support.feature_evidence(dict(make_row(), terrain_support=bad))

    def test_null_or_non_string_review_date_is_refused_by_name(self):
        # Bug caught: reviewed_on null leaks TypeError from date.fromisoformat.
        for bad in (None, 20200101, ['2020-01-01']):
            with self.subTest(reviewed_on=bad), self.assertRaisesRegex(ValueError, MALFORMED + '.*reviewed_on'):
                support.validate_binding(with_binding(reviewed_on=bad))

    def test_null_or_non_object_adapter_review_is_refused_by_name(self):
        # Bug caught: adapter_review null leaks AttributeError: 'NoneType' has no 'get'.
        for bad in (None, 'reviewed', ['cog_sha256']):
            row = dict(make_row(), adapter_review=bad)
            with self.subTest(adapter_review=bad), self.assertRaisesRegex(ValueError, MALFORMED + '.*adapter_review'):
                support.validate_binding(row)

    def test_missing_metadata_hash_is_refused_by_name_where_it_is_read(self):
        # Bug caught: feature_evidence leaks KeyError: 'metadata_sha256'. validate_binding does
        # not read that key, so it stays valid (the native reader checks it against the file).
        row = without_key('metadata_sha256')
        support.validate_binding(row)
        with self.assertRaisesRegex(ValueError, MALFORMED + '.*metadata_sha256'):
            support.feature_evidence(row)
        # binding_digest hashes whatever object it is given, as before.
        self.assertEqual(len(support.binding_digest(row)), 64)

    def test_feature_evidence_refuses_each_key_it_reads(self):
        # Bug caught: any other key read by feature_evidence leaking KeyError.
        for key in EVIDENCE_KEYS:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, MALFORMED + '.*' + key):
                support.feature_evidence(without_key(key))

    def test_existing_refusals_keep_message_and_order_for_wellformed_bindings(self):
        # Bug caught: the new key check runs ahead of, or replaces, the old refusals so an
        # old negative case sees a different message. Each case here is well-formed.
        legend = 'Unreviewed terrain support legend'
        bind = 'must bind the exact reviewed native depth product'
        cases = [
            ('wrong depth id', with_binding(depth_source_id='other'), bind),
            ('wrong cog hash', with_binding(depth_cog_sha256='d' * 64), bind),
            ('wrong profile', with_binding(profile='other'), legend),
            ('wrong rough codes', with_binding(rough_codes=[1]), legend),
            ('future review', with_binding(reviewed_on='2999-01-01'),
             'cannot be dated in the future'),
            ('empty evidence', with_binding(evidence=[]), 'original-source evidence'),
            ('uninventoried evidence', with_binding(evidence=['other']), 'original-source evidence'),
            ('null evidence', with_binding(evidence=None), 'original-source evidence'),
            ('null member', with_binding(archive_member=None), 'Unsafe terrain support archive member'),
            ('unsafe member', with_binding(archive_member='../x'), 'Unsafe terrain support archive member'),
            ('same member', with_binding(archive_member='native/depth'), 'separate categorical product'),
            # Order: identity before legend, legend before date, date before evidence,
            # evidence before member safety, safety before same-product.
            ('identity beats legend', with_binding(depth_source_id='other', profile='x'), bind),
            ('legend beats date', with_binding(profile='x', reviewed_on='2999-01-01'), legend),
            ('date beats evidence', with_binding(reviewed_on='2999-01-01', evidence=[]),
             'cannot be dated in the future'),
            ('evidence beats member', with_binding(evidence=[], archive_member='../x'),
             'original-source evidence'),
            ('safety beats same-product', with_binding(archive_member='native/depth/../depth'),
             'Unsafe terrain support archive member'),
        ]
        for name, row, message in cases:
            with self.subTest(case=name), self.assertRaisesRegex(ValueError, message) as caught:
                support.validate_binding(row)
            self.assertNotIn(MALFORMED, str(caught.exception))
        row = make_row()
        row['kind'] = 'multibeam'
        with self.assertRaisesRegex(ValueError, bind):
            support.validate_binding(row)


if __name__ == '__main__':
    unittest.main()
