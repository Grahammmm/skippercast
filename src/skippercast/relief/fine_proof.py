"""Versioned fine-zoom evidence on the unpadded Web Mercator XYZ grid."""
from dataclasses import dataclass
from math import isclose, isfinite
from numbers import Integral
from os import PathLike

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.errors import RasterioError
from rasterio.transform import Affine

TILE = 256
ORIGIN = 20037508.342789244  # Web Mercator half-width, as in build_bathy_tiles.tile_grid
NODATA = -9999.0
_CRS = CRS.from_epsg(3857)
_TOL = 1e-6  # absolute projected metres, not relative to the world origin
_Path = str | PathLike[str]


class FineProofError(ValueError):
    """The fine-proof raster or its proposed contents failed validation."""


def _index(value):
    return isinstance(value, Integral) and not isinstance(value, bool)


def _zoom(zoom):
    if not _index(zoom) or zoom not in (16, 17):
        raise FineProofError('zoom must be the integer 16 or 17')


def _rectangle(zoom, x0, y0, x1, y1):
    limit = 1 << int(zoom)
    if (not all(map(_index, (x0, y0, x1, y1)))
            or not (0 <= x0 <= x1 < limit and 0 <= y0 <= y1 < limit)):
        raise FineProofError('XYZ rectangle must be inclusive and inside the zoom grid')


def _resolution(zoom):
    return 2 * ORIGIN / (TILE * (1 << zoom))


def _transform(zoom, x0, y0):
    res = _resolution(zoom)
    return Affine(res, 0, -ORIGIN + x0 * TILE * res, 0, -res, ORIGIN - y0 * TILE * res)


def _aligned(actual, expected):
    return isclose(actual, expected, rel_tol=0, abs_tol=_TOL)


def _tile_range(ds, zoom):
    if not (ds.width > 0 and ds.height > 0 and ds.width % TILE == ds.height % TILE == 0):
        raise FineProofError('dimensions must be positive whole tiles of 256 pixels')
    t = ds.transform
    if t.b != 0 or t.d != 0 or not (t.a > 0 and t.e < 0):
        raise FineProofError('affine must be north-up with zero rotation/skew')
    res = _resolution(zoom)
    if not (_aligned(t.a, res) and _aligned(t.e, -res)):
        raise FineProofError('pixel sizes do not match the zoom lattice')
    if not (isfinite(t.c) and isfinite(t.f)):
        raise FineProofError('origin must be finite and aligned to the zoom lattice')
    # Find the candidate integer tile from the canonical pitch (not the file's
    # bounds or pixel sizes), then verify its projected origin independently.
    x0 = round((t.c + ORIGIN) / (TILE * res))
    y0 = round((ORIGIN - t.f) / (TILE * res))
    expected = _transform(zoom, x0, y0)
    if not (_aligned(t.c, expected.c) and _aligned(t.f, expected.f)):
        raise FineProofError('origin is not on the zoom tile lattice')
    x1, y1 = x0 + ds.width // TILE - 1, y0 + ds.height // TILE - 1
    _rectangle(zoom, x0, y0, x1, y1)
    return x0, y0, x1, y1


def _proven(cls, elev, spacing):
    missing = cls == NODATA
    if not (np.array_equal(elev == NODATA, missing) and np.array_equal(spacing == NODATA, missing)):
        raise FineProofError('partial nodata sentinel triple')
    if not all(np.isfinite(band).all() for band in (cls, elev, spacing)):
        raise FineProofError('nonfinite sample')
    proven = ~missing
    if np.any(proven & ((cls < 0) | (cls > 3) | (cls != np.trunc(cls)))):
        raise FineProofError('class must be an integer in [0, 3]')
    if np.any(proven & ((elev < -20) | (elev > 0))):
        raise FineProofError('elevation must be in [-20, 0] metres')
    if np.any(proven & ((spacing <= 0) | (spacing > 1))):
        raise FineProofError('spacing must be in (0, 1] metres')
    return proven


@dataclass(frozen=True, eq=False)
class FineProof:
    """Decoded evidence; consult ``proven`` before using a pixel's bands.

    Unproven pixels have class 0 and retain the sentinel in elevation and spacing.
    The XYZ endpoints are inclusive.
    """

    zoom: int
    x0: int
    y0: int
    x1: int
    y1: int
    cls: np.ndarray
    elev: np.ndarray
    spacing: np.ndarray
    proven: np.ndarray

    def certified(self, z: int, x: int, y: int) -> bool:
        """Check a full tile, without resampling or ignoring unproven pixels."""
        if (z != self.zoom or not all(map(_index, (z, x, y)))
                or not (self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1)):
            return False
        row, col = (int(y) - self.y0) * TILE, (int(x) - self.x0) * TILE
        tile = np.s_[row:row + TILE, col:col + TILE]
        elev = self.elev[tile]
        return bool(np.all(self.proven[tile] & (self.cls[tile] == 3)
                           & (elev >= -20) & (elev <= 0) & (self.spacing[tile] <= 1)))


def write(path: _Path, zoom: int, x0: int, y0: int, x1: int, y1: int,
          cls: np.ndarray, elev: np.ndarray, spacing: np.ndarray) -> None:
    """Validate evidence and write one self-contained lossless GeoTIFF."""
    _zoom(zoom)
    _rectangle(zoom, x0, y0, x1, y1)
    height, width = (int(y1) - int(y0) + 1) * TILE, (int(x1) - int(x0) + 1) * TILE
    bands = []
    for name, samples in zip(('class', 'elevation', 'spacing'), (cls, elev, spacing)):
        if np.ma.is_masked(samples):
            raise FineProofError(f'{name} mask must be expressed as explicit nodata triples')
        band = np.asarray(samples)
        if band.shape != (height, width):
            raise FineProofError(f'{name} shape must match the XYZ rectangle dimensions')
        if band.dtype.kind not in 'biuf':
            raise FineProofError(f'{name} samples must be real numbers')
        bands.append(band)
    _proven(*bands)
    # Validate in the input precision before conversion, so even values just
    # outside a boundary cannot round into the admissible range.
    stored = [band.astype('float64', copy=False) for band in bands]
    for name, raw, encoded in zip(('class', 'elevation', 'spacing'), bands, stored):
        if raw.dtype.itemsize > encoded.dtype.itemsize and not np.array_equal(raw, encoded):
            raise FineProofError(f'{name} samples must be exactly representable as float64')
    with rasterio.Env(GDAL_PAM_ENABLED='NO'), rasterio.open(
        path, 'w', driver='GTiff', width=width, height=height, count=3, dtype='float64',
        crs=_CRS, transform=_transform(int(zoom), int(x0), int(y0)), nodata=NODATA,
        tiled=True, blockxsize=TILE, blockysize=TILE, compress='deflate',
    ) as ds:
        ds.update_tags(sc_fine_proof='1', zoom=str(zoom))
        for index, band in enumerate(stored, 1):
            ds.write(band, index)


def read(path: _Path) -> FineProof:
    """Validate a GeoTIFF's grid, metadata, and full-resolution evidence."""
    try:
        with rasterio.open(path) as ds:
            if ds.driver != 'GTiff':
                raise FineProofError('driver must be GTiff')
            tags = ds.tags()
            if tags.get('sc_fine_proof') != '1':
                raise FineProofError('sc_fine_proof tag must be 1')
            if tags.get('zoom') not in ('16', '17'):
                raise FineProofError('zoom tag must be 16 or 17')
            zoom = int(tags['zoom'])
            if ds.crs != _CRS:
                raise FineProofError('CRS must be EPSG:3857')
            rectangle = _tile_range(ds, zoom)
            if ds.count != 3 or ds.dtypes != ('float64',) * 3:
                raise FineProofError('expected three Float64 bands')
            if ds.scales != (1.0,) * 3 or ds.offsets != (0.0,) * 3:
                raise FineProofError('band scale/offset must be identity')
            if ds.nodatavals != (NODATA,) * 3:
                raise FineProofError('band nodata metadata must be -9999.0')
            cls, elev, spacing = ds.read(masked=False)
            proven = _proven(cls, elev, spacing)
            for index in ds.indexes:
                if not np.array_equal(ds.read_masks(index) != 0, proven):
                    raise FineProofError(f'band {index} mask disagrees with the nodata footprint')
    except RasterioError as exc:
        raise FineProofError(f'raster read failed: {exc}') from exc
    return FineProof(zoom, *rectangle, np.where(proven, cls, 0).astype('uint8'), elev, spacing, proven)
