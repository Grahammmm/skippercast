#!/usr/bin/env python3
"""EC1: find the known seafloor error classes in one native GeoTIFF and write an `ec-detect-v1` receipt.

    python scripts/ec_detect.py PATH --source-id ID --receipt OUT.json [--adapter geotiff] [--max-pixels N] [--strip-rows R]

Reads the one named file with the survey stack and writes the receipt only: no raster, never modifies or repairs the
input, no sign flip, datum conversion or interpolation. Thresholds and the schema come from
skippercast.platform.seafloor_ec; seafloor/ is not imported. Checks in order: (a) fixture, (b) sign (either refusal
skips the rest), (c) sentinels, (d) holes, (e) pits and spikes, (f) duplicate signature.

Receipt conventions: `path_sha256` is the sha256 of the file's bytes (no directories are recorded, only `file_name`);
`bbox` is [col0, row0, col1, row1] in native pixels, end-exclusive (v[row0:row1, col0:col1]); metres are rounded to
6 decimals; a declared NaN nodata is recorded as null; `counts` are the codes EC2 would write if it applied the fills
(a cell of a listed hole takes that hole's code before `masked-sentinel`); a refused file has empty `counts` and lists.
Exit 0 prints one JSON line; exit 2 prints `detect refused: <field>: <reason>`. A machine-valid receipt is
review-required, not acceptance.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

import numpy as np
import rasterio
from rasterio.windows import Window
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from skippercast.platform import seafloor_ec as ec  # noqa: E402
from skippercast.platform.contracts import atomic_json  # noqa: E402

# P4's GTiff-only metadata reader and grid checks, loaded from beside this script (it imports nothing from seafloor/).
_spec = importlib.util.spec_from_file_location('preflight_native_grid', Path(__file__).with_name('preflight_native_grid.py'))
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)
Refused = preflight.Refused

T = ec.THRESHOLDS
MAX_PIXELS = 120_000_000
STRIP_ROWS = 1024
LIST_CAP = 10_000  # entries kept in holes[] (size 'hole') and clusters_deep[]; counts stay exact
CROSS = ndimage.generate_binary_structure(2, 1)  # 4-connectivity
SQUARE = np.ones((3, 3), bool)  # 8-neighbour ring
SENTINELS = np.array(T.SENTINELS, np.float64)
COMPOUND = re.compile(r'^\s*(COMPD_CS|COMPOUNDCRS)\[')
DEPTH_DOWN = re.compile(r'AXIS\["[^"]*depth[^"]*",\s*DOWN', re.IGNORECASE)
COUNT_NAMES = ('measured', 'measured-suspect-shoal', 'filled-hole', 'filled-pit', 'unresolved-hole',
               'unresolved-ring-range', 'masked-sentinel', 'nodata')


def _r(value):
    return round(float(value), 6)


def _bbox(sl):
    return [int(sl[1].start), int(sl[0].start), int(sl[1].stop), int(sl[0].stop)]


def gate(args):
    """Every refusal that needs no pixel read, in CLI order; returns (meta, strip_rows)."""
    if args.adapter != 'geotiff':
        raise Refused('adapter', 'bag is wave 2' if 'bag' in str(args.adapter).lower() else
                      f'only geotiff is supported, not {args.adapter!r}')
    if not str(args.source_id or '').strip():
        raise Refused('source_id', 'required')
    if not str(args.receipt or '').strip():
        raise Refused('receipt', 'required')
    if Path(args.receipt).exists():
        raise Refused('receipt', f'{args.receipt} already exists')
    max_pixels = preflight._int_in(args.max_pixels, 'max_pixels', 1)
    strip_rows = preflight._int_in(args.strip_rows, 'strip_rows', 1)
    try:
        meta = preflight.raster_meta(args.path)
    except rasterio.errors.RasterioIOError as err:
        raise Refused('path', str(err)) from None
    # Bands, projected metre CRS, north-up square cells, metre band unit; the pixel cap is ours (whole-grid passes).
    preflight.check_grid(meta, window=[0, 0, 1, 1], vertical_datum='undeclared', vertical_unit='metre',
                         vertical_sign='elevation-up', max_pixels=1)
    pixels = meta['width'] * meta['height']
    if pixels > max_pixels:
        raise Refused('pixels', f'{pixels} pixels exceeds the cap {max_pixels}')
    return meta, strip_rows


def scan(path, strip_rows):
    """Strip-read the band into float32 and classify each cell (declared nodata / sentinel / data) with strip stats."""
    with rasterio.open(path) as ds:
        h, w, nd, crs = ds.height, ds.width, ds.nodata, ds.crs
        v, valid, sent = np.empty((h, w), np.float32), np.empty((h, w), bool), np.empty((h, w), bool)
        n_valid = n_pos = n_data = 0
        total, lo, hi = 0.0, np.inf, -np.inf
        for r0 in range(0, h, strip_rows):
            raw = ds.read(1, window=Window(0, r0, w, min(strip_rows, h - r0)))
            ok = np.isfinite(raw)
            if nd is not None and not np.isnan(nd):
                ok &= raw != nd
            bad_value = ok & (np.isin(raw, SENTINELS) | (raw < ec.PLAUSIBLE_M[0]) | (raw > ec.PLAUSIBLE_M[1]))
            rows = slice(r0, r0 + raw.shape[0])
            v[rows], valid[rows], sent[rows] = raw, ok, bad_value
            good = raw[ok & ~bad_value].astype(np.float64)
            n_valid += int(ok.sum())
            n_pos += int((raw[ok] >= 0).sum())
            if good.size:
                n_data, total = n_data + good.size, total + float(good.sum())
                lo, hi = min(lo, float(good.min())), max(hi, float(good.max()))
    stats = {'n_valid': n_valid, 'n_pos': n_pos, 'n_data': n_data, 'mean': total / n_data if n_data else None,
             'min': lo, 'max': hi}
    return v, valid, sent, stats, {'nodata': nd, 'crs': crs.to_string(), 'wkt': crs.to_wkt()}


def fixture_reasons(path, v, valid):
    reasons = []
    if T.FIXTURE_PATH.search(str(Path(path).resolve())):
        reasons.append('path')
    if v.size < T.FIXTURE_MIN_PIXELS:
        reasons.append('pixels')
    if np.unique(v[::4, ::4][valid[::4, ::4]]).size <= T.FIXTURE_MAX_DISTINCT:  # 1-in-16 sample, then exact
        exact = np.unique(v[valid]).size
        if exact <= T.FIXTURE_MAX_DISTINCT:
            reasons.append('distinct')
        if exact == 1:
            reasons.append('range')
    return reasons


def sign_check(v, valid, stats, info):
    frac = stats['n_pos'] / stats['n_valid'] if stats['n_valid'] else None
    sign = {'refused': False, 'positive_fraction': None if frac is None else _r(frac), 'reason': None}
    if frac is not None and frac >= T.SIGN_POSITIVE_FRACTION:
        sign.update(refused=True, reason='all-positive')
    elif COMPOUND.search(info['wkt']) and DEPTH_DOWN.search(info['wkt']) and stats['n_valid'] \
            and float(np.median(v[valid])) < 0:
        sign.update(refused=True, reason='axis-down-negative')
    return sign


def find_holes(v, data, water, cell_m):
    """(d) Interior nodata/sentinel components with no land neighbour; returns (holes, per-cell predicted code)."""
    bad = ~data
    lab, n = ndimage.label(bad, CROSS)
    drop = np.zeros(n + 1, bool)
    drop[0] = True
    drop[np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])] = True
    drop[lab[ndimage.binary_dilation(data & (v >= 0), CROSS) & bad]] = True
    size = np.bincount(lab.ravel(), minlength=n + 1)
    code, holes, big, max_cells = np.zeros(n + 1, np.uint8), [], 0, T.hole_max_cells(cell_m)
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if drop[i]:
            continue
        cells = int(size[i])
        if cells > max_cells:
            code[i] = ec.CODES['unresolved-hole']
            if big < LIST_CAP:
                holes.append({'cells': cells, 'bbox': _bbox(sl), 'disposition': 'hole'})
            big += 1
            continue
        win = (slice(sl[0].start - 1, sl[0].stop + 1), slice(sl[1].start - 1, sl[1].stop + 1))  # interior: in range
        comp = lab[win] == i
        ring = v[win][ndimage.binary_dilation(comp, SQUARE) & ~comp & water[win]].astype(np.float64)
        shallowest, spread = float(ring.max()), float(ring.max() - ring.min())
        fill = spread <= T.hole_ring_max_range_m(shallowest)
        code[i] = ec.CODES['filled-hole' if fill else 'unresolved-ring-range']
        holes.append({'cells': cells, 'bbox': _bbox(sl), 'ring_shallowest_m': _r(shallowest),
                      'ring_range_m': _r(spread), 'disposition': 'fill' if fill else 'ring-range'})
    return holes, code[lab]


def outlier_components(mask, med, dev, deepest):
    """Components of one outlier mask; ring_median_m/deviation_m are taken at the most extreme cell."""
    lab, _n = ndimage.label(mask, CROSS)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        comp = lab[sl] == i
        d = dev[sl][comp]
        k = int(np.argmin(d) if deepest else np.argmax(d))
        out.append({'cells': int(comp.sum()), 'bbox': _bbox(sl), 'ring_median_m': _r(med[sl][comp][k]),
                    'deviation_m': _r(d[k])})
    return out


def find_outliers(v, water):
    """(e) Pits and spikes against the 3x3 median of water cells (NaN elsewhere, mode='nearest')."""
    med = ndimage.median_filter(np.where(water, v, np.float32(np.nan)), size=3, mode='nearest')
    dev = v - med
    limit = np.maximum(3.0, 0.20 * np.abs(med))  # ec.outlier_min_m, vectorised
    ok = water & np.isfinite(med)
    deep = outlier_components(ok & (dev < -limit), med, dev, True)
    spikes = outlier_components(ok & (dev > limit), med, dev, False)
    pits = [p for p in deep if p['cells'] <= T.OUTLIER_MAX_CELLS]
    clusters = [p for p in deep if p['cells'] > T.OUTLIER_MAX_CELLS][:LIST_CAP]
    return pits, clusters, spikes


def detect(path, source_id, meta, strip_rows):
    v, valid, sent, stats, info = scan(path, strip_rows)
    h, w = v.shape
    cell_m = abs(meta['transform'][0])
    nodata = info['nodata']
    signature = [w, h, info['crs'], _r(cell_m)] + (
        [_r(stats['min']), _r(stats['max']), _r(stats['mean'])] if stats['n_data'] else ['empty'] * 3)
    doc = {'schema': 'ec-detect-v1', 'ec_version': ec.EC_VERSION, 'source_id': source_id, 'file_name': Path(path).name,
           'path_sha256': preflight.sha256_file(path)[0], 'cell_m': _r(cell_m), 'crs': info['crs'], 'width': w,
           'height': h, 'nodata': None if nodata is None or np.isnan(nodata) else float(nodata), 'sentinel_cells': 0,
           'fixture': {'refused': False, 'reasons': fixture_reasons(path, v, valid)},
           'sign': {'refused': False, 'positive_fraction': None, 'reason': None},
           'holes': [], 'pits': [], 'clusters_deep': [], 'spikes': [], 'counts': {},
           'duplicate_signature': signature, 'disposition': 'REFUSED'}
    if doc['fixture']['reasons']:
        doc['fixture']['refused'] = True
        return doc
    doc['sign'] = sign_check(v, valid, stats, info)
    if doc['sign']['refused']:
        return doc
    data = valid & ~sent
    water = data & (v < 0) & (v >= ec.PLAUSIBLE_M[0])  # the builder's water rule
    holes, hole_code = find_holes(v, data, water, cell_m)
    pits, clusters, spikes = find_outliers(v, water)
    listed = hole_code > 0
    per = np.bincount(hole_code.ravel(), minlength=256)
    filled_pit = sum(p['cells'] for p in pits)
    shoal = sum(s['cells'] for s in spikes)
    counts = {'measured': int(data.sum()) - filled_pit - shoal, 'measured-suspect-shoal': shoal,
              'filled-hole': int(per[ec.CODES['filled-hole']]), 'filled-pit': filled_pit,
              'unresolved-hole': int(per[ec.CODES['unresolved-hole']]),
              'unresolved-ring-range': int(per[ec.CODES['unresolved-ring-range']]),
              'masked-sentinel': int((sent & ~listed).sum()), 'nodata': int((~valid & ~listed).sum())}
    disposition = 'FIX' if counts['filled-hole'] or counts['filled-pit'] else 'VERIFY' if (
        spikes or counts['unresolved-hole'] or counts['unresolved-ring-range']) else 'PASS'
    doc.update(sentinel_cells=int(sent.sum()), holes=holes, pits=pits, clusters_deep=clusters, spikes=spikes,
               counts={name: counts[name] for name in COUNT_NAMES}, disposition=disposition)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('path')
    ap.add_argument('--source-id')
    ap.add_argument('--receipt')
    ap.add_argument('--adapter', default='geotiff')
    ap.add_argument('--max-pixels', default=str(MAX_PIXELS))
    ap.add_argument('--strip-rows', default=str(STRIP_ROWS))
    args = ap.parse_args(argv)
    try:
        meta, strip_rows = gate(args)
        doc = detect(args.path, args.source_id.strip(), meta, strip_rows)
    except Refused as err:
        print(f'detect refused: {err}', file=sys.stderr)
        return 2
    problems = ec.check_receipt('ec-detect-v1', doc)
    if problems:  # a bug here, never a property of the input
        raise RuntimeError(f'ec-detect-v1 receipt invalid: {problems}')
    atomic_json(args.receipt, doc)
    print(json.dumps({'disposition': doc['disposition'], 'receipt': args.receipt}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
