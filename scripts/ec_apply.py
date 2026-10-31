"""Apply one ec-detect-v1 receipt to its survey grid (EC2): fill the receipt's `fill` holes and `pits` with the ring
shallowest and mask sentinels to nodata, then write corrected.tif, provenance.tif and EC-APPLY.json (ec-apply-v1).

Run with the survey stack (requirements-survey.txt):

    python scripts/ec_apply.py PATH --detect EC-DETECT.json --out-dir DIR

DIR must be outside the work tree and hold none of the three outputs. Fills use the shallowest 8-neighbour water cell of
the ring (never a mean, median or interpolation); no sign flip, no datum change. The no-deepening gate is not
configurable: if a treated cell got deeper or any untreated cell changed, nothing is written (exit 3). Refusals exit 2.
A receipt `bbox` is inclusive pixel indices `[col0, row0, col1, row1]`; a hole is the 4-connected invalid (masked,
nodata, NaN or sentinel) component with exactly that bbox and `cells`, a pit the `cells` deepest water cells in it.
An input validity mask is kept in corrected.tif. A machine-valid receipt is review-required, not acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio.enums import MaskFlags
from scipy import ndimage

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from skippercast.platform import seafloor_ec as ec  # noqa: E402

OUTPUTS = ('corrected.tif', 'provenance.tif', 'EC-APPLY.json')
EIGHT = np.ones((3, 3), dtype=bool)
HOLE_CODES = {'fill': ec.CODES['filled-hole'], 'ring-range': ec.CODES['unresolved-ring-range'],
              'hole': ec.CODES['unresolved-hole']}


class Refused(Exception):
    def __init__(self, message, code=2):
        super().__init__(f'apply refused: {message}')
        self.code = code


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(doc):
    return (json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode()


def _same(a, b):
    same = a == b
    return same | (np.isnan(a) & np.isnan(b)) if np.issubdtype(a.dtype, np.floating) else same


def _window(bbox, shape):
    """(window slices around the bbox grown by one cell, bbox slices relative to that window)."""
    if any(v != int(v) for v in bbox): raise Refused(f'bbox not integral: {bbox}')
    c0, r0, c1, r1 = (int(v) for v in bbox)
    if not (0 <= r0 <= r1 < shape[0] and 0 <= c0 <= c1 < shape[1]): raise Refused(f'bbox outside grid: {bbox}')
    wr, wc = max(r0 - 1, 0), max(c0 - 1, 0)
    window = (slice(wr, min(r1 + 2, shape[0])), slice(wc, min(c1 + 2, shape[1])))
    return window, (slice(r0 - wr, r1 - wr + 1), slice(c0 - wc, c1 - wc + 1))


def _hole(entry, invalid):
    """The 4-connected invalid component whose bbox and size are exactly the receipt's."""
    window, inner = _window(entry['bbox'], invalid.shape)
    labels, _ = ndimage.label(invalid[window])
    for label, found in enumerate(ndimage.find_objects(labels), 1):
        if found == inner and int((labels == label).sum()) == entry['cells']:
            return window, labels == label
    raise Refused(f'hole mismatch at bbox {entry["bbox"]}')


def _pit(entry, z, water):
    """The `cells` deepest water cells inside the pit's bbox."""
    window, inner = _window(entry['bbox'], z.shape)
    box = np.zeros(z[window].shape, dtype=bool)
    box[inner] = True
    candidates = np.flatnonzero(box & water[window])
    if box.sum() > 4 or len(candidates) < entry['cells']: raise Refused(f'pit mismatch at bbox {entry["bbox"]}')
    order = np.argsort(z[window].ravel()[candidates], kind='stable')[:entry['cells']]
    comp = np.zeros(box.shape, dtype=bool)
    comp.ravel()[candidates[order]] = True
    ring = z[window][ndimage.binary_dilation(comp, EIGHT) & ~comp & water[window]]
    median = float(np.median(ring)) if ring.size else None
    if median is None or not (z[window][comp] < median - ec.outlier_min_m(median)).all():
        raise Refused(f'pit mismatch at bbox {entry["bbox"]}: not an outlier below its ring')
    return window, comp


def _ring(window, comp, z, water):
    values = z[window][ndimage.binary_dilation(comp, EIGHT) & ~comp & water[window]]
    if not values.size: raise Refused('ring mismatch: no water ring')
    return float(values.min()), ec.shoal_pick(values.tolist())


def _fill(after, window, comp, value):
    after[window][comp] = value


def apply(path, detect_path, out_dir):
    try:
        raw = Path(detect_path).read_bytes()
        det = json.loads(raw)
    except (OSError, ValueError) as error:
        raise Refused(f'detect receipt unreadable: {error}') from None
    if not isinstance(det, dict): raise Refused('detect receipt is not an object')
    if det.get('disposition') == 'REFUSED': raise Refused('source refused by detect')
    if det.get('ec_version') != ec.EC_VERSION: raise Refused(f'ec_version {det.get("ec_version")!r} != {ec.EC_VERSION}')
    problems = ec.check_receipt('ec-detect-v1', det)
    if problems: raise Refused('detect receipt: ' + '; '.join(problems[:5]))
    out = Path(out_dir).expanduser().resolve()
    if out == REPO or REPO in out.parents: raise Refused(f'out-dir must be outside the work tree: {out}')
    if any((out / name).exists() for name in OUTPUTS): raise Refused(f'out-dir already holds outputs: {out}')
    input_sha = _sha256(path)
    if input_sha != det['path_sha256']: raise Refused('detect_sha256')

    with rasterio.open(path) as ds:
        if ds.driver != 'GTiff': raise Refused(f'driver {ds.driver} (GeoTIFF only)')
        band, nodata = ds.read(1, masked=True), ds.nodata
        own_mask = MaskFlags.per_dataset in ds.mask_flag_enums[0]  # an explicit validity mask: kept in the output
        z = band.data
        floating = np.issubdtype(z.dtype, np.floating)
        meta = dict(driver='GTiff', width=ds.width, height=ds.height, count=1, dtype=z.dtype.name, crs=ds.crs,
                    transform=ds.transform, nodata=nodata, compress='deflate', **({'predictor': 3} if floating else {}))
        cell_m = float(abs(ds.transform.a))
    finite = np.isfinite(z) if floating else np.ones(z.shape, dtype=bool)
    declared = np.ma.getmaskarray(band).copy()  # masked band 1: the validity mask plus the declared nodata
    if nodata is not None and not np.isnan(nodata): declared |= finite & (z == nodata)
    lo, hi = ec.PLAUSIBLE_M
    sentinel = finite & ~declared & (np.isin(z, ec.SENTINELS) | (z < lo) | (z > hi))
    valid = finite & ~declared & ~sentinel
    water = valid & (z < 0)
    masked = z.copy()
    if sentinel.any():
        if nodata is None and not floating: raise Refused('sentinel cells but no declared nodata')
        masked[sentinel] = np.nan if nodata is None else nodata

    codes = np.where(valid, ec.CODES['measured'], ec.CODES['nodata']).astype(np.uint8)
    codes[sentinel] = ec.CODES['masked-sentinel']
    for spike in det['spikes']:
        window, inner = _window(spike['bbox'], z.shape)
        codes[window][inner][water[window][inner]] = ec.CODES['measured-suspect-shoal']
    after, reference, treated, fixes = masked.copy(), masked.copy(), np.zeros(z.shape, dtype=bool), []
    invalid = ~valid

    def treat(kind, window, comp, code, value=None, deepest=None):
        if (treated[window] & comp).any(): raise Refused(f'duplicate {kind} at bbox {entry["bbox"]}')
        codes[window][comp] = code
        if value is None: return
        treated[window] |= comp
        if kind == 'hole': reference[window][comp] = value  # a hole has no depth: its baseline is the recomputed ring
        _fill(after, window, comp, value)
        fixes.append({'kind': kind, 'cells': int(comp.sum()), 'bbox': entry['bbox'], 'before_min_m': deepest,
                      'after_m': value})

    for entry in det['holes']:
        if entry['disposition'] not in HOLE_CODES: raise Refused(f'hole disposition {entry["disposition"]!r}')
        window, comp = _hole(entry, invalid)
        if entry['disposition'] != 'fill':
            treat('hole', window, comp, HOLE_CODES[entry['disposition']])
            continue
        deepest, shallowest = _ring(window, comp, z, water)
        claimed = entry.get('ring_shallowest_m')
        if claimed is None or abs(claimed - shallowest) > 1e-6:
            raise Refused(f'ring mismatch at bbox {entry["bbox"]}: {claimed} != {shallowest}')
        treat('hole', window, comp, ec.CODES['filled-hole'], shallowest, deepest)
    for entry in det['pits']:
        if entry['cells'] > ec.OUTLIER_MAX_CELLS: continue
        window, comp = _pit(entry, z, water)
        treat('pit', window, comp, ec.CODES['filled-pit'], *reversed(_ring(window, comp, z, water)))

    # No-deepening gate (not configurable): treated cells may only get shallower; nothing else may change.
    index = np.flatnonzero(treated)
    deepened = len(ec.no_deepening(reference.ravel()[index].tolist(), after.ravel()[index].tolist(), range(len(index))))
    deepened += int((~_same(after, masked) & ~treated).sum())
    if deepened: raise Refused(f'deepened {deepened} cells', code=3)
    # A numeric change alone is not a correction if the result is still invalid. Conversely, promoting an
    # intrinsically masked, already-correct depth is a real change even when its stored value is unchanged.
    after_valid = np.isfinite(after) & (after >= lo) & (after <= hi) & ~np.isin(after, ec.SENTINELS)
    if nodata is not None: after_valid &= ~_same(after, np.full_like(after, nodata))
    missing = treated & (~after_valid | (valid & _same(after, masked)))
    if missing.any(): raise Refused(f'uncorrected {int(missing.sum())} cells', code=3)

    out.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out / 'corrected.tif', 'w', **meta) as dst:
        dst.write(after, 1)
        if own_mask: dst.write_mask(valid | treated)  # untreated invalid cells stay invalid; only fills promote
    pmeta = {**{k: v for k, v in meta.items() if k != 'predictor'}, 'dtype': 'uint8', 'nodata': 255}
    with rasterio.open(out / 'provenance.tif', 'w', **pmeta) as dst:
        dst.write(codes, 1)
        dst.update_tags(EC_VERSION=ec.EC_VERSION, SKIPPERCAST_EC_CODES=json.dumps(dict(ec.CODES), sort_keys=True))
    receipt = {
        'schema': 'ec-apply-v1', 'ec_version': ec.EC_VERSION, 'source_id': det['source_id'],
        'detect_sha256': hashlib.sha256(raw).hexdigest(), 'input_sha256': input_sha,
        'corrected_sha256': _sha256(out / 'corrected.tif'), 'provenance_sha256': _sha256(out / 'provenance.tif'),
        'cell_m': cell_m, 'counts': {name: int((codes == code).sum()) for name, code in ec.CODES.items()},
        'duplicate_signature': det['duplicate_signature'], 'fixes': fixes, 'deepened_cells': 0,
        'disposition': 'FIX' if fixes else 'PASS'}
    (out / 'EC-APPLY.json').write_bytes(_canonical(receipt))
    return receipt, out / 'EC-APPLY.json'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Apply an ec-detect-v1 receipt: corrected grid, provenance, receipt.')
    parser.add_argument('path', help='The survey GeoTIFF the detect receipt was made from (never modified).')
    parser.add_argument('--detect', required=True, help='Its ec-detect-v1 receipt.')
    parser.add_argument('--out-dir', required=True, help='Output folder outside the work tree.')
    args = parser.parse_args(argv)
    try:
        receipt, path = apply(Path(args.path), Path(args.detect), Path(args.out_dir))
    except Refused as refusal:
        print(refusal, file=sys.stderr)
        return refusal.code
    print(json.dumps({'disposition': receipt['disposition'], 'receipt': str(path)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
