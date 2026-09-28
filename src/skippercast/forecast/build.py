"""Build SkipperCast forecast tiles from NOAA and ECMWF GRIB data.

    PYTHONPATH=src python -m skippercast.forecast.build --output var/forecasts \
        [--previous var/forecasts-published] [--models gfs_global,ecmwf_wam] [--force]

For each model: find the newest complete cycle; if it is already published,
reuse the previous tiles; otherwise download the needed fields for every
forecast hour, cut the California box, and write 1-degree tiles plus a
manifest. A model that fails keeps its previous tiles and reports the issue.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys
import time

import numpy as np

from .fetch import download_all, latest_cycle, plan_step
from .models import BOX, MODELS

SCHEMA = 1
MISSING = -32768


def stamp(moment=None):
    moment = moment or datetime.now(timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


# ---- decoding ------------------------------------------------------------------

def decode(message):
    """GRIB2 message bytes -> (values[lat_ascending, lon_ascending], lats, lons)."""
    import eccodes
    handle = eccodes.codes_new_from_message(message)
    try:
        grid_type = eccodes.codes_get(handle, 'gridType')
        if grid_type not in ('regular_ll', 'regular_gg'):
            raise ValueError(f'Unsupported grid type {grid_type}')
        ni, nj = eccodes.codes_get(handle, 'Ni'), eccodes.codes_get(handle, 'Nj')
        lat1 = eccodes.codes_get(handle, 'latitudeOfFirstGridPointInDegrees')
        lat2 = eccodes.codes_get(handle, 'latitudeOfLastGridPointInDegrees')
        lon1 = eccodes.codes_get(handle, 'longitudeOfFirstGridPointInDegrees')
        lon2 = eccodes.codes_get(handle, 'longitudeOfLastGridPointInDegrees')
        missing = eccodes.codes_get(handle, 'missingValue')
        values = eccodes.codes_get_values(handle).astype(np.float64)
        if eccodes.codes_get(handle, 'bitmapPresent'):
            values[values == missing] = np.nan
    finally:
        eccodes.codes_release(handle)
    grid = values.reshape(nj, ni)
    if grid_type == 'regular_gg':  # Gaussian latitudes are nearly, not exactly, uniform
        handle = eccodes.codes_new_from_message(message)
        try:
            lats = np.array(eccodes.codes_get_array(handle, 'distinctLatitudes'), dtype=float)
        finally:
            eccodes.codes_release(handle)
        if (lats[0] > lats[-1]) != (lat1 > lat2):
            lats = lats[::-1]
    else:
        lats = np.linspace(lat1, lat2, nj)
    if lats[0] > lats[-1]:
        grid, lats = grid[::-1], lats[::-1]
    span = (lon2 - lon1) % 360 or 360
    step = span / (ni - 1) if span != 360 else 360 / ni
    lons = (lon1 + step * np.arange(ni) + 180) % 360 - 180
    return grid, lats, lons


def subset(grid, lats, lons, box=BOX):
    """Cut the box plus one cell of margin; longitudes must be contiguous there."""
    dlat, dlon = abs(lats[1] - lats[0]), abs(float(np.diff(lons[:2])[0]) % 360)
    rows = np.where((lats >= box['south'] - 1.01 * dlat) & (lats <= box['north'] + 1.01 * dlat))[0]
    cols = np.where((lons >= box['west'] - 1.01 * dlon) & (lons <= box['east'] + 1.01 * dlon))[0]
    if rows.size == 0 or cols.size == 0:
        raise ValueError('Model grid does not cover the California box')
    order = cols[np.argsort(lons[cols])]
    if np.any(np.diff(lons[order]) <= 0) or np.any(np.abs(np.diff(lons[order]) - dlon) > 1e-6):
        raise ValueError('Longitudes are not contiguous across the box')
    return grid[np.ix_(rows, order)], lats[rows], lons[order]


def regrid(grid, lats, lons, target_lats, target_lons, nearest=False):
    """Bilinear (or nearest) resampling between ascending lat/lon grids."""
    if nearest:
        rows = np.clip(np.searchsorted(lats, target_lats), 1, len(lats) - 1)
        rows -= (target_lats - lats[rows - 1]) < (lats[rows] - target_lats)
        cols = np.clip(np.searchsorted(lons, target_lons), 1, len(lons) - 1)
        cols -= (target_lons - lons[cols - 1]) < (lons[cols] - target_lons)
        return grid[np.ix_(rows, cols)]
    along = np.stack([np.interp(target_lons, lons, row) for row in grid])
    return np.stack([np.interp(target_lats, lats, along[:, i]) for i in range(along.shape[1])], axis=1)


# ---- per-model build -----------------------------------------------------------

def convert(model, name, cube, times):
    how = model.field(name).convert
    if how == 'kelvin':
        return cube - 273.15
    if how == 'rate_per_hour':          # kg m-2 s-1 == mm/s
        return cube * 3600.0
    if how == 'fraction':
        return cube * 100.0
    if how == 'accumulated_m':          # total since initialization -> mean mm/h over the preceding interval
        rate = np.full_like(cube, np.nan)
        rate[0] = 0.0
        for t in range(1, len(times)):
            hours = (times[t] - times[t - 1]) / 3600
            rate[t] = np.maximum(cube[t] - cube[t - 1], 0) * 1000.0 / hours
        return rate
    return cube


def fetch_model(model, cycle, workers=16, log=print):
    """Download and decode every step -> (times, lats, lons, {field: cube}, sea mask)."""
    want = [(f.name, f.select) for f in model.fields]
    mask_key = '__mask__'

    def step_job(step):
        wanted = want + ([(mask_key, model.mask)] if model.mask and step == model.steps[0] else [])
        plan = plan_step(model, cycle, step, wanted)
        blobs = download_all([(name, url, rng) for name, url, rng in plan], workers=4)
        return step, {name: subset(*decode(blob)) for name, blob in blobs.items()}

    started = time.time()
    if model.family == 'ecmwf':
        workers = min(workers, 8)  # ECMWF's bucket throttles bursts harder than NOAA's
    with ThreadPoolExecutor(max_workers=max(1, workers // 4)) as pool:
        results = dict(pool.map(step_job, model.steps))
    log(f'{model.id}: {len(results)} steps downloaded and decoded in {time.time() - started:.0f}s')
    first = results[model.steps[0]]
    native = [f.name for f in model.fields if len(f.select) > 2 and f.select[2] == 'native']
    reference = first[native[0]] if native else first[model.fields[0].name]
    _, lats, lons = reference
    shape = reference[0].shape
    for step_fields in results.values():  # put every field on the reference grid
        for name, (grid, glats, glons) in list(step_fields.items()):
            if grid.shape != shape or not np.allclose(glats, lats) or not np.allclose(glons, lons):
                step_fields[name] = (regrid(grid, glats, glons, lats, lons, nearest=name == mask_key), lats, lons)
    times = [int(cycle.timestamp()) + 3600 * step for step in model.steps]
    cubes = {}
    for f in model.fields:
        cube = np.full((len(model.steps), *shape), np.nan)
        for t, step in enumerate(model.steps):
            got = results[step].get(f.name)
            if got is not None:
                if got[0].shape != shape or not np.allclose(got[1], lats) or not np.allclose(got[2], lons):
                    raise ValueError(f'{model.id} {f.name} grid changed at step {step}')
                cube[t] = got[0]
        cubes[f.name] = convert(model, f.name, cube, times)
    if model.mask:
        mask_grid = results[model.steps[0]].get(mask_key)
        if mask_grid is None:
            raise ValueError(f'{model.id} land-sea mask missing')
        sea = mask_grid[0] < 0.5
    else:
        first = model.fields[0].name
        sea = np.isfinite(cubes[first]).any(axis=0)
    return times, lats, lons, cubes, sea


def quantize(values, scale):
    q = np.round(values / scale)
    q = np.where(np.isfinite(q), np.clip(q, -32767, 32767), MISSING).astype('<i2')
    return base64.b64encode(q.tobytes()).decode()


def tile_keys(box=BOX):
    return [(lat, lon) for lat in range(box['south'], box['north']) for lon in range(box['west'], box['east'])]


def write_tiles(model, cycle, times, lats, lons, cubes, sea, out_dir):
    """Write 1-degree tiles containing at least one sea cell; return their keys."""
    dlat, dlon = float((lats[-1] - lats[0]) / (len(lats) - 1)), float((lons[-1] - lons[0]) / (len(lons) - 1))
    tiles_dir = out_dir / 'tiles'
    tiles_dir.mkdir(parents=True, exist_ok=True)
    keys = []
    for lat0, lon0 in tile_keys():
        core_rows = np.where((lats >= lat0) & (lats < lat0 + 1))[0]
        core_cols = np.where((lons >= lon0) & (lons < lon0 + 1))[0]
        if core_rows.size == 0 or core_cols.size == 0 or not sea[np.ix_(core_rows, core_cols)].any():
            continue
        rows = np.where((lats >= lat0 - 1.01 * dlat) & (lats <= lat0 + 1 + 1.01 * dlat))[0]
        cols = np.where((lons >= lon0 - 1.01 * dlon) & (lons <= lon0 + 1 + 1.01 * dlon))[0]
        key = f'{lat0}_{lon0}'
        tile = {
            'schema_version': SCHEMA, 'model': model.id, 'cycle': int(cycle.timestamp()), 'key': key,
            'times': times, 'lat0': round(float(lats[rows[0]]), 6), 'lon0': round(float(lons[cols[0]]), 6),
            'dlat': round(dlat, 8), 'dlon': round(dlon, 8), 'nlat': int(rows.size), 'nlon': int(cols.size),
            'sea': base64.b64encode(np.packbits(sea[np.ix_(rows, cols)].ravel().astype(np.uint8)).tobytes()).decode(),
            'fields': {name: {'scale': model.field(name).scale, 'data': quantize(cube[:, rows][:, :, cols], model.field(name).scale)}
                       for name, cube in cubes.items()},
        }
        (tiles_dir / f'{key}.json').write_text(json.dumps(tile, separators=(',', ':')))
        keys.append(key)
    return keys


def manifest_for(model, cycle, times, keys, lats, lons, built_at, seconds):
    return {
        'schema_version': SCHEMA, 'model': model.id, 'name': model.name, 'provider': model.provider, 'kind': model.kind,
        'cycle': int(cycle.timestamp()), 'cycle_iso': stamp(cycle), 'built_at': stamp(built_at), 'build_seconds': round(seconds),
        'times': times, 'fields': [f.name for f in model.fields], 'tiles': sorted(keys),
        'grid': {'dlat': round(float(lats[1] - lats[0]), 8), 'dlon': round(float(lons[1] - lons[0]), 8),
                 'resolution_km': model.resolution_km},
        'documentation': model.documentation, 'notes': model.notes,
        # Mirrors Open-Meteo's /static/meta.json so existing freshness checks keep working.
        'meta': {'last_run_initialisation_time': int(cycle.timestamp()),
                 'last_run_modification_time': int(built_at.timestamp()),
                 'last_run_availability_time': int(built_at.timestamp()),
                 'data_end_time': times[-1], 'temporal_resolution_seconds': 3600,
                 'update_interval_seconds': 86400 // len(model.cycles)},
    }


def build_one(model, output, previous, force, log):
    target = output / model.id
    prior_manifest = previous / model.id / 'manifest.json' if previous else None
    prior = json.loads(prior_manifest.read_text()) if prior_manifest and prior_manifest.is_file() else None
    cycle = latest_cycle(model)
    if cycle is None:
        raise RuntimeError('no complete cycle published in the last 48 hours')
    if prior and prior.get('cycle') == int(cycle.timestamp()) and not force:
        if target.resolve() != (previous / model.id).resolve():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(previous / model.id, target)
        log(f'{model.id}: {stamp(cycle)} already built; reusing')
        return prior, 'current'
    started = time.time()
    times, lats, lons, cubes, sea = fetch_model(model, cycle, log=log)
    staging = output / f'.{model.id}.staging'
    shutil.rmtree(staging, ignore_errors=True)
    keys = write_tiles(model, cycle, times, lats, lons, cubes, sea, staging)
    if not keys:
        raise RuntimeError('no sea tiles produced')
    manifest = manifest_for(model, cycle, times, keys, lats, lons, datetime.now(timezone.utc), time.time() - started)
    (staging / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    log(f'{model.id}: built {stamp(cycle)} into {len(keys)} tiles in {time.time() - started:.0f}s')
    return manifest, 'built'


def build(output, previous=None, models=None, force=False, log=print):
    output.mkdir(parents=True, exist_ok=True)
    status = {}
    for model_id in models or MODELS:
        model = MODELS[model_id]
        try:
            manifest, state = build_one(model, output, previous, force, log)
            status[model_id] = {'status': 'ok', 'state': state, 'cycle': manifest['cycle_iso'],
                                'built_at': manifest['built_at'], 'tiles': len(manifest['tiles'])}
        except Exception as error:  # keep the previous generation; report
            log(f'{model_id}: FAILED: {error}')
            kept = False
            if previous and (previous / model_id / 'manifest.json').is_file():
                target = output / model_id
                if target.resolve() != (previous / model_id).resolve():
                    shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(previous / model_id, target)
                kept = True
            status[model_id] = {'status': 'failed', 'issue': str(error)[:300], 'kept_previous': kept}
    index = {'schema_version': SCHEMA, 'generated_at': stamp(), 'box': BOX, 'models': status}
    (output / 'index.json').write_text(json.dumps(index, indent=1))
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--models', help='comma-separated subset of: ' + ','.join(MODELS))
    parser.add_argument('--force', action='store_true', help='rebuild even if the cycle is already published')
    args = parser.parse_args()
    index = build(args.output, args.previous, args.models.split(',') if args.models else None, args.force)
    print(json.dumps(index, indent=1))
    if all(m['status'] == 'failed' and not m.get('kept_previous') for m in index['models'].values()):
        sys.exit(1)


if __name__ == '__main__':
    main()
