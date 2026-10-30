#!/usr/bin/env python3
"""Refuse an unsuitable native grid before any builder or ingest call, or print its identity as JSON.

Outside the native-cache-keyed set: imports nothing from skippercast.seafloor. Reads only the one named file.
"""
import argparse
import hashlib
import json
import math
import sys

# Same cap as seafloor/bedrock_habitat.py and classified_habitat.py (max_pixels); cited, not imported.
MAX_PIXELS = 25_000_000
STRIP_ROWS = 512  # build_depth_contours.py strip read for a 2 m grid: 64 blocks x 16 m / 2 m
METRE = ('metre', 'meter', 'm')


class Refused(Exception):
    def __init__(self, field, reason):
        super().__init__(f'{field}: {reason}')
        self.field = field


def _int_in(value, field, low, high=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise Refused(field, f'not a number: {value!r}')
    if not math.isfinite(number) or number != int(number) or number < low or (high is not None and number > high):
        raise Refused(field, f'must be an integer >= {low}' + (f' and <= {high}' if high else ''))
    return int(number)


def _parse_window(window, width, height):
    if len(window) != 4:
        raise Refused('window', 'needs COL,ROW,WIDTH,HEIGHT')
    vals = []
    for value in window:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise Refused('window', f'not a number: {value!r}')
        if not math.isfinite(number):
            raise Refused('window', f'not finite: {value!r}')
        if number != int(number):
            raise Refused('window', f'not integral: {value!r}')
        if number < 0:
            raise Refused('window', f'negative: {value!r}')
        vals.append(int(number))
    col, row, w, h = vals
    if w < 1 or h < 1:
        raise Refused('window', 'width and height must be >= 1')
    if col + w > width or row + h > height:
        raise Refused('window', f'outside the {width}x{height} raster')
    return vals


def check_grid(meta, *, window, vertical_datum, vertical_unit, vertical_sign, max_pixels=MAX_PIXELS,
               strip_rows=STRIP_ROWS):
    """Validate a metadata dict (never touches files); returns the identity fields or raises Refused."""
    max_pixels = _int_in(max_pixels, 'max_pixels', 1, MAX_PIXELS)
    strip_rows = _int_in(strip_rows, 'strip_rows', 1)
    if meta.get('count') != 1:
        raise Refused('bands', f"need exactly 1 band, found {meta.get('count')}")
    if not meta.get('crs_wkt') or not meta.get('crs_projected') \
            or str(meta.get('crs_linear_units', '')).lower() not in METRE[:2]:
        raise Refused('crs', 'need a projected CRS with metre linear units')
    a, b, _c, d, e, _f = meta['transform']
    if b != 0 or d != 0 or a <= 0 or e >= 0:
        raise Refused('axis', 'grid must be north-up and unrotated (b=d=0, a>0, e<0)')
    if abs(abs(a) - abs(e)) > 1e-9:
        raise Refused('cell', f'cells are not square ({abs(a)} x {abs(e)})')
    width, height = meta['width'], meta['height']
    win = _parse_window(window, width, height) if window is not None else [0, 0, width, min(strip_rows, height)]
    pixels = win[2] * win[3]
    if pixels > max_pixels:
        raise Refused('pixels', f'{pixels} pixels exceeds the cap {max_pixels}')
    if not str(vertical_datum or '').strip():
        raise Refused('vertical_datum', 'declare a datum (the literal "undeclared" is allowed)')
    unit = str(vertical_unit or '').strip().lower()
    band_unit = str(meta.get('band_unit') or '').strip().lower()
    if unit not in METRE or (band_unit and band_unit not in METRE):
        raise Refused('vertical_unit', 'must be metre; the band must not declare another unit')
    if vertical_sign != 'elevation-up':
        raise Refused('vertical_sign', 'only "elevation-up" is supported')
    return {'preflight': 'pass', 'driver': meta.get('driver'), 'crs_wkt': meta['crs_wkt'], 'transform': list(meta['transform']),
            'cell_m': abs(a), 'width': width, 'height': height, 'window': win, 'pixels': pixels,
            'vertical_datum': vertical_datum, 'vertical_unit': vertical_unit, 'vertical_sign': vertical_sign}


def raster_meta(path):
    """The only rasterio user; GTiff only (BAG goes through P5 plus check_grid)."""
    import rasterio
    with rasterio.open(path) as ds:
        if ds.driver != 'GTiff':
            raise Refused('driver', f'{ds.driver} is not GTiff')
        crs = ds.crs
        return {'driver': ds.driver, 'crs_projected': bool(crs and crs.is_projected),
                'crs_linear_units': (crs.linear_units if crs and crs.is_projected else ''),
                'crs_wkt': crs.to_wkt() if crs else '', 'transform': list(ds.transform)[:6], 'width': ds.width,
                'height': ds.height, 'count': ds.count, 'band_unit': (ds.units[0] if ds.units else None) or ''}


def sha256_file(path):
    digest, size = hashlib.sha256(), 0
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('path')
    ap.add_argument('--vertical-datum', required=True)
    ap.add_argument('--vertical-unit', required=True)
    ap.add_argument('--vertical-sign', required=True)
    ap.add_argument('--window', help='COL,ROW,WIDTH,HEIGHT in native cells')
    ap.add_argument('--strip-rows', default=str(STRIP_ROWS))
    ap.add_argument('--max-pixels', default=str(MAX_PIXELS))
    args = ap.parse_args(argv)
    try:
        meta = raster_meta(args.path)
        out = check_grid(meta, window=args.window.split(',') if args.window is not None else None,
                         vertical_datum=args.vertical_datum, vertical_unit=args.vertical_unit,
                         vertical_sign=args.vertical_sign, max_pixels=args.max_pixels, strip_rows=args.strip_rows)
        digest, size = sha256_file(args.path)
    except Refused as err:
        print(f'preflight refused: {err}', file=sys.stderr)
        return 2
    print(json.dumps({'preflight': 'pass', 'path': args.path, 'sha256': digest, 'bytes': size,
                      **{k: v for k, v in out.items() if k != 'preflight'}}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
