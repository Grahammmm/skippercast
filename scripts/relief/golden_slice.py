#!/usr/bin/env python3
"""SC-MAP-GOLDEN-1: golden-slice end-to-end check of the map pipeline on a small fixed Morro Bay slice.

Run it after every stage merge:   python3 scripts/relief/golden_slice.py [--work DIR]

It reads six held rasters in place (read-only; approved roots only), clips them to a ~2 km x 1.3 km box around
Morro Rock and walks the pipeline stages inventory -> normalize -> select -> mosaic -> tiles -> contours ->
release -> qa (preview is not run here). Each stage writes a receipt (<work>/stages/<stage>.json) and prints
whether it ran as REAL (repo code) or THIN (stand-in kept in this file until the real stage merges). A stage
whose real module (src/skippercast/relief/<stage>.py) has merged but is not wired here FAILS the run on
purpose: wire it in REAL_ADAPTERS, then rerun.

Output: stage table (mode, status, wall s, peak RSS, bytes), hard checks, the known E2E-PROOF-1 spec gaps as
named expected-fail checks (reported as XFAIL; a gap that now passes is reported FLIPPED), and per-km2 runtime
rates for forecasting. Exit code 0 only when every stage and every hard check is green; XFAIL never hides.

Safety: stages run niced (nice 19, ionice idle), one at a time (<= 2 heavy jobs), gated on the map load rule
(load5 < 24) and the disk floors (/ 250 GB, /mnt/agentorange-backup 400 GB). Nothing is downloaded, uploaded,
published or written outside --work. A rerun with unchanged inputs and code does no work.
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VENV_PY = os.environ.get('GOLDEN_VENV_PY') or str(Path.home() / 'repos/skippercast/.venv/bin/python')
DEFAULT_WORK = Path.home() / 'agent-work' / 'golden-slice' / 'w1'

BOX = (-120.872, 35.368, -120.850, 35.380)          # W S E N: ~2.0 km x 1.3 km around Morro Rock
SD = '/mnt/agentorange-backup/seafloor-data'
SOURCES = [
    dict(key='mrr22-089', family='noaa_morrobay_topobathy_2022',
         path=f'{SD}/noaa_morrobay_topobathy_2022/noaa_morrobay_topobathy_2022-MRR22_089/MRR22_089.tif'),
    dict(key='mrr22-090', family='noaa_morrobay_topobathy_2022',
         path=f'{SD}/noaa_morrobay_topobathy_2022/noaa_morrobay_topobathy_2022-MRR22_090/MRR22_090.tif'),
    dict(key='mrr22-093', family='noaa_morrobay_topobathy_2022',
         path=f'{SD}/noaa_morrobay_topobathy_2022/noaa_morrobay_topobathy_2022-MRR22_093/MRR22_093.tif'),
    dict(key='mrr22-094', family='noaa_morrobay_topobathy_2022',
         path=f'{SD}/noaa_morrobay_topobathy_2022/noaa_morrobay_topobathy_2022-MRR22_094/MRR22_094.tif'),
    dict(key='ncmp15-10sfe9416', family='ncmp_topobathy_2015',
         path=f'{SD}/ncmp_topobathy_2015/ncmp_topobathy_2015-2015_NCMP_CA_10SFE9416_BareEarth_1mGrid/'
              '2015_NCMP_CA_10SFE9416_BareEarth_1mGrid.tif'),
    dict(key='bluetopo-bh4585bw', family='nbs_bluetopo',
         path=f'{SD}/nbs_bluetopo/nbs_bluetopo-BlueTopo_BH4585BW_20261006/BlueTopo_BH4585BW_20261006.tiff'),
]
CSMP_WANTED = ['Bathymetry_OffshoreMorroBay.zip', 'Bathymetry_OffshorePointEstero.zip',
               'Bathymetry_OffshorePointBuchon.zip']
CSMP_ROOTS = [f'{SD}/csmp', str(Path.home() / 'agent-work/seafloor-data-1/data')]

# Proof-only family rules (the reviewed table is E2E-04's, the rights rows E2E-05's). rank: lower = preferred.
FAMILY = {
    'noaa_morrobay_topobathy_2022': dict(rank=1, label='measured', catalog=None, datum='NAVD88',
                                         survey='NOAA OCM Morro Bay 2022 topobathy lidar DEM (MRR22)'),
    'ncmp_topobathy_2015': dict(rank=2, label='measured', catalog=None, datum='NAVD88',
                                survey='USACE NCMP 2015 topobathy lidar 1 m bare-earth DEM'),
    'nbs_bluetopo': dict(rank=9, label='estimated', catalog='noaa-bluetopo', datum='NAVD88',
                         survey='NOAA BlueTopo compiled bathymetry (estimated)'),
}

STAGES = ['inventory', 'normalize', 'select', 'mosaic', 'tiles', 'contours', 'release', 'qa']
UPSTREAM = {'inventory': [], 'normalize': ['inventory'], 'select': ['normalize'], 'mosaic': ['select'],
            'tiles': ['select', 'mosaic'], 'contours': ['select', 'normalize', 'mosaic'],
            'release': ['select', 'mosaic', 'tiles', 'contours'], 'qa': ['select', 'mosaic', 'tiles', 'release']}
# Stage -> what runs. 'real' = repo code, 'thin' = stand-in in this file.
MODE = {'inventory': 'thin', 'normalize': 'thin', 'select': 'thin', 'mosaic': 'real', 'tiles': 'real',
        'contours': 'real', 'release': 'thin', 'qa': 'thin'}
REAL_ADAPTERS = {}      # stage -> adapter name, filled in when a src/skippercast/relief/<stage>.py stage is wired
REPO_CODE = {           # repo files whose bytes change a stage's generation
    'select': ['catalog/sources.json'],
    'mosaic': ['research/scripts/coast_mvp/coast_mosaic.py'],
    'tiles': ['scripts/build_bathy_tiles.py'],
    'contours': ['scripts/build_depth_contours.py', 'research/scripts/coast_mvp/coast_contours.py',
                 'catalog/sources.json', 'regions/morro-bay/region.json'],
}
LOAD_MAX = 24.0
FLOORS = {'/': 250, '/mnt/agentorange-backup': 400}
MAX_ATTEMPTS = 2
NODATA = -999999.0
DST_CRS = 'EPSG:26910'


# ---------------------------------------------------------------- helpers
def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def canon(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def slice_area_km2():
    lat = (BOX[1] + BOX[3]) / 2
    return round((BOX[2] - BOX[0]) * 111.32 * math.cos(math.radians(lat)) * (BOX[3] - BOX[1]) * 111.32, 3)


def real_module(stage):
    return REPO / 'src' / 'skippercast' / 'relief' / f'{stage}.py'


def mode_of(stage):
    """real | thin | unwired (a real src/skippercast/relief module merged but no adapter here)."""
    if real_module(stage).exists() and stage not in REAL_ADAPTERS:
        return 'unwired'
    return MODE[stage]


def receipt_path(work, stage):
    return work / 'stages' / f'{stage}.json'


def read_receipt(work, stage):
    p = receipt_path(work, stage)
    return json.loads(p.read_text()) if p.exists() else None


def outputs_of(final):
    return [dict(path=str(p.relative_to(final.parent)), sha256=sha256(p), bytes=p.stat().st_size)
            for p in sorted(final.rglob('*')) if p.is_file()]


def host():
    return {'load5': round(os.getloadavg()[1], 2),
            **{f'free_gb[{k}]': round(shutil.disk_usage(k).free / 1e9, 1) for k in FLOORS}}


def gate(max_wait_min):
    """Wait for the map load rule and disk floors; return a held reason or None."""
    for _ in range(int(max_wait_min) + 1):
        why = []
        l5 = os.getloadavg()[1]
        if l5 >= LOAD_MAX:
            why.append(f'load5 {l5:.1f} >= {LOAD_MAX}')
        for mount, floor in FLOORS.items():
            free = shutil.disk_usage(mount).free / 1e9
            if free < floor:
                why.append(f'{mount} free {free:.0f} GB < floor {floor} GB')
        if not why:
            return None
        if any('floor' in w for w in why):
            return '; '.join(why)
        print(f'  gate: {"; ".join(why)}; waiting 60 s', flush=True)
        time.sleep(60)
    return f'load rule held for {max_wait_min} min'


def parse_time(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith('Elapsed (wall clock) time'):
            t = line.rsplit(' ', 1)[-1].split(':')
            out['wall_s'] = round(sum(float(x) * 60 ** i for i, x in enumerate(reversed(t))), 2)
        elif line.startswith('Maximum resident set size'):
            out['max_rss_mb'] = round(int(line.rsplit(' ', 1)[-1]) / 1024, 1)
    return out


def code_digest(stage):
    files = [(Path(__file__).name, sha256(__file__))] + [(f, sha256(REPO / f)) for f in REPO_CODE.get(stage, [])]
    return canon(files)


def input_fingerprint(stage):
    if stage != 'inventory':
        return []
    rows = []
    for s in SOURCES:
        try:
            st = os.stat(s['path'])
            rows.append([s['path'], st.st_size, st.st_mtime_ns])
        except OSError:
            rows.append([s['path'], None, None])
    return rows


# ---------------------------------------------------------------- stage runner (receipts, idempotence)
def run_stage(work, stage, max_wait_min):
    """Return a dict row: stage, mode, status (ran|done|failed|held|blocked), metrics."""
    mode = mode_of(stage)
    row = dict(stage=stage, mode=mode)
    if mode == 'unwired':
        row.update(status='unwired', note=f'real stage merged ({real_module(stage).relative_to(REPO)}) but not '
                                          'wired in golden_slice.py REAL_ADAPTERS')
        return row
    ups = []
    for u in UPSTREAM[stage]:
        r = read_receipt(work, u)
        if not r or r.get('status') != 'ok':
            row.update(status='blocked', note=f'upstream {u} not ok')
            return row
        ups.append({'stage': u, 'generation': r['generation']})
    gen = canon({'upstream': ups, 'code': code_digest(stage), 'inputs': input_fingerprint(stage),
                 'box': BOX, 'mode': mode})
    prev = read_receipt(work, stage)
    if prev and prev.get('status') == 'ok' and prev.get('generation') == gen and all(
            (work / o['path']).is_file() and (work / o['path']).stat().st_size == o['bytes']
            and sha256(work / o['path']) == o['sha256'] for o in prev['outputs']):
        row.update(status='done', metrics=prev['metrics'], note='no work (receipt current)')
        print(f'[{stage}] DONE (no work) {mode.upper()} generation {gen[:12]}')
        return row
    attempt = prev['attempt'] + 1 if prev and prev.get('generation') == gen and prev.get('status') != 'ok' else 1
    if attempt > MAX_ATTEMPTS:
        row.update(status='held', note=f'{MAX_ATTEMPTS} attempts failed for this generation; fix the cause and '
                                       f'delete {receipt_path(work, stage)} to retry')
        return row
    base = dict(schema='sc-golden-receipt/1', stage=stage, mode=mode, generation=gen, upstream=ups, box=BOX,
                attempt=attempt, host=host())
    held = gate(max_wait_min)
    if held:
        receipt_path(work, stage).write_text(json.dumps(dict(base, status='held', held_reason=held), indent=1))
        row.update(status='held', note=held)
        return row
    print(f'[{stage}] RUN {mode.upper()} (attempt {attempt}) generation {gen[:12]}', flush=True)
    stamp = time.strftime('%Y%m%dT%H%M%S')
    final = work / stage
    tmp = work / f'{stage}.tmp-{os.getpid()}'
    tmp.mkdir()
    tfile = work / 'stages' / f'{stage}.time'
    prefix = [x for x in (['nice', '-n', '19'] + (['ionice', '-c3'] if shutil.which('ionice') else [])) if x]
    cmd = prefix + ['/usr/bin/time', '-v', '-o', str(tfile), sys.executable, str(Path(__file__).resolve()),
                    '--run-stage', stage, '--work', str(work), '--out', str(tmp), '--final', str(final)]
    t0 = time.time()
    with open(work / 'stages' / f'{stage}.log', 'w') as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=REPO).returncode
    metrics = parse_time(tfile) if tfile.exists() else {}
    metrics.setdefault('wall_s', round(time.time() - t0, 2))
    if rc != 0:
        tmp.rename(work / f'{stage}.failed-{stamp}')
        receipt_path(work, stage).write_text(json.dumps(dict(base, status='failed', rc=rc, metrics=metrics,
                                                             outputs=[]), indent=1))
        tail = (work / 'stages' / f'{stage}.log').read_text()[-600:]
        row.update(status='failed', metrics=metrics, note=f'rc={rc}: ...{tail.strip()[-300:]}')
        return row
    if final.exists():
        final.rename(work / f'{stage}.old-{stamp}')
    tmp.rename(final)
    outputs = outputs_of(final)
    metrics.update(output_bytes=sum(o['bytes'] for o in outputs), output_files=len(outputs))
    receipt_path(work, stage).write_text(json.dumps(dict(base, status='ok', rc=0, metrics=metrics, outputs=outputs,
                                                         started_at=time.strftime('%Y-%m-%dT%H:%M:%S%z')), indent=1))
    row.update(status='ran', metrics=metrics)
    print(f'[{stage}] OK wall {metrics["wall_s"]} s, RSS {metrics.get("max_rss_mb")} MB, '
          f'{metrics["output_bytes"] / 1e6:.2f} MB in {len(outputs)} files', flush=True)
    return row


# ---------------------------------------------------------------- stage bodies (run inside --run-stage)
def st_inventory(work, out, final):
    import rasterio
    from rasterio.warp import transform_bounds
    rows, missing = [], []
    for s in SOURCES:
        if not os.path.exists(s['path']):
            missing.append(s['path'])
            continue
        with rasterio.open(s['path']) as ds:
            b = transform_bounds(ds.crs, 'EPSG:4326', *ds.bounds, densify_pts=21)
            touches = not (b[2] < BOX[0] or b[0] > BOX[2] or b[3] < BOX[1] or b[1] > BOX[3])
            rows.append(dict(s, bytes=os.stat(s['path']).st_size, crs=ds.crs.to_string()[:60],
                             geographic=bool(ds.crs.is_geographic), res=[float(v) for v in ds.res], bands=ds.count,
                             nodata=ds.nodata, bounds_wgs84=[round(v, 6) for v in b], touches_slice=touches))
    csmp = {n: [str(p) for root in CSMP_ROOTS if os.path.isdir(root) for p in Path(root).rglob(n)]
            for n in CSMP_WANTED}
    doc = dict(box=BOX, slice_km2=slice_area_km2(), sources=rows, missing=missing, csmp_zips_held=csmp)
    (out / 'inventory.json').write_text(json.dumps(doc, indent=1, sort_keys=True))
    print(json.dumps(dict(sources=len(rows), missing=len(missing), touching=sum(r['touches_slice'] for r in rows))))
    if missing or not all(r['touches_slice'] for r in rows):
        sys.exit('inventory: a fixed slice source is missing or does not touch the slice')


def st_normalize(work, out, final):
    """Thin normaliser: each source -> one EPSG:26910 metre Float32 band-1 grid clipped to the slice box."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import Resampling, transform_bounds
    inv = json.loads((work / 'inventory' / 'inventory.json').read_text())
    (out / 'grids').mkdir()
    w, s, e, n = transform_bounds('EPSG:4326', DST_CRS, *BOX, densify_pts=21)
    index = []
    for r in inv['sources']:
        res = 1.0 if r['res'][0] < 3 or r['geographic'] else 4.0
        west, north = math.floor(w / res) * res, math.ceil(n / res) * res
        width, height = math.ceil((e - west) / res), math.ceil((north - s) / res)
        tr = from_origin(west, north, res, res)
        with rasterio.open(r['path']) as ds, WarpedVRT(
                ds, crs=DST_CRS, transform=tr, width=width, height=height, src_nodata=ds.nodata, nodata=NODATA,
                dtype='float32', resampling=Resampling.bilinear if ds.crs.is_geographic else Resampling.nearest) as v:
            arr = v.read(1)
        valid = np.isfinite(arr) & (arr != NODATA) & (arr > -1e5)
        arr = np.where(valid, arr, NODATA).astype('float32')
        row = dict(key=r['key'], family=r['family'], source_path=r['path'], res_m=res, width=width, height=height,
                   valid_cells=int(valid.sum()), op='clip+warp to EPSG:26910 band 1 (' + (
                       'bilinear' if r['geographic'] else 'nearest') + ')')
        if not valid.any():
            row.update(skipped='no valid cells inside the slice')
            index.append(row)
            continue
        grid = out / 'grids' / f'{r["key"]}.tif'
        with rasterio.open(grid, 'w', driver='GTiff', crs=DST_CRS, transform=tr, width=width, height=height, count=1,
                           dtype='float32', nodata=NODATA, compress='deflate') as o:
            o.write(arr, 1)
        row.update(grid_path=str(final / 'grids' / grid.name), grid_sha256=sha256(grid),
                   source_sha256=None, zmin=round(float(arr[valid].min()), 2), zmax=round(float(arr[valid].max()), 2))
        index.append(row)
    (out / 'index.json').write_text(json.dumps({'grids': index}, indent=1, sort_keys=True))
    print(json.dumps(dict(grids=sum('grid_path' in g for g in index), skipped=sum('skipped' in g for g in index))))
    if sum('grid_path' in g for g in index) < 3:
        sys.exit('normalize: fewer than 3 usable grids in the slice')


def rights_class(row):
    if row is None:
        return 'private', 'no catalog/sources.json rights row (E2E-05 gap)'
    prov = (row.get('provider') or '') + ' ' + json.dumps(row.get('rights', {}))
    if 'MBARI' in prov:
        return 'excluded', 'MBARI research-only'
    if 'CSUMB' in prov:
        return 'private', 'CSUMB co-produced: private until the licence row clears'
    if row.get('review_status') != 'approved':
        return 'private', f'catalog row {row["id"]} review_status={row.get("review_status")}'
    if row.get('rights', {}).get('commercial_use') != 'allowed':
        return 'private', f'catalog row {row["id"]} commercial_use={row.get("rights", {}).get("commercial_use")}'
    return 'public', f'catalog row {row["id"]} approved, commercial use allowed'


def st_select(work, out, final):
    """Thin selector: rights class (public/private), label, max_zoom, mosaic sources + tiler native manifest."""
    catalog = {r['id']: r for r in json.loads((REPO / 'catalog/sources.json').read_text())['sources']}
    grids = [g for g in json.loads((work / 'normalize' / 'index.json').read_text())['grids'] if 'grid_path' in g]
    srcs, native, sel = {'public': [], 'private': []}, {'public': [], 'private': []}, []
    for g in sorted(grids, key=lambda g: g['key']):
        fam = FAMILY[g['family']]
        rc, why = rights_class(catalog.get(fam['catalog']) if fam['catalog'] else None)
        mz = 17 if fam['label'] == 'measured' and g['res_m'] <= 1.0 else None
        sid = f'r{fam["rank"]:02d}-{g["key"]}'
        sel.append(dict(id=sid, family=g['family'], resolution_m=g['res_m'], label=fam['label'], rights_class=rc,
                        rights_reason=why, max_zoom=mz, grid_sha256=g['grid_sha256']))
        m = dict(id=sid, path=g['grid_path'], sha256=g['grid_sha256'], resolution_m=g['res_m'], units='m',
                 value_convention='elevation_positive_up', vertical_datum=fam['datum'], vertical_offset_m=0,
                 citation=fam['survey'], rights=f'{rc}: {why}', attribution=fam['survey'],
                 offset_note='as supplied by the producer; no datum reconciliation (golden slice)')
        # build_bathy_tiles sorts (-res, id) and the LAST equal-resolution grid wins, the reverse of
        # coast_mosaic's (res, id) first-wins; the native id carries the inverted rank so both pick one survey.
        nat = dict(id=f'n{99 - fam["rank"]:02d}-{g["key"]}', path=g['grid_path'], resolution_m=g['res_m'],
                   source_file=Path(g['source_path']).name, archive_sha256=g['grid_sha256'], survey_id=fam['survey'],
                   vertical_datum=fam['datum'], depth_semantics='elevation_positive_up', max_zoom=mz,
                   label=fam['label'], rights_class=rc) if mz else None
        for scope in ('public', 'private'):
            if scope == 'public' and rc != 'public':
                continue
            srcs[scope].append(m)
            if nat:
                native[scope].append(nat)
    json.dump({'id': 'morro-bay-golden-slice', 'bounds': list(BOX)}, open(out / 'region.json', 'w'), indent=1)
    for scope in ('public', 'private'):
        json.dump({'schema_version': 1, 'sources': srcs[scope]}, open(out / f'sources.{scope}.json', 'w'),
                  indent=1, sort_keys=True)
        json.dump(native[scope], open(out / f'native.{scope}.json', 'w'), indent=1, sort_keys=True)
    summary = {k: dict(sources=len(srcs[k]), native=len(native[k])) for k in srcs}
    json.dump(dict(schema='sc-golden-selection/1', box=BOX, summary=summary, sources=sel),
              open(out / 'selection.json', 'w'), indent=1, sort_keys=True)
    print(json.dumps(summary))
    if not srcs['private']:
        sys.exit('select: no private sources')


def _sub(cmd, log_name, out):
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    (out / log_name).write_text(f'$ {" ".join(cmd).replace(str(REPO), "<repo>")}\nrc={p.returncode}\n'
                                f'--- stdout\n{p.stdout[-3000:]}\n--- stderr\n{p.stderr[-4000:]}\n')
    return p


def st_mosaic(work, out, final):
    """REAL: research/scripts/coast_mvp/coast_mosaic.py once per non-empty scope."""
    sel = work / 'select'
    result = {}
    for scope in ('public', 'private'):
        if not json.loads((sel / f'sources.{scope}.json').read_text())['sources']:
            (out / scope).mkdir()
            result[scope] = dict(status='held', reason=f'no {scope} sources (rights rows missing: E2E-05)')
            json.dump(result[scope], open(out / scope / 'HELD.json', 'w'))
            continue
        p = _sub([sys.executable, 'research/scripts/coast_mvp/coast_mosaic.py', '--region', str(sel / 'region.json'),
                  '--sources', str(sel / f'sources.{scope}.json'), '--output', str(out / scope)],
                 f'mosaic-{scope}.log', out)
        if p.returncode:
            sys.stderr.write(p.stderr[-3000:])
            sys.exit(p.returncode)
        result[scope] = dict(status='ok')
    json.dump(result, open(out / 'scopes.json', 'w'), indent=1, sort_keys=True)
    print(json.dumps(result))
    if result['private']['status'] != 'ok':
        sys.exit('mosaic: private scope not built')


def st_tiles(work, out, final):
    """REAL: scripts/build_bathy_tiles.py on the private mosaic with the private native manifest."""
    res = {}
    for scope in ('public', 'private'):
        mos = work / 'mosaic' / scope
        (out / scope).mkdir()
        if (mos / 'HELD.json').exists():
            res[scope] = 'held'
            json.dump(json.loads((mos / 'HELD.json').read_text()), open(out / scope / 'HELD.json', 'w'))
            continue
        cmd = [sys.executable, 'scripts/build_bathy_tiles.py', '--source', str(mos / 'elevation.tif'),
               '--label', 'Morro Bay golden slice (PRIVATE)', '--output', str(out / scope / 'relief.pmtiles'),
               '--coverage-json', str(out / scope / 'coverage.json'), '--variant', 'medium']
        native = work / 'select' / f'native.{scope}.json'
        if json.loads(native.read_text()):
            cmd += ['--native-manifest', str(native)]
        p = _sub(cmd, f'tiles-{scope}.log', out)
        if p.returncode:
            sys.stderr.write(p.stderr[-3000:])
            sys.exit(p.returncode)
        res[scope] = 'ok'
    json.dump(res, open(out / 'scopes.json', 'w'), indent=1)
    print(json.dumps(res))


def st_contours(work, out, final):
    """REAL: (A) build_depth_contours.py on the normalised grids (refusal recorded: E2E-09 input);
    (C) the preview fallback coast_contours.py on the private mosaic."""
    norm = {g['grid_sha256']: g for g in json.loads((work / 'normalize' / 'index.json').read_text())['grids']
            if 'grid_path' in g}
    use = json.loads((work / 'select' / 'selection.json').read_text())['sources']
    pick = {}
    for s in use:
        pick.setdefault(s['family'], s)
    grids = [f'--grid={s["id"]}={norm[s["grid_sha256"]]["grid_path"]}' for s in pick.values()]
    a = _sub([sys.executable, 'scripts/build_depth_contours.py', '--region', 'morro-bay', *grids,
              '--held-output', str(out / 'A-held.geojson')], 'contours-A.log', out)
    mos = work / 'mosaic' / 'private'
    c = _sub([sys.executable, 'research/scripts/coast_mvp/coast_contours.py', '--elevation', str(mos / 'elevation.tif'),
              '--contributor', str(mos / 'contributor.tif'), '--manifest', str(mos / 'manifest.json'),
              '--output', str(out / 'preview'), '--zoom', '10'], 'contours-C.log', out)
    json.dump(dict(A_build_depth_contours_rc=a.returncode, A_last_line=(a.stderr or a.stdout).strip()[-300:],
                   C_coast_contours_rc=c.returncode), open(out / 'attempts.json', 'w'), indent=1, sort_keys=True)
    print('A_build_depth_contours rc', a.returncode, '| C_coast_contours rc', c.returncode)
    if c.returncode:
        sys.stderr.write(c.stderr[-3000:])
        sys.exit(c.returncode)


def st_release(work, out, final):
    """Thin release: exact sha256 + bytes of every layer file; private (never uploadable) unless all public."""
    sel = json.loads((work / 'select' / 'selection.json').read_text())
    layers = ['tiles/private/relief.pmtiles', 'tiles/private/coverage.json', 'mosaic/private/elevation.tif',
              'mosaic/private/contributor.tif', 'mosaic/private/manifest.json', 'select/selection.json',
              'select/sources.private.json', 'select/native.private.json']
    layers += [str(p.relative_to(work)) for p in sorted((work / 'contours' / 'preview').glob('*.geojson'))]
    files = []
    for rel in layers:
        p = work / rel
        if p.is_file():
            files.append(dict(path=rel, sha256=sha256(p), bytes=p.stat().st_size))
    private = any(s['rights_class'] != 'public' for s in sel['sources'])
    rel_doc = dict(schema='sc-golden-release/1', box=BOX, files=files, private=private,
                   public_scope_held=(work / 'mosaic' / 'public' / 'HELD.json').exists(),
                   labels={k: sum(1 for s in sel['sources'] if s['label'] == k) for k in ('measured', 'estimated')},
                   notice='NOT FOR NAVIGATION. Private golden-slice build; never uploaded or published.')
    text = json.dumps(rel_doc, indent=1, sort_keys=True) + '\n'
    (out / 'release.json').write_text(text)
    print('release.json sha256', hashlib.sha256(text.encode()).hexdigest(), 'private', private, 'files', len(files))


# minimal PMTiles v3 reader for QA
def _varint(b, i):
    shift = result = 0
    while True:
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        if not c & 0x80:
            return result, i
        shift += 7


def pmt_header(path):
    with open(path, 'rb') as fh:
        h = fh.read(127)
    if h[:7] != b'PMTiles' or h[7] != 3:
        raise ValueError('not a PMTiles v3 archive')
    keys = ['root_offset', 'root_length', 'meta_offset', 'meta_length', 'leaf_offset', 'leaf_length', 'data_offset',
            'data_length', 'addressed_tiles', 'tile_entries', 'tile_contents']
    out = dict(zip(keys, struct.unpack('<QQQQQQQQQQQ', h[8:96])))
    out.update(internal_compression=h[97], minzoom=h[100], maxzoom=h[101])
    w, s, e, n = struct.unpack('<iiii', h[102:118])
    out['bounds'] = [w / 1e7, s / 1e7, e / 1e7, n / 1e7]
    return out


def pmt_metadata(path, h):
    with open(path, 'rb') as fh:
        fh.seek(h['meta_offset'])
        raw = fh.read(h['meta_length'])
    return json.loads(gzip.decompress(raw) if h['internal_compression'] == 2 else raw)


def _zxy(tid):
    acc, z = 0, 0
    while acc + (1 << z) * (1 << z) <= tid:
        acc += (1 << z) * (1 << z)
        z += 1
    t, n, x, y, s = tid - acc, 1 << z, 0, 0, 1
    while s < n:
        rx = 1 & (t // 2)
        ry = 1 & (t ^ rx)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        t //= 4
        s *= 2
    return z, x, y


def pmt_tiles(path, h):
    out = []

    def directory(raw):
        b = gzip.decompress(raw)
        n, i = _varint(b, 0)
        ids, runs, lens, offs, last = [], [], [], [], 0
        for _ in range(n):
            d, i = _varint(b, i)
            last += d
            ids.append(last)
        for _ in range(n):
            r, i = _varint(b, i)
            runs.append(r)
        for _ in range(n):
            ln, i = _varint(b, i)
            lens.append(ln)
        for k in range(n):
            o, i = _varint(b, i)
            offs.append(offs[k - 1] + lens[k - 1] if o == 0 and k > 0 else o - 1)
        return list(zip(ids, runs, offs, lens))

    with open(path, 'rb') as fh:
        def walk(off, ln):
            fh.seek(off)
            for tid, run, o, length in directory(fh.read(ln)):
                if run == 0:
                    walk(h['leaf_offset'] + o, length)
                else:
                    for k in range(run):
                        z, x, y = _zxy(tid + k)
                        out.append((z, x, y, h['data_offset'] + o, length))
        walk(h['root_offset'], h['root_length'])
    return out


def st_qa(work, out, final):
    """Thin machine QA bound to release.json: land paint, archive bounds vs slice, z16+ paint outside measured
    <=1 m support, NOT FOR NAVIGATION notice. Machine metrics only; review-required, not semantic acceptance."""
    import numpy as np
    import rasterio
    from affine import Affine
    from rasterio.io import MemoryFile
    from rasterio.warp import Resampling, reproject
    origin = 20037508.342789244

    def tile_tr(z, x, y):
        r = 2 * origin / (256 * (1 << z))
        return Affine(r, 0, -origin + x * 256 * r, 0, -r, origin - y * 256 * r)

    rel_sha = sha256(work / 'release' / 'release.json')
    archive = work / 'tiles' / 'private' / 'relief.pmtiles'
    h = pmt_header(archive)
    meta = pmt_metadata(archive, h)
    entries = pmt_tiles(archive, h)
    mos = rasterio.open(work / 'mosaic' / 'private' / 'elevation.tif')
    elev = mos.read(1, masked=True).astype('float32').filled(np.nan)
    fine = []       # measured <= 1 m grids: ok-mask of cells in 0..-20 m
    for n in json.loads((work / 'select' / 'native.private.json').read_text()):
        if n['max_zoom'] == 17 and n['label'] == 'measured':
            with rasterio.open(n['path']) as ds:
                v = ds.read(1, masked=True)
                ok = (~np.ma.getmaskarray(v)) & (v.data <= 0) & (v.data >= -20)
                fine.append((ok.astype('float32'), ds.transform, ds.crs))
    per_zoom, z16 = {}, dict(tiles=0, painted=0, painted_outside_support=0)
    with open(archive, 'rb') as fh:
        for z, x, y, off, ln in entries:
            fh.seek(off)
            with MemoryFile(fh.read(ln)) as mf, mf.open() as ds:
                alpha = ds.read(4) > 0 if ds.count == 4 else np.ones((ds.height, ds.width), bool)
            dst = np.full((256, 256), np.nan, dtype='float32')
            reproject(elev, dst, src_transform=mos.transform, src_crs=mos.crs, src_nodata=np.nan,
                      dst_transform=tile_tr(z, x, y), dst_crs='EPSG:3857', dst_nodata=np.nan,
                      resampling=Resampling.nearest)
            painted = int(alpha.sum())
            a = per_zoom.setdefault(z, dict(tiles=0, painted=0, land_leak=0))
            a['tiles'] += 1
            a['painted'] += painted
            a['land_leak'] += int((alpha & (dst > 3.0)).sum())
            if z >= 16:
                sup = np.zeros((256, 256), dtype='float32')
                for ok, tr, crs in fine:
                    tmp = np.zeros((256, 256), dtype='float32')
                    reproject(ok, tmp, src_transform=tr, src_crs=crs, dst_transform=tile_tr(z, x, y),
                              dst_crs='EPSG:3857', resampling=Resampling.max)
                    sup = np.maximum(sup, tmp)
                z16['tiles'] += 1
                z16['painted'] += painted
                z16['painted_outside_support'] += int((alpha & (sup <= 0)).sum())
    pct = lambda a, b: round(100.0 * a / b, 4) if b else None      # noqa: E731
    for a in per_zoom.values():
        a['land_leak_pct'] = pct(a['land_leak'], a['painted'])
    z16['painted_outside_support_pct'] = pct(z16['painted_outside_support'], z16['painted'])
    b = h['bounds']
    ratio = round((b[2] - b[0]) * (b[3] - b[1]) / ((BOX[2] - BOX[0]) * (BOX[3] - BOX[1])), 3)
    qa = dict(schema='sc-golden-qa/1', release_sha256=rel_sha,
              header=dict(minzoom=h['minzoom'], maxzoom=h['maxzoom'], tiles=h['addressed_tiles'], bounds=b),
              land_leak_by_zoom={str(k): v for k, v in sorted(per_zoom.items())},
              bounds=dict(archive=b, slice=list(BOX), area_ratio=ratio), z16plus=z16,
              not_for_navigation='NOT FOR NAVIGATION' in meta.get('description', ''),
              verdict_note='machine metrics only; review-required, not semantic acceptance')
    (out / 'qa.json').write_text(json.dumps(qa, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: qa[k] for k in ('header', 'bounds', 'z16plus')}))


STAGE_FN = {'inventory': st_inventory, 'normalize': st_normalize, 'select': st_select, 'mosaic': st_mosaic,
            'tiles': st_tiles, 'contours': st_contours, 'release': st_release, 'qa': st_qa}


# ---------------------------------------------------------------- checks
def jload(p):
    return json.loads(Path(p).read_text()) if Path(p).exists() else None


def hard_checks(work):
    """(name, passed, detail): must all pass for a green run."""
    inv, sel = jload(work / 'inventory/inventory.json'), jload(work / 'select/selection.json')
    qa, rel = jload(work / 'qa/qa.json'), jload(work / 'release/release.json')
    cov = jload(work / 'tiles/private/coverage.json')
    out = []
    out.append(('slice sources held and touch the slice', bool(inv) and not inv['missing'] and len(inv['sources']) == 6,
                f'{len(inv["sources"]) if inv else 0}/6 held'))
    out.append(('private scope has measured and estimated sources', bool(sel) and sel['summary']['private']['sources'] >= 3,
                json.dumps(sel['summary']) if sel else 'no selection'))
    man = jload(work / 'mosaic/private/manifest.json')
    out.append(('mosaic has cells', bool(man), 'manifest present' if man else 'no manifest'))
    pm = work / 'tiles/private/relief.pmtiles'
    hdr = None
    if pm.exists():
        try:
            hdr = pmt_header(pm)
        except ValueError:
            hdr = None
    out.append(('relief archive is valid PMTiles v3 with tiles', bool(hdr) and hdr['addressed_tiles'] > 0,
                f'zoom {hdr["minzoom"]}-{hdr["maxzoom"]}, {hdr["addressed_tiles"]} tiles' if hdr else 'no archive'))
    out.append(('tiler wrote a coverage sidecar', cov is not None, 'coverage.json'))
    gj = list((work / 'contours/preview').glob('*.geojson')) if (work / 'contours/preview').exists() else []
    out.append(('preview contours written', bool(gj), f'{len(gj)} geojson'))
    out.append(('release is private and never uploadable', bool(rel) and rel['private'] is True,
                'private=True' if rel else 'no release'))
    out.append(('QA bound to the release sha256', bool(qa) and qa['release_sha256'] == sha256(work / 'release/release.json')
                if qa and rel else False, 'release sha matches' if qa else 'no qa'))
    out.append(('archive carries the NOT FOR NAVIGATION notice', bool(qa) and qa['not_for_navigation'],
                'notice present' if qa and qa['not_for_navigation'] else 'notice missing'))
    return out


def gap_checks(work):
    """Known E2E-PROOF-1 spec gaps as named expected-fail checks: (gap card, name, passed|None, detail)."""
    inv, sel = jload(work / 'inventory/inventory.json'), jload(work / 'select/selection.json')
    qa, att = jload(work / 'qa/qa.json'), jload(work / 'contours/attempts.json')
    res = []
    held = [n for n, v in (inv or {}).get('csmp_zips_held', {}).items() if v]
    res.append(('E2E-02', 'csmp-zips-held (all 3 Morro/Estero/Buchon zips under approved roots)',
                len(held) == len(CSMP_WANTED), f'held: {held or "none"}'))
    res.append(('E2E-03', 'normaliser-merged (src/skippercast/relief/normalize.py)', real_module('normalize').exists(),
                'module present' if real_module('normalize').exists() else 'module absent; thin normaliser used'))
    pub = sel['summary']['public']['sources'] if sel else None
    res.append(('E2E-04/05', 'public-scope-nonempty (approved rights rows)', None if pub is None else pub > 0,
                f'public sources {pub}'))
    msrc = (REPO / 'research/scripts/coast_mvp/coast_mosaic.py').read_text()
    tsrc = (REPO / 'scripts/build_bathy_tiles.py').read_text()
    m_first = "rows.sort(key=lambda row: (row['resolution_m'], row['id']))" in msrc     # first id wins
    t_last = "sorted(sources, key=lambda s: (-s['resolution_m'], s['id']))" in tsrc       # last id wins
    if m_first and t_last:
        res.append(('E2E-04/06', 'tiebreak-agree (mosaic and tiler pick the same equal-resolution winner)', False,
                    'mosaic: lowest id wins; tiler: highest id wins (same ids -> opposite winners)'))
    else:
        res.append(('E2E-04/06', 'tiebreak-agree (mosaic and tiler pick the same equal-resolution winner)', None,
                    'sort rule text changed in coast_mosaic.py/build_bathy_tiles.py: re-evaluate by hand'))
    worst = max((v['land_leak_pct'] or 0 for v in qa['land_leak_by_zoom'].values()), default=None) if qa else None
    res.append(('E2E-06/MB-01', 'land-paint <= 1% of painted pixels at every zoom', None if worst is None else worst <= 1.0,
                f'worst zoom {worst}%'))
    ab = qa['bounds']['archive'] if qa else None
    tol = 1e-4      # degrees (~10 m): archive header bounds must be clipped to the slice box
    inside = None if ab is None else (ab[0] >= BOX[0] - tol and ab[1] >= BOX[1] - tol
                                      and ab[2] <= BOX[2] + tol and ab[3] <= BOX[3] + tol)
    res.append(('E2E-07', 'archive-bounds clipped to the slice box (tolerance 0.0001 deg)', inside,
                f'archive bounds {ab}, area ratio {qa["bounds"]["area_ratio"] if qa else None}x'))
    out_pct = qa['z16plus']['painted_outside_support_pct'] if qa else None
    res.append(('E2E-07', 'z16-17 paint outside measured <=1 m support <= 1%', None if out_pct is None else out_pct <= 1.0,
                f'{out_pct}% outside support'))
    a_rc = att['A_build_depth_contours_rc'] if att else None
    res.append(('E2E-09', 'build_depth_contours accepts the normalised grids', None if a_rc is None else a_rc == 0,
                f'rc {a_rc}: {att["A_last_line"][-120:] if att else ""}'))
    res.append(('E2E-11', 'preview-stage-merged (src/skippercast/relief/preview.py)', real_module('preview').exists(),
                'module present' if real_module('preview').exists() else 'module absent; preview not run here'))
    return res


# ---------------------------------------------------------------- driver
def ensure_python():
    try:
        import numpy  # noqa: F401
        import rasterio  # noqa: F401
        return
    except ImportError:
        if os.environ.get('GOLDEN_REEXEC') or not os.path.exists(VENV_PY):
            sys.exit('golden_slice needs numpy+rasterio (try the skippercast venv: ' + VENV_PY + ')')
        os.environ['GOLDEN_REEXEC'] = '1'
        os.execv(VENV_PY, [VENV_PY] + sys.argv)


def fmt(v, spec):
    return '-' if v is None else format(v, spec)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--work', type=Path, default=DEFAULT_WORK, help=f'work dir (default {DEFAULT_WORK})')
    ap.add_argument('--max-wait-min', type=int, default=10, help='max minutes to wait for the load rule per stage')
    ap.add_argument('--forecast-km2', type=float, help='also print a linear compute forecast for this area')
    ap.add_argument('--run-stage', choices=STAGES, help=argparse.SUPPRESS)
    ap.add_argument('--out', type=Path, help=argparse.SUPPRESS)
    ap.add_argument('--final', type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    ensure_python()
    work = args.work.expanduser().resolve()
    if str(work).startswith('/mnt/privatevault'):
        sys.exit('refused: never touch /mnt/privatevault')
    if args.run_stage:
        STAGE_FN[args.run_stage](work, args.out, args.final)
        return 0
    (work / 'stages').mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rows, blocked = [], False
    print(f'golden slice {BOX} ({slice_area_km2()} km2), work {work}, repo {REPO}')
    for stage in STAGES:
        if blocked:
            rows.append(dict(stage=stage, mode=mode_of(stage), status='blocked', note='earlier stage not ok'))
            continue
        row = run_stage(work, stage, args.max_wait_min)
        rows.append(row)
        if row['status'] not in ('ran', 'done'):
            blocked = True
    rows.append(dict(stage='preview', mode='skipped', status='skipped',
                     note='needs a local app build + browser (E2E-11); not part of the golden slice'))
    hard = hard_checks(work) if not blocked else []
    gaps = gap_checks(work) if not blocked else []

    print('\nSTAGES')
    print(f'{"stage":<10} {"mode":<8} {"status":<8} {"wall s":>8} {"RSS MB":>8} {"out MB":>8}  note')
    for r in rows:
        m = r.get('metrics') or {}
        ob = m.get('output_bytes')
        print(f'{r["stage"]:<10} {r["mode"].upper():<8} {r["status"].upper():<8} {fmt(m.get("wall_s"), ".1f"):>8} '
              f'{fmt(m.get("max_rss_mb"), ".0f"):>8} {fmt(ob and ob / 1e6, ".2f"):>8}  {r.get("note", "")}')
    real = [r['stage'] for r in rows if r['mode'] == 'real']
    thin = [r['stage'] for r in rows if r['mode'] == 'thin']
    print(f'real stages: {", ".join(real) or "none"} | thin stand-ins: {", ".join(thin) or "none"}')
    executed = sum(1 for r in rows if r['status'] == 'ran')
    print(f'stages executed this run: {executed}; already done (no work): {sum(r["status"] == "done" for r in rows)}')

    print('\nCHECKS (must pass)')
    for name, ok, detail in hard:
        print(f'  {"PASS" if ok else "FAIL"}  {name}  [{detail}]')
    print('\nKNOWN GAPS (E2E-PROOF-1; expected to fail until the named card lands)')
    flipped = 0
    for card, name, ok, detail in gaps:
        tag = 'FLIPPED' if ok else ('UNKNOWN' if ok is None else 'XFAIL')
        flipped += bool(ok)
        print(f'  {tag:<8} {card:<12} {name}  [{detail}]')
    if flipped:
        print(f'  {flipped} gap(s) now pass: the card landed; move the check from KNOWN GAPS into CHECKS.')

    rate = {r['stage']: (r['metrics']['wall_s'] / slice_area_km2()) for r in rows if r.get('metrics')}
    if rate:
        print(f'\nRUNTIME RATES (slice {slice_area_km2()} km2; linear, a floor not a promise: real runs add overlap, '
              'memory growth and I/O)')
        for s, v in rate.items():
            line = f'  {s:<10} {v:8.2f} s/km2'
            if args.forecast_km2:
                line += f'  -> {v * args.forecast_km2 / 3600:8.2f} h for {args.forecast_km2:g} km2'
            print(line)
    ok_all = (all(r['status'] in ('ran', 'done', 'skipped') for r in rows) and hard
              and all(ok for _, ok, _ in hard))
    summary = dict(box=BOX, repo_head=subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'],
                                                      capture_output=True, text=True).stdout.strip(),
                   stages=rows, checks=[dict(name=n, passed=o, detail=d) for n, o, d in hard],
                   gaps=[dict(card=c, name=n, state='FLIPPED' if o else ('UNKNOWN' if o is None else 'XFAIL'),
                              detail=d) for c, n, o, d in gaps],
                   green=bool(ok_all), total_s=round(time.time() - t0, 1))
    (work / 'golden-summary.json').write_text(json.dumps(summary, indent=1, sort_keys=True, default=str))
    print(f'\nGOLDEN SLICE {"GREEN" if ok_all else "RED"} in {time.time() - t0:.0f} s (summary: {work}/golden-summary.json)')
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
