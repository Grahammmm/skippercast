"""Real, offline GRIB scan-direction regressions with ecCodes coordinate oracles."""
import numpy as np
import pytest

from skippercast.forecast.build import decode, subset

eccodes = pytest.importorskip('eccodes')


def message(*, negative=True, ascending=False, first=240, last=238,
            ni=3, missing=False, gaussian=False):
    sample = 'regular_gg_sfc_grib2' if gaussian else 'regular_ll_sfc_grib2'
    handle = eccodes.codes_grib_new_from_samples(sample)
    try:
        nj = eccodes.codes_get(handle, 'Nj') if gaussian else 2
        settings = {
            'Ni': ni, 'Nj': nj, 'iScansNegatively': int(negative),
            'jPointsAreConsecutive': 0, 'alternativeRowScanning': 0,
            'longitudeOfFirstGridPointInDegrees': first,
            'longitudeOfLastGridPointInDegrees': last,
            'iDirectionIncrementInDegrees': ((first - last) if negative else (last - first)) % 360 / (ni - 1),
        }
        if not gaussian:
            settings.update({
                'jScansPositively': int(ascending),
                'latitudeOfFirstGridPointInDegrees': 35 if ascending else 36,
                'latitudeOfLastGridPointInDegrees': 36 if ascending else 35,
                'jDirectionIncrementInDegrees': 1,
            })
        for key, value in settings.items():
            eccodes.codes_set(handle, key, value)
        values = np.arange(1, ni * nj + 1, dtype=float) * 10
        if missing:
            eccodes.codes_set(handle, 'bitmapPresent', 1)
            values[0] = eccodes.codes_get(handle, 'missingValue')
        eccodes.codes_set_values(handle, values)
        return eccodes.codes_get_message(handle)
    finally:
        eccodes.codes_release(handle)


def assert_coordinate_identity(encoded, decoded):
    """Compare every cell against coordinates read independently by ecCodes."""
    handle = eccodes.codes_new_from_message(encoded)
    try:
        latitudes = eccodes.codes_get_array(handle, 'latitudes')
        longitudes = eccodes.codes_get_array(handle, 'longitudes')
        values = eccodes.codes_get_values(handle)
        bitmap = (eccodes.codes_get_array(handle, 'bitmap')
                  if eccodes.codes_get(handle, 'bitmapPresent') else np.ones(len(values)))
    finally:
        eccodes.codes_release(handle)
    expected = {
        (round(float(lat), 6), round(float((lon + 180) % 360 - 180), 6)):
        float(value) if present else np.nan
        for lat, lon, value, present in zip(latitudes, longitudes, values, bitmap)
    }
    grid, lats, lons = decoded
    actual = {(round(float(lat), 6), round(float(lon), 6)): grid[row, col]
              for row, lat in enumerate(lats) for col, lon in enumerate(lons)}
    assert actual.keys() == expected.keys()
    for coordinate, value in expected.items():
        if np.isnan(value):
            assert np.isnan(actual[coordinate]), coordinate
        else:
            assert actual[coordinate] == value, coordinate


@pytest.mark.parametrize('gaussian', [False, True], ids=['regular_ll', 'regular_gg'])
def test_negative_i_coordinates_and_values_match_eccodes(gaussian):
    encoded = message(gaussian=gaussian)
    decoded = decode(encoded)
    assert_coordinate_identity(encoded, decoded)
    np.testing.assert_array_equal(decoded[2], [-122, -121, -120])
    if not gaussian:
        np.testing.assert_array_equal(decoded[1], [35, 36])
        np.testing.assert_array_equal(decoded[0], [[60, 50, 40], [30, 20, 10]])


def test_negative_i_california_subset_preserves_all_columns():
    encoded = message()
    result = subset(*decode(encoded))
    assert_coordinate_identity(encoded, result)
    np.testing.assert_array_equal(result[2], [-122, -121, -120])
    np.testing.assert_array_equal(result[0], [[60, 50, 40], [30, 20, 10]])


def test_positive_i_control_is_unchanged():
    encoded = message(negative=False, first=238, last=240)
    decoded = decode(encoded)
    assert_coordinate_identity(encoded, decoded)
    np.testing.assert_array_equal(decoded[1], [35, 36])
    np.testing.assert_array_equal(decoded[2], [-122, -121, -120])
    np.testing.assert_array_equal(decoded[0], [[40, 50, 60], [10, 20, 30]])
    assert_coordinate_identity(encoded, subset(*decoded))


def test_negative_i_with_ascending_latitude_does_not_double_flip():
    encoded = message(ascending=True)
    decoded = decode(encoded)
    assert_coordinate_identity(encoded, decoded)
    np.testing.assert_array_equal(decoded[1], [35, 36])
    np.testing.assert_array_equal(decoded[0], [[30, 20, 10], [60, 50, 40]])


def test_negative_i_bitmap_missing_stays_at_its_coordinate():
    encoded = message(missing=True)
    decoded = decode(encoded)
    assert_coordinate_identity(encoded, decoded)
    assert np.isnan(decoded[0][1, 2])
    assert np.isfinite(decoded[0]).sum() == 5
    assert_coordinate_identity(encoded, subset(*decoded))


@pytest.mark.parametrize('negative', [False, True], ids=['positive-i', 'negative-i'])
@pytest.mark.parametrize('full_circle', [False, True], ids=['antimeridian', 'full-circle'])
def test_cyclic_longitudes_preserve_coordinate_value_identity(negative, full_circle):
    ni, start, end = (4, 0, 270) if full_circle else (3, 179, 181)
    first, last = (end, start) if negative else (start, end)
    encoded = message(negative=negative, first=first, last=last, ni=ni)
    decoded = decode(encoded)
    assert_coordinate_identity(encoded, decoded)
    expected_lons = [0, 90, -180, -90] if full_circle else [179, -180, -179]
    np.testing.assert_array_equal(decoded[2], expected_lons)
    box = {'south': 35, 'north': 36, 'west': -180, 'east': 179 if full_circle else -179}
    regional = subset(*decoded, box=box)
    if full_circle:
        assert_coordinate_identity(encoded, regional)
    else:
        np.testing.assert_array_equal(regional[2], [-180, -179])
        np.testing.assert_array_equal(regional[0], decoded[0][:, 1:])
    assert np.all(np.diff(regional[2]) > 0)
