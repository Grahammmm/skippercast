#!/usr/bin/env python3
"""Build local "Deep" PMTiles from a regional bathymetry mosaic and optional native surveys.

    python scripts/build_bathy_tiles.py --source /path/to/elevation.tif
    python scripts/build_bathy_tiles.py --source /path/to/elevation.tif --native-manifest /path/to/native.json

Writes `var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` (override with `--output`), zooms 8-13,
256 px web-mercator PNG tiles, and prints the file size, zoom range and tile count. Medium relief
is the default. A native manifest adds <=2 m or 5 m projected metre grids at nominal depths 0-300 ft,
feathered across 40 m of overlap at z14-15. At z16-17, every surveyed core pixel must instead
have class-3 support from a <=1 m native grid in nominal 0-20 m; z18 is never emitted.
Use --clip-bounds WEST SOUTH EAST NORTH for a regional archive. A native entry's max_zoom
is a ceiling; support_path is an aligned uint8 raster, and no mask means unknown support.
Pixel spacing is not a claim of finer survey accuracy. Vertical references remain as supplied.

The look is "Deep": the cmocean `deep` ramp with fixed depth stops at every zoom, lit by a
four-direction hillshade. Vertical exaggeration still increases from the study's canyon setting
at zoom 11 and below to its nearshore setting at zoom 13.

The source raster (EPSG:3310, elevation metres, positive up) stays the source of truth; tiles
are only a delivery format. Cells above +3 m NAVD88 in the background mosaic are masked before
resampling (no vertical conversion is performed here). A cell with no survey is fully transparent,
never filled with a depth: the raster's nodata is only filled *inside the hillshade window*
(nearest valid value) so the survey edge does not cast a fake cliff, and the filled cells are
discarded afterwards. The raster is gitignored and its rights need review before publication, so
the archive is not committed either; it is a local build output (see docs/archive/map-engine-test.md).

Requires the survey stack (numpy, scipy, rasterio; see requirements-survey.txt). The colour
ramp is cmocean `deep` (Thyng et al. 2016, MIT licence), embedded as a 256-entry table so
cmocean and matplotlib are not dependencies. NOT FOR NAVIGATION: research preview.
"""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'var/seafloor/tiles/morro-bay-seafloor-deep.pmtiles'
TILE = 256
PAD = 2                      # halo (pixels) read around each tile so hillshade matches across seams
ORIGIN = 20037508.342789244  # web-mercator half-width, metres
NODATA = -999999.0
LAND_LIMIT_M = 3.0         # NAVD88 for normalized background mosaics
MINZOOM, MAXZOOM = 8, 13     # 10 m cells are ~15.6 m/px at zoom 13; deeper zooms only overzoom
EARTH = 6378137.0

# cmocean "deep" colour table: 256 sRGB triplets, 8-bit, from cmocean 4.0.3.
# The MIT License (MIT). Copyright (c) 2015 Kristen M. Thyng. Permission is hereby granted, free of
# charge, to any person obtaining a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# subject to the following conditions: the above copyright notice and this permission notice shall
# be included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS
# IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY.
DEEP_HEX = (
    'fdfeccfbfdcbf9fccaf7fbc8f5fac7f3fac6f1f9c5eff8c4edf7c3ebf7c1e9f6c0e7f5bfe5f4bee3f4bde1f3bcdff2bb',
    'ddf2badbf1b9d9f0b8d7efb7d4efb6d2eeb5d0edb4ceecb3ccecb3caebb2c8eab1c6eab0c4e9afc1e8afbfe7aebde7ad',
    'bbe6acb9e5acb7e5abb5e4aab2e3aab0e2a9aee2a9ace1a8aae0a8a7e0a7a5dfa7a3dea6a1dda69fdda59cdca59adba5',
    '98daa496daa494d9a492d8a490d7a48dd7a38bd6a389d5a387d4a385d3a383d3a381d2a37fd1a37dd0a37ccfa37acea3',
    '78cea376cda375cca373cba371caa370c9a36ec8a36dc7a36bc6a36ac5a469c4a467c3a466c2a465c2a464c1a463c0a4',
    '62bfa461bea460bda45fbca45ebba45dbaa45cb9a45bb8a45ab7a45ab6a459b4a458b3a458b2a457b1a456b0a456afa4',
    '55aea355ada354aca353aba353aaa352a9a352a8a351a7a351a6a251a5a250a4a250a3a24fa2a24fa1a24fa0a24e9fa1',
    '4e9ea14d9da14d9ca14d9ba14c9aa04c99a04b98a04b97a04b96a04a959f4a949f4a939f49929f49919e49909e488f9e',
    '488e9e488d9d478c9d478b9d478a9d46899d46889c46879c45869c45859c45849b44839b44829b44819b44809b437f9a',
    '437e9a437d9a427c9a427b99427a994279994178994177994176984075984074984073984072984071973f70973f6f97',
    '3f6e973f6d973f6c963e6b963e6a963e69963e68963e67953e66953e65953e64953e63943e62943e61943e60943e5f93',
    '3e5e933e5c933e5b933e5a923e59923e58923e57913e56913f55903f54903f538f3f528f3f508e404f8d404e8d404d8c',
    '404c8b414b8a414a8941498841488741478541468441458341448142438041427e41417d41407b41407a413f78413e76',
    '413d75403c73403c71403b70403a6e3f396c3f386b3f38693e37673e36663d35643d35623d34613c335f3c325d3b325c',
    '3b315a3a30583a3057392f55392e54382d52382d51372c4f362b4d362a4c352a4a352949342847342846332744322643',
    '32254131254030243e30233d2f223b2f223a2e21392d20372d1f362c1f342b1e332b1d322a1c30291c2f281b2d281a2c',
)

# Ramp B (MAP-DESIGN-LOCK §1.2): fixed depths in metres -> cmocean LUT positions.
RAMP_DEPTH_M = (0.0, 1.5, 3.0, 6.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 91.44, 150.0, 300.0, 700.0)
RAMP_POSITIONS = (0.03, 0.07, 0.11, 0.18, 0.26, 0.35, 0.44, 0.53, 0.61, 0.68, 0.78, 0.87, 0.94, 1.00)
# Vertical exaggeration still follows the canyon/nearshore settings of the map style study.
CANYON_VE, NEARSHORE_VE = 2.2, 6.0
CANYON_ZOOM, NEARSHORE_ZOOM = 11, 13
# (azimuth deg, weight); altitude 38 deg. Same as bathy.py `multi`.
LIGHTS = ((225.0, 0.2), (315.0, 0.4), (270.0, 0.2), (360.0, 0.2))
ALTITUDE = 38.0
BLEND_GAIN = 1.8

# MAPSTYLE-2 relief enhancement (contrast and exposure only; shared ramp and mask). Controls:
#   ve_boost / gain_boost  fractional rise of vertical exaggeration / hillshade strength, ramped in
#                          from 0 at zoom 11 to full at zoom 13 (the shelf zooms)
#   unsharp, sigma_m, clip local-contrast boost on the shading: amount, blur radius in ground metres
#                          (1-4 px), and the largest detail it may add (a bound, so a cliff or a
#                          survey seam cannot blow out); faded to zero within 2 sigma of no survey
#   light2, light2_az      weight and azimuth of a second light from the opposite (SE) side, so ridges
#                          show from either side; the four base lights share the remaining weight
#   curv                   weight of a ridge/trough term (smoothed Laplacian: crests lighter, hollows
#                          darker), light-direction free
#   ev                     exposure lift in stops, peaking in the mid-depths of the ramp, 0 at both ends
BASE_ENHANCE = {'ve_boost': 0.0, 'gain_boost': 0.0, 'unsharp': 0.0, 'sigma_m': 50.0, 'clip': 0.25,
                'light2': 0.0, 'light2_az': 135.0, 'curv': 0.0, 'ev': 0.0}
ENHANCE = {
    'base': BASE_ENHANCE,
    'mild': {**BASE_ENHANCE, 've_boost': 0.15, 'gain_boost': 0.10, 'unsharp': 0.6, 'light2': 0.10,
             'curv': 0.10, 'ev': 0.05},
    'medium': {**BASE_ENHANCE, 've_boost': 0.30, 'gain_boost': 0.20, 'unsharp': 1.0, 'light2': 0.15,
               'curv': 0.20, 'ev': 0.10},
    'strong': {**BASE_ENHANCE, 've_boost': 0.50, 'gain_boost': 0.35, 'unsharp': 1.6, 'light2': 0.20,
               'curv': 0.35, 'ev': 0.18},
}
BLUR_MAX_PX = 4.0            # widest local-contrast blur sigma in pixels
# Halo wider than every kernel, so neighbouring tiles compute identical edge pixels: the widest blur reaches
# int(4 sigma + 0.5) px (scipy's default truncate), the hillshade gradient one more and one pixel margin.
ENHANCED_PAD = int(4 * BLUR_MAX_PX + 0.5) + 2


def deep_lut():
    return np.frombuffer(bytes.fromhex(''.join(DEEP_HEX)), dtype=np.uint8).reshape(256, 3)


def zoom_ramp(zoom):
    """0 at the canyon zoom and below, 1 at the nearshore zoom and above."""
    return min(1.0, max(0.0, (zoom - CANYON_ZOOM) / (NEARSHORE_ZOOM - CANYON_ZOOM)))


def style_for_zoom(zoom, enhance=None):
    """Vertical exaggeration and hillshade gain for a zoom level."""
    enhance = enhance or BASE_ENHANCE
    t = zoom_ramp(zoom)
    ve = CANYON_VE + (NEARSHORE_VE - CANYON_VE) * t
    return {'ve': ve * (1.0 + enhance['ve_boost'] * t), 'gain': BLEND_GAIN * (1.0 + enhance['gain_boost'] * t)}


def lights_for(enhance=None):
    enhance = enhance or BASE_ENHANCE
    w2 = enhance['light2']
    if w2 <= 0:
        return LIGHTS
    return tuple((az, w * (1.0 - w2)) for az, w in LIGHTS) + ((enhance['light2_az'], w2),)


def pad_for(enhance=None):
    enhance = enhance or BASE_ENHANCE
    return PAD if enhance == BASE_ENHANCE else ENHANCED_PAD


def ramp_position(elevation):
    """Interpolate the fixed depth stops, clamping beyond either end of the ramp."""
    return np.interp(-elevation, RAMP_DEPTH_M, RAMP_POSITIONS)


def deep_colour(position):
    """cmocean-style lookup: index = int(x * 256), clamped, so x == 1 is the last entry."""
    index = np.clip((np.asarray(position) * 256).astype(np.int64), 0, 255)
    return deep_lut()[index].astype(np.float64) / 255.0


def fill_nodata(elevation, invalid):
    """Nearest-valid fill for hillshade only; callers keep `invalid` as the alpha mask."""
    from scipy import ndimage
    if not invalid.any():
        return elevation.astype(np.float64)
    nearest = ndimage.distance_transform_edt(invalid, return_distances=False, return_indices=True)
    return elevation[tuple(nearest)].astype(np.float64)


def light_vector(azimuth, altitude=ALTITUDE):
    az, alt = math.radians(90.0 - azimuth), math.radians(altitude)
    return np.array([math.cos(az) * math.cos(alt), math.sin(az) * math.cos(alt), math.sin(alt)])


def raw_intensity(elevation, ground_m, vert_exag, azimuth):
    """Un-normalised illumination, matplotlib LightSource.hillshade with north-up rows."""
    d_row, d_col = np.gradient(vert_exag * elevation, -ground_m, ground_m)
    normal = np.stack([-d_col, -d_row, np.ones_like(elevation)], axis=-1)
    normal /= np.sqrt((normal ** 2).sum(axis=-1, keepdims=True))
    return normal @ light_vector(azimuth)


def rescale(raw, lo, hi):
    """matplotlib's contrast rescale using the extremes of the whole picture (here: the whole zoom)."""
    if hi - lo > 1e-6:
        raw = (raw - lo) / (hi - lo)
    return np.clip(raw, 0.0, 1.0)


def combined_intensity(raws, ranges, lights=LIGHTS):
    return sum(w * rescale(r, *ranges[i]) for i, ((_, w), r) in enumerate(zip(lights, raws)))


def shade(position_rgb, intensity, median, gain=BLEND_GAIN):
    """Soft blend of hillshade intensity into the colour (bathy.py `blend`, gain 1.8)."""
    f = (intensity - median) * gain
    return np.clip(position_rgb * (1.0 + f[..., None]), 0.0, 1.0)


def edge_fade(invalid, width):
    """0 on and next to no-survey cells, rising to 1 at `width` pixels inside the survey (1 everywhere if none)."""
    if not invalid.any():
        return np.ones(invalid.shape)
    from scipy import ndimage
    return np.clip((ndimage.distance_transform_edt(~invalid) - 1.0) / width, 0.0, 1.0)


def local_contrast(intensity, invalid, ground, enhance):
    """Bounded unsharp mask of the shading. The blur counts surveyed cells only and the boost fades out
    near the survey edge, so the nearest-fill used for the hillshade cannot show up as a ridge."""
    amount = enhance['unsharp']
    if amount <= 0:
        return intensity
    from scipy import ndimage
    sigma = min(BLUR_MAX_PX, max(1.0, enhance['sigma_m'] / ground))
    valid = (~invalid).astype(np.float64)
    blur = ndimage.gaussian_filter(intensity * valid, sigma, mode='nearest') \
        / np.maximum(ndimage.gaussian_filter(valid, sigma, mode='nearest'), 1e-6)
    detail = np.clip(intensity - blur, -enhance['clip'], enhance['clip'])
    return intensity + amount * detail * edge_fade(invalid, 2.0 * sigma)


def ridge_signal(filled, invalid):
    """Crest-positive curvature of the lightly smoothed bottom (metres per pixel squared), 0 near no survey."""
    from scipy import ndimage
    return -ndimage.laplace(ndimage.gaussian_filter(filled, 1.0, mode='nearest')) * edge_fade(invalid, 3.0)


def expose(rgb, position, ev):
    """Lift the mid-depths by up to `ev` stops; the shallow and deep ends of the ramp keep their colour."""
    if ev <= 0:
        return rgb
    lift = 2.0 ** (ev * np.sin(np.pi * np.clip(position, 0.0, 1.0)))
    return np.clip(rgb * lift[..., None], 0.0, 1.0)


# ---- PNG ------------------------------------------------------------------------------------
def _chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def encode_png(rgba):
    """Deterministic 8-bit PNG: RGB when fully opaque, RGBA otherwise; per-row Sub/Up/None filter."""
    height, width = rgba.shape[:2]
    opaque = bool((rgba[..., 3] == 255).all())
    pixels = np.ascontiguousarray(rgba[..., :3] if opaque else rgba)
    rows = pixels.reshape(height, -1).astype(np.int16)
    bpp = pixels.shape[2]
    sub = rows.copy()
    sub[:, bpp:] = rows[:, bpp:] - rows[:, :-bpp]
    up = rows.copy()
    up[1:] = rows[1:] - rows[:-1]
    out = bytearray()
    for y in range(height):
        options = ((0, rows[y]), (1, sub[y]), (2, up[y]))
        kind, row = min(options, key=lambda o: int(np.abs(((o[1] + 128) % 256) - 128).sum()))
        out.append(kind)
        out += (row % 256).astype(np.uint8).tobytes()
    header = struct.pack('>IIBBBBB', width, height, 8, 2 if opaque else 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', header)
            + _chunk(b'IDAT', zlib.compress(bytes(out), 9)) + _chunk(b'IEND', b''))


# ---- PMTiles v3 -----------------------------------------------------------------------------
def tile_id(z, x, y):
    """Hilbert-curve tile id, as in the PMTiles v3 specification."""
    acc = sum(4 ** i for i in range(z))
    tx, ty, s, d = x, y, (1 << z) // 2, 0
    while s > 0:
        rx, ry = int((tx & s) > 0), int((ty & s) > 0)
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                tx, ty = s - 1 - tx, s - 1 - ty
            tx, ty = ty, tx
        s //= 2
    return acc + d


def _varint(n):
    out = bytearray()
    while True:
        byte = n & 0x7f
        n >>= 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def serialize_directory(entries):
    """entries: [(tile_id, offset, length, run_length)] sorted by tile id."""
    out = bytearray(_varint(len(entries)))
    last = 0
    for e in entries:
        out += _varint(e[0] - last)
        last = e[0]
    for e in entries:
        out += _varint(e[3])
    for e in entries:
        out += _varint(e[2])
    for i, e in enumerate(entries):
        out += _varint(0 if i and e[1] == entries[i - 1][1] + entries[i - 1][2] else e[1] + 1)
    return bytes(out)


def write_pmtiles(path, tiles, *, metadata, bounds, minzoom, maxzoom, center):
    """tiles: {(z, x, y): png bytes}. One clustered root directory; identical tiles share bytes."""
    ordered = sorted((tile_id(*zxy), data) for zxy, data in tiles.items())
    body, seen, entries = bytearray(), {}, []
    for tid, data in ordered:
        digest = hashlib.sha256(data).digest()
        if digest not in seen:
            seen[digest] = (len(body), len(data))
            body += data
        offset, length = seen[digest]
        if entries and entries[-1][0] + entries[-1][3] == tid and entries[-1][1] == offset and entries[-1][2] == length:
            entries[-1] = (*entries[-1][:3], entries[-1][3] + 1)
        else:
            entries.append((tid, offset, length, 1))
    root = gzip.compress(serialize_directory(entries), mtime=0)
    meta = gzip.compress(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode(), mtime=0)
    if 127 + len(root) > 16384:
        raise ValueError('root directory exceeds 16 KB; this builder writes no leaf directories')
    root_offset, meta_offset = 127, 127 + len(root)
    data_offset = meta_offset + len(meta)
    e7 = lambda v: int(round(v * 1e7))
    header = (b'PMTiles' + bytes([3])
              + struct.pack('<QQQQQQQQQQQ', root_offset, len(root), meta_offset, len(meta),
                            data_offset + len(body), 0,        # no leaf directories
                            data_offset, len(body), len(ordered), len(entries), len(seen))
              + bytes([1, 2, 1, 2, minzoom, maxzoom])         # clustered, gzip dirs, no tile compression, PNG
              + struct.pack('<iiii', *(e7(v) for v in bounds))
              + bytes([center[0]]) + struct.pack('<ii', e7(center[1]), e7(center[2])))
    assert len(header) == 127, len(header)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix('.part')
    part.write_bytes(header + root + meta + bytes(body))
    part.replace(path)
    return path


# ---- Tile rendering -------------------------------------------------------------------------
def tile_range(bounds, z):
    west, south, east, north = bounds
    n = 1 << z

    def x_of(lon):
        return min(n - 1, max(0, int((lon + 180.0) / 360.0 * n)))

    def y_of(lat):
        r = math.radians(lat)
        return min(n - 1, max(0, int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * n)))
    return range(x_of(west), x_of(east) + 1), range(y_of(north), y_of(south) + 1)


def tile_grid(z, x, y, pad=PAD):
    """Affine transform of the padded tile window and the ground metres per pixel at its centre."""
    from affine import Affine
    res = 2 * ORIGIN / (TILE * (1 << z))
    left, top = -ORIGIN + x * TILE * res, ORIGIN - y * TILE * res
    centre_y = top - TILE * res / 2
    lat = math.degrees(2 * math.atan(math.exp(centre_y / EARTH)) - math.pi / 2)
    return Affine(res, 0, left - pad * res, 0, -res, top + pad * res), res * math.cos(math.radians(lat))


def warp_window(elevation, src_transform, src_crs, z, x, y, pad=PAD):
    """Warp the background only; native survey resampling is handled by warp_native."""
    from rasterio.warp import Resampling, reproject
    transform, ground = tile_grid(z, x, y, pad)
    size = TILE + 2 * pad
    dest = np.full((size, size), NODATA, dtype=np.float32)
    source_spacing = max(math.hypot(src_transform.a, src_transform.d),
                         math.hypot(src_transform.b, src_transform.e))
    # At detail zooms, averaging an enlarged grid leaves steps at its cell edges.
    resampling = Resampling.bilinear if z >= 14 and ground < source_spacing else Resampling.average
    # tolerance=0: exact per-pixel transform, so overlapping halos of neighbouring tiles get identical cells.
    reproject(elevation, dest, src_transform=src_transform, src_crs=src_crs, dst_transform=transform,
              dst_crs='EPSG:3857', src_nodata=NODATA, dst_nodata=NODATA, resampling=resampling,
              init_dest_nodata=True, tolerance=0)
    return dest, ground


SHALLOW_M = 300 * 0.3048
DETAIL_M = 20.0
NATIVE_BASE_MAXZOOM = 15
NATIVE_MAXZOOM = 17
FEATHER_M = 40.0


def feather_tier(coarse, native, ground, feather_m=FEATHER_M):
    """Blend elevations, not RGB. No filling of holes or new support outside either survey.

    The caller supplies a halo wider than the feather plus the shading kernels. A smoothstep
    taper at native coverage/depth edges prevents a sharp slope break in the overlap. Where
    coarse support is absent, retain native measured support rather than blending to nodata.
    Vertical references are not transformed: this is explicitly a mixed-datum preview.
    """
    from scipy import ndimage
    valid = np.isfinite(native) & (native != NODATA) & (native <= 0) & (native >= -SHALLOW_M)
    base_valid = np.isfinite(coarse) & (coarse != NODATA)
    if ground <= 0 or feather_m <= 0:
        raise ValueError('ground spacing and feather width must be positive')
    weight = (np.ones(valid.shape) if valid.all() else
              np.clip((ndimage.distance_transform_edt(valid) - 1) * ground / feather_m, 0, 1))
    weight = weight * weight * (3 - 2 * weight)
    result = coarse.copy()
    overlap = valid & base_valid
    result[overlap] = (coarse[overlap] * (1 - weight[overlap]) + native[overlap] * weight[overlap])
    result[valid & ~base_valid] = native[valid & ~base_valid]
    return result, valid


def _manifest_entries(path):
    """Read and shape-check the manifest before any raster is opened; raise ValueError."""
    try:
        sources = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f'cannot read {path}: {type(e).__name__}') from None
    if not isinstance(sources, list) or not sources:
        raise ValueError('native manifest must be a nonempty list')
    seen = set()
    for i, s in enumerate(sources):
        if not isinstance(s, dict):
            raise ValueError(f'entry {i}: must be an object')
        for key in ('id', 'path'):
            if not isinstance(s.get(key), str) or not s[key]:
                raise ValueError(f'entry {i}: {key} must be a non-empty string')
        if s['id'] in seen:
            raise ValueError(f'entry {i}: duplicate id')
        seen.add(s['id'])
        r = s.get('resolution_m')
        if isinstance(r, bool) or not isinstance(r, (int, float)) or not math.isfinite(r):
            raise ValueError(f'entry {i}: resolution_m must be a finite number')
        if 'max_zoom' in s and (type(s['max_zoom']) is not int or s['max_zoom'] < 0):
            raise ValueError(f'entry {i}: max_zoom must be a nonnegative integer')
        if s.get('support_path') is not None and (not isinstance(s['support_path'], str) or not s['support_path']):
            raise ValueError(f'entry {i}: support_path must be a non-empty string or null')
        if 'support_class_cap' in s and (type(s['support_class_cap']) is not int or s['support_class_cap'] not in (1, 2, 3)):
            raise ValueError(f'entry {i}: support_class_cap must be 1, 2 or 3')
    return sources


def load_native_manifest(path):
    """Local input paths only; archived metadata never contains those host paths."""
    import rasterio
    from rasterio.warp import transform_bounds
    sources = _manifest_entries(path)
    for i, source in enumerate(sources):
        try:
            ds = rasterio.open(source['path'])
        except rasterio.errors.RasterioIOError:
            raise ValueError(f'entry {i}: cannot open grid file') from None
        with ds:
            resolution = float(source['resolution_m'])
            if (not (0 < resolution <= 2.0 or resolution == 5.0) or ds.count != 1 or not ds.crs.is_projected
                    or not math.isclose(ds.crs.linear_units_factor[1], 1.0)
                    or not np.allclose(ds.res, resolution, atol=0.01)):
                raise ValueError(f'entry {i}: native grid must be a single-band <=2 m or 5 m projected metre grid')
            source['bounds'] = transform_bounds(ds.crs, 'EPSG:4326', *ds.bounds, densify_pts=21)
    # Coarser native first; finer grids win. Stable source IDs settle equal-resolution ties.
    return sorted(sources, key=lambda s: (-s['resolution_m'], s['id']))


def mask_native(values, nodata=None, limit_m=SHALLOW_M):
    """Native cells outside the shallow-only contract (finite, not nodata, 0 to -300 ft) become NODATA.

    Applied to the source cells BEFORE area averaging, so land, deep water and nodata cells can never
    average into an apparently valid shallow pixel (nor feed relief or z14-15 native support).
    """
    values = np.asarray(values, dtype=np.float32)
    keep = np.isfinite(values) & (values != NODATA) & (values <= 0) & (values >= -limit_m)
    if nodata is not None and np.isfinite(nodata):
        keep &= values != np.float32(nodata)
    return np.where(keep, values, np.float32(NODATA)).astype(np.float32)


def overlap_window(ds, bounds, crs, margin=0):
    """Enclose a bounds window in source cells and intersect it with the actual raster."""
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds
    window = from_bounds(*transform_bounds(crs, ds.crs, *bounds, densify_pts=21), transform=ds.transform)
    col0 = max(0, math.floor(window.col_off) - margin)
    row0 = max(0, math.floor(window.row_off) - margin)
    col1 = min(ds.width, math.ceil(window.col_off + window.width) + margin)
    row1 = min(ds.height, math.ceil(window.row_off + window.height) + margin)
    return Window(col0, row0, col1 - col0, row1 - row0) if col1 > col0 and row1 > row0 else None


def coverage(elevation, cell_m, native_sources, clip_bounds=None):
    """Nominal shallow source-cell coverage, not a union or datum qualification.

    cell_m is square spacing or (x, y) spacing for a rectangular background.
    """
    import rasterio
    from rasterio.windows import Window
    x, y = (cell_m, cell_m) if np.isscalar(cell_m) else cell_m
    x, y = abs(float(x)), abs(float(y))
    cells = int(np.count_nonzero(mask_native(elevation) != NODATA))
    background = {'cells': cells, 'cell_m': x, 'km2': round(cells * x * y / 1e6, 4)}
    if x != y:
        background['cell_y_m'] = y
    native = []
    for source in native_sources:
        cells = 0
        with rasterio.open(source['path']) as ds:
            part = overlap_window(ds, clip_bounds, 'EPSG:4326') if clip_bounds else Window(0, 0, ds.width, ds.height)
            if part is not None:
                # Count the overlapping source-cell envelope in bounded strips, even for untiled TIFFs.
                row0, row1 = part.row_off, part.row_off + part.height
                step = max(1, 1048576 // part.width)
                for row in range(row0, row1, step):
                    window = Window(part.col_off, row, part.width, min(step, row1 - row))
                    values = ds.read(1, window=window)
                    values = np.where(ds.read_masks(1, window=window) == 0, np.float32(NODATA), values)
                    cells += int(np.count_nonzero(mask_native(values, ds.nodata) != NODATA))
            native.append({'id': source['id'], 'resolution_m': source['resolution_m'], 'cells': cells,
                           'km2': round(cells * abs(ds.res[0] * ds.res[1]) / 1e6, 4)})
    return {'limit_m': SHALLOW_M,
            'basis': 'cells inside nominal 0-300 ft per source; sources can overlap, so do not add them',
            'background': background, 'native': native}


def warp_native(source, z, x, y, pad, limit_m=SHALLOW_M, *, certified=None):
    import rasterio
    from rasterio.transform import array_bounds
    from rasterio.warp import Resampling, reproject
    transform, ground = tile_grid(z, x, y, pad)
    size = TILE + 2 * pad
    dest = np.full((size, size), NODATA, dtype=np.float32)
    with rasterio.open(source['path']) as ds:
        # Read only the source cells under this padded tile (plus an averaging margin), mask them
        # to the shallow contract, then average: the mask must precede Resampling.average.
        margin = math.ceil(transform.a / max(abs(ds.res[0]), 1e-9)) + 2
        window = overlap_window(ds, array_bounds(size, size, transform), 'EPSG:3857', margin)
        if window is None:
            return dest, ground
        values = ds.read(1, window=window)
        # GDAL validity mask (same window): a zero byte is NODATA whatever the stored number or
        # ds.nodata (possibly None) says, so a masked shallow-looking cell cannot average in or
        # qualify z14-15 native support.
        values = np.where(ds.read_masks(1, window=window) == 0, np.float32(NODATA), values)
        values = mask_native(values, ds.nodata, limit_m)
        grid = dict(src_transform=ds.window_transform(window), src_crs=ds.crs,
                    dst_transform=transform, dst_crs='EPSG:3857', tolerance=0)
        reproject(values, dest, **grid, src_nodata=NODATA,
                  dst_nodata=NODATA, resampling=Resampling.average, init_dest_nodata=True)
        if certified is not None and has_support(source) and max(ds.res) <= 1:
            try:
                with rasterio.open(source['support_path']) as support:
                    if (support.count != 1 or support.dtypes[0] != 'uint8' or support.shape != ds.shape
                            or support.crs != ds.crs or support.transform != ds.transform):
                        raise ValueError('support grid must be aligned with native elevation and single-band uint8')
                    measured = (support.read(1, window=window) == 3) & (support.read_masks(1, window=window) != 0)
            except rasterio.errors.RasterioIOError:
                raise ValueError(f"cannot read support grid for native source {source['id']}") from None
            # Zeros are evidence against certification, not source nodata to skip. A minority of
            # unknown/interpolated/invalid/deep cells must veto certification before resampling.
            reproject((measured & (values != NODATA)).astype('uint8'), certified, **grid,
                      dst_nodata=255, resampling=Resampling.min, init_dest_nodata=True)
    return dest, ground


def tile_core_region(z, x, y, clip):
    """Mask pixel centres on half-open clip edges without clipping the shading halo."""
    if clip is None:
        return True
    west, south, east, north = clip
    transform, _ = tile_grid(z, x, y, pad=0)
    offsets = np.arange(TILE) + 0.5
    xx = transform.c + transform.a * offsets
    yy = transform.f + transform.e * offsets
    return ((xx >= west) & (xx < east))[None, :] & ((yy > south) & (yy <= north))[:, None]


def source_maxzoom(source):
    cap = NATIVE_MAXZOOM if source['resolution_m'] <= 1 else NATIVE_BASE_MAXZOOM
    return min(cap, source.get('max_zoom', cap))


def has_support(source):
    return bool(source.get('support_path')) and source.get('support_class_cap', 3) == 3


def tiered_windows(elevation, src_transform, src_crs, bounds, z, sources, pad, native_support=None,
                   *, clip=None, omissions=None):
    """Background through z13; native through z15; wholly certified shallow native at z16-17.

    Support counts describe source support in emitted tile cores, not halos or blended background.
    Sources can overlap; these counts are not additive or a claim of vertical accuracy.
    """
    if z <= MAXZOOM:
        return zoom_windows(elevation, src_transform, src_crs, bounds, z, pad, clip=clip)
    if z > NATIVE_MAXZOOM:
        return {}
    detail = z > NATIVE_BASE_MAXZOOM
    sources = [(s, *tile_range(s['bounds'], z)) for s in sources if z <= source_maxzoom(s)]
    limit_m = DETAIL_M if detail else SHALLOW_M
    out, candidates = {}, set()
    bx, by = tile_range(bounds, z)
    for _, xs, ys in sources:
        candidates.update((x, y) for x in range(max(xs.start, bx.start), min(xs.stop, bx.stop))
                          for y in range(max(ys.start, by.start), min(ys.stop, by.stop)))
    for x, y in sorted(candidates):
        _, ground = tile_grid(z, x, y)
        halo = pad + math.ceil(FEATHER_M / ground) + 2
        window, ground = warp_window(elevation, src_transform, src_crs, z, x, y, halo)
        fine_support = np.zeros(window.shape, dtype=bool)
        core = (slice(halo, -halo), slice(halo, -halo))
        region = tile_core_region(z, x, y, clip)
        used = []
        measured = np.zeros(window.shape, dtype=bool) if detail else None
        background_water = (window[core] != NODATA) if detail else None
        if detail:
            window.fill(NODATA)
        for source, xs, ys in sources:
            # Include adjoining native tiles for their halo, even if this tile has no core coverage.
            if x < xs.start - 1 or x > xs.stop or y < ys.start - 1 or y > ys.stop:
                continue
            certified = np.zeros(window.shape, dtype='uint8') if detail else None
            native, _ = warp_native(source, z, x, y, halo, limit_m, certified=certified)
            if certified is not None and measured is not None:
                # Don't blend estimated background into certified native. The winning source
                # must itself certify the pixel, even over a certified lower-priority source.
                valid = native != NODATA
                window[valid] = native[valid]
                measured[valid] = certified[valid] == 1
            else:
                window, valid = feather_tier(window, native, ground)
            fine_support |= valid
            if (valid[core] & region).any():
                used.append(source)
        if not (fine_support[core] & region).any():
            continue
        if measured is not None and background_water is not None:
            if ((background_water | fine_support[core]) & region & ~measured[core]).any():
                if omissions is not None:
                    omissions['omitted_uncertified'] += 1
                continue
            window[~measured] = NODATA
        invalid = ~np.isfinite(window) | (window == NODATA)
        out[(x, y)] = (window, invalid, ground)
        if native_support is not None:
            for source in used:
                entry = native_support.setdefault(source['id'], {
                    'id': source['id'], 'resolution_m': source['resolution_m'], 'tiles': 0})
                entry['tiles'] += 1
    return out


def zoom_windows(elevation, src_transform, src_crs, bounds, z, pad=PAD, *, clip=None):
    """{(x, y): (padded elevation, invalid mask, ground metres per pixel)} for tiles with any survey."""
    xs, ys = tile_range(bounds, z)
    out = {}
    for x in xs:
        for y in ys:
            window, ground = warp_window(elevation, src_transform, src_crs, z, x, y, pad)
            invalid = ~np.isfinite(window) | (window == NODATA)
            if not (~invalid[pad:-pad, pad:-pad] & tile_core_region(z, x, y, clip)).any():
                continue
            out[(x, y)] = (window, invalid, ground)
    return out


def relief(window, invalid, ground, ve, lights, enhance):
    """Per-light raw illumination and (when the curvature term is on) the ridge signal of one window."""
    filled = fill_nodata(window, invalid)
    raws = [raw_intensity(filled, ground, ve, az) for az, _ in lights]
    ridge = ridge_signal(filled, invalid) if enhance['curv'] > 0 else None
    return raws, ridge


def zoom_shading(windows, z, enhance=None):
    """Two passes: zoom-wide hillshade extremes and median (the study's picture-wide constants), then the
    shading intensity of every padded window. Returns (style, {key: intensity}, median)."""
    enhance = enhance or BASE_ENHANCE
    style, lights = style_for_zoom(z, enhance), lights_for(enhance)
    lo = [np.inf] * len(lights)
    hi = [-np.inf] * len(lights)
    ridge_samples = []
    for window, invalid, ground in windows.values():
        valid = ~invalid
        raws, ridge = relief(window, invalid, ground, style['ve'], lights, enhance)
        for i, raw in enumerate(raws):
            lo[i], hi[i] = min(lo[i], float(raw[valid].min())), max(hi[i], float(raw[valid].max()))
        if ridge is not None:
            ridge_samples.append(np.abs(ridge[valid & (ridge != 0)])[::7])
    ranges = list(zip(lo, hi))
    # the ridge term is scaled by the zoom-wide 95th percentile of |ridge| and soft-limited with tanh
    ridge_scale = 1.0
    if ridge_samples and sum(len(s) for s in ridge_samples):
        ridge_scale = max(float(np.percentile(np.concatenate(ridge_samples), 95)), 1e-6)
    samples, shaded = [], {}
    for key, (window, invalid, ground) in windows.items():
        raws, ridge = relief(window, invalid, ground, style['ve'], lights, enhance)
        intensity = local_contrast(combined_intensity(raws, ranges, lights), invalid, ground, enhance)
        if ridge is not None:
            intensity = intensity + enhance['curv'] * np.tanh(ridge / ridge_scale)
        shaded[key] = intensity
        samples.append(intensity[~invalid][::5])
    return style, shaded, float(np.median(np.concatenate(samples)))


def window_rgba(window, invalid, intensity, median, style, enhance=None):
    """RGBA of a whole padded window (halo included); render_zoom keeps only the tile core."""
    enhance = enhance or BASE_ENHANCE
    position = ramp_position(window.astype(np.float64))
    rgb = expose(shade(deep_colour(position), intensity, median, style['gain']), position, enhance['ev'])
    rgba = np.zeros(window.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = np.round(rgb * 255).astype(np.uint8)
    rgba[..., 3] = np.where(invalid, 0, 255)
    rgba[invalid, :3] = 0          # no survey: transparent, colour irrelevant
    return rgba


def render_zoom(windows, z, enhance=None, *, clip=None):
    """PNG tiles of one zoom; every window's shading is computed over its halo, then cropped to the core."""
    enhance = enhance or BASE_ENHANCE
    style, shaded, median = zoom_shading(windows, z, enhance)
    tiles = {}
    for (x, y), (window, invalid, _) in windows.items():
        pad = (window.shape[0] - TILE) // 2
        rgba = window_rgba(window, invalid, shaded[(x, y)], median, style, enhance)
        core = rgba[pad:-pad, pad:-pad]
        if clip is not None:
            core[~tile_core_region(z, x, y, clip)] = 0
        tiles[(z, x, y)] = encode_png(core)
    return tiles


def output_for(variant, directory=None):
    """base keeps the MAPSTYLE-1 path; the others go in a <variant>/ subdirectory under the same file name,
    so the existing public-build guard (scripts/client-build.mjs) matches every variant unchanged."""
    directory = Path(directory) if directory else DEFAULT_OUTPUT.parent
    return directory / DEFAULT_OUTPUT.name if variant == 'base' else directory / variant / DEFAULT_OUTPUT.name


def supported_maxzoom(sources, *, require_support=False):
    """Upper bound only. Default builds don't attempt fine levels with no certification input."""
    return max([MAXZOOM] + [min(source_maxzoom(s), NATIVE_BASE_MAXZOOM)
                            if require_support and not has_support(s) else source_maxzoom(s)
                            for s in sources])


def build(source, output, minzoom=MINZOOM, maxzoom=None, log=print, variant='medium', native_sources=None,
          label='Morro Bay', coverage_json=None, clip_bounds=None):
    import rasterio
    from rasterio.warp import transform_bounds
    enhance = ENHANCE[variant]
    pad = pad_for(enhance)
    native_sources = native_sources or []
    if maxzoom is None:
        maxzoom = supported_maxzoom(native_sources, require_support=True)
    else:
        maxzoom = min(maxzoom, supported_maxzoom(native_sources))
    if not 0 <= minzoom <= maxzoom <= NATIVE_MAXZOOM:
        raise ValueError('zoom range has no supported levels')
    clip = None
    if clip_bounds is not None:
        west, south, east, north = clip_bounds
        if not (-180 <= west < east <= 180 and -85.05112878 <= south < north <= 85.05112878):
            raise ValueError('clip bounds must be ordered W S E N within Web Mercator')
        clip = transform_bounds('EPSG:4326', 'EPSG:3857', *clip_bounds)
    with rasterio.open(source) as ds:
        if ds.crs.to_epsg() != 3310 or ds.count != 1:
            raise ValueError(f'expected one band in EPSG:3310, got {ds.crs} with {ds.count} bands')
        nodata = ds.nodata if ds.nodata is not None else NODATA
        elevation = ds.read(1).astype(np.float32)
        elevation[~np.isfinite(elevation) | (elevation == np.float32(nodata)) | (elevation > LAND_LIMIT_M)] = NODATA
        src_transform, src_crs = ds.transform, ds.crs
        bounds = transform_bounds(ds.crs, 'EPSG:4326', *ds.bounds, densify_pts=21)
    if clip_bounds is not None:
        bounds = clip_bounds
    elif maxzoom > MAXZOOM:
        for native in native_sources:
            if source_maxzoom(native) > MAXZOOM:
                b = native['bounds']
                bounds = (min(bounds[0], b[0]), min(bounds[1], b[1]), max(bounds[2], b[2]), max(bounds[3], b[3]))

    tiles, support_by_zoom = {}, {}
    for z in range(minzoom, maxzoom + 1):
        support, omitted = {}, {'omitted_uncertified': 0}
        windows = tiered_windows(elevation, src_transform, src_crs, bounds, z, native_sources, pad, support,
                                 clip=clip, omissions=omitted)
        support_by_zoom[str(z)] = dict(omitted, tiles=len(windows),
                                       limit_m=DETAIL_M if z > NATIVE_BASE_MAXZOOM else SHALLOW_M,
                                       sources=sorted(support.values(), key=lambda s: (s['resolution_m'], s['id'])))
        if windows:
            tiles.update(render_zoom(windows, z, enhance, clip=clip))
        log(f'zoom {z}: {len(windows)} tiles')
    centre = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
    if not tiles:
        raise ValueError('no survey support in requested zoom range')
    # Header and metadata describe the levels actually written, not manifest potential.
    minzoom, maxzoom = min(t[0] for t in tiles), max(t[0] for t in tiles)
    metadata = {
        'name': f'SkipperCast {label} seafloor (Deep)' + ('' if variant == 'base' else f', relief {variant}'),
        'description': 'Styled raster of regional bathymetry: cmocean deep ramp with fixed depth stops and '
                       'four-direction hillshade. Transparent = no survey. Mixed vertical references; '
                       'research preview, NOT FOR NAVIGATION.',
        'attribution': 'USGS California Seafloor Mapping Program and other public surveys (via SkipperCast); colours: cmocean',
        'type': 'baselayer', 'format': 'png', 'version': '1', 'ramp': 'deep-fixed-v1', 'relief_variant': variant,
        'relief_settings': enhance,
        'native_sources': [{k: s[k] for k in ('id', 'resolution_m', 'source_file', 'archive_sha256',
                                           'survey_id', 'survey_dates', 'vertical_datum', 'source_url',
                                           'depth_semantics', 'release_date') if k in s}
                           for s in native_sources],
        'shallow_limit_m': SHALLOW_M, 'feather_m': FEATHER_M if native_sources else 0,
        'native_support_by_zoom': support_by_zoom,
        'native_support_basis': 'source support in emitted tile cores; overlapping, not additive; '
                                'z16-17 requires class 3 at <=1 m and nominal 0-20 m; background through z13',
        'minzoom': minzoom, 'maxzoom': maxzoom,
        'bounds': list(clip_bounds) if clip_bounds is not None else [round(v, 6) for v in bounds],
        'center': [round(centre[0], 6), round(centre[1], 6), 10],
    }
    if native_sources:
        metadata['attribution'] = ('Survey sources: ' + ', '.join(s.get('survey_id', s['id']) for s in native_sources)
                                   + '; background where supplied; colours: cmocean')
        metadata['description'] = ('Native <=2 m/5 m shallow surveys where supplied, background where supplied; '
                                   '40 m elevation overlap feather. Transparent = no survey. Vertical '
                                   'references as supplied, not datum-corrected; research preview, NOT FOR NAVIGATION.')
    coverage_sources = [s for s in native_sources if maxzoom > MAXZOOM
                        and source_maxzoom(s) >= max(MAXZOOM + 1, minzoom)]
    metadata['detail_coverage'] = coverage(elevation, (src_transform.a, src_transform.e), coverage_sources, clip_bounds)
    write_pmtiles(output, tiles, metadata=metadata, bounds=bounds, minzoom=minzoom, maxzoom=maxzoom,
                  center=(10, centre[0], centre[1]))
    if coverage_json is not None:
        sidecar = Path(coverage_json)
        part = sidecar.with_name(sidecar.name + '.part')
        part.write_text(json.dumps(dict(metadata['detail_coverage'], archive=Path(output).name),
                                   indent=2, sort_keys=True) + '\n')
        part.replace(sidecar)
    size = Path(output).stat().st_size
    log(f'{output}: {size / 1e6:.1f} MB, zooms {minzoom}-{maxzoom}, {len(tiles)} tiles, relief {variant}')
    return size


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--source', required=True, help='elevation GeoTIFF (EPSG:3310, metres, positive up)')
    parser.add_argument('--output', default=None, help='archive path (one variant only; default var/seafloor/tiles/...)')
    parser.add_argument('--coverage-json', help='local coverage JSON sidecar (one variant only)')
    parser.add_argument('--native-manifest', help='local JSON list of native grid paths and source provenance')
    parser.add_argument('--clip-bounds', type=float, nargs=4, metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'),
                        help='region bounds in WGS84 degrees; defaults to the survey envelope')
    parser.add_argument('--label', default='Morro Bay', help='survey sector name in archive metadata')
    parser.add_argument('--variant', default='medium', choices=[*ENHANCE, 'all'],
                        help='relief enhancement: base (unenhanced), mild, medium, strong, or all four')
    parser.add_argument('--minzoom', type=int, default=MINZOOM)
    parser.add_argument('--maxzoom', type=int, default=None)
    args = parser.parse_args(argv)
    if not Path(args.source).is_file():
        print(f'build_bathy_tiles: source not found: {args.source}', file=sys.stderr)
        return 2
    try:
        native_sources = load_native_manifest(args.native_manifest) if args.native_manifest else []
    except ValueError as e:
        print(f'build_bathy_tiles: native manifest: {e}', file=sys.stderr)
        return 2
    if args.maxzoom is None:
        args.maxzoom = supported_maxzoom(native_sources, require_support=True)
    if not 0 <= args.minzoom <= args.maxzoom <= NATIVE_MAXZOOM:
        print('build_bathy_tiles: need 0 <= minzoom <= maxzoom <= 17', file=sys.stderr)
        return 2
    if args.variant == 'all' and args.output:
        print('build_bathy_tiles: --variant all writes the default file names; drop --output', file=sys.stderr)
        return 2
    if args.variant == 'all' and args.coverage_json:
        print('build_bathy_tiles: --variant all requires dropping --coverage-json', file=sys.stderr)
        return 2
    for variant in (ENHANCE if args.variant == 'all' else [args.variant]):
        try:
            build(args.source, Path(args.output) if args.output else output_for(variant), args.minzoom, args.maxzoom,
                  variant=variant, native_sources=native_sources, label=args.label, coverage_json=args.coverage_json,
                  clip_bounds=args.clip_bounds)
        except ValueError as e:
            print(f'build_bathy_tiles: {e}', file=sys.stderr)
            return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
