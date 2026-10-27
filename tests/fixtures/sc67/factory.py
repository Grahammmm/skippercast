"""Small, portable synthetic terrain-support fixtures for SC67.

Every value is built in memory from the reviewed legend; nothing here reads a
cache, raster, network source or box-specific path.
"""
import numpy as np

from skippercast.seafloor.terrain_support import ROUGH_CODES, SMOOTH_CODES

NODATA = -32768


def legend_grid():
    """A 3x3 int16 grid holding all four rough, all four smooth and one NoData code."""
    values = np.array([list(ROUGH_CODES[:3]),
                       [ROUGH_CODES[3], *SMOOTH_CODES[:2]],
                       [*SMOOTH_CODES[2:], NODATA]], dtype='int16')
    return values, values != NODATA


def expected_support(values):
    return np.isin(values, ROUGH_CODES) & (values != NODATA)


def reader_style_mask(values):
    """Mirror support_reader: a masked read whose mask is inverted into a plain boolean array."""
    read = np.ma.masked_equal(values, NODATA)
    return read.data, ~np.ma.getmaskarray(read)


def invalid_masks(values):
    """Malformed validity containers, keyed by class label.

    Integer zero/one masks select whole rows through NumPy fancy indexing; the
    first two rows of legend_grid hold only reviewed codes, so the unchecked
    baseline accepts them and returns a wrongly typed, wrongly derived result.
    """
    rows, cols = values.shape
    hidden = np.zeros(values.shape, dtype=bool)
    hidden[0, 0] = True  # a masked-off rough cell the unchecked path would count
    zero_one = np.zeros(values.shape, dtype='uint8')
    zero_one[0, :] = 1
    signed = np.zeros(values.shape, dtype='int64')
    signed[1, 1] = -2
    return {
        'uint8_zero_one': zero_one,
        'uint8_255': np.full(values.shape, 255, dtype='uint8'),
        'signed_fancy_index': signed,
        'float': np.ones(values.shape, dtype='float64'),
        'object': np.array([[True] * cols] * rows, dtype=object),
        'python_scalar': True,
        'numpy_scalar': np.True_,
        'zero_dimensional': np.array(True),
        'list': [[True] * cols for _ in range(rows)],
        'one_dimensional': np.ones(cols, dtype=bool),
        'broadcast_row': np.ones((1, cols), dtype=bool),
        'broadcast_column': np.ones((rows, 1), dtype=bool),
        'transposed_shape': np.ones((cols + 1, rows), dtype=bool),
        'three_dimensional': np.ones((1, rows, cols), dtype=bool),
        'masked_validity': np.ma.array(np.ones(values.shape, dtype=bool),
                                       mask=hidden),
    }
