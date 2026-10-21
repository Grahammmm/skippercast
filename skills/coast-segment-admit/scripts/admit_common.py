"""Bounded offline admission utilities; workflow tooling, never product code."""
import argparse
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path

import stat
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / 'src'), str(REPO / 'skills/coast-campaign-shared/scripts')]
from coast_refs import (Resolver, canonical, directory_fd, loads, object_digest,
                        relative_parts, sha256, write_once)
from coast_sample import window_key, window_dir
from validate_coast_receipt import GraphValidator, validate, validate_schema
from skippercast.coastal.coordinator import catalog_bridge as bridge

HEADER = ('author_profile', 'author_model', 'card_id', 'code_commit', 'skill_commit')
MAX_JSON = bridge.MAX_DOCUMENT_BYTES


def absolute(value):
    path = Path(value)
    if not path.is_absolute() or any(p in ('.', '..') for p in str(value).split('/')):
        raise ValueError('every file argument must be absolute and normalized')
    return path


def read_json(path):
    path = absolute(path)
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON:
                raise ValueError('bounded regular JSON file required')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                raw = stream.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ValueError('JSON read bound exceeded')
        finally:
            os.close(fd)
    value = loads(raw)
    if not isinstance(value, dict):
        raise ValueError('JSON input must be an object')
    return value


def file_ref(path, root_id, root):
    path, root = absolute(path), absolute(root)
    relative = path.relative_to(root).as_posix()
    relative_parts(relative)
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('regular, non-hardlinked file required')
            h = hashlib.sha256()
            size = 0
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(chunk)
                    size += len(chunk)
            after = os.fstat(fd)
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError('file changed while hashing')
        finally:
            os.close(fd)
    return dict(root_id=root_id, path=relative, sha256=h.hexdigest(), bytes=size)


def ensure_dir(path):
    path = absolute(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
    finally:
        os.close(fd)


def freeze(path, value):
    path = absolute(path)
    # All helpers require operator-exclusive/quiescent staging; refuse symlink ancestors.
    with directory_fd(path.parent):
        return write_once(path, value)


def header(selection):
    return dict(created_utc=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                **{k: selection[k] for k in HEADER})


def context(campaign_path, selection_path):
    campaign, selection = read_json(campaign_path), read_json(selection_path)
    validate_schema(campaign)
    if selection.get('schema') != 'coast-selection-v1':
        raise ValueError('coast-selection-v1 required')
    required = {'schema', *HEADER, 'campaign_sha256', 'allowed_root_ids', 'catalog', 'discovery',
                'ledger_snapshot', 'max_total_bytes', 'budget', 'windows', 'preconditions'}
    if not required <= selection.keys() or selection.keys() - required - {'replacement_plan_of'}:
        raise ValueError('unknown or missing selection field')
    if selection['campaign_sha256'] != sha256(canonical(campaign)):
        raise ValueError('selection must pin canonical campaign bytes')
    for key in HEADER:
        if not isinstance(selection.get(key), str) or not selection[key]:
            raise ValueError('actual runtime provenance required: ' + key)
    current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    if selection['code_commit'] != current or selection['skill_commit'] != current:
        raise ValueError('card code/skill commit differs from the pinned checkout')
    root = absolute(campaign_path).parent
    queue_id = 'queue:' + campaign['campaign_segment_id']
    if file_ref(campaign_path, queue_id, root)['sha256'] != selection['campaign_sha256']:
        raise ValueError('campaign must retain its exact canonical frozen file bytes')
    bridge.check_budget(selection['budget'])
    cap = selection['max_total_bytes']
    if type(cap) is not int or not 0 < cap <= bridge.MAX_TOTAL_BYTES:
        raise ValueError('max_total_bytes exceeds installed cap')
    windows = selection['windows']
    if not isinstance(windows, list) or not 1 <= len(windows) <= bridge.MAX_JOBS:
        raise ValueError('HELD PC-6: select 1..4 distinct sources, one window each')
    ids = [w['source_id'] for w in windows]
    if len(set(ids)) != len(ids) or not set(ids) <= set(campaign['source_inventory']):
        raise ValueError('duplicate source or source absent from campaign inventory')
    keys = []
    for w in windows:
        expected_fields = {'source_id','pixel_window','grid_definition','input','raw_provenance',
                           'retained_inputs','reader','vertical','rights','rights_summary','datum'}
        if not isinstance(w, dict) or set(w) != expected_fields:
            raise ValueError('unknown or missing selected-window field')
        bridge._window(w['pixel_window'])
        g = w['grid_definition']
        if g['tiling_version'] != 'single-selected-v1' or g['pixel_window'] != w['pixel_window']:
            raise ValueError('HELD PC-6: incompatible grid adapter')
        if g['tile_width'] != w['pixel_window'][2] or g['tile_height'] != w['pixel_window'][3]:
            raise ValueError('single-selected tile dimensions differ')
        key = window_key(w['source_id'], object_digest(g), 0)
        if key not in campaign['intended_windows']:
            raise ValueError('window absent from campaign intended inventory')
        keys.append(key)
        if not w['raw_provenance'] or any(r['root_id'] != 'raw:campaign' for r in w['raw_provenance']):
            raise ValueError('explicit raw:campaign provenance required')
        if w['reader'] != 'native-raster-v1':
            raise ValueError('unadmitted reader; no automatic fallback')
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate source-grid window')
    return campaign, selection, root, queue_id


def resolver_for(roots_path, selection, root, queue_id):
    bindings = read_json(roots_path)
    allowed = selection['allowed_root_ids']  # independent card selection, not receipt-provided roots
    if len(set(allowed)) != len(allowed) or queue_id not in allowed or 'raw:campaign' not in allowed:
        raise ValueError('card must admit queue and raw root IDs')
    if bindings.get(queue_id) != str(root):
        raise ValueError('campaign queue binding differs from campaign path')
    return Resolver(bindings, allowed_root_ids=allowed)


def verify_provenance(w, resolver):
    if len(w['raw_provenance']) > 8 or len(w['retained_inputs']) > 16:
        raise ValueError('provenance population exceeds bounded staging contract')
    if sum(r['bytes'] for r in w['raw_provenance']+w['retained_inputs']) > bridge.MAX_TOTAL_BYTES:
        raise ValueError('provenance bytes exceed staging bound')
    graph = GraphValidator(resolver)
    for ref in w['raw_provenance'] + w['retained_inputs']:
        graph.reference(ref)
    resolver.read(w['input'], retain=False)
    if w['input'] not in w['raw_provenance']:
        # A derived input needs a supported, graph-validated derivation with both
        # original and output refs. Never call a different GTiff the original BAG.
        needed = {w['input']['sha256']} | {r['sha256'] for r in w['raw_provenance']}
        found = set()
        def collect(value):
            if isinstance(value, dict):
                if {'path', 'sha256', 'bytes'} <= value.keys():
                    found.add(value['sha256'])
                for v in value.values():
                    collect(v)
            elif isinstance(value, list):
                for v in value:
                    collect(v)
        for ref in w['retained_inputs']:
            if ref['path'].endswith('.json'):
                collect(loads(resolver.read(ref)))
        if not needed <= found:
            raise ValueError('derived input missing supported raw/output derivation lineage')


def check_stage(stage, campaign, selection):
    if (stage.get('schema') != 'coast-cache-stage-v1' or stage.get('holds')
            or stage.get('campaign_sha256') != sha256(canonical(campaign))
            or stage.get('selection_sha256') != sha256(canonical(selection))):
        raise ValueError('cache stage held or input binding changed')
    if [s['source_id'] for s in stage['sources']] != [w['source_id'] for w in selection['windows']]:
        raise ValueError('cache stage source population mismatch')
    total = sum(s['hot_cache']['bytes'] for s in stage['sources'])
    if total > selection['max_total_bytes'] or any(s['hot_cache']['bytes'] > selection['budget']['bytes'] for s in stage['sources']):
        raise ValueError('cache stage byte cap overrun')
    for w, s in zip(selection['windows'], stage['sources']):
        hot = s['hot_cache']
        if hot['root_id'] != 'queue:'+campaign['campaign_segment_id'] or not hot['path'].startswith('cache/'):
            raise ValueError('cache stage requires explicit campaign cache namespace')
        if s['hot_cache']['sha256'] != w['input']['sha256'] or s['hot_cache']['bytes'] != w['input']['bytes']:
            raise ValueError('cache stage differs from selected input')
    return stage


def owner_id(x, y):
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError('nonfinite centre transform')
    return f'seg:3310:{math.floor(x/5000)*5000}:{math.floor(y/5000)*5000}:5000'


def geographic_records(campaign):
    from pyproj import Transformer
    from skippercast.coastal.coordinator.segments import from_bbox
    projected = Transformer.from_crs('OGC:CRS84', 'EPSG:3310', always_xy=True).transform_bounds(*campaign['bbox_crs84'], densify_pts=41)
    if not all(math.isfinite(v) for v in projected):
        raise ValueError('nonfinite campaign transform')
    a,b,c,d = projected
    if (math.ceil(c/5000)-math.floor(a/5000)) * (math.ceil(d/5000)-math.floor(b/5000)) > 4096:
        raise ValueError('campaign exceeds 4096 record bound')
    return from_bbox(campaign['bbox_crs84'], region=campaign['campaign_segment_id'])


def geometry(campaign, selection, stage, root):
    """Compare reviewed grid metadata with cached native metadata, then partition."""
    from pyproj import Transformer
    import rasterio
    from shapely.geometry import Polygon, box
    from skippercast.coastal.handoff.common import validate_native_source, validate_derived_geotiff
    records = geographic_records(campaign)
    by_id = {r['segment_id']: r for r in records}
    grids, windows, groups = [], [], {}
    for w, cached in zip(selection['windows'], stage['sources']):
        ref = cached['hot_cache']
        if file_ref(root/ref['path'], ref['root_id'], root) != ref:
            raise ValueError('cached source SHA256 mismatch')
        path = root/ref['path']
        native_ref = {k:ref[k] for k in ('path', 'sha256', 'bytes')}
        # Reuse the existing container guard before GDAL: BAG external links,
        # virtual datasets and unbound TIFF sidecars must not be opened.
        if path.suffix.lower() == '.bag':
            validate_native_source(root, native_ref)
        else:
            validate_derived_geotiff(root, native_ref)
        # Native drivers only; metadata reads, no pixel read, no URL or VRT driver.
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO'):
            with rasterio.open(path, driver='BAG' if path.suffix.lower() == '.bag' else 'GTiff') as ds:
                if ds.crs is None:
                    raise ValueError('native raster CRS unavailable')
                observed = dict(source_sha256=ref['sha256'], raster_crs=ds.crs.to_string(),
                                affine_transform=list(ds.transform)[:6], width=ds.width, height=ds.height,
                                tile_width=w['pixel_window'][2], tile_height=w['pixel_window'][3],
                                tiling_version='single-selected-v1', pixel_window=w['pixel_window'])
        if canonical(observed) != canonical(w['grid_definition']):
            raise ValueError('reviewed grid differs from cached native metadata')
        col,row,width,height = w['pixel_window']
        if col+width > observed['width'] or row+height > observed['height']:
            raise ValueError('pixel window outside raster')
        a,b,c,d,e,f = observed['affine_transform']
        x,y = col+width/2, row+height/2
        centre = Transformer.from_crs(observed['raster_crs'], 'EPSG:3310', always_xy=True).transform(a*x+b*y+c, d*x+e*y+f)
        owner = owner_id(*centre)
        if owner not in by_id:
            raise ValueError('owner absent from frozen campaign; correct inventory explicitly')
        geographic = Transformer.from_crs(observed['raster_crs'], 'OGC:CRS84', always_xy=True)
        corners = [(col,row),(col+width,row),(col+width,row+height),(col,row+height)]
        points = []
        for start,end in zip(corners,corners[1:]+corners[:1]):
            for step in range(42):
                px = start[0]+(end[0]-start[0])*step/42
                py = start[1]+(end[1]-start[1])*step/42
                points.append(geographic.transform(a*px+b*py+c, d*px+e*py+f))
        footprint = Polygon(points)
        if (not footprint.is_valid or footprint.is_empty
                or footprint.intersection(box(*campaign['bbox_crs84'])).area <= 0
                or footprint.intersection(box(*by_id[owner]['bbox_crs84'])).area <= 0):
            raise ValueError('window has no positive campaign/owner footprint overlap')
        grid_sha = object_digest(observed)
        key = window_key(w['source_id'], grid_sha, 0)
        groups.setdefault(owner, []).append(key)
        grids.append(dict(source_id=w['source_id'], grid_sha256=grid_sha, definition=observed, cols=1, rows=1, total=1))
        windows.append(dict(window_key=key, window_dir=window_dir(key), source_id=w['source_id'], grid_sha256=grid_sha,
                            idx=0, pixel_window=w['pixel_window'], owner_segment_id=owner, footprint=list(footprint.bounds),
                            overlapping_segment_ids=sorted(r['segment_id'] for r in records if footprint.intersection(box(*r['bbox_crs84'])).area > 0)))
    if len(groups) != 1:
        raise ValueError('multiple owner groups; partition inventory: ' + canonical(groups).decode().strip())
    return by_id[next(iter(groups))], grids, windows


def cli(action, arguments):
    parser = argparse.ArgumentParser(description=action.__doc__)
    for name in arguments:
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    try:
        for v in vars(args).values():
            absolute(v)
        result = action(**vars(args))
        print(canonical(result).decode(), end='')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('HOLD: '+str(exc), file=sys.stderr)
        raise SystemExit(3)
