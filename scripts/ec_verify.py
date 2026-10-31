#!/usr/bin/env python3
"""EC3: verify a corrected grid against independent second surveys (plans/seafloor-ec DESIGN §6).

`ec_verify.py --a DIR_A --a-source ID --b PATH --b-source ID --b-datum TEXT … --catalog-entries ENTRIES.json --a-datum TEXT
--out-dir DIR` resamples each B nearest onto A's native lattice and, for comparable independent pairs, marks A's measured
and filled cells `verified` (30) when they agree within `tol_m` or `unresolved-conflict` (41) otherwise, with the shallower
reading in `shoal_hint.tif`. Datum-suspect pairs mark their footprint 43 unless a comparable pair verifies the cell. Depths
are never changed and nothing is converted: `corrected.tif` is only hashed. Writes `provenance.tif`, `shoal_hint.tif` and
`EC-VERIFY.json` (`ec-verify-v1`) into DIR, outside the work tree. Exit 0 with one JSON line; exit 2 on refusal.
A machine-valid receipt is review-required; `verified` is agreement within a published tolerance, not a navigation claim.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

from skippercast.platform.seafloor_ec import (  # noqa: E402
    CODES, DATUM_SUSPECT, EC_VERSION, PLAUSIBLE_M, check_receipt, independent, tol_m)

OUTPUTS = ('provenance.tif', 'shoal_hint.tif', 'EC-VERIFY.json')
UNDECLARED = ('undeclared', 'unverified source datum')
TREATABLE = (CODES['measured'], CODES['measured-suspect-shoal'], CODES['filled-hole'], CODES['filled-pit'])


class Refused(Exception):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def tol(depth):
    """Vectorised `seafloor_ec.tol_m`; main() refuses if the two ever disagree."""
    import numpy as np
    return 2.0 * np.sqrt(0.5 ** 2 + (0.013 * np.abs(depth)) ** 2)


def _r(value):
    return None if value is None else round(float(value), 6)


def signature(ds, values):
    """EC1's duplicate signature `[width, height, crs, cell_m, min, max, mean]` over the finite cells, 6 decimals."""
    import numpy as np
    finite = values[np.isfinite(values)]
    stats = [finite.min(), finite.max(), finite.mean()] if finite.size else [None] * 3
    return [ds.width, ds.height, ds.crs.to_string() if ds.crs else '', _r(ds.res[0]), *map(_r, stats)]


def read_b(path, a_ds, max_pixels):
    """B on A's grid (nearest, the coast_qa call re-implemented; research/ is not imported), its sha256 and signature."""
    import numpy as np
    import rasterio
    from rasterio.warp import Resampling, reproject
    with rasterio.open(path) as src:
        crs = src.crs
        if not (crs and crs.is_projected and str(crs.linear_units).lower() in ('metre', 'meter')):
            raise Refused(f'b crs not projected-metre: {Path(path).name}')
        if src.width * src.height > max_pixels:
            raise Refused(f'pixel cap: {Path(path).name}')
        values = src.read(1, masked=True).astype('float64').filled(np.nan)
        sig = signature(src, values)
        out = np.full((a_ds.height, a_ds.width), np.nan, dtype='float64')
        reproject(values, out, src_transform=src.transform, src_crs=crs, src_nodata=np.nan, dst_transform=a_ds.transform,
                  dst_crs=a_ds.crs, dst_nodata=np.nan, resampling=Resampling.nearest)
    return out, sha256(path), sig


def comparability(datums, joint, suspect):
    """(comparable, reason) from the declared datums and the E9 test (DESIGN §6; EC3 decision 3)."""
    a_undeclared, b_undeclared = (d.strip().lower() in UNDECLARED for d in datums)
    if not a_undeclared and not b_undeclared:
        return (True, 'ok') if datums[0] == datums[1] else (False, 'datum-differs')
    if joint < DATUM_SUSPECT['min_cells']:
        return False, 'datum-unchecked'
    return (False, 'datum-suspect') if suspect else (True, 'ok')


def verify(args):
    import numpy as np
    import rasterio
    if any(len(v) != len(args.b) for v in (args.b_source, args.b_datum)):
        raise Refused('each --b needs one --b-source and one --b-datum')
    if abs(tol(0.0) - tol_m(0.0)) > 1e-12 or abs(tol(100.0) - tol_m(100.0)) > 1e-12:
        raise Refused('tolerance differs from seafloor_ec.tol_m')
    a_dir, out_dir = Path(args.a), Path(args.out_dir).expanduser().resolve()
    if out_dir == REPO or REPO in out_dir.parents:
        raise Refused(f'out-dir must be outside the work tree: {out_dir}')
    if any((out_dir / name).exists() for name in OUTPUTS):
        raise Refused('outputs exist')
    apply_path, corrected_path, prov_path = (a_dir / n for n in ('EC-APPLY.json', 'corrected.tif', 'provenance.tif'))
    receipt = json.loads(apply_path.read_text(encoding='utf-8'))
    if check_receipt('ec-apply-v1', receipt):
        raise Refused('apply receipt: ' + '; '.join(check_receipt('ec-apply-v1', receipt)))
    if receipt['source_id'] != args.a_source:
        raise Refused('apply receipt source_id differs from --a-source')
    if receipt['provenance_sha256'] != sha256(prov_path):
        raise Refused('provenance_sha256')
    corrected_sha = sha256(corrected_path)
    if receipt['corrected_sha256'] != corrected_sha:
        raise Refused('corrected_sha256')
    entries = json.loads(Path(args.catalog_entries).read_text(encoding='utf-8'))
    missing = sorted({args.a_source, *args.b_source} - set(entries))
    if missing:
        raise Refused('catalog entry missing: ' + ', '.join(missing))
    with rasterio.open(corrected_path) as a_ds, rasterio.open(prov_path) as p_ds:
        if a_ds.width * a_ds.height > args.max_pixels:
            raise Refused('pixel cap: A')
        a = a_ds.read(1, masked=True).astype('float64').filled(np.nan)
        prov, profile, tags = p_ds.read(1), p_ds.profile, p_ds.tags()
        if prov.shape != a.shape:
            raise Refused('provenance grid differs from corrected grid')
        a_ok = np.isin(prov, TREATABLE) & np.isfinite(a)
        verified, conflict, suspect = (np.zeros(a.shape, bool) for _ in range(3))
        hint = np.full(a.shape, np.nan)
        pairs = []
        for path, b_source, b_datum in zip(args.b, args.b_source, args.b_datum):
            b, b_sha, b_sig = read_b(path, a_ds, args.max_pixels)
            duplicate = b_sha == receipt['input_sha256'] or b_sig == receipt['duplicate_signature']
            ind, reason = independent(entries[args.a_source], args.a_file, entries[b_source], Path(path).name, duplicate)
            joint = a_ok & np.isfinite(b) & (b < 0) & (b >= PLAUSIBLE_M[0])
            diff = (a - b)[joint]
            n = int(joint.sum())
            mean = float(diff.mean()) if n else None
            mad = float(np.median(np.abs(diff - np.median(diff)))) if n else None
            e9 = bool(n >= DATUM_SUSPECT['min_cells'] and abs(mean) > tol_m(float(np.median(np.abs(a[joint]))))
                      and mad < DATUM_SUSPECT['max_mad_m'])
            datums = [args.a_datum, b_datum]
            comparable, why = comparability(datums, n, e9) if ind else (False, reason)
            agree = disagree = np.zeros(a.shape, bool)
            if comparable:
                agree = joint & (np.abs(a - b) <= tol(np.minimum(np.abs(a), np.abs(b))))
                disagree = joint & ~agree
                verified |= agree
                conflict |= disagree
                hint[joint] = np.fmax(hint[joint], np.maximum(a, b)[joint])  # shallowest reading of every comparable pair
            elif ind and why == 'datum-suspect':
                suspect |= joint
            pairs.append({'second_source_id': b_source, 'second_file_sha256': b_sha, 'independent': ind,
                          'reason': why, 'datums': datums, 'comparable': comparable,
                          'jointly_valid_cells': n, 'mean_signed_diff_m': _r(mean), 'mad_m': _r(mad),
                          'verified_cells': int(agree.sum()), 'conflict_cells': int(disagree.sum()), 'datum_suspect': e9})
        new = prov.copy()
        new[suspect & ~verified] = CODES['unresolved-datum-suspect']
        new[verified] = CODES['verified']
        new[conflict] = CODES['unresolved-conflict']
        hint[~conflict] = np.nan
        out_dir.mkdir(parents=True, exist_ok=True)
        if np.array_equal(new, prov):
            shutil.copyfile(prov_path, out_dir / 'provenance.tif')
        else:
            with rasterio.open(out_dir / 'provenance.tif', 'w', **profile) as dst:
                dst.update_tags(**tags)
                dst.write(new, 1)
        hint_profile = {'driver': 'GTiff', 'width': a_ds.width, 'height': a_ds.height, 'count': 1, 'dtype': 'float32',
                        'crs': a_ds.crs, 'transform': a_ds.transform, 'nodata': float('nan'), 'compress': 'deflate',
                        'predictor': 3}
        with rasterio.open(out_dir / 'shoal_hint.tif', 'w', **hint_profile) as dst:
            dst.update_tags(EC_VERSION=EC_VERSION)
            dst.write(hint.astype('float32'), 1)
    codes, cells = np.unique(new, return_counts=True)
    name = {code: key for key, code in CODES.items()}
    written = int(np.isin(new, (CODES['verified'], CODES['unresolved-conflict'])).sum())
    doc = {'schema': 'ec-verify-v1', 'ec_version': EC_VERSION, 'source_id': args.a_source,
           'apply_sha256': sha256(apply_path), 'corrected_sha256': corrected_sha,
           'provenance_sha256': sha256(out_dir / 'provenance.tif'), 'shoal_hint_sha256': sha256(out_dir / 'shoal_hint.tif'),
           'counts': {name[int(c)]: int(k) for c, k in zip(codes, cells)}, 'pairs': pairs,
           'disposition': 'VERIFY' if written else 'PASS'}
    problems = check_receipt('ec-verify-v1', doc)
    if problems:
        raise RuntimeError('ec-verify receipt invalid: ' + '; '.join(problems))
    (out_dir / 'EC-VERIFY.json').write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n',
                                           encoding='utf-8')
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--a', required=True, help='directory with corrected.tif, provenance.tif and EC-APPLY.json')
    parser.add_argument('--a-source', required=True)
    parser.add_argument('--a-datum', required=True, help='verbatim declared datum, or undeclared')
    parser.add_argument('--a-file', default='', help="A's original input file name (BAG survey id; geotiff ignores it)")
    parser.add_argument('--b', action='append', default=[], help='second-survey GeoTIFF (repeatable)')
    parser.add_argument('--b-source', action='append', default=[])
    parser.add_argument('--b-datum', action='append', default=[])
    parser.add_argument('--catalog-entries', required=True, help='JSON {source_id: catalog entry}')
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--max-pixels', type=int, default=120_000_000)
    args = parser.parse_args(argv)
    try:
        doc = verify(args)
    except Refused as exc:
        print(f'verify refused: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'disposition': doc['disposition'], 'receipt': str(Path(args.out_dir) / 'EC-VERIFY.json')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
