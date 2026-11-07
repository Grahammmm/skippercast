#!/usr/bin/env python3
"""Build the "Deep" seafloor base tiles (PMTiles, PNG) from the 10 m Morro Bay survey raster.

    python scripts/build_bathy_tiles.py --source /path/to/elevation.tif

Writes `var/seafloor/tiles/morro-bay-seafloor-deep.pmtiles` (override with `--output`), zooms 8-13,
256 px web-mercator PNG tiles, and prints the file size, zoom range and tile count.

The look is "style 2, Deep" of the map style study (G decision 2026-11-06): the cmocean
`deep` ramp over a nonlinear depth stretch, lit by a four-direction hillshade. The study's
renderer used one fixed crop per picture; tiles cover every zoom, so the depth breakpoints and
the vertical exaggeration follow the zoom (the study's canyon values at zoom 11 and below, its
nearshore values at zoom 13, linear in between: a 1000 px wide canyon view picks zoom 11 tiles and
a 1650 px nearshore view picks zoom 13 tiles, as the study's two pictures did).

The source raster (EPSG:3310, elevation metres, positive up, all negative here) stays the
source of truth; tiles are only a delivery format. A cell with no survey is fully transparent,
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

# Depth stretch (depth in metres -> ramp position 0..1) and vertical exaggeration, copied from
# bathy.py CFG/CROPS of the map style study. Linear interpolation of the breakpoints between
# zoom CANYON_ZOOM and zoom NEARSHORE_ZOOM keeps shelf detail in close and canyon depth in the wide view.
BN = (0.0, 0.22, 0.42, 0.58, 0.74, 0.9, 1.0)
CANYON = {'bp': (60.0, 250.0, 400.0, 550.0, 750.0, 1000.0, 1600.0), 've': 2.2}
NEARSHORE = {'bp': (0.0, 10.0, 20.0, 35.0, 55.0, 85.0, 140.0), 've': 6.0}
CANYON_ZOOM, NEARSHORE_ZOOM = 11, 13
# (azimuth deg, weight); altitude 38 deg. Same as bathy.py `multi`.
LIGHTS = ((225.0, 0.2), (315.0, 0.4), (270.0, 0.2), (360.0, 0.2))
ALTITUDE = 38.0
BLEND_GAIN = 1.8

# MAPSTYLE-2 relief enhancement (contrast and exposure only; ramp, depth stretch and the no-survey
# transparency are untouched). `base` is the MAPSTYLE-1 look, byte for byte. Controls:
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
ENHANCED_PAD = 12            # halo for the blurs: 3 sigma of the widest (4 px) kernel, so tiles still match at seams


def deep_lut():
    return np.frombuffer(bytes.fromhex(''.join(DEEP_HEX)), dtype=np.uint8).reshape(256, 3)


def zoom_ramp(zoom):
    """0 at the canyon zoom and below, 1 at the nearshore zoom and above."""
    return min(1.0, max(0.0, (zoom - CANYON_ZOOM) / (NEARSHORE_ZOOM - CANYON_ZOOM)))


def style_for_zoom(zoom, enhance=None):
    """Depth breakpoints, vertical exaggeration and hillshade gain for a zoom level."""
    enhance = enhance or BASE_ENHANCE
    t = zoom_ramp(zoom)
    bp = tuple(a + (b - a) * t for a, b in zip(CANYON['bp'], NEARSHORE['bp']))
    ve = CANYON['ve'] + (NEARSHORE['ve'] - CANYON['ve']) * t
    return {'bp': bp, 've': ve * (1.0 + enhance['ve_boost'] * t), 'gain': BLEND_GAIN * (1.0 + enhance['gain_boost'] * t)}


def lights_for(enhance=None):
    enhance = enhance or BASE_ENHANCE
    w2 = enhance['light2']
    if w2 <= 0:
        return LIGHTS
    return tuple((az, w * (1.0 - w2)) for az, w in LIGHTS) + ((enhance['light2_az'], w2),)


def pad_for(enhance=None):
    enhance = enhance or BASE_ENHANCE
    return PAD if enhance == BASE_ENHANCE else ENHANCED_PAD


def ramp_position(elevation, bp):
    """Nonlinear depth stretch: shelf detail kept, canyon depth kept (bathy.py `nd`)."""
    return np.interp(-elevation, bp, BN)


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
    sigma = min(4.0, max(1.0, enhance['sigma_m'] / ground))
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
    from rasterio.warp import Resampling, reproject
    transform, ground = tile_grid(z, x, y, pad)
    size = TILE + 2 * pad
    dest = np.full((size, size), NODATA, dtype=np.float32)
    reproject(elevation, dest, src_transform=src_transform, src_crs=src_crs, dst_transform=transform,
              dst_crs='EPSG:3857', src_nodata=NODATA, dst_nodata=NODATA, resampling=Resampling.average,
              init_dest_nodata=True)
    return dest, ground


def zoom_windows(elevation, src_transform, src_crs, bounds, z, pad=PAD):
    """{(x, y): (padded elevation, invalid mask, ground metres per pixel)} for tiles with any survey."""
    xs, ys = tile_range(bounds, z)
    out = {}
    for x in xs:
        for y in ys:
            window, ground = warp_window(elevation, src_transform, src_crs, z, x, y, pad)
            invalid = ~np.isfinite(window) | (window == NODATA)
            if not (~invalid[pad:-pad, pad:-pad]).any():
                continue
            out[(x, y)] = (window, invalid, ground)
    return out


def relief(window, invalid, ground, ve, lights, enhance):
    """Per-light raw illumination and (when the curvature term is on) the ridge signal of one window."""
    filled = fill_nodata(window, invalid)
    raws = [raw_intensity(filled, ground, ve, az) for az, _ in lights]
    ridge = ridge_signal(filled, invalid) if enhance['curv'] > 0 else None
    return raws, ridge


def render_zoom(windows, z, enhance=None):
    """Two passes: zoom-wide hillshade extremes and median (the study's picture-wide constants), then RGBA."""
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
    median = float(np.median(np.concatenate(samples)))
    tiles = {}
    for (x, y), (window, invalid, _) in windows.items():
        pad = (window.shape[0] - TILE) // 2
        position = ramp_position(window.astype(np.float64), style['bp'])
        rgb = expose(shade(deep_colour(position), shaded[(x, y)], median, style['gain']), position, enhance['ev'])
        rgba = np.zeros(window.shape + (4,), dtype=np.uint8)
        rgba[..., :3] = np.round(rgb * 255).astype(np.uint8)
        rgba[..., 3] = np.where(invalid, 0, 255)
        rgba[invalid, :3] = 0          # no survey: transparent, colour irrelevant
        tiles[(z, x, y)] = encode_png(rgba[pad:-pad, pad:-pad])
    return tiles


def output_for(variant, directory=None):
    """base keeps the MAPSTYLE-1 path; the others go in a <variant>/ subdirectory under the same file name,
    so the existing public-build guard (scripts/client-build.mjs) matches every variant unchanged."""
    directory = Path(directory) if directory else DEFAULT_OUTPUT.parent
    return directory / DEFAULT_OUTPUT.name if variant == 'base' else directory / variant / DEFAULT_OUTPUT.name


def build(source, output, minzoom=MINZOOM, maxzoom=MAXZOOM, log=print, variant='base'):
    import rasterio
    from rasterio.warp import transform_bounds
    enhance = ENHANCE[variant]
    pad = pad_for(enhance)
    with rasterio.open(source) as ds:
        if ds.crs.to_epsg() != 3310 or ds.count != 1:
            raise ValueError(f'expected one band in EPSG:3310, got {ds.crs} with {ds.count} bands')
        nodata = ds.nodata if ds.nodata is not None else NODATA
        elevation = ds.read(1).astype(np.float32)
        elevation[~np.isfinite(elevation) | (elevation == np.float32(nodata))] = NODATA
        src_transform, src_crs = ds.transform, ds.crs
        bounds = transform_bounds(ds.crs, 'EPSG:4326', *ds.bounds, densify_pts=21)
    if not (elevation[elevation != NODATA] <= 0).all():
        log('warning: source has cells at or above zero elevation; they are drawn with the shallowest colour')
    tiles = {}
    for z in range(minzoom, maxzoom + 1):
        windows = zoom_windows(elevation, src_transform, src_crs, bounds, z, pad)
        tiles.update(render_zoom(windows, z, enhance))
        log(f'zoom {z}: {len(windows)} tiles')
    centre = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
    metadata = {
        'name': 'SkipperCast Morro Bay seafloor (Deep)' + ('' if variant == 'base' else f', relief {variant}'),
        'description': 'Styled raster of the 10 m Morro Bay survey: cmocean deep ramp, nonlinear depth stretch and '
                       'four-direction hillshade. Transparent = no survey. Mixed vertical references; '
                       'research preview, NOT FOR NAVIGATION.',
        'attribution': 'USGS California Seafloor Mapping Program and other public surveys (via SkipperCast); colours: cmocean',
        'type': 'baselayer', 'format': 'png', 'version': '1', 'relief_variant': variant,
        'relief_settings': enhance,
        'minzoom': minzoom, 'maxzoom': maxzoom, 'bounds': [round(v, 6) for v in bounds],
        'center': [round(centre[0], 6), round(centre[1], 6), 10],
    }
    write_pmtiles(output, tiles, metadata=metadata, bounds=bounds, minzoom=minzoom, maxzoom=maxzoom,
                  center=(10, centre[0], centre[1]))
    size = Path(output).stat().st_size
    log(f'{output}: {size / 1e6:.1f} MB, zooms {minzoom}-{maxzoom}, {len(tiles)} tiles, relief {variant}')
    return size


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--source', required=True, help='elevation GeoTIFF (EPSG:3310, metres, positive up)')
    parser.add_argument('--output', default=None, help='archive path (one variant only; default var/seafloor/tiles/...)')
    parser.add_argument('--variant', default='base', choices=[*ENHANCE, 'all'],
                        help='relief enhancement: base (MAPSTYLE-1 look), mild, medium, strong, or all four')
    parser.add_argument('--minzoom', type=int, default=MINZOOM)
    parser.add_argument('--maxzoom', type=int, default=MAXZOOM)
    args = parser.parse_args(argv)
    if not Path(args.source).is_file():
        print(f'build_bathy_tiles: source not found: {args.source}', file=sys.stderr)
        return 2
    if not 0 <= args.minzoom <= args.maxzoom <= 15:
        print('build_bathy_tiles: need 0 <= minzoom <= maxzoom <= 15', file=sys.stderr)
        return 2
    if args.variant == 'all' and args.output:
        print('build_bathy_tiles: --variant all writes the default file names; drop --output', file=sys.stderr)
        return 2
    for variant in (ENHANCE if args.variant == 'all' else [args.variant]):
        build(args.source, Path(args.output) if args.output else output_for(variant), args.minzoom, args.maxzoom,
              variant=variant)
    return 0


if __name__ == '__main__':
    sys.exit(main())
