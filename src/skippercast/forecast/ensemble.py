"""NOAA GEFS 0.25° wind-ensemble members at the regions' forecast points.

    PYTHONPATH=src python -m skippercast.forecast.ensemble --output var/forecasts \
        [--previous var/forecasts-published] [--force]

GEFS publishes 31 members (control `gec00` and perturbations `gep01`-`gep30`)
every six hours on NOAA's Open Data Dissemination bucket on AWS. Each member
and forecast step is one GRIB2 file with a text `.idx`, so this reads only the
10 m wind components and the surface gust with HTTP range requests, the same
way the tile builder reads GFS (`fetch.py`). It samples the nearest sea cell
(GFS 0.25° land mask) to every regional forecast point instead of writing
tiles: the regional pipeline needs member series at a few dozen points, not a
map.

Output, next to the tiles on the `forecasts` branch:

    ncep_gefs025/manifest.json            cycle, meta and upstream receipt
    ncep_gefs025/regions/<region>.json    member series for that region's points

A failed build keeps the previous generation, exactly like a tile model.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

from . import fetch
from .models import GFS_AWS

GEFS_AWS = 'https://noaa-gefs-pds.s3.amazonaws.com'
MODEL_ID = 'ncep_gefs025'
NAME = 'NOAA GEFS 0.25° wind ensemble'
PROVIDER = 'NOAA NCEP'
DOCUMENTATION = 'https://registry.opendata.aws/noaa-gefs/'
PRODUCT_DOCUMENTATION = 'https://www.nco.ncep.noaa.gov/pmb/products/gens/'
MEMBERS = 31                       # gec00 + gep01..gep30
STEPS = tuple(range(0, 193, 3))    # native three-hour output through eight days
CYCLES = (0, 6, 12, 18)
CYCLE_DELAY_HOURS = 3.5            # pgrb2sp25 f192 usually lands 3.75-5 h after initialization
FIELDS = {'u10': ('UGRD', '10 m above ground'), 'v10': ('VGRD', '10 m above ground'), 'gust': ('GUST', 'surface')}
MASK = ('LAND', 'surface')         # from the same-cycle GFS 0.25° analysis (identical grid)
SEA_RADIUS_KM = 30
MAX_MISSING_FRACTION = 0.1         # more missing member-steps than this fails the build
SCHEMA = 1
ROOT = Path(__file__).resolve().parents[3]


def stamp(moment=None):
    moment = moment or datetime.now(timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def log_err(message):
    print(message, file=sys.stderr, flush=True)


# ---- locations -----------------------------------------------------------------

def member_name(member):
    if not 0 <= member < MEMBERS:
        raise ValueError('GEFS member out of range')
    return 'gec00' if member == 0 else f'gep{member:02d}'


def cycle_prefix(cycle):
    return f'{GEFS_AWS}/gefs.{cycle:%Y%m%d}/{cycle:%H}/atmos/pgrb2sp25/'


def gefs_url(cycle, member, step):
    return f'{cycle_prefix(cycle)}{member_name(member)}.t{cycle:%H}z.pgrb2s.0p25.f{step:03d}'


def mask_url(cycle):
    return f'{GFS_AWS}/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos/gfs.t{cycle:%H}z.pgrb2.0p25.f000'


def latest_cycle(now=None, lookback_hours=48, exists=None):
    """Newest cycle whose control and last perturbation both publish the final step."""
    exists = exists or fetch.exists
    now = now or datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    for back in range(0, lookback_hours + 1):
        cycle = start - timedelta(hours=back)
        if cycle.hour not in CYCLES or cycle > now - timedelta(hours=CYCLE_DELAY_HOURS - 1):
            continue
        if all(exists(gefs_url(cycle, member, STEPS[-1]) + '.idx') for member in (0, MEMBERS - 1)):
            return cycle
    return None


def region_points(root=ROOT):
    """{region_id: [(latitude, longitude), ...]} for regions whose ensemble is GEFS."""
    out = {}
    for path in sorted(Path(root, 'regions').glob('*/region.json')):
        region = json.loads(path.read_text())
        if (region.get('intelligence') or {}).get('wind_ensemble_model') != 'gfs025':
            continue
        out[region['id']] = [(float(p['latitude']), float(p['longitude'])) for p in region.get('forecast_points', [])]
    return out


# ---- sampling ------------------------------------------------------------------

def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def nearest_sea(lats, lons, sea, lat, lon, radius_km=SEA_RADIUS_KM):
    """(row, col, grid_lat, grid_lon, km) of the nearest sea cell within the radius, or None."""
    import numpy as np
    window = radius_km / 111.0 + 0.3
    rows = np.where(np.abs(lats - lat) <= window)[0]
    delta = (lons - lon + 180) % 360 - 180
    cols = np.where(np.abs(delta) <= window / max(math.cos(math.radians(lat)), 0.1))[0]
    best = None
    for r in rows:
        for c in cols:
            if not sea[r, c]:
                continue
            km = distance_km(lat, lon, float(lats[r]), float(lons[c]))
            if km <= radius_km and (best is None or km < best[4]):
                best = (int(r), int(c), round(float(lats[r]), 5), round(float(lons[c]), 5), round(km, 2))
    return best


def split_messages(blob):
    """Individual GRIB2 messages from concatenated bytes (edition 2 length is in section 0)."""
    out, start = [], 0
    while start < len(blob):
        if blob[start:start + 4] != b'GRIB' or len(blob) < start + 16 or blob[start + 7] != 2:
            raise ValueError('Expected GRIB2, not an error page')
        length = int.from_bytes(blob[start + 8:start + 16], 'big')
        if length < 16 or start + length > len(blob):
            raise ValueError('Truncated GRIB2 message')
        out.append(blob[start:start + length])
        start += length
    return out


def decode_one(blob):
    from .build import decode
    messages = split_messages(blob)
    if len(messages) != 1:
        raise ValueError('Expected exactly one GRIB2 message per range')
    return decode(messages[0])


def read_mask(cycle, http=None):
    """GFS 0.25° land fraction for the cycle -> (lats, lons, sea bool grid, url, sha256)."""
    http = http or fetch.http
    url = mask_url(cycle)
    text = http(url + '.idx')
    if text is None:
        raise FileNotFoundError(f'GFS land mask index missing for {cycle:%Y%m%d%H}')
    found = fetch.select_gfs(fetch.parse_gfs_idx(text.decode()), *MASK)
    if not found:
        raise ValueError('GFS land mask absent from the index')
    blob = http(url, found)
    if blob is None:
        raise FileNotFoundError(url)
    grid, lats, lons = decode_one(blob)
    return lats, lons, grid < 0.5, url, hashlib.sha256(blob).hexdigest()


def fetch_member_step(cycle, member, step, cells, shape, http=None):
    """{field: [value per cell or None]} plus receipts for one member and step.

    Returns (values, receipts, missing_fields). A missing file is reported, not raised."""
    import numpy as np
    http = http or fetch.http
    url = gefs_url(cycle, member, step)
    text = http(url + '.idx')
    if text is None:
        return {}, [], list(FIELDS)
    rows = fetch.parse_gfs_idx(text.decode())
    found = {name: fetch.select_gfs(rows, *selector) for name, selector in FIELDS.items()}
    missing = [name for name, rng in found.items() if not rng]
    # Adjacent messages (UGRD and VGRD sit next to each other) share one range request.
    groups = []
    for name, rng in sorted(((n, r) for n, r in found.items() if r), key=lambda item: item[1][0]):
        if groups and groups[-1][1][1] is not None and groups[-1][1][1] + 1 == rng[0]:
            groups[-1] = (groups[-1][0] + [name], (groups[-1][1][0], rng[1]))
        else:
            groups.append(([name], rng))
    blobs = {}
    for names, rng in groups:
        blob = http(url, rng)
        if blob is None:
            missing.extend(names)
            continue
        parts = split_messages(blob)
        if len(parts) != len(names):
            raise ValueError(f'{url}: expected {len(names)} GRIB messages in range {rng}, got {len(parts)}')
        blobs.update(zip(names, parts))
    values, receipts = {}, []
    for name in FIELDS:
        blob = blobs.get(name)
        if blob is None:
            continue
        grid, _, _ = decode_one(blob)
        if grid.shape != shape:
            raise ValueError(f'GEFS grid {grid.shape} differs from the land mask {shape}')
        receipts.append({'member': member, 'step': step, 'field': name, 'url': url, 'range': list(found[name]),
                         'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()})
        values[name] = [None if cell is None or not np.isfinite(grid[cell[0], cell[1]]) else float(grid[cell[0], cell[1]])
                        for cell in cells]
    return values, receipts, sorted(set(missing), key=list(FIELDS).index)


def speed(u, v):
    return None if u is None or v is None else math.hypot(u, v)


def collect(cycle, points, http=None, workers=32, log=log_err):
    """Member series at `points` -> (samples, upstream receipt summary).

    samples: [{latitude, longitude, grid, distance_km, wind_speed_10m, wind_gusts_10m}]
    where each series is [member][step] in m/s (None = unavailable)."""
    started = time.time()
    lats, lons, sea, murl, msha = read_mask(cycle, http)
    cells = [nearest_sea(lats, lons, sea, lat, lon) for lat, lon in points]
    shape = sea.shape
    jobs = [(member, step) for member in range(MEMBERS) for step in STEPS]

    def one(job):
        member, step = job
        return job, fetch_member_step(cycle, member, step, [c and c[:2] for c in cells], shape, http)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = dict(pool.map(one, jobs))
    missing = [{'member': m, 'step': s, 'fields': got[2]} for (m, s), got in sorted(results.items()) if got[2]]
    incomplete = sum(1 for (_, _), got in results.items() if got[2])
    if incomplete > MAX_MISSING_FRACTION * len(jobs):
        raise RuntimeError(f'{incomplete} of {len(jobs)} GEFS member-steps incomplete')
    receipts = sorted((r for got in results.values() for r in got[1]),
                      key=lambda r: (r['member'], r['step'], r['field']))
    digest = hashlib.sha256()
    for r in receipts:
        digest.update(f"{r['url']}|{r['range'][0]}|{r['sha256']}\n".encode())
    samples = []
    for index, ((lat, lon), cell) in enumerate(zip(points, cells)):
        wind = [[None] * len(STEPS) for _ in range(MEMBERS)]
        gust = [[None] * len(STEPS) for _ in range(MEMBERS)]
        for (member, step), (values, _, _) in results.items():
            t = STEPS.index(step)
            u, v = (values.get(k, [None] * len(points))[index] for k in ('u10', 'v10'))
            w = speed(u, v)
            wind[member][t] = None if w is None else round(w, 2)
            g = values.get('gust', [None] * len(points))[index]
            gust[member][t] = None if g is None else round(g, 2)
        samples.append({'latitude': lat, 'longitude': lon,
                        'grid': None if cell is None else [cell[2], cell[3]],
                        'distance_km': None if cell is None else cell[4],
                        'wind_speed_10m': wind, 'wind_gusts_10m': gust})
    upstream = {'provider': 'NOAA Open Data Dissemination (AWS)', 'bucket': GEFS_AWS, 'cycle_prefix': cycle_prefix(cycle),
                'product': 'pgrb2sp25', 'fields': {k: ':'.join(v) for k, v in FIELDS.items()},
                'land_mask': {'url': murl, 'field': ':'.join(MASK), 'sha256': msha},
                'messages': len(receipts), 'bytes': sum(r['bytes'] for r in receipts),
                'messages_sha256': digest.hexdigest(), 'missing': missing}
    log(f'{MODEL_ID}: {len(receipts)} GRIB messages for {len(points)} points in {time.time() - started:.0f}s')
    return samples, upstream


# ---- output --------------------------------------------------------------------

def manifest_for(cycle, times, upstream, regions, built_at, seconds):
    return {
        'schema_version': SCHEMA, 'model': MODEL_ID, 'name': NAME, 'provider': PROVIDER, 'kind': 'wind-ensemble',
        'cycle': int(cycle.timestamp()), 'cycle_iso': stamp(cycle), 'built_at': stamp(built_at), 'build_seconds': round(seconds),
        'members': MEMBERS, 'steps': list(STEPS), 'times': times, 'units': {'wind_speed_10m': 'm/s', 'wind_gusts_10m': 'm/s'},
        'regions': sorted(regions), 'resolution_km': 25, 'sea_radius_km': SEA_RADIUS_KM,
        'documentation': DOCUMENTATION, 'product_documentation': PRODUCT_DOCUMENTATION, 'upstream': upstream,
        'notes': 'Native three-hour GEFS members at the nearest GFS-0.25° sea cell to each regional forecast point; no interpolation in this file.',
        'meta': {'last_run_initialisation_time': int(cycle.timestamp()),
                 'last_run_modification_time': int(built_at.timestamp()),
                 'last_run_availability_time': int(built_at.timestamp()),
                 'data_end_time': times[-1], 'temporal_resolution_seconds': 3 * 3600,
                 'update_interval_seconds': 86400 // len(CYCLES)},
    }


def write(target, cycle, by_region, samples_by_point, upstream, started):
    """Stage then rename, like the tile builder."""
    times = [int(cycle.timestamp()) + 3600 * s for s in STEPS]
    staging = target.parent / f'.{target.name}.staging'
    shutil.rmtree(staging, ignore_errors=True)
    (staging / 'regions').mkdir(parents=True)
    for region_id, points in by_region.items():
        document = {'schema_version': SCHEMA, 'model': MODEL_ID, 'region_id': region_id, 'cycle': int(cycle.timestamp()),
                    'cycle_iso': stamp(cycle), 'steps': list(STEPS), 'times': times, 'members': MEMBERS,
                    'units': {'wind_speed_10m': 'm/s', 'wind_gusts_10m': 'm/s'},
                    'points': [samples_by_point[p] for p in points]}
        (staging / 'regions' / f'{region_id}.json').write_text(json.dumps(document, separators=(',', ':')))
    manifest = manifest_for(cycle, times, upstream, by_region, datetime.now(timezone.utc), time.time() - started)
    (staging / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return manifest


def build(output, previous=None, force=False, now=None, regions=None, http=None, exists=None, log=log_err):
    """Build or reuse the ensemble. Returns a status dict; keeps the previous build on failure."""
    output.mkdir(parents=True, exist_ok=True)
    target = output / MODEL_ID
    prior_dir = previous / MODEL_ID if previous else None
    prior_manifest = prior_dir / 'manifest.json' if prior_dir else None
    by_region = regions if regions is not None else region_points()
    try:
        cycle = latest_cycle(now, exists=exists)
        if cycle is None:
            raise RuntimeError('no complete GEFS cycle published in the last 48 hours')
        prior = json.loads(prior_manifest.read_text()) if prior_manifest and prior_manifest.is_file() else None
        if (prior and prior.get('cycle') == int(cycle.timestamp()) and sorted(prior.get('regions', [])) == sorted(by_region)
                and not force):
            if target.resolve() != prior_dir.resolve():
                shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(prior_dir, target)
            log(f'{MODEL_ID}: {stamp(cycle)} already built; reusing')
            return {'status': 'ok', 'state': 'current', 'cycle': prior['cycle_iso'], 'built_at': prior['built_at']}
        started = time.time()
        points = sorted({p for pts in by_region.values() for p in pts})
        samples, upstream = collect(cycle, points, http=http, log=log)
        manifest = write(target, cycle, by_region, dict(zip(points, samples)), upstream, started)
        return {'status': 'ok', 'state': 'built', 'cycle': manifest['cycle_iso'], 'built_at': manifest['built_at'],
                'points': len(points), 'messages': upstream['messages'], 'missing_member_steps': len(upstream['missing'])}
    except Exception as error:
        log(f'{MODEL_ID}: FAILED: {error}')
        kept = False
        if prior_manifest and prior_manifest.is_file():
            if target.resolve() != prior_dir.resolve():
                shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(prior_dir, target)
            kept = True
        return {'status': 'failed', 'issue': str(error)[:300], 'kept_previous': kept}


# ---- reading (numpy-free; used by the regional intelligence pipeline) -----------

def local_root():
    root = os.environ.get('SKIPPERCAST_FORECAST_ROOT')
    return Path(root) if root and Path(root, MODEL_ID, 'manifest.json').is_file() else None


def feed_url(relative):
    from .local import FEED
    return f'{FEED}/{MODEL_ID}/{relative}'


def read(relative, client):
    """A published ensemble file: the live job's local build if present, else the feed.

    Either way a receipt (url, bytes, sha256) is added to the client's requests."""
    root = local_root()
    path = root / MODEL_ID / relative if root else None
    if path is not None and path.is_file():
        body = path.read_bytes()
        client.requests.append({'url': feed_url(relative), 'attempt': 1, 'retrieved_at': stamp(),
                                'transport': 'local build of the forecasts branch (SKIPPERCAST_FORECAST_ROOT)',
                                'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
        return json.loads(body)
    return client.get(feed_url(relative), True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--force', action='store_true', help='rebuild even if the cycle is already published')
    args = parser.parse_args()
    status = build(args.output, args.previous, args.force)
    print(json.dumps({MODEL_ID: status}, indent=1))
    if status['status'] != 'ok' and not status.get('kept_previous'):
        sys.exit(1)


if __name__ == '__main__':
    main()
