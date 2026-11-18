"""Build a private regional layer of NOAA chart hazards; never package or export it.

Pass the extract work directory (containing out/) as --enc-root and, if the
report is stored separately, pass its ENC-EXTRACT.json as --enc-manifest.
An ok stage receipt verifies local bytes only; it does not admit public display.
"""
from __future__ import annotations

import argparse
import json
from math import isfinite
import os
from pathlib import Path
from typing import TypeGuard

from skippercast.paths import repo_root
from skippercast.relief import receipts

TARGET = 'layers/enc'
LAYER = 'enc-hazards.geojson'
MANIFEST = 'ENC-EXTRACT.json'
KINDS = ('WRECKS', 'OBSTRN', 'UWTROC')
MILITARY = frozenset({'san-clemente', 'san-nicolas'})
NOTICE = 'NOT FOR NAVIGATION'
PRIVATE = {'private_only': True, 'publication_allowed': False}


def _object(raw: bytes) -> dict:
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError('expected a JSON object')
    return obj


def _box(bounds):
    from shapely.geometry import box

    if (not isinstance(bounds, list) or len(bounds) != 4
            or any(type(x) not in (int, float) for x in bounds)):
        raise ValueError('expected WGS84 [west, south, east, north] bounds')
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError('invalid WGS84 bounds')
    return box(*bounds)


def _private(meta: object) -> TypeGuard[dict]:
    return isinstance(meta, dict) and all(meta.get(key) is value for key, value in PRIVATE.items())


def _reaches(report, clip):
    if report.get('schema_version') != 1 or not _private(report.get('policy')):
        raise ValueError('expected a private ENC-EXTRACT.json v1 report')
    seen = set()
    holds = set()
    overlaps = []
    for row in report['reaches']:
        rid = row['id']
        if not receipts.REGION_ID.fullmatch(rid) or rid in seen:
            raise ValueError('invalid or duplicate ENC reach id')
        seen.add(rid)
        intersects = clip.intersects(_box(row['bbox']))
        if row['hold'] or rid in MILITARY:
            if intersects:
                raise receipts.Held(f'region intersects ENC military/access hold: {rid}')
            if row['hold']:
                holds.add(rid)
        elif intersects:
            overlaps.append(row)
    if not MILITARY <= holds:
        raise ValueError('report lacks military hold footprints')
    return sorted(overlaps, key=lambda row: row['id'])


def _rows(path, raw, reach, kind):
    from shapely.errors import ShapelyError
    from shapely.geometry import shape

    doc = _object(raw)
    meta = doc.get('enc_extract')
    if (doc.get('type') != 'FeatureCollection' or 'crs' in doc or not _private(meta)
            or meta.get('reach_id') != reach or meta.get('object_class') != kind
            or not isinstance(doc.get('features'), list)):
        raise ValueError(f'{path.name}: expected the matching private ENC FeatureCollection')
    for index, feature in enumerate(doc['features']):
        at = f'{path.name} feature {index}'
        if not isinstance(feature, dict) or feature.get('type') != 'Feature' or not feature.get('geometry'):
            raise ValueError(f'{at}: missing feature geometry')
        try:
            geom = shape(feature['geometry'])
        except (AttributeError, KeyError, TypeError, ValueError, ShapelyError):
            raise ValueError(f'{at}: invalid feature geometry') from None
        if geom.is_empty or geom.has_z or not geom.is_valid:
            raise ValueError(f'{at}: expected nonempty valid 2D geometry')
        west, south, east, north = geom.bounds
        if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
            raise ValueError(f'{at}: geometry outside WGS84')
        src = feature['properties']
        cell, edition = src['enc_source_cell'], src['enc_edition']
        if not isinstance(cell, str) or not cell or type(edition) not in (str, int):
            raise ValueError(f'{at}: invalid cell provenance')
        props = {'kind': kind, 'source_cell': cell, 'source_edition': edition, 'nav_warning': NOTICE}
        if kind == 'OBSTRN':
            props['fish_haven'] = src['enc_fish_haven'] is True
        depth = src.get('VALSOU')
        if depth is not None:
            if type(depth) not in (int, float) or not isfinite(depth):
                raise ValueError(f'{at}: invalid chart depth')
            # Preserve the native unit and positive-down sign; no datum conversion.
            props.update(chart_depth=depth, depth_label='chart depth',
                         chart_depth_unit_code=src.get('enc_depth_unit_code'))
        lnam = src.get('LNAM')
        yield lnam if isinstance(lnam, str) else None, geom, props


def _prepare(region, root, manifest):
    if region.id in MILITARY:
        raise receipts.Held(f'ENC military island hold: {region.id}')
    if not root.is_dir():
        raise ValueError('ENC root is missing or not a directory')
    if any(path.is_symlink() for path in (region.dir, region.stages_dir, region.dir / 'layers',
                                          region.dir / TARGET)):
        raise ValueError('symlink in private ENC output path')
    config = repo_root() / 'regions' / region.id / 'region.json'
    config_bytes, report_bytes = config.read_bytes(), manifest.read_bytes()
    contract = _object(config_bytes)
    if contract.get('id') != region.id:
        raise ValueError('region.json does not match --region')
    clip = _box(contract['bounds'])
    reaches = _reaches(_object(report_bytes), clip)
    inputs = [receipts.Input(config, 'region'), receipts.Input(manifest, 'extract-report')]
    pin = {'region': receipts.sha256_bytes(config_bytes), 'extract-report': receipts.sha256_bytes(report_bytes)}
    rows = []
    for reach in reaches:
        rid = reach['id']
        for kind in KINDS:
            name = f'{rid}.{kind}.geojson'
            entry = reach['files'][kind]
            if Path(entry['path']).name != name:
                raise ValueError(f'{name}: report file name does not match reach and class')
            path = root / 'out' / name  # never follow an absolute path recorded by the producer
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError(f'{name}: symlink in ENC input path')
            raw = path.read_bytes()
            digest = receipts.sha256_bytes(raw)
            if digest != entry['sha256']:
                raise ValueError(f'{name}: SHA-256 does not match ENC-EXTRACT.json')
            role = f'enc:{name}'
            inputs.append(receipts.Input(path, role))
            pin[role] = digest
            rows.extend(_rows(path, raw, rid, kind))
    return receipts.Plan(inputs, params=PRIVATE), pin, clip, rows


def _write(directory, clip, rows):
    from shapely.errors import ShapelyError
    from shapely.geometry import mapping

    seen = set()
    features = []
    for lnam, geom, props in rows:
        try:
            clipped = geom.intersection(clip).normalize()
        except ShapelyError:
            # GEOS error details can contain private geometry coordinates.
            raise ValueError('cannot clip ENC feature to region bounds') from None
        if clipped.is_empty:
            continue
        feature = {'type': 'Feature', 'geometry': mapping(clipped), 'properties': props}
        wire = receipts.canonical(feature)
        # Adjacent reach clipping or different source cells may yield distinct
        # parts/records for the same LNAM. Suppress only exact output repeats.
        if lnam and (lnam, wire) in seen:
            continue
        if lnam:
            seen.add((lnam, wire))
        features.append(wire)
    features.sort()
    header = receipts.canonical({'type': 'FeatureCollection', **PRIVATE, 'nav_warning': NOTICE})
    path = directory / LAYER
    with open(path, 'xb', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        stream.write(header[:-1] + b',"features":[' + b','.join(features) + b']}\n')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='region.py enc', description=__doc__)
    parser.add_argument('--region', required=True)
    out = os.environ.get('SC_RELIEF_OUT') or None
    parser.add_argument('--out', type=Path, default=out, required=out is None, help='private output root')
    parser.add_argument('--enc-root', type=Path, required=True)
    parser.add_argument('--enc-manifest', type=Path, help=f'default: ENC root/{MANIFEST}')
    args = parser.parse_args(argv)
    try:
        region = receipts.Region(args.out, args.region)
        root = args.enc_root.expanduser().resolve()
        manifest = (args.enc_manifest or root / MANIFEST).expanduser().resolve()
        # Preflight before StageRun can create a lock, attempt receipt or target.
        plan, pin, clip, rows = _prepare(region, root, manifest)
    except receipts.Held as exc:
        print(f'[enc] HELD: {exc}')
        return receipts.EXIT_CODES['held']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'[enc] BLOCKED: {exc}')
        return receipts.EXIT_CODES['blocked']

    def write_layer(directory):
        pending = receipts.read_receipt(region.receipt_path('enc'))
        if pending is None or {row['role']: row['sha256'] for row in pending['inputs']} != pin:
            raise receipts.ReceiptError('ENC inputs changed after preflight')
        _write(directory, clip, rows)

    code = receipts.stage_digest([('enc.py', Path(__file__))])
    result = receipts.run_stage(receipts.StageRun(region, 'enc', write_layer, code, plan=plan, target=TARGET))
    print(result.line())
    return result.exit_code
