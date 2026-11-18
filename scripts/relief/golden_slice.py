#!/usr/bin/env python3
"""SC-MAP-GOLDEN-1: offline relief pipeline check; defaults to six small synthetic rasters."""
import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TypedDict

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
class Family(TypedDict):
    rank: int
    catalog: str
    datum: str
    survey: str


FAMILY: dict[str, Family] = {
    'noaa_morrobay_topobathy_2022': Family(rank=1, catalog='noaa-morro-bay-topobathy-2022-9630', datum='NAVD88',
                                         survey='NOAA OCM Morro Bay 2022 topobathy lidar DEM (MRR22)'),
    'ncmp_topobathy_2015': Family(rank=2, catalog='usace-ncmp-ca-8482', datum='NAVD88',
                                survey='USACE NCMP 2015 topobathy lidar 1 m bare-earth DEM'),
    'nbs_bluetopo': Family(rank=9, catalog='noaa-bluetopo', datum='NAVD88',
                         survey='NOAA BlueTopo compiled bathymetry (estimated)'),
}

STAGES = ['inventory', 'normalize', 'select', 'mosaic', 'tiles', 'contours', 'release', 'qa', 'preview']
UPSTREAM = {'inventory': [], 'normalize': ['inventory'], 'select': ['normalize'], 'mosaic': ['select'],
            'tiles': ['select', 'mosaic'], 'contours': ['select', 'normalize', 'mosaic'],
            'release': ['select', 'mosaic', 'tiles', 'contours'], 'qa': ['select', 'mosaic', 'tiles', 'release'],
            'preview': ['release', 'qa']}
# Stage -> what runs. 'real' = repo code, 'thin' = stand-in in this file.
MODE = {'inventory': 'thin', 'normalize': 'thin', 'select': 'thin', 'mosaic': 'real', 'tiles': 'real',
        'contours': 'real', 'release': 'thin', 'qa': 'thin', 'preview': 'skipped'}
REAL_ADAPTERS = {}      # stage -> callable(work, out, final, slice_name) for a merged relief module
REPO_CODE = {           # repo files whose bytes change a stage's generation
    'select': ['catalog/sources.json'],
    'mosaic': ['research/scripts/coast_mvp/coast_mosaic.py'],
    'tiles': ['scripts/build_bathy_tiles.py'],
    'contours': ['scripts/build_depth_contours.py', 'research/scripts/coast_mvp/coast_contours.py',
                 'catalog/sources.json', 'regions/morro-bay/region.json'],
}
LOAD_MAX = 24.0
FLOORS = {'/': 250, '/mnt/agentorange-backup': 400}
FIXTURE_RESERVE_GIB = 1
CGROUP = Path('/proc/self/cgroup')
COMPETING_MAP = r'(^|[[:space:]/])(coast_mosaic|build_bathy_tiles|run_bounded)[.]py([[:space:]]|$)'
THREAD_VARS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'GDAL_NUM_THREADS',
               'NUMEXPR_NUM_THREADS', 'BLIS_NUM_THREADS')
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
    if real_module(stage).is_file():
        return 'real' if stage in REAL_ADAPTERS else 'unwired'
    return MODE[stage]


def receipt_path(work, stage):
    return work / 'stages' / f'{stage}.json'


def read_receipt(work, stage):
    p = receipt_path(work, stage)
    return json.loads(p.read_text()) if p.exists() else None


def outputs_of(final):
    return [dict(path=str(p.relative_to(final.parent)), sha256=sha256(p), bytes=p.stat().st_size)
            for p in sorted(final.rglob('*')) if p.is_file()]


def host(work, slice_name):
    mounts = FLOORS if slice_name == 'morro-bay' else (work,)
    return {'load5': os.getloadavg()[1], **{f'free_gb[{k}]': shutil.disk_usage(k).free / 1e9 for k in mounts}}


def heavy_refusal():
    """Fail closed before any work; this snapshot is not a host-wide lock."""
    try:
        paths = [line.split(':', 2)[2] for line in CGROUP.read_text().splitlines()]
        if not any(re.fullmatch(r'mapjob-.+\.service', part) for path in paths for part in path.split('/')):
            return 'requires a localmapq mapjob- systemd service; no golden-slice dispatch is installed'
        probe = subprocess.run(['pgrep', '-f', '--', COMPETING_MAP], capture_output=True, text=True, timeout=3)
    except (OSError, IndexError, UnicodeError, subprocess.TimeoutExpired) as exc:
        return f'cannot establish heavy-job admission ({type(exc).__name__})'
    if probe.returncode == 0:
        return 'competing mosaic, tiler or run_bounded.py process detected'
    if probe.returncode != 1 or probe.stdout.strip() or probe.stderr.strip():
        return 'cannot verify absence of competing map jobs (pgrep failed)'
    return None


def gate(snapshot, slice_name, work):
    if slice_name == 'synthetic':
        if shutil.disk_usage(work).free < FIXTURE_RESERVE_GIB * 1024**3:
            return f'synthetic work volume needs {FIXTURE_RESERVE_GIB} GiB free'
        return None
    if snapshot['load5'] >= LOAD_MAX:
        return f'load5 {snapshot["load5"]} >= {LOAD_MAX}; not waiting'
    for mount, floor in FLOORS.items():
        if snapshot[f'free_gb[{mount}]'] < floor:
            return f'{mount} below {floor} GB floor; not waiting'
    return None


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
    if stage in REAL_ADAPTERS and real_module(stage).is_file():
        files.append((str(real_module(stage).relative_to(REPO)), sha256(real_module(stage))))
    return canon(files)


def input_fingerprint(work, stage, slice_name):
    if stage != 'inventory':
        return []
    rows = []
    for s in slice_sources(work, slice_name):
        try:
            st = os.stat(s['path'])
            rows.append([s['path'], st.st_size, sha256(s['path']) if slice_name == 'synthetic' else st.st_mtime_ns])
        except OSError:
            rows.append([s['path'], None, None])
    return rows


# ---------------------------------------------------------------- stage runner (receipts, idempotence)
def run_stage(work, stage, slice_name):
    """Return a dict row: stage, mode, status (ran|done|failed|held|blocked), metrics."""
    mode = mode_of(stage)
    row = dict(stage=stage, mode=mode)
    if mode == 'skipped':
        row.update(status='skipped', note='E2E-11 preview module not on this checkout')
        return row
    if mode == 'unwired':
        row.update(status='unwired', note=f'real stage merged (src/skippercast/relief/{stage}.py) but not '
                                          'wired in golden_slice.py REAL_ADAPTERS')
        return row
    ups = []
    for u in UPSTREAM[stage]:
        r = read_receipt(work, u)
        if not r or r.get('status') != 'ok':
            row.update(status='blocked', note=f'upstream {u} not ok')
            return row
        ups.append({'stage': u, 'generation': r['generation']})
    gen = canon({'upstream': ups, 'code': code_digest(stage), 'inputs': input_fingerprint(work, stage, slice_name),
                 'box': BOX, 'mode': mode, 'slice': slice_name})
    prev = read_receipt(work, stage)
    if prev and prev.get('status') == 'ok' and prev.get('generation') == gen and all(
            (work / o['path']).is_file() and (work / o['path']).stat().st_size == o['bytes']
            and sha256(work / o['path']) == o['sha256'] for o in prev['outputs']):
        row.update(status='done', metrics=prev['metrics'], note='no work (receipt current)')
        print(f'[{stage}] DONE (no work) {mode.upper()} generation {gen[:12]}')
        return row
    attempt = prev['attempt'] + 1 if prev and prev.get('generation') == gen and prev.get('status') != 'ok' else 1
    limit = 1 if slice_name == 'morro-bay' else MAX_ATTEMPTS
    if attempt > limit:
        row.update(status='held', note=f'{limit} attempt(s) used for this generation; fix the cause and '
                                       f'delete {receipt_path(work, stage)} to retry')
        return row
    base = dict(schema='sc-golden-receipt/1', stage=stage, mode=mode, generation=gen, upstream=ups, box=BOX,
                attempt=attempt, host=host(work, slice_name))
    held = gate(base['host'], slice_name, work)
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
                    '--slice', slice_name, '--run-stage', stage, '--work', str(work), '--out', str(tmp),
                    '--final', str(final)]
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
def slice_sources(work, slice_name):
    if slice_name == 'morro-bay':
        return SOURCES
    return [dict(key=s['key'], family=s['family'], path=str(work / 'fixture' / f'{s["key"]}.tif')) for s in SOURCES]


def prepare_fixture(work):
    """Tiny, deterministic depth grids, with an explicit synthetic support band on two NOAA-like grids."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import transform

    fixture = work / 'fixture'
    version = sha256(__file__)
    sources = slice_sources(work, 'synthetic')
    if (fixture / 'version').is_file() and (fixture / 'version').read_text() == version and all(
            Path(s['path']).is_file() for s in sources):
        return
    lon, lat = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2
    xs, ys = transform('EPSG:4326', DST_CRS, [lon], [lat])
    rng = np.random.default_rng(2554)
    size = 128
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        fixture.mkdir(exist_ok=True)
        for i, source in enumerate(sources):
            # The first pair overlaps at the box center with distinct depths for the real tie-break probe.
            res = 4 if i == 5 else 1
            x, y = int(xs[0]) // res * res + (0, 0, 72, -72, 0, 0)[i], int(ys[0]) // res * res
            crs, tr = DST_CRS, from_origin(x - size // 2 * res, y + size // 2 * res, res, res)
            if i == 4:
                dx, dy = 1 / (111320 * math.cos(math.radians(lat))), 1 / 111320
                crs, tr = 'EPSG:4326', from_origin(lon - 64 * dx, lat + 150 * dy, dx, dy)
            depth = (np.float32((-6, -14, -9, -10, -11, -18)[i]) +
                     rng.uniform(-0.2, 0.2, (size, size)).astype('float32'))
            depth[58:70, 58:70] = (-6, -14, -9, -10, -11, -18)[i]
            depth[:8, :8] = NODATA
            support = np.ones((size, size), dtype='float32')
            support[:, :14] = 0  # Valid shallow depths which are intentionally not measured.
            count = 2 if i < 2 else 3 if i == 5 else 1
            path = Path(tmp) / Path(source['path']).name
            with rasterio.open(path, 'w', driver='GTiff', width=size, height=size, count=count,
                               dtype='float32', crs=crs, transform=tr, nodata=NODATA, compress='deflate') as ds:
                ds.write(depth, 1)
                if i < 2:
                    ds.write(support, 2)
                    ds.set_band_description(2, 'synthetic measured-cell support')
                elif i == 5:
                    ds.write(support * 100, 2)  # Non-elevation BlueTopo-like bands must be ignored.
                    ds.write(support * 20, 3)
            path.replace(source['path'])
        (Path(tmp) / 'version').write_text(version)
        (Path(tmp) / 'version').replace(fixture / 'version')


def st_inventory(work, out, final, slice_name):
    import rasterio
    from rasterio.warp import transform_bounds
    rows, missing = [], []
    for s in slice_sources(work, slice_name):
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
            for n in CSMP_WANTED} if slice_name == 'morro-bay' else {}
    doc = dict(box=BOX, slice_km2=slice_area_km2(), sources=rows, missing=missing, csmp_zips_held=csmp)
    (out / 'inventory.json').write_text(json.dumps(doc, indent=1, sort_keys=True))
    print(json.dumps(dict(sources=len(rows), missing=len(missing), touching=sum(r['touches_slice'] for r in rows))))
    if missing or not all(r['touches_slice'] for r in rows):
        sys.exit('inventory: a fixed slice source is missing or does not touch the slice')


def st_normalize(work, out, final, slice_name):
    """Thin normaliser: each source -> one EPSG:26910 metre Float32 band-1 grid clipped to the slice box."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import Resampling, transform_bounds
    inv = json.loads((work / 'inventory' / 'inventory.json').read_text())
    (out / 'grids').mkdir()
    box_w, box_s, box_e, box_n = transform_bounds('EPSG:4326', DST_CRS, *BOX, densify_pts=21)
    index = []
    for r in inv['sources']:
        res = 1.0 if r['res'][0] < 3 or r['geographic'] else 4.0
        w, s, e, n = box_w, box_s, box_e, box_n
        if slice_name == 'synthetic':
            # No full-box grid for a 128x128 input; retain actual spacing and footprint.
            with rasterio.open(r['path']) as ds:
                sw, ss, se, sn = transform_bounds(ds.crs, DST_CRS, *ds.bounds, densify_pts=21)
            w, s, e, n = max(w, sw), max(s, ss), min(e, se), min(n, sn)
        west, north = math.floor(w / res) * res, math.ceil(n / res) * res
        width, height = math.ceil((e - west) / res), math.ceil((north - s) / res)
        tr = from_origin(west, north, res, res)
        support = None
        with rasterio.open(r['path']) as ds, WarpedVRT(
                ds, crs=DST_CRS, transform=tr, width=width, height=height, src_nodata=ds.nodata, nodata=NODATA,
                dtype='float32', resampling=Resampling.bilinear if ds.crs.is_geographic else Resampling.nearest) as v:
            arr = v.read(1, masked=True).filled(NODATA)
            # Only the generated test fixture has measured-cell evidence. A validity mask, nominal
            # spacing, or a bilinearly interpolated NCMP depth is not evidence of measurement.
            if (slice_name == 'synthetic' and ds.descriptions[1:2] == ('synthetic measured-cell support',)
                    and ds.crs == DST_CRS and ds.transform == tr and ds.shape == (height, width) and res <= 1):
                support = v.read(2, masked=True).filled(0) == 1
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
        if support is not None and (support & valid & (arr <= 0) & (arr >= -20)).any():
            measured = grid.with_name(f'{r["key"]}.measured.tif')
            with rasterio.open(grid) as ds, rasterio.open(measured, 'w', **ds.profile) as dst:
                dst.write(np.where(support & valid, arr, NODATA), 1)
            row.update(measured_path=str(final / 'grids' / measured.name), measured_sha256=sha256(measured))
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
    rights = row.get('rights') or {}
    for field in ('commercial_use', 'public_display'):
        if rights.get(field) != 'allowed':
            return 'private', f'catalog row {row["id"]} {field}={rights.get(field)}'
    if row.get('publication_allowed') is not True:
        return 'private', f'catalog row {row["id"]} publication_allowed={row.get("publication_allowed")}'
    return 'public', f'catalog row {row["id"]} permits public display and publication'


def st_select(work, out, final, slice_name):
    """Thin selector: rights class (public/private), label, max_zoom, mosaic sources + tiler native manifest."""
    catalog = {r['id']: r for r in json.loads((REPO / 'catalog/sources.json').read_text())['sources']}
    grids = [g for g in json.loads((work / 'normalize' / 'index.json').read_text())['grids'] if 'grid_path' in g]
    srcs, native, sel = {'public': [], 'private': []}, {'public': [], 'private': []}, []
    for g in sorted(grids, key=lambda g: g['key']):
        fam = FAMILY[g['family']]
        rc, why = rights_class(catalog.get(fam['catalog']))
        measured = slice_name == 'synthetic' and g['res_m'] <= 1.0 and 'measured_path' in g
        mz = 17 if measured else None
        label = 'measured' if measured else 'estimated'
        citation = ('Synthetic fixture resembling ' if slice_name == 'synthetic' else '') + fam['survey']
        sid = f'r{fam["rank"]:02d}-{g["key"]}'
        sel.append(dict(id=sid, family=g['family'], resolution_m=g['res_m'], label=label, rights_class=rc,
                        rights_reason=why, max_zoom=mz, grid_sha256=g['grid_sha256'],
                        measured_scope='masked native grid only' if measured else None))
        if rc == 'excluded':
            continue
        m = dict(id=sid, path=g['grid_path'], sha256=g['grid_sha256'], resolution_m=g['res_m'], units='m',
                 value_convention='elevation_positive_up', vertical_datum=fam['datum'], vertical_offset_m=0,
                 citation=citation, rights=f'{rc}: {why}', attribution=citation,
                 offset_note='as supplied by the producer; no datum reconciliation (golden slice)')
        # Keep the legacy family-rank workaround for detail builds. The tie probe
        # uses the original mosaic IDs to measure the underlying tie rules.
        nat = dict(id=f'n{99 - fam["rank"]:02d}-{g["key"]}', path=g['measured_path'], resolution_m=g['res_m'],
                   mosaic_id=sid,
                   source_file=Path(g['source_path']).name, archive_sha256=g['measured_sha256'], survey_id=citation,
                   vertical_datum=fam['datum'], depth_semantics='elevation_positive_up', max_zoom=mz,
                   label=label, rights_class=rc) if mz else None
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
    json.dump(dict(schema='sc-golden-selection/1', slice=slice_name, box=BOX, summary=summary, sources=sel),
              open(out / 'selection.json', 'w'), indent=1, sort_keys=True)
    print(json.dumps(summary))
    if not srcs['private']:
        sys.exit('select: no private sources')


def _sub(cmd, log_name, out):
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    (out / log_name).write_text(f'$ {" ".join(cmd).replace(str(REPO), "<repo>")}\nrc={p.returncode}\n'
                                f'--- stdout\n{p.stdout[-3000:]}\n--- stderr\n{p.stderr[-4000:]}\n')
    return p


def st_mosaic(work, out, final, slice_name):
    """REAL: research/scripts/coast_mvp/coast_mosaic.py once per non-empty scope."""
    sel = work / 'select'
    result = {}
    for scope in ('public', 'private'):
        if not json.loads((sel / f'sources.{scope}.json').read_text())['sources']:
            (out / scope).mkdir()
            result[scope] = dict(status='held', reason=f'no {scope} sources admitted by catalogue rights')
            json.dump(result[scope], open(out / scope / 'HELD.json', 'w'))
            continue
        p = _sub([sys.executable, 'research/scripts/coast_mvp/coast_mosaic.py', '--region', str(sel / 'region.json'),
                  '--sources', str(sel / f'sources.{scope}.json'), '--output', str(out / scope),
                  *(['--reserve-gib', str(FIXTURE_RESERVE_GIB)] if slice_name == 'synthetic' else [])],
                 f'mosaic-{scope}.log', out)
        if p.returncode:
            sys.stderr.write(p.stderr[-3000:])
            sys.exit(p.returncode)
        result[scope] = dict(status='ok')
    json.dump(result, open(out / 'scopes.json', 'w'), indent=1, sort_keys=True)
    print(json.dumps(result))
    if result['private']['status'] != 'ok':
        sys.exit('mosaic: private scope not built')


def st_tiles(work, out, final, slice_name):
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
               '--label', f'{slice_name} golden slice (PRIVATE)', '--output', str(out / scope / 'relief.pmtiles'),
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


def st_contours(work, out, final, slice_name):
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


def st_release(work, out, final, slice_name):
    """Thin release: exact sha256 + bytes of private diagnostic layers; never uploadable."""
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
    rel_doc = dict(schema='sc-golden-release/1', slice=slice_name, box=BOX, files=files, private=True,
                   public_scope_held=(work / 'mosaic' / 'public' / 'HELD.json').exists(),
                   labels={k: sum(1 for s in sel['sources'] if s['label'] == k) for k in ('measured', 'estimated')},
                   notice='NOT FOR NAVIGATION. Private golden-slice build; never uploaded or published.')
    text = json.dumps(rel_doc, indent=1, sort_keys=True) + '\n'
    (out / 'release.json').write_text(text)
    print('release.json sha256', hashlib.sha256(text.encode()).hexdigest(), 'private True', 'files', len(files))


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


def tiebreak_probe(work, inputs):
    """Observe a co-located, equal-spacing pair using the same IDs in both real stages."""
    import numpy as np
    import rasterio
    from rasterio.transform import rowcol
    from rasterio.warp import transform
    sys.path.insert(0, str(REPO))
    from scripts import build_bathy_tiles as tiler

    unknown = dict(agrees=None, detail='no decisive two-source overlap at the synthetic probe point')
    native = jload(work / 'select/native.private.json') or []
    mos = work / 'mosaic/private'
    manifest = jload(mos / 'manifest.json')
    if len(native) != 2 or not manifest or not all('mosaic_id' in s for s in native):
        return unknown
    pair = [dict(s, id=s['mosaic_id']) for s in native]
    if pair[0]['resolution_m'] != pair[1]['resolution_m']:
        return unknown
    inputs.write_text(json.dumps(pair))
    sources = tiler.load_native_manifest(inputs)
    lon, lat = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2
    with rasterio.open(mos / 'contributor.tif') as codes:
        sx, sy = transform('EPSG:4326', codes.crs, [lon], [lat])
        code = next(codes.sample([(sx[0], sy[0])]))[0]
        mosaic_id = next((s['id'] for s in manifest['sources'] if s['code'] == code), None)
        base = np.full(codes.shape, tiler.NODATA, dtype='float32')
        tr, crs = codes.transform, codes.crs
    # Remove background from the native-only comparison so the display feather is not a third candidate.
    z = 17
    xs, ys = tiler.tile_range((lon, lat, lon + 1e-8, lat + 1e-8), z)
    x, y = xs.start, ys.start
    sx, sy = transform('EPSG:4326', 'EPSG:3857', [lon], [lat])

    def sample(window):
        pad = (window.shape[0] - tiler.TILE) // 2
        grid, _ = tiler.tile_grid(z, x, y, pad)
        return float(window[rowcol(grid, sx[0], sy[0])])

    a = {s['id']: sample(tiler.warp_native(s, z, x, y, tiler.PAD, tiler.DETAIL_M)[0]) for s in sources}
    if mosaic_id not in a or any(v == tiler.NODATA or not math.isfinite(v) for v in a.values()):
        return unknown
    windows = tiler.tiered_windows(base, tr, crs, BOX, z, sources, tiler.PAD)
    if (x, y) not in windows:
        return unknown
    depth = sample(windows[x, y][0])
    matches = [sid for sid, value in a.items() if math.isclose(value, depth, abs_tol=0.01)]
    if len(matches) != 1:
        return unknown
    tiler_id = matches[0]
    return dict(agrees=tiler_id == mosaic_id, mosaic_id=mosaic_id, tiler_id=tiler_id,
                detail=f'mosaic {mosaic_id}; tiler {tiler_id} (same input IDs)')


def st_qa(work, out, final, slice_name):
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
    if slice_name == 'synthetic':
        (out / 'tiebreak.json').write_text(json.dumps(tiebreak_probe(work, out / 'tie-inputs.json')))
    print(json.dumps({k: qa[k] for k in ('header', 'bounds', 'z16plus')}))


STAGE_FN = {'inventory': st_inventory, 'normalize': st_normalize, 'select': st_select, 'mosaic': st_mosaic,
            'tiles': st_tiles, 'contours': st_contours, 'release': st_release, 'qa': st_qa}


def execute_stage(stage, work, out, final, slice_name):
    mode = mode_of(stage)
    if mode in ('skipped', 'unwired'):
        sys.exit(f'{stage}: {mode}; no runnable adapter')
    adapter = REAL_ADAPTERS[stage] if real_module(stage).is_file() else STAGE_FN[stage]
    adapter(work, out, final, slice_name)


# ---------------------------------------------------------------- checks
def jload(p):
    return json.loads(Path(p).read_text()) if Path(p).exists() else None


def hard_checks(work):
    """(name, passed, detail): must all pass for a green run."""
    inv, sel = jload(work / 'inventory/inventory.json'), jload(work / 'select/selection.json')
    qa, rel = jload(work / 'qa/qa.json'), jload(work / 'release/release.json')
    cov = jload(work / 'tiles/private/coverage.json')
    out = []
    out.append(('six slice sources available and touch the slice', bool(inv) and not inv['missing']
                and len(inv['sources']) == 6 and all(s['touches_slice'] for s in inv['sources']),
                f'{len(inv["sources"]) if inv else 0}/6 available'))
    out.append(('private scope has at least three sources', bool(sel) and sel['summary']['private']['sources'] >= 3,
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
    tie = jload(work / 'qa/tiebreak.json')
    res.append(('E2E-04/06', 'tiebreak-agree (mosaic and tiler pick the same equal-resolution winner)',
                tie['agrees'] if tie else None, tie['detail'] if tie else 'synthetic probe not run'))
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
    preview = read_receipt(work, 'preview') if mode_of('preview') == 'real' else None
    res.append(('E2E-11', 'preview-stage-executed (src/skippercast/relief/preview.py)',
                bool(preview and preview['status'] == 'ok'), 'receipt present' if preview else 'module absent'))
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
    ap.add_argument('--slice', choices=('synthetic', 'morro-bay'), default='synthetic',
                    help='synthetic (default); morro-bay requires localmapq admission (not installed)')
    ap.add_argument('--work', type=Path, help=f'work directory (default {DEFAULT_WORK}/<slice>)')
    ap.add_argument('--forecast-km2', type=float, help='also print a linear compute forecast for this area')
    ap.add_argument('--run-stage', choices=STAGES, help=argparse.SUPPRESS)
    ap.add_argument('--out', type=Path, help=argparse.SUPPRESS)
    ap.add_argument('--final', type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.slice == 'morro-bay':
        refusal = heavy_refusal()
        if refusal:
            sys.exit(f'heavy Morro Bay slice refused: {refusal}')
    for var in THREAD_VARS:
        os.environ[var] = '1'
    work = (args.work or DEFAULT_WORK / args.slice).expanduser().resolve()
    if str(work).startswith('/mnt/privatevault'):
        sys.exit('refused: never touch /mnt/privatevault')
    if args.slice == 'synthetic' and work.is_relative_to(Path('/mnt/agentorange-backup')):
        sys.exit('refused: synthetic slice cannot use the held-data mount')
    ensure_python()
    if args.run_stage:
        execute_stage(args.run_stage, work, args.out, args.final, args.slice)
        return 0
    (work / 'stages').mkdir(parents=True, exist_ok=True)
    if args.slice == 'synthetic':
        if held := gate({}, args.slice, work):
            sys.exit(held)
        prepare_fixture(work)
    t0 = time.time()
    rows, blocked = [], False
    print(f'golden slice {args.slice} {BOX} ({slice_area_km2()} km2), work {work}, repo {REPO}')
    for stage in STAGES:
        if blocked:
            rows.append(dict(stage=stage, mode=mode_of(stage), status='blocked', note='earlier stage not ok'))
            continue
        row = run_stage(work, stage, args.slice)
        rows.append(row)
        if row['status'] not in ('ran', 'done', 'skipped'):
            blocked = True
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
        print(f'  {flipped} gap(s) passed on this slice; review the evidence before promoting a check.')

    rate = {r['stage']: (r['metrics']['wall_s'] / slice_area_km2()) for r in rows if r.get('metrics')}
    if rate:
        print(f'\nRUNTIME RATES (box {slice_area_km2()} km2; synthetic fixtures do not predict real-data runtime)')
        for s, v in rate.items():
            line = f'  {s:<10} {v:8.2f} s/km2'
            if args.forecast_km2 and args.slice == 'morro-bay':
                line += f'  -> {v * args.forecast_km2 / 3600:8.2f} h for {args.forecast_km2:g} km2'
            print(line)
    ok_all = (all(r['status'] in ('ran', 'done', 'skipped') for r in rows) and hard
              and all(ok for _, ok, _ in hard))
    summary = dict(slice=args.slice, box=BOX, repo_head=subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'],
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
