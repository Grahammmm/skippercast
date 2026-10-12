"""Private interpreted-bedrock geometry, not production habitat admission.

The caller qualifies original units, source rights, CRS transformation, depth
datum and cache identity. Inputs are unmodified valid bedrock interpretations
in the same projected metre CRS as normalized positive-down depth. This module
does not read/download files, infer rugosity, rank fish habitat or publish.
"""
from dataclasses import dataclass
import math

import numpy as np
from pyproj import CRS
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import unary_union

MAX_WINDOW_EDGE = 512


@dataclass(frozen=True)
class NativeFragments:
    crs: CRS
    by_record: dict


def _metre_crs(value):
    crs = CRS.from_user_input(value)
    if (not crs.is_projected or len(crs.axis_info) != 2
            or any(a.unit_conversion_factor != 1 for a in crs.axis_info)):
        raise ValueError('Interpreted bedrock needs a projected horizontal metre CRS')
    return crs


def _polygons(records):
    for key, geometry in records.items():
        if (not isinstance(key, str) or not key or geometry.geom_type not in
                ('Polygon', 'MultiPolygon') or not geometry.is_valid):
            raise ValueError('Keep invalid or unidentified original polygons held; no repair')


def window_fragments(records, depth_m, valid, affine, crs, *, depth_band_description):
    """Intersect one <=512² native depth window; never filter tile fragments.

    Every polygon is in the supplied CRS already. No reprojection, rasterization
    of geology, filling, smoothing, inset or simplification is performed.
    """
    crs = _metre_crs(crs)
    _polygons(records)
    if depth_band_description != 'depth_m_positive_down':
        raise ValueError('Require the verified normalized positive-down metre depth band')
    values, good = np.asarray(depth_m), np.asarray(valid)
    if (values.ndim != 2 or values.shape != good.shape or good.dtype != np.bool_
            or not np.issubdtype(values.dtype, np.floating)
            or not all(0 < n <= MAX_WINDOW_EDGE for n in values.shape)):
        raise ValueError('Require one bounded native floating depth and boolean valid mask')
    coefficients = tuple(affine)[:6]
    if (not all(math.isfinite(v) for v in coefficients)
            or affine.determinant == 0):
        raise ValueError('Require a finite nondegenerate native affine grid')
    mask = good & np.isfinite(values) & (values >= 7.62) & (values <= 91.44)
    parts = [shape(g) for g, value in shapes(mask.astype('uint8'), mask=mask,
                                            transform=affine) if value == 1]
    support = unary_union(parts)
    fragments = {}
    for key, geometry in records.items():
        result = geometry.intersection(support)
        if result.is_empty or result.area == 0:
            continue
        if not result.is_valid:
            raise ValueError('Invalid native intersection remains held')
        # Boundary-only pieces may accompany genuine area in a collection.
        area_parts = _area_parts(result)
        fragments[key] = unary_union(area_parts)
    return NativeFragments(crs, fragments)


def _area_parts(geometry):
    if geometry.geom_type == 'Polygon':
        return [geometry] if geometry.area > 0 else []
    if hasattr(geometry, 'geoms'):
        return [part for child in geometry.geoms for part in _area_parts(child)]
    return []


def assemble_components(batches, *, existing=None, min_area_m2=1000):
    """Join native fragments first, subtract an optional native baseline, then size.

    Returns (original record key, polygon) pairs in deterministic record order.
    Without a qualified baseline these are physical hypotheses, not additional
    habitat. A baseline must carry the identical horizontal CRS. Adjacent tiles
    must be assembled together before the minimum connected-component test.
    """
    if not math.isfinite(min_area_m2) or min_area_m2 <= 0:
        raise ValueError('Require a positive finite native component area')
    batches = list(batches)
    if not batches:
        return []
    crs = _metre_crs(batches[0].crs)
    grouped = {}
    for batch in batches:
        if not crs.equals(_metre_crs(batch.crs)):
            raise ValueError('Native tile CRS mismatch')
        _polygons(batch.by_record)
        for key, geometry in batch.by_record.items():
            grouped.setdefault(key, []).append(geometry)
    occupied = unary_union([])
    if existing is not None:
        if not crs.equals(_metre_crs(existing.crs)):
            raise ValueError('Native baseline CRS mismatch')
        _polygons(existing.by_record)
        occupied = unary_union(list(existing.by_record.values()))
    result = []
    for key in sorted(grouped):
        merged = unary_union(grouped[key])
        available = merged.difference(occupied)
        if not available.is_valid:
            raise ValueError('Invalid assembled native geometry remains held')
        result.extend((key, polygon) for polygon in _area_parts(available)
                      if polygon.area >= min_area_m2)
        # Even smaller physical fragments remain occupied for later records;
        # discarding an area does not make another interpretation independent.
        occupied = occupied.union(merged)
    return result
