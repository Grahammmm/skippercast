"""Explicit bounded reads from authenticated original regular BAG cells.

This primitive does not normalize, warp, fill or repair data. It returns source
cell values and registration for private diagnostics; it does not qualify a
habitat polygon or assert parity with the production EPSG:3310 pipeline.
"""
from dataclasses import dataclass
import math
from pathlib import Path
import re
from urllib.parse import urlparse
import hashlib

import h5py
import numpy as np
import rasterio
from pyproj import CRS
from rasterio.windows import Window

from skippercast.platform.bottom_targets import bag_metadata, source_url_allowed
from ..io import sha256


MAX_NATIVE_WINDOW_SLOTS = 262_144
METERS_PER_FOOT = 0.3048
MINIMUM_DEPTH_FT = 25
MAXIMUM_DEPTH_FT = 300
MAX_PRODUCT_UNCERTAINTY_M = 1


@dataclass(frozen=True)
class OriginalRegularBagWindow:
    source_id: str
    cell_id_prefix: str
    source_sha256: str
    metadata_sha256: str
    elevation_m: np.ndarray
    depth_m_positive_down: np.ndarray
    product_uncertainty_m: np.ndarray
    source_pair_valid: np.ndarray
    qualifies_25_300ft_uncertainty_0_1m: np.ndarray
    transform: object
    horizontal_crs: CRS
    source_crs_wkt: str
    vertical_datum: str
    spacing_m: tuple[float, float]
    row_off: int
    col_off: int

    def cell_id(self, row, col):
        if not (0 <= row < self.elevation_m.shape[0] and 0 <= col < self.elevation_m.shape[1]):
            raise IndexError('Local cell index is outside the original window')
        return f'{self.cell_id_prefix}:{self.row_off + row}:{self.col_off + col}'


def _integer_window(window):
    if not isinstance(window, Window):
        raise ValueError('An explicit rasterio Window is required')
    values = (window.row_off, window.col_off, window.height, window.width)
    if any(not math.isfinite(float(value)) or not float(value).is_integer() for value in values):
        raise ValueError('Native source windows require integer pixel offsets and sizes')
    row_off, col_off, height, width = (int(value) for value in values)
    if row_off < 0 or col_off < 0 or height <= 0 or width <= 0:
        raise ValueError('Native source window must have positive in-bounds dimensions')
    slots = height * width
    if slots > MAX_NATIVE_WINDOW_SLOTS:
        raise ValueError(f'Native source window exceeds {MAX_NATIVE_WINDOW_SLOTS} full-cell slots')
    return Window(col_off, row_off, width, height), row_off, col_off


def read_original_regular_bag_window(path, row, window, *, expected_metadata_sha256):
    """Authenticate one regular original BAG and read a capped native window.

    ``row`` is the existing inventoried source record. Its URL, original-byte
    hash, declared datum, horizontal CRS and nominal spacing are all checked;
    the exact embedded-metadata hash is separately required from reviewed source
    evidence. Cell qualification uses only direct depth and product uncertainty.
    """
    path = Path(path)
    if row.get('kind') != 'bathymetry' or row.get('format') != 'bag':
        raise ValueError('Only an inventoried original bathymetry BAG is supported')
    url = row.get('url', '')
    filename = Path(urlparse(url).path).name
    pattern = re.fullmatch(r'(H\d+)_MB_(\d+)m_MLLW_(\d+of\d+)\.bag', filename)
    if (not source_url_allowed(url) or path.suffix.lower() != '.bag' or row.get('title') != filename
            or pattern is None):
        raise ValueError('Original BAG path must match its inventoried NOAA source URL')
    expected_sha = row.get('sha256')
    if not isinstance(expected_sha, str) or sha256(path) != expected_sha:
        raise ValueError('Original BAG bytes do not match the inventoried source hash')
    if (not isinstance(expected_metadata_sha256, str) or len(expected_metadata_sha256) != 64
            or any(ch not in '0123456789abcdef' for ch in expected_metadata_sha256)):
        raise ValueError('An exact reviewed embedded-metadata SHA-256 is required')
    bounded_window, row_off, col_off = _integer_window(window)

    try:
        with h5py.File(path, 'r') as original:
            if 'BAG_root' not in original:
                raise ValueError('Source is not a regular BAG HDF5 product')
            bag_root = original['BAG_root']
            if ('varres_refinements' in bag_root
                    and bag_root['varres_refinements'].size > 0):
                raise ValueError('Variable-resolution BAG is not accepted by this regular-grid reader')
            if not {'elevation', 'uncertainty', 'metadata'} <= set(bag_root.keys()):
                raise ValueError('Original BAG must contain elevation, uncertainty and metadata datasets')
            if bag_root['elevation'].shape != bag_root['uncertainty'].shape:
                raise ValueError('Original BAG depth and uncertainty grids do not align')
            if bag_root['metadata'].size > 1_000_000:
                raise ValueError('Oversized BAG metadata')
            xml = bag_root['metadata'][:].tobytes().decode('utf-8').rstrip('\0')
    except (OSError, KeyError) as error:
        raise ValueError('Unable to authenticate original BAG structure and metadata') from error

    metadata_hash = hashlib.sha256(xml.encode()).hexdigest()
    if metadata_hash != expected_metadata_sha256:
        raise ValueError('Embedded BAG metadata hash does not match reviewed source evidence')
    survey_id = Path(urlparse(url).path).name.split('_')[0]
    cell_prefix = f'{pattern.group(1)}:{pattern.group(2)}m:{pattern.group(3)}'
    metadata = bag_metadata(xml, survey_id, strict=True)
    if metadata['vertical_datum'] != 'MLLW' or metadata['uncertainty_type'] != 'productUncert':
        raise ValueError('Original BAG must declare MLLW and productUncert')
    if row.get('vertical_datum') != 'MLLW':
        raise ValueError('Inventoried source datum must be MLLW')

    with rasterio.open(path) as dataset:
        if dataset.driver != 'BAG' or dataset.count != 2 or not dataset.crs:
            raise ValueError('Expected an original regular BAG with elevation and uncertainty bands')
        if (bounded_window.col_off + bounded_window.width > dataset.width
                or bounded_window.row_off + bounded_window.height > dataset.height):
            raise ValueError('Native source window exceeds the original BAG bounds')
        source_crs = CRS.from_user_input(dataset.crs)
        if not source_crs.is_compound:
            raise ValueError('Original BAG GDAL CRS must retain its compound horizontal and vertical CRS')
        sub_crs = source_crs.sub_crs_list
        horizontal_parts = [part for part in sub_crs if part.is_projected or part.is_bound]
        vertical_parts = [part for part in sub_crs if part.is_vertical]
        if len(horizontal_parts) != 1 or len(vertical_parts) != 1:
            raise ValueError('Original BAG compound CRS must contain one horizontal and one vertical component')
        horizontal_part = horizontal_parts[0]
        horizontal = horizontal_part.source_crs if horizontal_part.is_bound else horizontal_part.to_2d()
        vertical = vertical_parts[0]
        if ('MLLW' not in vertical.name or len(vertical.axis_info) != 1
                or vertical.axis_info[0].unit_name.lower() not in {'metre', 'meter', 'metres', 'meters'}
                or vertical.axis_info[0].unit_conversion_factor != 1):
            raise ValueError('Original BAG GDAL vertical CRS must retain MLLW depth in metres')
        expected_crs = CRS.from_user_input(row.get('horizontal_crs', ''))
        metadata_crs = CRS.from_wkt(metadata['horizontal_wkt'])
        metadata_horizontal = (metadata_crs.source_crs if metadata_crs.is_bound
                               else metadata_crs.to_2d())
        if (not horizontal.is_projected
                or expected_crs.to_epsg() is None
                or horizontal.to_epsg() != expected_crs.to_epsg()
                or not horizontal.equals(expected_crs)
                or metadata_horizontal.to_epsg() != expected_crs.to_epsg()
                or not metadata_horizontal.equals(expected_crs)
                or any(axis.unit_name.lower() not in {'metre', 'meter', 'metres', 'meters'}
                       or axis.unit_conversion_factor != 1 for axis in horizontal.axis_info)):
            raise ValueError('Original BAG projected CRS differs from its reviewed metre CRS')
        x_spacing, y_spacing = dataset.res
        if (dataset.transform.b != 0 or dataset.transform.d != 0
                or dataset.transform.a <= 0 or dataset.transform.e >= 0
                or x_spacing != y_spacing or not 1 <= x_spacing <= 4
                or row.get('resolution_m') != x_spacing
                or float(pattern.group(2)) != x_spacing):
            raise ValueError('Original BAG must have the inventoried square 1–4 m native spacing')

        elevation = dataset.read(1, window=bounded_window, masked=True).astype('float32')
        uncertainty = dataset.read(2, window=bounded_window, masked=True).astype('float32')
        elevation_values = elevation.filled(np.nan)
        uncertainty_values = uncertainty.filled(np.nan)
        valid = (~np.ma.getmaskarray(elevation) & ~np.ma.getmaskarray(uncertainty)
                 & np.isfinite(elevation_values) & np.isfinite(uncertainty_values))
        depth = -elevation_values
        qualifies = (valid & (depth >= MINIMUM_DEPTH_FT * METERS_PER_FOOT)
                     & (depth <= MAXIMUM_DEPTH_FT * METERS_PER_FOOT)
                     & (uncertainty_values > 0)
                     & (uncertainty_values <= MAX_PRODUCT_UNCERTAINTY_M))
        return OriginalRegularBagWindow(
            source_id=row['id'], cell_id_prefix=cell_prefix,
            source_sha256=expected_sha, metadata_sha256=metadata_hash,
            elevation_m=elevation_values, depth_m_positive_down=depth,
            product_uncertainty_m=uncertainty_values, source_pair_valid=valid,
            qualifies_25_300ft_uncertainty_0_1m=qualifies,
            transform=dataset.window_transform(bounded_window), horizontal_crs=horizontal,
            source_crs_wkt=source_crs.to_wkt(),
            vertical_datum=metadata['vertical_datum'], spacing_m=(x_spacing, y_spacing),
            row_off=row_off, col_off=col_off)
