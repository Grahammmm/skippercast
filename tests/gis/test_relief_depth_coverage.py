"""Synthetic fixtures for the depth-band coverage metric."""

import numpy as np
import pytest

from skippercast.relief.depth_coverage import depth_coverage


def _result(shallow=(0, 0, 0), deeper=(0, 0, 0), *, unknown=0, deepest=None, reaches=False):
    return {
        'bands': {
            name: {'measured_m2': measured, 'estimated_m2': estimated, 'unsurveyed_m2': unsurveyed}
            for name, (measured, estimated, unsurveyed) in (
                ('0-66ft', shallow), ('66-300ft', deeper), ('unknown-band', (0, 0, unknown))
            )
        },
        'deepest_m': deepest,
        'reaches_300ft': reaches,
    }


def test_C1_empty_lattice_returns_complete_zero_result():
    # A reduction on an empty grid must not raise or fabricate a deepest point.
    empty = np.empty((0, 2))
    result = depth_coverage(empty, empty, empty, cell_area_m2=2.5)
    assert result == _result()
    assert result['reaches_300ft'] is False


@pytest.mark.parametrize('field', [
    pytest.param('support', id='C1: support cannot broadcast'),
    pytest.param('water', id='C1: water cannot broadcast'),
    pytest.param('coarse', id='C1: coarse cannot broadcast'),
])
def test_C1_misaligned_arrays_raise_exact_error(field):
    # Broadcast-compatible shapes still describe different lattices.
    inputs = dict.fromkeys(('elevation', 'support', 'water', 'coarse'), np.zeros((2, 2)))
    inputs[field] = np.zeros((1, 2))
    with pytest.raises(ValueError) as error:
        depth_coverage(**inputs, cell_area_m2=1)
    assert type(error.value) is ValueError


def test_C2_support_validity_water_land_and_coarse_precedence():
    # Catch support overriding validity, coarse overriding survey, or either
    # dry or positive-up land cells leaking into an area or depth result.
    elevation = [[-3, -3, -40, -3, 1, -500], [np.nan, np.inf, -np.inf, np.nan, np.nan, np.nan]]
    support = [[3, 1, 2, 0, 3, 3], [3, 2, 1, 0, 0, 0]]
    water = [[True, True, True, True, True, False], [True, True, True, True, True, False]]
    coarse = [[-120, -40, -1, -40, -30, -10], [-3, -40, np.inf, np.nan, 2, -1]]
    result = depth_coverage(elevation, support, water, coarse=coarse, cell_area_m2=2.5)
    assert result == _result(shallow=(2.5, 5, 2.5), deeper=(0, 2.5, 2.5), unknown=5, deepest=40.0)
    assert type(result['deepest_m']) is float
    assert result['reaches_300ft'] is False


def test_C2_missing_coarse_keeps_survey_holes_in_unknown_band():
    # Relief's finite nodata sentinel is not a measured abyss, even with class 3.
    result = depth_coverage(
        [[np.nan, -np.finfo(np.float32).max]], [[0, 3]], [[True, True]], cell_area_m2=4,
    )
    assert result == _result(unknown=8)


@pytest.mark.parametrize('dtype', [np.float32, np.float64], ids=['float32', 'float64'])
@pytest.mark.parametrize('source', ['measured', 'estimated', 'unsurveyed'])
@pytest.mark.parametrize(('depth_m', 'band', 'reaches'), [
    pytest.param(0, 'shallow', False, id='C2: at sea level'),
    pytest.param(20.1167, 'shallow', False, id='C2: just shallower than 66 ft'),
    pytest.param(20.1168, 'shallow', False, id='C2: exactly 66 ft stays shallow'),
    pytest.param(20.1169, 'deeper', False, id='C2: just deeper than 66 ft'),
    pytest.param(91.4399, 'deeper', False, id='C3: just short of 300 ft'),
    pytest.param(91.44, 'deeper', True, id='C3: exactly 300 ft is in band and reaches'),
    pytest.param(91.4401, None, True, id='C3: beyond 300 ft reaches but adds no area'),
])
def test_C2_C3_depth_edges_per_source(depth_m, band, reaches, source, dtype):
    # One cell per case catches gaps, double counts, Float32 cutoff drift and
    # coarse-only depth being reported as surveyed depth.
    depth = np.array([depth_m], dtype=dtype)
    is_surveyed = source != 'unsurveyed'
    elevation = -depth if is_surveyed else np.full_like(depth, np.nan)
    support = [3] if source == 'measured' else [2]
    result = depth_coverage(elevation, support, [True], coarse=-depth, cell_area_m2=2.5)
    area = {
        'measured': (2.5, 0, 0), 'estimated': (0, 2.5, 0), 'unsurveyed': (0, 0, 2.5),
    }[source]
    assert result == _result(
        **({band: area} if band else {}),
        deepest=float(depth[0]) if is_surveyed else None,
        reaches=reaches and is_surveyed,
    )
