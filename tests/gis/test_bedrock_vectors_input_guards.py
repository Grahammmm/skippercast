"""Argument-shape guards for the private bedrock fragment kernel; offline fixtures.

Contract: a caller bug in the argument types is refused by name with ValueError
(never silently reinterpreted, never an AttributeError/TypeError from deep inside),
while healthy inputs and every numeric result stay as before.
"""
import unittest
from decimal import Decimal
from fractions import Fraction

from affine import Affine
import numpy as np
from pyproj import CRS
from shapely.geometry import box

from skippercast.seafloor.bedrock_vectors import (
    NativeFragments, assemble_components, window_fragments,
)

CRS_METRES = CRS.from_epsg(26910)
AFFINE = Affine(10, 0, 0, 0, -10, 40)


def window(records, affine=AFFINE):
    return window_fragments(records, np.full((4, 4), 30., dtype='float32'),
                            np.ones((4, 4), dtype=bool), affine, CRS_METRES,
                            depth_band_description='depth_m_positive_down')


class AssembleComponentsGuards(unittest.TestCase):
    def setUp(self):
        self.batch = NativeFragments(CRS_METRES, {'a': box(0, 0, 40, 40)})

    def test_minimum_area_bool_refused_not_read_as_one_square_metre(self):
        # Bug caught: bool guard placed after the numeric test (or missing), so
        # True passes isfinite and > 0, means 1 m2 and keeps every sliver.
        for value in (True, False):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'real number'):
                assemble_components([self.batch], min_area_m2=value)

    def test_minimum_area_not_a_real_number_refused_by_name(self):
        # Bug caught: str/None/list reaching math.isfinite and raising TypeError,
        # a numpy bool slipping through as a number, NaN/inf losing their refusal.
        for value in ('1000', None, [1000], float('nan'), float('inf'), np.bool_(True)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'component area'):
                assemble_components([self.batch], min_area_m2=value)

    def test_decimal_minimum_area_accepted_but_nonfinite_or_nonpositive_refused(self):
        # Bug caught: the numeric guard keyed on numbers.Real alone rejects a
        # valid Decimal threshold; accepting Decimal must not let NaN/inf/sNaN/<=0 through.
        for value in (Decimal('NaN'), Decimal('sNaN'), Decimal('Infinity'),
                      Decimal('0'), Decimal('-5')):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'component area'):
                assemble_components([self.batch], min_area_m2=value)

    def test_minimum_area_refused_even_for_empty_batches(self):
        # Bug caught: the early `return []` for no batches hiding a bad area.
        with self.assertRaisesRegex(ValueError, 'real number'):
            assemble_components([], min_area_m2=True)

    def test_nonpositive_minimum_area_refusal_unchanged(self):
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'positive finite'):
                assemble_components([self.batch], min_area_m2=value)

    def test_batches_not_iterable_of_native_fragments_refused(self):
        # Bug caught: None / a lone NativeFragments / dict batch raising TypeError or
        # AttributeError ('crs') instead of a named ValueError.
        for batches in (None, 5, self.batch, [{'crs': CRS_METRES}], ['x'], 'ab',
                        [self.batch, None]):
            with self.subTest(batches=repr(batches)), self.assertRaisesRegex(
                    ValueError, 'NativeFragments'):
                assemble_components(batches)

    def test_batch_with_non_dict_records_or_non_geometry_refused(self):
        # Bug caught: a hand-built NativeFragments with a list or a string record.
        for by_record in ([box(0, 0, 1, 1)], {'a': 'x'}):
            with self.subTest(by_record=repr(by_record)), self.assertRaisesRegex(
                    ValueError, 'shapely geometries'):
                assemble_components([NativeFragments(CRS_METRES, by_record)])

    def test_healthy_assembly_and_generators_unchanged(self):
        # Control: the guards must not refuse real numbers (int, float, numpy) or
        # a generator of batches, and the 1600 m2 component count is unchanged.
        for value in (1000, 1000.0, np.float64(1000), np.int64(1000),
                      Decimal('1000'), Fraction(1000)):
            with self.subTest(value=value):
                rows = assemble_components([self.batch], min_area_m2=value)
                self.assertEqual([(k, g.area) for k, g in rows], [('a', 1600)])
        self.assertEqual(assemble_components([self.batch], min_area_m2=Decimal('2000')), [])
        self.assertEqual(len(assemble_components(iter([self.batch]))), 1)
        self.assertEqual(len(assemble_components([self.batch])), 1)  # 1000 m2 default
        self.assertEqual(assemble_components([self.batch], min_area_m2=2000), [])


class WindowFragmentsGuards(unittest.TestCase):
    def test_affine_must_be_an_affine_not_a_tuple(self):
        # Bug caught: a plain 6-tuple passes tuple(affine) and fails later with
        # AttributeError on .determinant.
        for affine in ((10, 0, 0, 0, -10, 40), [10, 0, 0, 0, -10, 40], None, 'x'):
            with self.subTest(affine=repr(affine)), self.assertRaisesRegex(
                    ValueError, 'affine.Affine'):
                window({'a': box(0, 0, 40, 40)}, affine)

    def test_records_must_be_a_dict_of_shapely_geometries(self):
        # Bug caught: list of records -> AttributeError 'items'; a string record
        # -> AttributeError 'geom_type'.
        for records in ([box(0, 0, 40, 40)], None, {'a': 'x'}, {'a': None},
                        {'a': box(0, 0, 40, 40).__geo_interface__}):
            with self.subTest(records=repr(records)[:40]), self.assertRaisesRegex(
                    ValueError, 'shapely geometries'):
                window(records)

    def test_existing_refusals_keep_their_names(self):
        # Control: a non-str key or a non-polygon geometry keeps the held-record
        # message; a bad CRS keeps the metre message.
        with self.assertRaisesRegex(ValueError, 'no repair'):
            window({1: box(0, 0, 40, 40)})
        with self.assertRaisesRegex(ValueError, 'no repair'):
            window({'a': box(0, 0, 40, 40).centroid})
        with self.assertRaisesRegex(ValueError, 'metre CRS'):
            window_fragments({'a': box(0, 0, 40, 40)}, np.full((4, 4), 30.),
                             np.ones((4, 4), dtype=bool), AFFINE, 4326,
                             depth_band_description='depth_m_positive_down')

    def test_healthy_window_and_assembly_unchanged(self):
        # Control: healthy 4x4 window yields one 1600 m2 component under the
        # 7.62-91.44 m band; a depth outside the band still drops out.
        fragments = window({'a': box(0, 0, 40, 40)})
        self.assertEqual(sorted(fragments.by_record), ['a'])
        self.assertEqual(fragments.crs, CRS_METRES)
        rows = assemble_components([fragments], min_area_m2=1000)
        self.assertEqual([(k, g.area) for k, g in rows], [('a', 1600)])
        deep = window_fragments({'a': box(0, 0, 40, 40)}, np.full((4, 4), 95.),
                                np.ones((4, 4), dtype=bool), AFFINE, CRS_METRES,
                                depth_band_description='depth_m_positive_down')
        self.assertEqual(deep.by_record, {})


if __name__ == '__main__':
    unittest.main()
