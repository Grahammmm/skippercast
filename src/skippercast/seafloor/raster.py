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
    if not horizontal.is_projected or any(a.unit_name != 'metre' for a in horizontal.axis_info):
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


def read_native(dataset, window, row, *, uncertainty_band=None, interpolated_band=None):
    if window.width * window.height > 1_048_576:
        raise ValueError('Use bounded native windows (at most 1,048,576 pixels)')
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
