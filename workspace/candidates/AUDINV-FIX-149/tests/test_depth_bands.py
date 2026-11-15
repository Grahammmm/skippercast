"""Synthetic acceptance: disjoint metre bands and fail-closed normalized inputs."""
import importlib.util
import math
from pathlib import Path
import pytest

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('candidate_bands', PACKAGE / 'depth_bands.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
OPTIONS = dict(producer='synthetic-map', qualified=True, units='m', sign='positive_down', storage='normalized_depth')


def test_boundaries_once_and_metric_not_feet():
    values = [0, math.nextafter(91.44, 0), 91.44, math.nextafter(91.44, math.inf),
              math.nextafter(182.88, 0), 182.88, math.nextafter(182.88, math.inf), 300, 600]
    result = module.depth_bands(values, [True] * len(values), **OPTIONS)
    assert result['valid_cells_by_band'] == {'0-300ft': 3, '300-600ft': 3, '>600ft': 3}
    assert result['deepest_mapped_cell_m'] == 600
    assert result['visual_certified'] is False


@pytest.mark.parametrize('field,value', [('units', 'unknown'), ('units', 'ft'), ('sign', 'unknown'),
    ('sign', 'positive_up'), ('storage', 'raw'), ('qualified', False), ('producer', '')])
def test_reject_unqualified_semantics(field, value):
    with pytest.raises(ValueError):
        module.depth_bands([1], [True], **dict(OPTIONS, **{field: value}))


@pytest.mark.parametrize('values,mask', [([-1], [True]), ([float('nan')], [True]),
    ([float('inf')], [True]), ([1], []), ([1], [1]), ([True], [True]), ([float('nan')], [False])])
def test_reject_invalid_samples_even_unsupported(values, mask):
    with pytest.raises(ValueError):
        module.depth_bands(values, mask, **OPTIONS)


def test_unsupported_is_not_visual_or_source_depth_evidence():
    result = module.depth_bands([300], [False], **OPTIONS)
    assert sum(result['valid_cells_by_band'].values()) == 0
    assert result['deepest_mapped_cell_m'] is None
    assert result['quality'] == 'unavailable' and not result['visual_certified']
