"""Bounded native-resolution windows shared by original raster adapters."""
from dataclasses import dataclass
import math

import numpy as np
from pyproj import CRS
from rasterio.windows import Window, from_bounds
from rasterio.warp import transform_bounds


@dataclass
class NativeRaster:
    depth_m: np.ndarray
    valid: np.ndarray
    interpolated: np.ndarray | None
    uncertainty_m: np.ndarray | None
    transform: object
    crs: object
    vertical_datum: str
    resolution_m: float
    survey_id: str
    sha256: str


def bounds_window(dataset, bounds, *, bounds_crs='EPSG:4326', margin_m=100):
    horizontal = CRS.from_user_input(dataset.crs).to_2d()
    if not horizontal.is_projected or any(a.unit_name.lower() not in {'metre', 'meter', 'metres', 'meters'}
                                          or a.unit_conversion_factor != 1 for a in horizontal.axis_info):
        raise ValueError('Adapter requires a projected raster in meters')
    if dataset.transform.b or dataset.transform.d or dataset.transform.a <= 0 or dataset.transform.e >= 0:
        raise ValueError('Adapter requires a north-up raster')
    if not 0 <= margin_m <= 1000:
        raise ValueError('Invalid seam margin')
    left, bottom, right, top = transform_bounds(bounds_crs, horizontal, *bounds, densify_pts=41)
    raw = from_bounds(left-margin_m, bottom-margin_m, right+margin_m, top+margin_m,
                      transform=dataset.transform)
    x0, y0 = max(0, math.floor(raw.col_off)), max(0, math.floor(raw.row_off))
    x1 = min(dataset.width, math.ceil(raw.col_off + raw.width))
    y1 = min(dataset.height, math.ceil(raw.row_off + raw.height))
    if x1 <= x0 or y1 <= y0:
        raise ValueError('Requested window does not intersect source')
    return Window(x0, y0, x1-x0, y1-y0)


def chunks(window, size=512):
    for y in range(int(window.row_off), int(window.row_off + window.height), size):
        for x in range(int(window.col_off), int(window.col_off + window.width), size):
            yield Window(x, y, min(size, window.col_off + window.width-x),
                         min(size, window.row_off + window.height-y))


def _require_native_vertical(dataset, *, uncertainty_band=None):
    """Refuse metadata incompatible with the legacy metre/elevation reader.

    This adapter does not convert units or packed samples. Missing metadata
    retains the existing producer-elevation convention; it is not evidence of
    a resolved vertical contract or datum. Sources needing conversion belong in
    the evidence-bound coastal.vertical path, not an implicit conversion here.
    """
    metre_units = {'m', 'metre', 'metres', 'meter', 'meters'}
    for band in (1,) if uncertainty_band is None else (1, uncertainty_band):
        if dataset.scales[band-1] != 1 or dataset.offsets[band-1] != 0:
            raise ValueError('Native raster requires unpacked samples (scale=1, offset=0)')
        units = dataset.units[band-1]
        if units is not None and units.lower() not in metre_units:
            raise ValueError('Native raster requires vertical units in metres')
        for tags in (dataset.tags(), dataset.tags(band)):
            if 'z_units' in tags and tags['z_units'].lower() not in metre_units:
                raise ValueError('Native raster requires vertical units in metres')
            # Uncertainty magnitudes have no up/down convention. Only the
            # elevation band is negated to produce positive-down depth.
            if band == 1:
                for key in ('vertical_sign', 'z_positive', 'positive'):
                    if key in tags and tags[key] not in {'up', 'positive_up'}:
                        raise ValueError('Native raster requires positive-up elevation')
    if dataset.crs:
        crs = CRS.from_user_input(dataset.crs)
        parts = crs.sub_crs_list if crs.is_compound else [crs]
        verticals = [part for part in parts if part.is_vertical]
        if len(verticals) > 1:
            raise ValueError('Native raster requires an unambiguous vertical CRS')
        for vertical in verticals:
            if len(vertical.axis_info) != 1:
                raise ValueError('Native raster requires one vertical CRS axis')
            axis = vertical.axis_info[0]
            if axis.unit_name.lower() not in metre_units or axis.unit_conversion_factor != 1:
                raise ValueError('Native raster requires vertical CRS units in metres')
            # BAG stores an elevation array even when its CRS axis is depth.
            if dataset.driver != 'BAG' and axis.direction != 'up':
                raise ValueError('Native raster requires positive-up elevation CRS')


def read_native(dataset, window, row, *, uncertainty_band=None, interpolated_band=None):
    if window.width * window.height > 1_048_576:
        raise ValueError('Use bounded native windows (at most 1,048,576 pixels)')
    _require_native_vertical(dataset, uncertainty_band=uncertainty_band)
    elevation = dataset.read(1, window=window, masked=True).astype('float32')
    raw = elevation.filled(np.nan)
    valid = ~np.ma.getmaskarray(elevation) & np.isfinite(raw)
    depth = np.where(valid, -raw, np.nan).astype('float32')
    uncertainty = None
    if uncertainty_band:
        uncertainty = dataset.read(uncertainty_band, window=window, masked=True).astype('float32').filled(np.nan)
        uncertainty[~valid | ~np.isfinite(uncertainty) | (uncertainty < 0)] = np.nan
    interpolated = None
    if interpolated_band:
        flags = dataset.read(interpolated_band, window=window, masked=True)
        # Unknown flag values are conservatively excluded, never invented as measured.
        interpolated = np.ma.getmaskarray(flags) | (flags.filled(1) != 0)
    return NativeRaster(depth, valid, interpolated, uncertainty, dataset.window_transform(window),
                        CRS.from_user_input(dataset.crs).to_2d(), row['vertical_datum'],
                        max(dataset.res), row['id'], row['sha256'])
