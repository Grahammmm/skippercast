"""F21-04 / SCA-545: offline EC3 vertical-metadata controls, not a navigation claim.

Pytest runs only the valid matching-metre control (with the survey stack).
Run `python -B -m tests.unit.test_f21_04_audit` to also replay the audit against
unchanged EC3. It reports a gap with exit 1, not an expected product behavior.
Before applying tolerances or reclassifying provenance, EC3 must establish
reviewed units, scale, offset and sign for BOTH bands. Equivalent encodings
must give the same classifications as the physical-metre pair, or explicitly
refuse the unsupported vertical metadata without writing results.
"""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest


ENCODINGS = {
    # (band unit, metres per unit, GDAL scale, GDAL offset, vertical sign)
    'metres': ('m', 1, 1, 0, 'elevation-up'),
    'unit': ('ft', 0.3048, 1, 0, 'elevation-up'),
    'scale': ('m', 1, 2, 0, 'elevation-up'),
    'offset': ('m', 1, 1, 7, 'elevation-up'),
    'sign': ('m', 1, 1, 0, 'depth-down'),
}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observe(root, name, *, a_encoding='metres', b_encoding='metres', matching=False):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from scripts import ec_verify

    def tif(path, values, encoding=None):
        unit, factor, scale, offset, sign = ENCODINGS[encoding or 'metres']
        direction = 1 if sign == 'elevation-up' else -1
        with rasterio.open(path, 'w', driver='GTiff', crs='EPSG:3310',
                           transform=from_origin(0, 100, 1, 1), width=8, height=8,
                           count=1, dtype='float32' if encoding else 'uint8') as ds:
            if encoding:
                ds.set_band_unit(1, unit)
                ds.scales, ds.offsets = (scale,), (offset,)
                ds.update_tags(1, vertical_sign=sign)  # synthetic review declaration, not a product schema
            ds.write((direction * values / factor - offset) / scale if encoding else values, 1)
        if encoding:
            with rasterio.open(path) as ds:
                assert (ds.units[0], ds.scales[0], ds.offsets[0], ds.tags(1)['vertical_sign']) == (
                    unit, scale, offset, sign)
                np.testing.assert_allclose(direction * factor * (ds.read(1) * scale + offset), values, atol=2e-6)

    case = root / name
    a_dir = case / 'a'
    a_dir.mkdir(parents=True)
    corrected, prov, receipt = (a_dir / n for n in ('corrected.tif', 'provenance.tif', 'EC-APPLY.json'))
    second, catalog, out = case / 'b.tif', case / 'entries.json', case / 'out'
    tif(corrected, np.full((8, 8), -10.0), a_encoding)
    tif(prov, np.full((8, 8), 10, dtype='uint8'))
    # Survey variation puts the matching control above the copy-overlap MAD threshold.
    nearby = np.tile([-10.3, -9.7] * 4, (8, 1))
    tif(second, nearby if matching else nearby * 0.3048, b_encoding)
    receipt.write_text(json.dumps(dict(
        schema='ec-apply-v1', ec_version='1.0', source_id='synthetic-a', detect_sha256='a' * 64,
        input_sha256='b' * 64, corrected_sha256=_sha(corrected), provenance_sha256=_sha(prov),
        cell_m=1, counts={'measured': 64}, duplicate_signature=[8, 8, 'EPSG:3310', 1, -10, -10, -10],
        fixes=[], deepened_cells=0, disposition='PASS')), encoding='utf-8')
    catalog.write_text(json.dumps({key: {'id': key, 'adapter': 'geotiff'}
                                  for key in ('synthetic-a', 'synthetic-b')}), encoding='utf-8')
    inputs = {p: _sha(p) for p in (corrected, prov, receipt, second, catalog)}
    try:
        result = ec_verify.verify(SimpleNamespace(
            a=a_dir, a_source='synthetic-a', a_file='input-a.tif', a_datum='MLLW',
            b=[second], b_source=['synthetic-b'], b_datum=['MLLW'], catalog_entries=catalog,
            out_dir=out, max_pixels=64))
    except ec_verify.Refused as exc:
        assert not out.exists(), 'vertical-metadata refusal wrote results'
        return str(exc)
    finally:
        assert {p: _sha(p) for p in inputs} == inputs, 'EC3 changed fixture inputs'
    pair, = result['pairs']
    with rasterio.open(out / 'provenance.tif') as ds:
        codes, counts = np.unique(ds.read(1), return_counts=True)
    return (pair['independent'], pair['comparable'], pair['verified_cells'], pair['conflict_cells'],
            dict(zip(map(int, codes), map(int, counts))))


MATCH = (True, True, 64, 0, {30: 64})
CONFLICT = (True, True, 0, 64, {41: 64})


@pytest.mark.gis
def test_matching_metres(tmp_path):
    assert _observe(tmp_path, 'matching-metres', matching=True) == MATCH


def _audit(root):
    matching = _observe(root, 'matching-metres', matching=True)
    physical = _observe(root, 'physical-metres')
    print(f'matching-metres: {matching}; physical-metres: {physical}')
    assert matching == MATCH and physical == CONFLICT, 'metre controls did not qualify this replay'
    gap = False
    for field in ('unit', 'scale', 'offset', 'sign'):
        for side in ('a', 'b'):
            name = f'{side}-{field}'
            # Re-encode A of the agreeing pair or B of the conflicting pair.
            # This makes raw-value comparison observable on either input side.
            observed = _observe(root, name, a_encoding=field if side == 'a' else 'metres',
                                b_encoding=field if side == 'b' else 'metres', matching=side == 'a')
            explicit_refusal = isinstance(observed, str) and (
                field in observed.lower() or 'vertical metadata' in observed.lower())
            ok = observed == (matching if side == 'a' else physical) or explicit_refusal
            print(f'{name}: {observed}; {"contract met" if ok else "GAP"}')
            gap |= not ok
    return int(gap)


if __name__ == '__main__':
    # No input paths or live catalog; all writes are disposable synthetic files.
    with TemporaryDirectory(prefix='f21-04-') as scratch:
        raise SystemExit(_audit(Path(scratch)))
