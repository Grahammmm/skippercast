"""SC67: classify accepts only a same-shape two-dimensional boolean validity mask.

Integer masks would otherwise select rows through NumPy fancy indexing, and
broadcastable or masked containers would silently change which codes count.
Each refusal must happen before any code is selected or summarized.
"""
import unittest
from unittest.mock import patch

import numpy as np

from skippercast.seafloor import terrain_support
from tests.fixtures.sc67.factory import (NODATA, expected_support, invalid_masks, legend_grid,
                                         reader_style_mask)

TOKEN = 'invalid_terrain_support_mask'
MASK_CLASSES = tuple(invalid_masks(legend_grid()[0]))


def snapshot(item):
    if isinstance(item, np.ma.MaskedArray):
        return ('masked', item.data.tobytes(), item.data.dtype.str, item.shape,
                np.ma.getmaskarray(item).tobytes())
    if isinstance(item, np.ndarray):
        return ('array', item.tobytes(), item.dtype.str, item.shape)
    return ('other', repr(item))


class SupportMaskTests(unittest.TestCase):
    def assert_refused_before_selection(self, values, valid):
        before = (snapshot(values), snapshot(valid))
        with patch.object(np, 'unique', wraps=np.unique) as unique, \
                patch.object(np, 'floor', wraps=np.floor) as floor, \
                patch.object(np, 'isin', wraps=np.isin) as isin:
            with self.assertRaisesRegex(ValueError, TOKEN):
                terrain_support.classify(values, valid)
        self.assertEqual((unique.call_count, floor.call_count, isin.call_count), (0, 0, 0))
        self.assertEqual((snapshot(values), snapshot(valid)), before)

    def test_reviewed_codes_under_boolean_mask(self):
        values, valid = legend_grid()
        before = (snapshot(values), snapshot(valid))
        actual = terrain_support.classify(values, valid)
        self.assertIs(type(actual), np.ndarray)
        self.assertEqual(actual.dtype, np.bool_)
        self.assertEqual(actual.shape, values.shape)
        for code in terrain_support.ROUGH_CODES:
            self.assertTrue(actual[values == code].all(), code)
        for code in terrain_support.SMOOTH_CODES:
            self.assertFalse(actual[values == code].any(), code)
        self.assertFalse(actual[values == NODATA].any())
        np.testing.assert_array_equal(actual, expected_support(values))
        self.assertEqual((snapshot(values), snapshot(valid)), before)

    def test_masked_off_rough_code_stays_false(self):
        values, valid = legend_grid()
        valid[0, 0] = False
        actual = terrain_support.classify(values, valid)
        self.assertFalse(actual[0, 0])
        self.assertEqual(int(actual.sum()), len(terrain_support.ROUGH_CODES) - 1)

    def test_all_false_mask_has_no_support(self):
        values, _ = legend_grid()
        actual = terrain_support.classify(values, np.zeros(values.shape, dtype=bool))
        self.assertEqual(actual.dtype, np.bool_)
        self.assertEqual(actual.shape, values.shape)
        self.assertFalse(actual.any())

    def test_empty_same_shape_masks_have_no_support(self):
        for shape in ((0, 0), (0, 3), (3, 0)):
            with self.subTest(shape=shape):
                actual = terrain_support.classify(np.zeros(shape, dtype='int16'), np.zeros(shape, dtype=bool))
                self.assertEqual(actual.dtype, np.bool_)
                self.assertEqual(actual.shape, shape)

    def test_reader_style_masks_remain_valid(self):
        values, _ = legend_grid()
        for dtype in ('int16', 'int32', 'float32'):
            with self.subTest(dtype=dtype):
                data, valid = reader_style_mask(values.astype(dtype))
                before = (snapshot(data), snapshot(valid))
                actual = terrain_support.classify(data, valid)
                np.testing.assert_array_equal(actual, expected_support(values))
                self.assertEqual((snapshot(data), snapshot(valid)), before)

    def test_invalid_codes_still_refused_under_boolean_mask(self):
        for bad in (2, np.nan, -.5, np.inf):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as caught:
                    terrain_support.classify(np.array([[bad]]), np.ones((1, 1), dtype=bool))
                self.assertNotIn(TOKEN, str(caught.exception))

    def test_reject_values_list(self):
        values, valid = legend_grid()
        self.assert_refused_before_selection(values.tolist(), valid)

    def test_reject_values_one_dimensional(self):
        values, _ = legend_grid()
        self.assert_refused_before_selection(values.ravel(), np.ones(values.size, dtype=bool))

    def test_reject_values_three_dimensional(self):
        values, valid = legend_grid()
        self.assert_refused_before_selection(values[None], valid[None])

    def test_reject_values_masked_array(self):
        values, valid = legend_grid()
        self.assert_refused_before_selection(np.ma.masked_equal(values, NODATA), valid)


def _mask_test(label):
    def test(self):
        values, _ = legend_grid()
        self.assert_refused_before_selection(values, invalid_masks(values)[label])
    test.__name__ = 'test_reject_' + label
    test.__doc__ = 'Refuse the ' + label.replace('_', ' ') + ' validity class before selection.'
    return test


for _label in MASK_CLASSES:
    setattr(SupportMaskTests, 'test_reject_' + _label, _mask_test(_label))


if __name__ == '__main__':
    unittest.main()
