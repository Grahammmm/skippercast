"""scripts/ec_verify.py (EC3) on synthetic corrected/provenance pairs and hand-written ec-apply-v1 receipts in tmp_path."""
import hashlib
import importlib.util
import json
import shutil

import numpy as np
import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis
rasterio = pytest.importorskip('rasterio')
from rasterio.transform import from_origin  # noqa: E402

ENTRIES = {k: {'id': k, 'adapter': v} for k, v in (('usgs-a', 'geotiff'), ('usgs-b', 'geotiff'), ('usgs-c', 'geotiff'),
           ('bluetopo', 'bluetopo-geotiff-source-review'), ('bag-a', 'bag'), ('bag-b', 'bag'))}
_SPEC = importlib.util.spec_from_file_location('ec_verify', ROOT / 'scripts/ec_verify.py')
EC = importlib.util.module_from_spec(_SPEC)  # seafloor_ec (CODES, check_receipt) through the script's own src path
_SPEC.loader.exec_module(EC)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tif(path, values, crs='EPSG:32610', dtype='float32', nodata=-9999.0, driver='GTiff', x0=500000, **extra):
    with rasterio.open(path, 'w', driver=driver, width=values.shape[1], height=values.shape[0], count=1, dtype=dtype,
                       crs=crs, transform=from_origin(x0, 3900000, 2.0, 2.0), nodata=nodata, **extra) as ds:
        ds.write(np.asarray(values, dtype=dtype), 1)
        if dtype == 'uint8':
            ds.update_tags(EC_VERSION='1.0', SKIPPERCAST_EC_CODES=json.dumps(dict(EC.CODES)))
    return path


def _prov(a, codes, **kw):  # (re)write A's provenance.tif and point EC-APPLY.json at it
    _tif(a / 'provenance.tif', codes, dtype='uint8', nodata=255, compress='deflate', **kw)
    receipt = json.loads((a / 'EC-APPLY.json').read_text())
    (a / 'EC-APPLY.json').write_text(json.dumps({**receipt, 'provenance_sha256': _sha(a / 'provenance.tif')}))


def _a_dir(tmp_path, values, codes, source='usgs-a', signature=None):
    (a := tmp_path / 'a').mkdir()
    _tif(a / 'input.tif', values)
    _tif(a / 'corrected.tif', values)
    receipt = {'schema': 'ec-apply-v1', 'ec_version': '1.0', 'source_id': source, 'detect_sha256': '0' * 64,
               'input_sha256': _sha(a / 'input.tif'), 'corrected_sha256': _sha(a / 'corrected.tif'),
               'cell_m': 2.0, 'counts': {'measured': codes.size}, 'fixes': [], 'deepened_cells': 0, 'disposition': 'PASS',
               'duplicate_signature': signature or [1, 1, 'EPSG:32610', 2.0, -1.0, -1.0, -1.0]}
    (a / 'EC-APPLY.json').write_text(json.dumps(receipt))
    _prov(a, codes)
    (tmp_path / 'entries.json').write_text(json.dumps(ENTRIES))
    return a


def _run(tmp_path, out, bs=(), a_source='usgs-a', a_datum='MLLW', extra=()):
    argv = ['--a', str(tmp_path / 'a'), '--a-source', a_source, '--a-datum', a_datum,
            '--catalog-entries', str(tmp_path / 'entries.json'), '--out-dir', str(tmp_path / out), *extra]
    for path, source, datum in bs:
        argv += ['--b', str(path), '--b-source', source, '--b-datum', datum]
    if code := EC.main(argv):
        return code, None, None
    receipt = json.loads((tmp_path / out / 'EC-VERIFY.json').read_text())
    assert EC.check_receipt('ec-verify-v1', receipt) == []
    with rasterio.open(tmp_path / out / 'provenance.tif') as p, rasterio.open(tmp_path / out / 'shoal_hint.tif') as h:
        return receipt, p.read(1), h.read(1)


@pytest.mark.parametrize('b_name, verdict', [('H54321_MB_2m.tif', 'PASS'), ('H12345_MB_2m.tif', 'FAIL'), ('unknown.tif', 'FAIL')])
def test_region_review_real_bag_receipt_uses_intake_acquisition(tmp_path, monkeypatch, b_name, verdict):
    from tests.unit import test_region_review as review
    import csv

    producer = tmp_path / 'producer'
    producer.mkdir()
    values = np.tile(-20.0 - 0.5 * np.arange(32), (32, 1)).astype('float32')
    adir = _a_dir(producer, values, np.full(values.shape, 10, 'uint8'), source='s-a')
    entries = {**review.ECSRC, 's-a': {**review.ECSRC['s-a'], 'adapter': 'bag'},
               's-b': {**review.ECSRC['s-b'], 'adapter': 'bag'}}
    (producer / 'entries.json').write_text(json.dumps(entries))
    b = _tif(producer / 'H54321_MB_2m.tif', values + 0.3)
    doc, _, _ = _run(producer, 'verified', [(b, 's-b', 'MLLW')], a_source='s-a', extra=['--a-file', 'BAG__H12345_MB_2m.bag'])
    assert doc['pairs'][0]['verified_cells'] == 1024 and doc['pairs'][0]['independent']
    assert 'a_file' not in doc and 'second_file' not in doc['pairs'][0]
    run = tmp_path / 'run'
    region = {'id': 'syn-bay', 'status': 'active', 'source_bindings': {'bathymetry': list(review.SRC)}}
    review.ec_run(run, monkeypatch, region, lambda d, c: d['s-a'].update({'verify/EC-VERIFY.json': doc}))
    monkeypatch.setattr(review.rr, 'loader', lambda _: (region, entries))
    record = json.loads((run / 'EC.json').read_text())
    record['inputs'][0]['sha256'] = _sha(adir / 'input.tif')
    (run / 'EC.json').write_text(json.dumps(record))
    with (run / 'INTAKE.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, ['source_id', 'sha256', 'local_path'])
        writer.writeheader()
        writer.writerows([{'source_id': 's-a', 'sha256': _sha(adir / 'input.tif'), 'local_path': '/private/BAG__H12345_MB_2m.bag'},
                          {'source_id': 's-b', 'sha256': _sha(b), 'local_path': f'/private/{b_name}'}])
    review.seal_ec(run)
    code, packet = review.rerun(run)
    check = next(c for c in packet['checks'] if c['id'] == 'ec-independence')
    assert check['verdict'] == verdict
    assert code == (0 if verdict == 'PASS' else 1)


def test_slope_verifies_patch_and_spike_conflict_with_shoal_hint_and_reruns_identically(tmp_path):
    a = np.tile(-20.0 - 0.5 * np.arange(32), (32, 1)).astype('float32')
    codes = np.full((32, 32), 10, 'uint8')
    codes[5, 5], codes[20, 5] = 20, 11
    a[20, 5] += 6.0
    b = a + 0.3
    b[10:14, 20:24] = -5.0
    b[20, 5] = a[20, 4]
    adir = _a_dir(tmp_path, a, codes)
    corrected = (adir / 'corrected.tif').read_bytes()
    receipt, prov, hint = _run(tmp_path, 'out', [(_tif(tmp_path / 'b.tif', b), 'usgs-b', 'MLLW')])
    conflict = np.zeros((32, 32), bool)
    conflict[10:14, 20:24] = conflict[20, 5] = True
    assert (prov[conflict] == 41).all() and (prov[~conflict] == 30).all() and prov[5, 5] == 30
    assert (hint[10:14, 20:24] == -5.0).all() and hint[20, 5] == a[20, 5] and np.isnan(hint[~conflict]).all()
    assert receipt['pairs'][0]['conflict_cells'] == 17 and receipt['pairs'][0]['verified_cells'] == 32 * 32 - 17
    assert receipt['counts'] == {'verified': 32 * 32 - 17, 'unresolved-conflict': 17}
    assert receipt['disposition'] == 'VERIFY' and (adir / 'corrected.tif').read_bytes() == corrected
    _run(tmp_path, 'again', [(tmp_path / 'b.tif', 'usgs-b', 'MLLW')])
    for name in ('provenance.tif', 'shoal_hint.tif', 'EC-VERIFY.json'):
        assert (tmp_path / 'out' / name).read_bytes() == (tmp_path / 'again' / name).read_bytes(), name


@pytest.fixture
def flat(tmp_path):
    a = np.tile(-19.5 - 0.01 * np.arange(110), (100, 1)).astype('float32')
    _a_dir(tmp_path, a, np.full(a.shape, 10, 'uint8'))
    return a


@pytest.mark.parametrize('offset, a_datum, b_datum, code, comparable, reason', [
    (1.2, 'undeclared', 'MLLW', 43, False, 'datum-suspect'), (1.2, 'MLLW', 'MLLW', 41, True, 'ok'),
    (0.8, 'MLLW', 'MLLW', 30, True, 'ok'), (0.8, 'unverified source datum', 'MLLW', 30, True, 'ok'),
    (1.2, 'MLLW', 'NAVD88', 10, False, 'datum-differs')])
def test_datum_comparability(tmp_path, flat, offset, a_datum, b_datum, code, comparable, reason):
    b = _tif(tmp_path / 'b.tif', flat[:, :100] + offset)  # B covers the first 100 columns only
    receipt, prov, _ = _run(tmp_path, 'out', [(b, 'usgs-b', b_datum)], a_datum=a_datum)
    pair = receipt['pairs'][0]
    assert (pair['jointly_valid_cells'], pair['comparable'], pair['reason']) == (10_000, comparable, reason)
    assert pair['datum_suspect'] is (offset == 1.2) and pair['mad_m'] < 1e-4
    assert (prov[:, :100] == code).all() and (prov[:, 100:] == 10).all()


def test_datum_suspect_never_overrides_verified_and_e9_sees_every_jointly_valid_depth(tmp_path, flat):
    suspect, agree = _tif(tmp_path / 'b.tif', flat + 1.2), _tif(tmp_path / 'c.tif', flat + 0.3)
    receipt, prov, _ = _run(tmp_path, 'out', [(suspect, 'usgs-b', 'undeclared'), (agree, 'usgs-c', 'MLLW')])
    assert [p['reason'] for p in receipt['pairs']] == ['datum-suspect', 'ok'] and (prov == 30).all()
    small = _tif(tmp_path / 'd.tif', np.where(np.arange(110) < 5, flat + 0.3, -9999.0))  # 500 joint cells
    receipt, prov, _ = _run(tmp_path, 'out2', [(small, 'usgs-c', 'undeclared')])
    assert receipt['pairs'][0]['reason'] == 'datum-unchecked' and (prov == 10).all()
    top = np.arange(100)[:, None] < 10  # 1,100 measured cells over 9,900 finite unresolved (42) ones
    _prov(tmp_path / 'a', np.where(top, 10, 42).repeat(110, 1).astype('uint8'))
    for far, code in ((2.0, 43), (0.3, 30)):  # the 42 depths count in E9 but never change
        b = _tif(tmp_path / f'm{far}.tif', np.where(top, flat + 0.3, flat + far))
        receipt, prov, _ = _run(tmp_path, f'm{far}', [(b, 'usgs-b', 'MLLW')], a_datum='undeclared')
        assert (receipt['pairs'][0]['jointly_valid_cells'], receipt['pairs'][0]['datum_suspect']) == (11_000, far > 1)
        assert (prov[:10] == code).all() and (prov[10:] == 42).all()


def test_non_independent_pairs_never_verify(tmp_path, flat):
    adir = tmp_path / 'a'
    sig = [110, 100, 'EPSG:32610', 2.0, round(float(flat.min()), 6), round(float(flat.max()), 6),
           round(float(flat.astype('float64').mean()), 6)]
    cases = [('bluetopo', _tif(tmp_path / 'bt.tif', flat + 0.3), 'compilation:bluetopo-geotiff-source-review'),
             ('usgs-b', shutil.copyfile(adir / 'input.tif', tmp_path / 'same.tif'), 'duplicate'),
             ('usgs-a', _tif(tmp_path / 'own.tif', flat + 0.3), 'same-acquisition:usgs-a')]
    for i, (source, path, reason) in enumerate(cases):
        receipt, prov, _ = _run(tmp_path, f'out{i}', [(path, source, 'MLLW')])
        assert (receipt['pairs'][0]['independent'], receipt['pairs'][0]['reason']) == (False, reason)
        assert (tmp_path / f'out{i}' / 'provenance.tif').read_bytes() == (adir / 'provenance.tif').read_bytes()
        assert receipt['disposition'] == 'PASS'
    receipt, _, _ = _run(tmp_path, 'none')
    assert receipt['pairs'] == [] and receipt['disposition'] == 'PASS' and receipt['counts'] == {'measured': 11_000}
    assert (tmp_path / 'none' / 'provenance.tif').read_bytes() == (adir / 'provenance.tif').read_bytes()
    receipt_doc = json.loads((adir / 'EC-APPLY.json').read_text())
    (adir / 'EC-APPLY.json').write_text(json.dumps({**receipt_doc, 'duplicate_signature': sig, 'source_id': 'bag-a'}))
    reencoded = _tif(tmp_path / 'H12345_MB_2m.tif', flat, compress='lzw')  # other bytes, same signature
    receipt, _, _ = _run(tmp_path, 'sig', [(reencoded, 'usgs-b', 'MLLW')], a_source='bag-a')
    assert receipt['pairs'][0]['reason'] == 'duplicate'
    bag_b = _tif(tmp_path / 'H12345_MB_4m.tif', flat + 0.3)
    for out, extra, reason in (('bag', ['--a-file', 'BAG__H12345_MB_2m.bag'], 'same-acquisition:H12345'),
                               ('bagx', [], 'unknown-acquisition')):
        receipt, prov, _ = _run(tmp_path, out, [(bag_b, 'bag-b', 'MLLW')], a_source='bag-a', extra=extra)
        assert receipt['pairs'][0]['reason'] == reason and (prov == 10).all()


def test_refusals_write_nothing(tmp_path, flat, capsys):
    good = _tif(tmp_path / 'b.tif', flat + 0.3)
    adir = tmp_path / 'a'
    cases = [('cap', [(good, 'usgs-b', 'MLLW')], ['--max-pixels', '100'], 'pixel cap'),
             ('geo', [(_tif(tmp_path / 'g.tif', flat, crs='EPSG:4326'), 'usgs-b', 'MLLW')], [], 'projected-metre'),
             ('envi', [(_tif(tmp_path / 'e.tif', flat + 0.3, driver='ENVI'), 'usgs-b', 'MLLW')], [], 'not GeoTIFF (ENVI)'),
             ('miss', [(good, 'nowhere', 'MLLW')], [], 'catalog entry missing: nowhere'),
             ('count', [], ['--b', str(good)], 'each --b needs'),
             (str(ROOT / 'var' / 'ec3-never'), [], [], 'outside the work tree')]
    for out, bs, extra, message in cases:
        assert _run(tmp_path, out, bs, extra=extra)[0] == 2 and message in capsys.readouterr().err
        assert not (tmp_path / out).exists() and not (ROOT / 'var' / 'ec3-never').exists()
    _run(tmp_path, 'done')
    assert _run(tmp_path, 'done')[0] == 2 and 'outputs exist' in capsys.readouterr().err
    for kw in ({'x0': 600000}, {'crs': 'EPSG:32611'}):  # same shape, other lattice: refused before any write
        _prov(adir, np.full(flat.shape, 10, 'uint8'), **kw)
        assert _run(tmp_path, 'shifted', [(good, 'usgs-b', 'MLLW')])[0] == 2 and 'provenance grid' in capsys.readouterr().err
        assert not (tmp_path / 'shifted').exists()
    receipt = json.loads((adir / 'EC-APPLY.json').read_text())
    for tamper, message in (({'deepened_cells': 1}, 'apply receipt'), ({'provenance_sha256': 'f' * 64}, 'provenance_sha256'),
                            ({'corrected_sha256': 'f' * 64}, 'corrected_sha256'), ({'source_id': 'usgs-b'}, 'source_id')):
        (adir / 'EC-APPLY.json').write_text(json.dumps({**receipt, **tamper}))
        assert _run(tmp_path, 'tampered', [(good, 'usgs-b', 'MLLW')])[0] == 2 and message in capsys.readouterr().err
        assert not (tmp_path / 'tampered').exists()
