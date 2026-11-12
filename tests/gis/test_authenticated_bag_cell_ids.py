"""Authenticated BAG cell identities name actual integer-indexed cells only."""
from decimal import Decimal
from fractions import Fraction

import numpy as np
import pytest
from rasterio.windows import Window

from skippercast.coastal.authenticated_v1 import adapter_bag
from skippercast.coastal.authenticated_v1.adapter_bag import OriginalRegularBagWindow
from tests.gis.test_authenticated_worker_v1 import capture, fixture  # noqa: F401

PREFIX = 'H11879:2m:1of5'
ROW_OFF, COL_OFF, HEIGHT, WIDTH = 7, 11, 4, 3
MESSAGE = 'Local cell indices must be integers'
OUTSIDE = 'Local cell index is outside the original window'


class _Index:
    def __init__(self, value):
        self.value = value

    def __index__(self):
        return self.value


def _window():
    shape = (HEIGHT, WIDTH)
    floats = np.zeros(shape)
    flags = np.zeros(shape, dtype=bool)
    return OriginalRegularBagWindow(
        source_id='synthetic', cell_id_prefix=PREFIX, source_sha256='0' * 64, metadata_sha256='1' * 64,
        elevation_m=floats, depth_m_positive_down=floats, product_uncertainty_m=floats,
        source_pair_valid=flags, qualifies_25_300ft_uncertainty_0_1m=flags, transform=None,
        horizontal_crs=None, source_crs_wkt='', vertical_datum='', spacing_m=(2.0, 2.0),
        row_off=ROW_OFF, col_off=COL_OFF, raw_elevation_data=floats, raw_uncertainty_data=floats,
        elevation_mask=flags, uncertainty_mask=flags)


def _expect(row, col):
    return f'{PREFIX}:{ROW_OFF + row}:{COL_OFF + col}'


NONINDEX = [
    0.5, 1.25, 0.0, 1.0, float('nan'), float('inf'), -float('inf'),
    np.float32(0.0), np.float32(1.0), np.float64(0.0), np.float64(1.0), np.float64(0.5),
    True, False, np.bool_(True), np.bool_(False),
    None, '1', b'1', Decimal(1), Fraction(1, 1), Fraction(1, 2), [1], (1,), object(),
    _Index(1.0), _Index('1'),
]


@pytest.mark.parametrize('bad', NONINDEX, ids=[f'{n}-{type(v).__name__}' for n, v in enumerate(NONINDEX)])
@pytest.mark.parametrize('axis', ['row', 'col'])
def test_noninteger_indices_refuse_with_named_type_error_in_each_position(bad, axis):
    window = _window()
    args = (bad, 1) if axis == 'row' else (1, bad)
    with pytest.raises(TypeError, match=MESSAGE):
        window.cell_id(*args)


def test_fractional_pair_refuses():
    with pytest.raises(TypeError, match=MESSAGE):
        _window().cell_id(0.5, 1.25)


@pytest.mark.parametrize('make', [int, np.int32, np.int64, np.uint64, np.uint8, _Index])
def test_integer_protocol_is_canonical_at_first_and_last_cells(make):
    window = _window()
    for row, col in ((0, 0), (HEIGHT - 1, WIDTH - 1), (HEIGHT - 1, 0), (0, WIDTH - 1)):
        identity = window.cell_id(make(row), make(col))
        assert identity == _expect(row, col)
        assert type(identity) is str and '.' not in identity and 'e' not in identity


@pytest.mark.parametrize('make', [int, np.int64, np.uint64, _Index])
def test_integer_bounds_remain_index_errors_on_each_axis(make):
    window = _window()
    # The row axis is HEIGHT long and the column axis WIDTH long; HEIGHT > WIDTH.
    assert window.cell_id(make(WIDTH), make(0)) == _expect(WIDTH, 0)
    for args in ((HEIGHT, 0), (0, WIDTH), (HEIGHT + 5, 0), (0, WIDTH + 5)):
        with pytest.raises(IndexError, match=OUTSIDE):
            window.cell_id(*(make(value) for value in args))


@pytest.mark.parametrize('make', [int, np.int64, _Index])
def test_negative_integers_remain_index_errors(make):
    window = _window()
    for args in ((-1, 0), (0, -1), (-HEIGHT, 0), (0, -WIDTH)):
        with pytest.raises(IndexError, match=OUTSIDE):
            window.cell_id(*(make(value) for value in args))


@pytest.mark.parametrize('huge', [2 ** 70, -(2 ** 70), 2 ** 64 - 1])
def test_huge_integers_remain_index_errors_without_overflow(huge):
    window = _window()
    for args in ((huge, 0), (0, huge)):
        with pytest.raises(IndexError, match=OUTSIDE):
            window.cell_id(*args)
        with pytest.raises(IndexError, match=OUTSIDE):
            window.cell_id(*(_Index(value) for value in args))
    if huge >= 0 and huge < 2 ** 64:
        with pytest.raises(IndexError, match=OUTSIDE):
            window.cell_id(np.uint64(huge), np.uint64(0))


def test_broken_index_noninteger_gets_named_type_error_but_other_errors_propagate():
    class Boom:
        def __index__(self):
            raise RuntimeError('user failure')

    window = _window()
    with pytest.raises(TypeError, match=MESSAGE):
        window.cell_id(_Index(1.5), 0)
    with pytest.raises(RuntimeError, match='user failure'):
        window.cell_id(Boom(), 0)


def test_identity_calls_leave_window_state_untouched():
    window = _window()
    before = {name: np.array(getattr(window, name)) for name in
              ('elevation_m', 'source_pair_valid', 'raw_elevation_data', 'elevation_mask')}
    offsets = (window.row_off, window.col_off, window.cell_id_prefix, window.metadata_sha256)
    for _ in range(2):
        assert window.cell_id(np.int64(1), 2) == _expect(1, 2)
        for bad in (0.5, 1.0, True, None):
            with pytest.raises(TypeError):
                window.cell_id(bad, 0)
        with pytest.raises(IndexError):
            window.cell_id(-1, 0)
    for name, array in before.items():
        assert np.array_equal(getattr(window, name), array)
    assert offsets == (window.row_off, window.col_off, window.cell_id_prefix, window.metadata_sha256)


def test_real_sealed_reader_returns_repaired_identity_object(fixture):  # noqa: F811
    root, bag, row, xmlsha, source, spec, grant = fixture
    with capture(fixture) as view:
        window = adapter_bag.read_snapshot_window(
            view, row, Window(2, 1, 3, 4), expected_metadata_sha256=xmlsha)
        assert type(window) is OriginalRegularBagWindow
        assert (window.row_off, window.col_off) == (1, 2)
        assert window.elevation_m.shape == (4, 3)
        prefix = window.cell_id_prefix
        snapshot_state = (window.row_off, window.col_off, window.transform,
                          window.metadata_sha256, window.elevation_m.copy(), window.elevation_mask.copy())
        for make in (int, np.int32, np.int64, np.uint64):
            assert window.cell_id(make(0), make(0)) == f'{prefix}:1:2'
            assert window.cell_id(make(3), make(2)) == f'{prefix}:4:4'
        for bad in (0.5, 1.0, np.float64(1.0), True, np.bool_(False), None, '1', Fraction(1, 1)):
            with pytest.raises(TypeError, match=MESSAGE):
                window.cell_id(bad, 0)
            with pytest.raises(TypeError, match=MESSAGE):
                window.cell_id(0, bad)
        for args in ((-1, 0), (4, 0), (0, 3), (0, -1)):
            with pytest.raises(IndexError, match=OUTSIDE):
                window.cell_id(*args)
        assert (window.row_off, window.col_off, window.transform, window.metadata_sha256) == snapshot_state[:4]
        assert np.array_equal(window.elevation_m, snapshot_state[4], equal_nan=True)
        assert np.array_equal(window.elevation_mask, snapshot_state[5])
