"""Reconcile a saved depth-coverage report without reading its source rasters."""

import math
from pathlib import Path

from skippercast.relief.package import decode_document

_INCLUDED_SCOPE = '0-300ft-plus-unknown'
_BANDS = ('0-66ft', '66-300ft', 'unknown-band')
_CLASSES = ('measured_m2', 'estimated_m2', 'unsurveyed_m2')


def _area(value: object, name: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            area = float(value)
        except OverflowError:
            pass
        else:
            if math.isfinite(area) and area >= 0:
                return area
    raise ValueError(f'{name} must be a finite nonnegative number')


def reconcile(
    coverage_path: Path, *, aggregate_m2: float, scope: str, tolerance_m2: float,
) -> dict:
    """Compare the sum of the report's exclusive areas to an independent total.

    ``scope`` must be ``0-300ft-plus-unknown``. The caller must establish that
    both inputs describe the same lattice; the scope tag alone cannot prove it.
    All-water totals are invalid because the producer excludes known depths
    past 300 ft. Tolerance is absolute in m², inclusive at the boundary.

    Missing bands or class areas raise ValueError, even when the remaining
    numbers reconcile. Class percentages describe the summed partition, not
    the independent check total, and are omitted on mismatch or zero area.
    """
    if scope == 'all-water':
        raise ValueError('all-water is not comparable: known depths past 300 ft are omitted')
    if scope != _INCLUDED_SCOPE:
        raise ValueError(f'aggregate scope must be {_INCLUDED_SCOPE}')
    aggregate = _area(aggregate_m2, 'aggregate_m2')
    tolerance = _area(tolerance_m2, 'tolerance_m2')
    bands = decode_document(coverage_path.read_bytes()).get('bands')
    if not isinstance(bands, dict) or bands.keys() != set(_BANDS):
        raise ValueError('incomplete or invalid bands: expected 0-66ft, 66-300ft and unknown-band')

    areas = {}
    for band in _BANDS:
        row = bands[band]
        if not isinstance(row, dict) or not row.keys() >= set(_CLASSES):
            raise ValueError(f'incomplete class areas in {band}')
        areas[band] = {key: _area(row[key], f'{band}.{key}') for key in _CLASSES}
    unknown = areas['unknown-band']
    if unknown['measured_m2'] or unknown['estimated_m2']:
        raise ValueError('unknown-band may only contain unsurveyed water')

    try:
        class_totals = {key: math.fsum(row[key] for row in areas.values()) for key in _CLASSES}
        band_totals = {band: math.fsum(row.values()) for band, row in areas.items()}
        total = math.fsum(area for row in areas.values() for area in row.values())
    except OverflowError as exc:
        raise ValueError('summed area must be finite') from exc
    delta = total - aggregate
    matched = abs(delta) <= tolerance
    result = dict(scope=scope, band_totals_m2=band_totals, class_totals_m2=class_totals,
                  total_m2=total, aggregate_m2=aggregate, tolerance_m2=tolerance,
                  delta_m2=delta, matched=matched)
    if matched and total > 0 and aggregate > 0:
        result['class_percentages'] = {key.removesuffix('_m2'): area / total * 100
                                       for key, area in class_totals.items()}
    return result
