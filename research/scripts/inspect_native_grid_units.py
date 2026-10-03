#!/usr/bin/env python3
"""Bounded offline grid inspection; never a normalization or qualification receipt."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.windows import Window, from_bounds
from rasterio.warp import transform_bounds

from skippercast.platform.contracts import bbox
from skippercast.seafloor.io import sha256

VERSION = 'native-grid-unit-inspection-v1'


def geometry(dataset, bounds, max_pixels):
    """Select native pixels without a seam margin, reprojection or resampling."""
    bbox(list(bounds))
    if not isinstance(max_pixels, int) or not 0 < max_pixels <= 25_000_000:
        raise ValueError('Inspection requires a pixel bound up to 25,000,000')
    crs = CRS.from_user_input(dataset.crs).to_2d()
    tr = dataset.transform
    if tr.b or tr.d or tr.a <= 0 or tr.e >= 0:
        raise ValueError('Inspection requires a north-up grid')
    if len(crs.axis_info) != 2:
        raise ValueError('Missing horizontal axis units')
    factors = [a.unit_conversion_factor for a in crs.axis_info]
    if any(not math.isfinite(f) or f <= 0 for f in factors) or factors[0] != factors[1]:
        raise ValueError('Unsupported horizontal axis units')
    if crs.is_geographic:
        if any(a.unit_name.lower() != 'degree' for a in crs.axis_info):
            raise ValueError('Geographic inspection requires degree axes')
    elif not crs.is_projected:
        raise ValueError('Unsupported horizontal CRS')
    left, bottom, right, top = transform_bounds(4326, crs, *bounds, densify_pts=41)
    raw = from_bounds(left, bottom, right, top, transform=tr)
    x0, y0 = max(0, math.floor(raw.col_off)), max(0, math.floor(raw.row_off))
    x1 = min(dataset.width, math.ceil(raw.col_off + raw.width))
    y1 = min(dataset.height, math.ceil(raw.row_off + raw.height))
    if x1 <= x0 or y1 <= y0:
        raise ValueError('Requested window does not intersect source')
    window = Window(x0, y0, x1-x0, y1-y0)
    if window.width * window.height > max_pixels:
        raise ValueError('Native window exceeds pixel bound; select a smaller window')
    spacing = list(dataset.res)
    result = dict(horizontal_crs=crs.to_string(),
                  native_coordinate_spacing=spacing,
                  horizontal_axis_units=[a.unit_name for a in crs.axis_info])
    if crs.is_projected:
        result['projected_grid_spacing_m'] = [v*factors[0] for v in spacing]
        result['spacing_method'] = 'Native projected-coordinate increments converted to metres; not ground scale or survey accuracy.'
    else:
        geod = crs.get_geod()
        affine = dataset.window_transform(window)
        # Ellipsoidal longitude-step length depends on latitude. Sample every
        # native row center and its edges, bounding the entire requested window.
        ranges = [[math.inf, -math.inf], [math.inf, -math.inf]]
        for start in range(0, int(window.height)+1, 4096):
            indices = np.arange(start, min(start+4096, int(window.height)+1))
            lat = affine.f + indices*affine.e
            lon = np.full(lat.shape, affine.c + spacing[0]/2)
            dx = np.abs(geod.inv(lon, lat, lon+spacing[0], lat)[2])
            centers = lat[:-1] if indices[-1] == window.height else lat
            mid_lon = np.full(centers.shape, lon[0])
            mid_lat = centers-spacing[1]/2
            dx_mid = np.abs(geod.inv(mid_lon, mid_lat, mid_lon+spacing[0], mid_lat)[2])
            dy = np.abs(geod.inv(mid_lon, centers, mid_lon, centers-spacing[1])[2])
            for limits, samples in zip(ranges, (np.concatenate((dx, dx_mid)), dy)):
                if not np.isfinite(samples).all():
                    raise ValueError('Invalid geographic ground spacing')
                if samples.size:
                    limits[0] = min(limits[0], float(samples.min()))
                    limits[1] = max(limits[1], float(samples.max()))
        result['ellipsoidal_pixel_spacing_m_range'] = ranges
        result['spacing_method'] = 'Ellipsoidal native row/edge step lengths; variable ground spacing, not acquisition resolution or accuracy.'
    return window, crs, result


def inspect(path, bounds, *, value_convention, vertical_datum, max_pixels=25_000_000):
    """Inspect caller-declared metre values. No inferred vertical datum/units."""
    if value_convention not in {'elevation-m-positive-up', 'depth-m-positive-down'}:
        raise ValueError('Declare the source metre-value convention explicitly')
    if not isinstance(vertical_datum, str) or not vertical_datum.strip():
        raise ValueError('Declare a vertical datum or unknown')
    path = Path(path)
    source_hash = sha256(path)
    valid_count = shallow_count = 0
    values_hash, masks_hash = hashlib.sha256(), hashlib.sha256()
    with rasterio.open(path) as dataset:
        if dataset.count != 1:
            raise ValueError('Inspection requires an original single-band grid')
        window, crs, description = geometry(dataset, bounds, max_pixels)
        if window.width > 1_048_576:
            raise ValueError('Native row exceeds read bound; select a narrower window')
        to_geo = Transformer.from_crs(crs, 4326, always_xy=True)
        # Fixed complete row strips make the digest independent of TIFF blocks.
        strip_height = min(64, 1_048_576//int(window.width))
        for y in range(int(window.row_off), int(window.row_off+window.height), strip_height):
            chunk = Window(window.col_off, y, window.width,
                           min(strip_height, window.row_off+window.height-y))
            raw = dataset.read(1, window=chunk)
            mask = dataset.read_masks(1, window=chunk)
            values_hash.update(np.ascontiguousarray(raw).tobytes())
            masks_hash.update(np.ascontiguousarray(mask).tobytes())
            yy, xx = np.indices(raw.shape)
            x, lat_y = dataset.window_transform(chunk) * (xx+.5, yy+.5)
            lon, lat = to_geo.transform(x, lat_y)
            inside = (lon >= bounds[0]) & (lon < bounds[2]) & (lat >= bounds[1]) & (lat < bounds[3])
            valid = (mask != 0) & np.isfinite(raw) & inside
            depth = -raw.astype('float64') if value_convention == 'elevation-m-positive-up' else raw
            valid_count += int(valid.sum())
            shallow_count += int((valid & (depth > 0) & (depth <= 91.44)).sum())
        source_details = dict(source_crs_wkt=dataset.crs.to_wkt(),
                              native_window=list(window.flatten()),
                              native_window_affine=list(dataset.window_transform(window)),
                              native_dtype=dataset.dtypes[0], source_shape=[dataset.height, dataset.width])
    if sha256(path) != source_hash:
        raise ValueError('Source changed during inspection')
    return dict(version=VERSION, source_sha256=source_hash, source_bytes=path.stat().st_size,
                requested_bounds_wgs84=list(bounds), max_pixels=max_pixels,
                value_convention=value_convention, declared_vertical_datum=vertical_datum,
                valid_pixels_in_requested_bounds=valid_count,
                nominal_0_300ft_valid_grid_pixels=shallow_count,
                native_values_sha256=values_hash.hexdigest(), native_masks_sha256=masks_hash.hexdigest(),
                **description, **source_details,
                measured_support='unverified', interpolation_mask='unverified',
                terrain_eligible=False, exportable=False, coverage_credit=False,
                limitations='Inspection only. Source grid pixels may be interpolated. No fill, resampling, datum conversion, measured-support qualification, habitat ranking, area or legal clearance. Metre value convention and datum are caller declarations requiring publisher evidence.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--bounds', nargs=4, type=float, required=True, metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'))
    parser.add_argument('--value-convention', choices=['elevation-m-positive-up', 'depth-m-positive-down'], required=True)
    parser.add_argument('--vertical-datum', required=True)
    parser.add_argument('--max-pixels', type=int, default=25_000_000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (args.source.resolve() == args.output.resolve() or
            args.output.exists() and args.source.samefile(args.output)):
        parser.error('Output must not overwrite source')
    receipt = inspect(args.source, args.bounds, value_convention=args.value_convention,
                      vertical_datum=args.vertical_datum, max_pixels=args.max_pixels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # A predictable output+'.tmp' can be the input itself. Create an exclusive
    # new file instead, preserving originals and existing unrelated scratch.
    fd, temporary = tempfile.mkstemp(prefix='.'+args.output.name+'.', suffix='.tmp',
                                     dir=args.output.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(args.output)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
