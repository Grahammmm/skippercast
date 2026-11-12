#!/usr/bin/env python3
"""Build the private chlorophyll overlay image for the map-style test page (MAPLAYER-CHLR-1).

    python scripts/build_chlorophyll_layer.py --sector central-coast

Fetches the newest NOAA CoastWatch VIIRS SNPP/NOAA-20 merged OCI chlorophyll daily file
(the same official source and reader the app pipeline uses, src/skippercast/pipeline/
noaa_chlorophyll.py) for one sector box and writes, under `var/chlorophyll/<sector>/`
(gitignored, never part of a public build):

    chlorophyll.png    web-mercator RGBA image of the box, "NASA ocean-colour rainbow" (style 4)
    chlorophyll.json   data time, bounds, cell counts, dataset path, resolution and the labels
    source.json        the raw receipt (every cell, gaps as null) so the image can be rebuilt offline

Style 4 of the map style study (layers.py chlr(4), G pick 2026-11-06): matplotlib `turbo` on a log
scale 0.05 to 15 mg/m3, overlay opacity 0.85, bilinear. Cells with no retrieval (cloud, glint, land)
are left fully transparent: a gap is never filled with a made-up value. Smoothing is only between
neighbouring valid cells (normalised convolution), so the picture shows the real ~4 km grid, not a
finer one. Other sectors plug in by adding a box to SECTORS. NOT FOR NAVIGATION: research preview.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
import urllib.request

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from scripts.build_bathy_tiles import encode_png  # noqa: E402

DEFAULT_OUTPUT = ROOT / 'var' / 'chlorophyll'
# sector id -> (west, south, east, north) in degrees. The first one is the pilot.
SECTORS = {
    'central-coast': (-123.0, 34.4, -120.0, 37.2),   # Point Conception to Pigeon Point, to 150 km offshore
}
VMIN, VMAX = 0.05, 15.0     # mg/m3, the study's LogNorm(.05, 15)
OPACITY = 0.85              # the study's alpha
EARTH = 6378137.0
LABEL = 'NOAA VIIRS (SNPP + NOAA-20) merged OCI chlorophyll-a, near real time. Satellite estimate, clouds leave gaps. NOT FOR NAVIGATION.'

# matplotlib `turbo` (Apache-2.0, Google) sampled every 8th of 256 steps, linear in between.
TURBO = np.array([
    (48, 18, 59), (57, 42, 115), (64, 64, 162), (68, 86, 199), (70, 107, 227), (70, 128, 246), (66, 148, 255), (55, 168, 250),
    (40, 188, 235), (28, 205, 216), (24, 221, 194), (31, 233, 175), (50, 242, 152), (78, 249, 125), (109, 254, 98), (139, 255, 75),
    (164, 252, 60), (185, 246, 53), (205, 236, 52), (223, 223, 55), (238, 207, 58), (248, 190, 57), (253, 172, 52), (254, 150, 43),
    (251, 126, 33), (244, 102, 23), (235, 80, 14), (223, 63, 8), (208, 47, 5), (190, 33, 2), (169, 22, 1), (146, 11, 1),
    (122, 4, 3),
], dtype=float)


def turbo(position):
    """RGB (0-255, float) for positions 0..1."""
    x = np.clip(position, 0, 1) * (len(TURBO) - 1)
    lo = np.minimum(x.astype(int), len(TURBO) - 2)
    frac = (x - lo)[..., None]
    return TURBO[lo] * (1 - frac) + TURBO[lo + 1] * frac


def legend_stops(n=13):
    """[[mg/m3, '#rrggbb'], ...] log-spaced over the colour scale, for the page's legend bar."""
    values = np.logspace(math.log10(VMIN), math.log10(VMAX), n)
    colours = np.round(turbo(np.linspace(0, 1, n))).astype(int)
    return [[round(float(v), 4), '#%02x%02x%02x' % tuple(c)] for v, c in zip(values, colours)]


def mercator_y(lat):
    return EARTH * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def inverse_mercator_lat(y):
    return np.degrees(2 * np.arctan(np.exp(y / EARTH)) - np.pi / 2)


def grid_from_result(result):
    """(lats, lons, values) from a noaa_chlorophyll.fetch() result; values are NaN where no retrieval."""
    lats = np.array(sorted({s['latitude'] for s in result['samples']}))
    lons = np.array(sorted({s['longitude'] for s in result['samples']}))
    values = np.full((len(lats), len(lons)), np.nan)
    li = {v: i for i, v in enumerate(lats)}
    xi = {v: i for i, v in enumerate(lons)}
    for s in result['samples']:
        if s['chlorophyll'] is not None:
            values[li[s['latitude']], xi[s['longitude']]] = s['chlorophyll']
    return lats, lons, values


def render(lats, lons, values, bounds, px_m=400.0):
    """RGBA uint8 image in web-mercator pixels over `bounds` (W, S, E, N), plus its pixel size."""
    west, south, east, north = bounds
    x0, x1 = math.radians(west) * EARTH, math.radians(east) * EARTH
    y0, y1 = float(mercator_y(south)), float(mercator_y(north))
    width, height = max(2, round((x1 - x0) / px_m)), max(2, round((y1 - y0) / px_m))
    px = x0 + (np.arange(width) + .5) * (x1 - x0) / width
    py = y1 - (np.arange(height) + .5) * (y1 - y0) / height
    lon = np.degrees(px / EARTH)
    lat = inverse_mercator_lat(py)
    # fractional grid index of every output pixel
    fi = np.interp(lat, lats, np.arange(len(lats)), left=-1, right=len(lats))
    fj = np.interp(lon, lons, np.arange(len(lons)), left=-1, right=len(lons))
    coords = np.array(np.meshgrid(fi, fj, indexing='ij')).reshape(2, -1)
    valid = np.isfinite(values)
    logv = np.where(valid, np.log10(np.clip(np.where(valid, values, 1), 1e-4, None)), 0.0)
    num = ndimage.map_coordinates(logv * valid, coords, order=1, mode='constant', cval=0.0).reshape(height, width)
    den = ndimage.map_coordinates(valid.astype(float), coords, order=1, mode='constant', cval=0.0).reshape(height, width)
    # Only where at least half the surrounding weight is real retrieval; the edge fades over a quarter.
    # The source cell under each pixel (nearest grid node) must itself hold a retrieval, so colour
    # interpolation can never paint inside a missing cell.
    ni = np.clip(np.rint(fi), 0, len(lats) - 1).astype(int)
    nj = np.clip(np.rint(fj), 0, len(lons) - 1).astype(int)
    inside = ((fi >= 0) & (fi <= len(lats) - 1))[:, None] & ((fj >= 0) & (fj <= len(lons) - 1))[None, :]
    ok = (den >= .5) & valid[np.ix_(ni, nj)] & inside
    mean_log = np.where(ok, num / np.where(den > 0, den, 1), 0)
    position = (mean_log - math.log10(VMIN)) / (math.log10(VMAX) - math.log10(VMIN))
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., :3] = np.round(turbo(position)).astype(np.uint8)
    alpha = np.clip((den - .5) * 4, 0, 1) * OPACITY
    rgba[..., 3] = np.round(alpha * 255).astype(np.uint8)
    rgba[~ok] = 0
    return rgba


class Client:
    """The two things pipeline.noaa_chlorophyll needs: get(url, as_binary) and now."""

    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def get(self, url, as_binary=False):
        req = urllib.request.Request(url, headers={'User-Agent': 'SkipperCast map-style test (research preview)'})
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
        return body if as_binary else body.decode('utf-8')


def build(sector, output=DEFAULT_OUTPUT, receipt=None, px_m=400.0, log=print):
    bounds = SECTORS[sector]
    out = Path(output) / sector
    out.mkdir(parents=True, exist_ok=True)
    if receipt:
        result = json.loads(Path(receipt).read_text())
    else:
        from skippercast.pipeline import noaa_chlorophyll
        result = noaa_chlorophyll.fetch(Client(), {'longitude': [bounds[0], bounds[2]], 'latitude': [bounds[1], bounds[3]]})
        (out / 'source.json').write_text(json.dumps(result, separators=(',', ':')))
    lats, lons, values = grid_from_result(result)
    rgba = render(lats, lons, values, bounds, px_m)
    (out / 'chlorophyll.png').write_bytes(encode_png(rgba))
    sample = datetime.fromisoformat(result['sample_at'].replace('Z', '+00:00'))
    finite = values[np.isfinite(values)]
    meta = {
        'sector': sector, 'bounds': list(bounds), 'sample_at': result['sample_at'],
        'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'age_hours_at_build': round((datetime.now(timezone.utc) - sample).total_seconds() / 3600, 1),
        'max_age_hours': 96, 'dataset': result.get('dataset'), 'title': result.get('title'),
        'license': result.get('license'), 'units': 'mg m-3', 'native_resolution_degrees': result.get('native_resolution_degrees'),
        'valid_cells': int(finite.size), 'total_cells': int(values.size),
        'min': float(finite.min()) if finite.size else None, 'max': float(finite.max()) if finite.size else None,
        'median': float(np.median(finite)) if finite.size else None,
        'image': {'width': int(rgba.shape[1]), 'height': int(rgba.shape[0]), 'pixel_m': px_m, 'projection': 'web-mercator'},
        'style': {'id': 'chlorophyll-4', 'ramp': 'turbo', 'scale': 'log10', 'vmin': VMIN, 'vmax': VMAX, 'opacity': OPACITY,
                  'legend': legend_stops()},
        'label': LABEL, 'query_url': result.get('query_url'),
    }
    (out / 'chlorophyll.json').write_text(json.dumps(meta, indent=1))
    log(f"{sector}: sample {meta['sample_at']}, {meta['valid_cells']}/{meta['total_cells']} valid cells, image {rgba.shape[1]}x{rgba.shape[0]}")
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--sector', default='central-coast', choices=sorted(SECTORS))
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--receipt', help='rebuild from a saved source.json instead of fetching')
    parser.add_argument('--pixel-m', type=float, default=400.0)
    args = parser.parse_args(argv)
    build(args.sector, args.output, args.receipt, args.pixel_m)


if __name__ == '__main__':
    main()
