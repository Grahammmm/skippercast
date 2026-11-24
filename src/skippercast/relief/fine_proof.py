"""Versioned fine-zoom evidence on the unpadded Web Mercator XYZ grid."""
from dataclasses import dataclass
from math import isclose, isfinite
from numbers import Integral
from os import PathLike
from pathlib import Path
from struct import error as StructError, unpack
from warnings import catch_warnings, filterwarnings

import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning, RasterioError
from rasterio.transform import Affine

TILE = 256
ORIGIN = 20037508.342789244  # Web Mercator half-width, as in build_bathy_tiles.tile_grid
NODATA = -9999.0
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


def _tile_range(ds, t, zoom):
    if not (ds.width > 0 and ds.height > 0 and ds.width % TILE == ds.height % TILE == 0):
        raise FineProofError('dimensions must be positive whole tiles of 256 pixels')

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


def _geo_tags(file):
    """Read only the bounded GeoTIFF fields in the primary image directory."""
    order = {b'II': '<', b'MM': '>'}.get(file.read(2))
    if order is None:
        raise FineProofError('invalid TIFF byte order')
    magic, = unpack(order + 'H', file.read(2))
    if magic == 42:
        offset_fmt, count_fmt, entry_size, inline_size = 'I', 'H', 12, 4
    elif magic == 43 and unpack(order + 'HH', file.read(4)) == (8, 0):
        offset_fmt, count_fmt, entry_size, inline_size = 'Q', 'Q', 20, 8
    else:
        raise FineProofError('invalid TIFF header')
    offset, = unpack(order + offset_fmt, file.read(inline_size))
    file.seek(offset)
    count, = unpack(order + count_fmt, file.read(2 if magic == 42 else 8))
    if count > 65535:
        raise FineProofError('too many TIFF directory entries')

    # (TIFF datatype, element size, struct code, maximum element count).
    # No raster data, secondary IFDs or arbitrary-size tags are decoded here.
    fields = {33550: (12, 8, 'd', 3), 33922: (12, 8, 'd', 6),
              34264: (12, 8, 'd', 16), 34735: (3, 2, 'H', 40),
              34737: (2, 1, 's', 65535)}
    tags = {}
    for _ in range(count):
        entry = file.read(entry_size)
        tag, kind, length = unpack(order + 'HH' + offset_fmt, entry[:-inline_size])
        if tag not in fields:
            continue
        dtype, size, code, max_length = fields[tag]
        if tag in tags or kind != dtype or not 0 < length <= max_length:
            raise FineProofError(f'invalid GeoTIFF field {tag}')
        width = size * length
        value = entry[-inline_size:]
        if width <= inline_size:
            data = value[:width]
        else:
            start, = unpack(order + offset_fmt, value)
            next_entry = file.tell()
            file.seek(start)
            data = file.read(width)
            file.seek(next_entry)
        tags[tag] = unpack(f'{order}{length}{code}', data)
    return tags


def _internal_transform(file):
    tags = _geo_tags(file)
    # V1 uses the registered projected CRS and metre units, not user-defined
    # projection parameters. Permit the writer's optional citations and the
    # equivalent explicit WGS84/angular/linear unit keys; reject overrides.
    error = 'internal CRS must be EPSG:3857 with canonical GeoKeys'
    directory = tags.get(34735, ())
    if (directory[:3] not in ((1, 1, 0), (1, 1, 1)) or len(directory) < 4
            or len(directory) != 4 + 4 * directory[3]):
        raise FineProofError(error)
    allowed = {1024: 1, 2048: 4326, 2054: 9102, 3072: 3857, 3076: 9001}
    citations = {1026: b'WGS 84 / Pseudo-Mercator', 2049: b'WGS 84', 3073: b'WGS 84 / Pseudo-Mercator'}
    keys = {}
    for i in range(4, len(directory), 4):
        key, location, count, value = directory[i:i + 4]
        if key in keys:
            raise FineProofError(error)
        if key in citations:
            # Do not accept strings that embed alternate projection definitions.
            text, = tags.get(34737, (b'',))
            valid = (location == 34737 and value + count <= len(text)
                     and text[value:value + count].rstrip(b'|\0') == citations[key])
        else:
            valid = location == 0 and count == 1 and (
                value in (1, 2) if key == 1025 else allowed.get(key) == value
            )
        if not valid:
            raise FineProofError(error)
        keys[key] = value
    if keys.get(1024) != 1 or keys.get(3072) != 3857:
        raise FineProofError(error)

    if 34264 in tags and 33550 not in tags and 33922 not in tags:
        matrix = tags[34264]
        if (len(matrix) != 16 or matrix[2] != 0 or matrix[6] != 0
                or matrix[12:] != (0, 0, 0, 1)):
            raise FineProofError('invalid internal affine matrix')
        transform = Affine(*matrix[:2], matrix[3], *matrix[4:6], matrix[7])
    elif 34264 not in tags and len(tags.get(33550, ())) == 3 and len(tags.get(33922, ())) == 6:
        sx, sy, _ = tags[33550]
        i, j, _, x, y, _ = tags[33922]
        transform = Affine(sx, 0, x - i * sx, 0, -sy, y + j * sy)
    else:
        raise FineProofError('expected one unambiguous internal affine transform')
    if keys.get(1025) == 2:  # PixelIsPoint tiepoints describe centres, not corners.
        transform = transform @ Affine.translation(-0.5, -0.5)
    return transform


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
        crs='EPSG:3857', transform=_transform(int(zoom), int(x0), int(y0)), nodata=NODATA,
        tiled=True, blockxsize=TILE, blockysize=TILE, compress='deflate',
    ) as ds:
        ds.update_tags(sc_fine_proof='1', zoom=str(zoom))
        for index, band in enumerate(stored, 1):
            ds.write(band, index)


def read(path: _Path) -> FineProof:
    """Validate a GeoTIFF's internal grid, metadata, and full-resolution evidence."""
    path = Path(path).absolute()  # a pinned local file, not a GDAL URI or subdataset
    try:
        # GDAL handles pixels and masks only. Asking for even INTERNAL georeferencing
        # makes Rasterio resolve EPSG through the installed PROJ database at open.
        with (
            path.open('rb') as file,
            rasterio.Env(GDAL_PAM_ENABLED='NO', GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', PROJ_NETWORK='OFF'),
            _open_pixels(path) as ds,
        ):
            tags = ds.tags()
            if tags.get('sc_fine_proof') != '1':
                raise FineProofError('sc_fine_proof tag must be 1')
            if tags.get('zoom') not in ('16', '17'):
                raise FineProofError('zoom tag must be 16 or 17')
            zoom = int(tags['zoom'])
            rectangle = _tile_range(ds, _internal_transform(file), zoom)
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
    except (OSError, RasterioError, StructError, OverflowError) as exc:
        raise FineProofError(f'raster read failed (GTiff driver required): {exc}') from exc
    return FineProof(zoom, *rectangle, np.where(proven, cls, 0).astype('uint8'), elev, spacing, proven)


def _open_pixels(path):
    with catch_warnings():
        filterwarnings('ignore', category=NotGeoreferencedWarning)
        return rasterio.open(path, driver='GTiff', GEOREF_SOURCES='NONE')
