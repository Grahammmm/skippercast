import os, pytest
pytestmark = pytest.mark.skipif(os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1", reason="audit repro: set SKIPPERCAST_AUDIT_CLOUD=1")

"""Audit repros: coast raw prefetch (#804), shelf depth contours (6686e33), COAST tier-1 local screen (5df20cc).

Each non-guard test FAILS on current main for the reason in its docstring. Synthetic data only; no network
(every HTTP connection is an in-process fake), nothing written outside tmp_path.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from tests._support import ROOT

# ============================================================================ prefetch

from skippercast.coastal import prefetch as p

URL = 'https://data.ngdc.noaa.gov/survey.bag'


@pytest.fixture(autouse=True)
def _isolated_retry_state(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'RETRY_STATE', tmp_path / 'shared/retry-state.json')


class Reply(io.BytesIO):
    def __init__(self, status=200, body=b'', headers=None):
        super().__init__(body)
        self.status, self.headers = status, headers or {}

    def getheaders(self):
        return list(self.headers.items())

    def getheader(self, name):
        return next((v for k, v in self.headers.items() if k.lower() == name.lower()), None)


class Scripted:
    """Fake connection factory: `entity(callno)` -> (body, headers) for the entity served on that call."""

    def __init__(self, entity):
        self.entity, self.calls = entity, []

    def factory(self, host, port, addresses, **kwargs):
        server = self

        class Connection:
            def request(self, method, target, headers):
                self.method, self.headers = method, headers
                server.calls.append((method, headers.get('Range')))

            def getresponse(self):
                body, extra = server.entity(len(server.calls))
                headers = {'Content-Length': str(len(body)), **extra}
                if self.method == 'HEAD':
                    return Reply(headers=headers)
                begin, end = map(int, self.headers['Range'].removeprefix('bytes=').split('-'))
                part = body[begin:end + 1]
                return Reply(206, part, {**headers, 'Content-Length': str(len(part)),
                                         'Content-Range': f'bytes {begin}-{end}/{len(body)}'})

            def close(self):
                pass
        return Connection()

    def session(self):
        return p.TransferSession(allowed_hosts=['data.ngdc.noaa.gov'],
                                 resolver=lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))],
                                 connection_factory=self.factory, proxies={}, attempts=1,
                                 user_agent='SkipperCast/test coast-campaign-raw-prefetch')


def _row(**kw):
    return {'source': 'noaa-nos', 'url': URL, 'segments': ['C1'], 'bytes': 10, 'sha256': None,
            'licence': 'Public domain; not for navigation', **kw}


def _runner(tmp_path, server, rows=None):
    mount = tmp_path / 'disk'
    mount.mkdir(exist_ok=True)
    return p.Prefetch({'schema_version': 1, 'files': rows or [_row()], 'unresolved': []}, server.session(),
                      root=mount / 'raw', mount=mount, mirror=tmp_path / 'mirror', status=tmp_path / 'status.json',
                      lock_dir=tmp_path / 'locks', clock=lambda: 1000,
                      disk_usage=lambda _: SimpleNamespace(free=p.RESERVE + 10_000_000), ismount=lambda _: True)


def test_prefetch_weak_etag_change_mid_transfer_is_concatenated(tmp_path, monkeypatch):
    """Defect: `validator()` drops a weak ETag and falls back to Last-Modified (1 s granularity) as the If-Range
    resume identity; a response whose (weak) ETag shows a DIFFERENT entity is still appended, so the final file
    mixes bytes of two remote versions and, with no publisher SHA, is receipted as verified.
    Expected: any change of the response ETag (weak or strong) versus HEAD is a Hold; no mixed file is promoted."""
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    old, new = b'AAAAAAAAAA', b'BBBBBBBBBB'
    lm = 'Wed, 21 Oct 2026 07:28:00 GMT'

    def entity(call):        # call 1 HEAD, call 2 first range: old entity; afterwards the publisher replaced it
        return (old, {'ETag': 'W/"v1"', 'Last-Modified': lm}) if call <= 2 else (new, {'ETag': 'W/"v2"', 'Last-Modified': lm})
    server = Scripted(entity)
    run = _runner(tmp_path, server)
    code = run.run()
    final = run.root / 'noaa-nos' / p.filename(_row())
    assert not (final.exists() and final.read_bytes() not in (old, new)), \
        f'mixed-entity file promoted as verified: {final.read_bytes()!r} (exit {code})'


def test_prefetch_missing_primary_manifest_wipes_mirror_receipts(tmp_path):
    """Defect: `manifest()` treats raw/<source>/manifest.jsonl as authoritative and immediately "repairs" the mirror
    from it. If the primary is missing (disk swapped/reformatted, file lost on exFAT) the off-disk mirror - the only
    other copy of the verified receipts - is overwritten with an empty manifest.
    Expected: a mirror holding receipts the primary lacks is a Hold (preserve both), never silently truncated."""
    run = _runner(tmp_path, Scripted(lambda c: (b'x' * 10, {})))
    record = {'url': URL, 'bytes': 10, 'sha256': 'a' * 64, 'path': '/elsewhere/file', 'licence': 'x'}
    mirror = run.mirror / 'noaa-nos.jsonl'
    mirror.parent.mkdir(parents=True)
    mirror.write_text(json.dumps(record, sort_keys=True) + '\n')
    try:
        run.manifest('noaa-nos')
    except p.Hold:
        pass
    assert URL in mirror.read_text(), 'mirror receipts were wiped by an empty primary manifest'


def test_prefetch_receipt_before_rename_leaves_stale_verified_record(tmp_path, monkeypatch):
    """Defect: fetch() writes the verified receipt (manifest + mirror, with `path` = final) BEFORE os.replace(partial,
    final). If the rename fails, and the remote entity then changes, the next pass Holds on the partial identity but
    the manifest still carries a 'verified' record for a final path that never existed.
    Expected: a manifest record never names a final file that does not exist (receipt after rename, or a pending
    marker that is removed/never trusted when the promotion does not complete)."""
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    version = {'etag': '"v1"'}
    server = Scripted(lambda c: (b'0123456789', {'ETag': version['etag']}))
    run = _runner(tmp_path, server)
    final = run.root / 'noaa-nos' / p.filename(_row())
    real = os.replace

    def failing(src, dst, *a, **k):
        if Path(dst) == final:
            raise OSError('synthetic exFAT rename failure')
        return real(src, dst, *a, **k)
    monkeypatch.setattr(p.os, 'replace', failing)
    assert run.run() == 2
    monkeypatch.setattr(p.os, 'replace', real)
    version['etag'] = '"v2"'                                  # publisher replaced the file before the retry
    assert _runner(tmp_path, server).run() == 2
    records = [json.loads(line) for line in (run.root / 'noaa-nos/manifest.jsonl').read_text().splitlines()]
    dangling = [r for r in records if not Path(r['path']).exists()]
    assert not dangling, f'manifest claims verified files that do not exist: {[r["path"] for r in dangling]}'


def test_guard_prefetch_unreceipted_nonempty_partial_is_held(tmp_path, monkeypatch):
    """Guard: nonempty .part bytes without a receipt are never trusted or appended to."""
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    server = Scripted(lambda c: (b'0123456789', {'ETag': '"v1"'}))
    run = _runner(tmp_path, server)
    run.manifest('noaa-nos')
    partial = run.root / 'noaa-nos' / (p.filename(_row()) + '.part')
    partial.write_bytes(b'0123')
    assert run.run() == 2
    assert partial.read_bytes() == b'0123' and not (run.root / 'noaa-nos' / p.filename(_row())).exists()


def test_guard_prefetch_tampered_partial_prefix_is_held(tmp_path, monkeypatch):
    """Guard: a receipted partial whose prefix bytes changed fails the prefix SHA-256 and is preserved."""
    monkeypatch.setattr(p, 'RANGE_BYTES', 4)
    fail = {'at': 3}

    def entity(c):                                             # disconnect on the 2nd range request
        if c == fail['at']:
            raise OSError('synthetic disconnect')
        return (b'0123456789', {'ETag': '"v1"'})
    server = Scripted(entity)
    run = _runner(tmp_path, server)
    assert run.run() == 75
    partial = run.root / 'noaa-nos' / (p.filename(_row()) + '.part')
    partial.write_bytes(b'XXXX')
    fail['at'] = None
    nxt = _runner(tmp_path, server)
    nxt.clock = lambda: 10 ** 9
    assert nxt.run() == 2 and partial.read_bytes() == b'XXXX'


# ============================================================================ depth contours

def _load_builder():
    spec = importlib.util.spec_from_file_location('audit_build_depth_contours', ROOT / 'scripts/build_depth_contours.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tif(path, values, x0, y0, cell=2.0, crs='EPSG:32610', dtype='float32', nodata=-9999.0):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[1], height=values.shape[0], count=1, dtype=dtype,
                       crs=crs, transform=from_origin(x0, y0, cell, cell), nodata=nodata) as ds:
        ds.write(np.asarray(values, dtype=dtype), 1)
    return path


def _sources(*ids, native=2):
    return {i: {'id': i, 'review_status': 'approved', 'needs': ['bathymetry'], 'name': f'Synthetic {i}',
                'documentation_url': 'https://example.invalid/doc', 'rights': {'attribution': 'Synthetic'},
                'survey_year': 2008, 'vertical_datum': None, 'native_resolution_m': native,
                'reviewed_at': '2026-10-01'} for i in ids}


def _run_builder(monkeypatch, grids, sources):
    pytest.importorskip('rasterio')
    bs = _load_builder()
    region = {'id': 'synthetic-bay', 'bounds': [-121.5, 35.0, -120.0, 36.0],
              'source_bindings': {'bathymetry': list(sources)}}
    captured = {}
    monkeypatch.setattr(bs, 'load_region', lambda ident: region)
    monkeypatch.setattr(bs, 'load_catalogs', lambda: (None, sources))
    monkeypatch.setattr(bs, 'atomic_json', lambda path, value: captured.setdefault('doc', value) and {'sha256': '0' * 64, 'bytes': 1})
    argv = ['build_depth_contours.py', '--region', 'synthetic-bay']
    for ident, path in grids.items():
        argv += ['--grid', f'{ident}={path}']
    monkeypatch.setattr(sys, 'argv', argv)
    bs.main()
    return captured['doc']


def _slope(shape, shallow=-10.0, deep=-60.0):
    import numpy as np
    h, w = shape
    return np.tile(np.linspace(shallow, deep, w), (h, 1))


X0, Y0 = 690_000.0, 3_915_000.0


def test_contours_supplied_grid_with_no_water_is_silently_skipped(tmp_path, monkeypatch):
    """Defect: build_depth_contours.py ~84-87/162-163 keeps only values < 0 as water. A supplied, approved grid in the
    positive-down depth convention (or any grid contributing zero blocks, e.g. the same file passed twice) yields
    supported_blocks=0, no features and `continue`: the build succeeds and the output looks complete for the region.
    Expected: refuse when a supplied grid contributes no valid water block (or has no negative values at all)."""
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    b = _tif(tmp_path / 'b.tif', -_slope((64, 64)), X0 + 128, Y0)          # positive-down depths: same seafloor, other sign
    try:
        doc = _run_builder(monkeypatch, {'usgs-a': a, 'usgs-b': b}, _sources('usgs-a', 'usgs-b'))
    except (SystemExit, ValueError):
        return
    listed = {s['source_id']: s['supported_blocks'] for s in doc['provenance']['sources']}
    pytest.fail(f'build succeeded with a supplied grid contributing nothing: {listed}')


def test_contours_native_resolution_not_checked_against_catalog(tmp_path, monkeypatch):
    """Defect: the provenance records `native_cell_m` from catalog native_resolution_m (2 m) without comparing it to
    the supplied GeoTIFF's real cell size; a 4 m resample (not the "original producer GeoTIFF") is accepted and
    labelled 2 m. depth_contours.py's docstring says the grids are "checked by SHA-256" but no hash is checked either.
    Expected: refuse a grid whose cell size differs from the reviewed native resolution."""
    a = _tif(tmp_path / 'a.tif', _slope((32, 32)), X0, Y0, cell=4.0)
    try:
        doc = _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a', native=2))
    except (SystemExit, ValueError):
        return
    pytest.fail(f"4 m grid accepted and recorded as native_cell_m={doc['provenance']['sources'][0]['native_cell_m']}")


def test_guard_contours_feet_levels_and_lonlat(tmp_path, monkeypatch):
    """Guard: a 10-60 m slope gives 30 ft-multiple contours inside 33-196 ft, in lon/lat order, labelled in feet."""
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    doc = _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a'))
    depths = sorted(f['properties']['depth_ft'] for f in doc['features'] if f['properties']['kind'] == 'contour')
    assert depths and all(d % 30 == 0 and 30 <= d <= 196 for d in depths)
    lon, lat = doc['features'][0]['geometry']['coordinates'][0][0]
    assert -121.5 < lon < -120.0 and 35.0 < lat < 36.0 and doc['provenance']['units'] == 'ft'


# ============================================================================ local screen

def _ls_harness():
    pytest.importorskip('rasterio')
    from tests.unit import test_coast_local_screen as t
    return t


@pytest.fixture
def lsmodel(monkeypatch):
    t = _ls_harness()
    fake = t.FakeModel()
    monkeypatch.setattr(t.ls, '_post', fake)
    monkeypatch.setattr(t.ls, '_get', lambda url, timeout: {'data': [{'id': 'fake-model'}]})
    return t


def _rewrite_summary(plan, edit):
    path = plan / 'runs/run-00.json'
    summary = json.loads(path.read_text())
    edit(summary)
    path.write_bytes((json.dumps(summary, sort_keys=True, separators=(',', ':')) + '\n').encode())


def test_local_screen_failed_map_stage_passes(tmp_path, lsmodel):
    """Defect: local_screen.py cmd_stats/_pc9_window trusts the window-level `state == "map_done"` and never checks
    that stages.map.state == "done" (coast_receipt_versions.py:83 does). A window whose map stage FAILED but whose
    stale products still hash is screened tier1 "pass" with no STATE_INCONSISTENT flag.
    Expected: map_done with a map stage not "done" -> STATE_INCONSISTENT -> flag."""
    t = lsmodel
    _, plan = t.build_plan(tmp_path, [dict(col=0, row=0, state='map_done')])

    def fail_map(s):
        s['windows'][0]['stages']['map']['state'] = 'failed'
    _rewrite_summary(plan, fail_map)
    code, doc = t.screen(plan)
    assert code == 0
    w = doc['windows'][0]
    assert w['tier1'] != 'pass', f"failed map stage screened as pass; reasons={w['tier1_reasons']}"


def test_local_screen_empty_population_reports_clean(tmp_path, lsmodel):
    """Defect: a plan whose admission and run summary both hold zero windows assembles exit 0 with no plan flag
    (summary.flags == [], must_examine == []), indistinguishable from a clean screen.
    Expected: an empty admitted population is a plan-level flag (or a refusal), never a clean result."""
    t = lsmodel
    _, plan = t.build_plan(tmp_path, [])
    code, doc = t.screen(plan)
    assert code != 0 or (doc and doc['summary']['flags']), f"empty plan screened clean: {doc and doc['summary']}"


def test_local_screen_dropped_catalog_ref_disables_depth_check_silently(tmp_path, lsmodel):
    """Defect: normalize() only checks the catalog when admission['catalog'] is a dict; an admission without it
    raises no problem, so DEPTH_RANGE_OUT can never fire and windows pass with depth_range_reason
    "catalog_range_unavailable" and no plan flag.
    Expected: a PC-9 admission without a catalog ref is a plan receipt/integrity problem (flag)."""
    t = lsmodel
    root, plan = t.build_plan(tmp_path, [dict(col=0, row=0, state='map_done')], depth_range=[0.0, 5.0])
    adm = json.loads((plan / 'admission.json').read_text())
    del adm['catalog']
    (plan / 'admission.json').write_bytes(t.ls.canonical(adm))

    def repin(s):
        s['admission'] = t._ref(root, plan / 'admission.json')
    _rewrite_summary(plan, repin)
    code, doc = t.screen(plan)
    assert code == 0
    w = doc['windows'][0]
    assert w['tier1'] != 'pass' or doc['summary']['flags'], \
        f"catalog ref dropped: depth check silently off, tier1={w['tier1']}, plan flags={doc['summary']['flags']}"


def test_guard_local_screen_depth_range_out_with_catalog(tmp_path, lsmodel):
    """Guard: with the catalog ref present, depths outside the catalog range flag DEPTH_RANGE_OUT."""
    t = lsmodel
    _, plan = t.build_plan(tmp_path, [dict(col=0, row=0, state='map_done')], depth_range=[0.0, 5.0])
    _, doc = t.screen(plan)
    assert 'DEPTH_RANGE_OUT' in doc['windows'][0]['deterministic']['flags'] and doc['windows'][0]['tier1'] == 'flag'


def test_local_screen_thresholds_file_bad_values_silently_ignored(tmp_path, lsmodel):
    """Defect: load_thresholds() keeps the built-in default for any key that is misspelt or not a number, while
    stats.json records the file's path and SHA as the thresholds source. A stricter reviewed threshold written as a
    string ("0.001") is silently replaced by the default 60 deg, so a window it should flag passes.
    Expected: unknown keys or non-numeric values in --thresholds are refused."""
    t = lsmodel
    _, plan = t.build_plan(tmp_path, [dict(col=0, row=0, state='map_done')])
    thresholds = tmp_path / 'tier2-thresholds.json'
    thresholds.write_text(json.dumps({'tier1_slope_p99_max_deg': '0.001'}))
    code, doc = t.screen(plan, '--thresholds', str(thresholds))
    assert code != 0 or 'SLOPE_P99_HIGH' in doc['windows'][0]['deterministic']['flags'], \
        f"string threshold ignored: in force {doc['thresholds']['tier1_slope_p99_max_deg']}, tier1={doc['windows'][0]['tier1']}"
