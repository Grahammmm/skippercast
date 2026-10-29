"""Adapt local C2 tiles + native C1 contributors + C5 rights to MvpManifest.

No geometry changes, downloads, source-raster reads or clearance decisions.
Run as python -m research.scripts.coast_mvp.coast_manifest from the repo root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from research.scripts.coast_mvp.coast_c1_preview import validate_manifest, text
from research.scripts.coast_mvp.coast_rights import _used_sources, NOT_FOR_NAVIGATION

TERRAIN = 'terrain/{z}/{x}/{y}.png'
VECTOR = 'vector/{z}/{x}/{y}.pbf'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def local_file(root, relative):
    """Only regular files below the admitted directory, without symlink hops."""
    path = root / relative
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
        raise ValueError(f'Local regular asset required: {relative}')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Asset escapes C2 directory')
    return path


def read_json(path):
    if path.stat().st_size > 32_000_000:
        raise ValueError('Preview JSON exceeds 32 MB cap')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('JSON object required')
    return value


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def tiles_and_bounds(root, c2):
    zoom = c2.get('zoom')
    if type(zoom) is not int or not 0 <= zoom <= 18:
        raise ValueError('C2 zoom must be an integer in 0..18')
    # Accept only the producer's exact relative templates, never arbitrary URLs.
    if c2.get('terrain_template') != TERRAIN or c2.get('vector_template') != VECTOR:
        raise ValueError('C2 local tile templates required')
    tiles, assets = set(), {}
    for kind, extension in [('terrain', 'png'), ('vector', 'pbf')]:
        directory = root / kind
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError('Local tile directory required')
        paths = list(directory.rglob(f'*.{extension}'))
        if not paths or len(paths) > 64:
            raise ValueError('Tile count must be in 1..64')
        for path in paths:
            relative = path.relative_to(root).as_posix()
            file = local_file(root, relative)
            parts = path.relative_to(directory).parts
            if len(parts) != 3:
                raise ValueError('XYZ tile layout required')
            coordinates = [parts[0], parts[1], path.stem]
            if any(not p.isascii() or not p.isdecimal() or str(int(p)) != p for p in coordinates):
                raise ValueError('Canonical numeric XYZ paths required')
            z, x, y = map(int, coordinates)
            if z != zoom or not 0 <= x < 2**z or not 0 <= y < 2**z:
                raise ValueError('Tile outside C2 zoom/range')
            if kind == 'terrain':
                tiles.add((x, y))
            assets[relative] = digest(file)
    if type(c2.get('terrain_tiles')) is not int or len(tiles) != c2['terrain_tiles']:
        raise ValueError('C2 terrain tile count mismatch')
    xs, ys = [x for x, _ in tiles], [y for _, y in tiles]
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    if len(tiles) != (x1 - x0) * (y1 - y0):
        raise ValueError('Rectangular C2 terrain coverage required')
    # C2's vector layer may be sparse, but never outside its terrain coverage.
    for relative in assets:
        kind, _, x, y = relative.split('/')
        if kind == 'vector' and (int(x), int(y[:-4])) not in tiles:
            raise ValueError('Vector tile outside terrain coverage')
    lat = lambda y: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2**zoom))))
    bounds = [x0 / 2**zoom * 360 - 180, lat(y1), x1 / 2**zoom * 360 - 180, lat(y0)]
    if not -85 <= bounds[1] < bounds[3] <= 85:
        raise ValueError('Tile bounds exceed viewer latitude limits')
    return bounds, assets


def joined_sources(c1, rights):
    used = validate_manifest(c1)
    rows = {r['source_id']: r for r in _used_sources(rights)}
    if set(rows) != {r['id'] for r in used}:
        raise ValueError('Rights must cover exactly the C1 contributors')
    sources = []
    for row in sorted(used, key=lambda r: r['id']):
        other = rows[row['id']]
        for left, right in [('sha256', 'sha256'), ('contributed_cells', 'contributed_cells'),
                            ('citation', 'source_url'), ('rights', 'license'), ('attribution', 'attribution')]:
            if row[left] != other[right]:
                raise ValueError(f'C1/rights mismatch: {row["id"]}.{left}')
        resolution = row.get('resolution_m')
        if not number(resolution) or resolution <= 0:
            raise ValueError('Positive finite native source resolution required')
        # No machine-readable legal acceptance exists in these producer contracts.
        # All rows remain held, including apparently public-domain/CC0 sources.
        sources.append(dict(
            id=row['id'], label=other['name'], url=row['citation'],
            attribution=row['attribution'], license=row['rights'], datum=row['vertical_datum'],
            resolutionM=resolution, permissionRequired=True, sha256=row['sha256'],
            termsUrl=other['terms_url'], contributedCells=row['contributed_cells'],
            datumNote=row['offset_note'], csumbInvolved=other['csumb'],
            rightsStatus='needs_permission' if other['csumb'] else 'review_required'))
    return sources, {row['code']: row for row in used}


def check_contours(geojson, c2, codes, bounds):
    features = geojson.get('features')
    if (geojson.get('type') != 'FeatureCollection' or not isinstance(features, list) or not features
            or type(c2.get('contour_features')) is not int or len(features) != c2['contour_features']):
        raise ValueError('C2 contour feature count mismatch')
    for feature in features:
        properties, geometry = feature.get('properties', {}), feature.get('geometry', {})
        code = properties.get('source_code')
        if type(code) is not int or code not in codes:
            raise ValueError('Contour contributor absent from C1')
        source = codes[code]
        depth = properties.get('depth_ft')
        metres = properties.get('depth_m')
        if (properties.get('source_id') != source['id']
                or properties.get('source_resolution_m') != source['resolution_m']
                or not number(depth) or depth <= 0 or not number(metres)
                or not math.isclose(metres, depth * 0.3048, abs_tol=1e-9)):
            raise ValueError('Contour provenance/feet-to-metres mismatch')
        points = geometry.get('coordinates')
        if geometry.get('type') != 'LineString' or not isinstance(points, list) or len(points) < 2:
            raise ValueError('C2 LineString required')
        for point in points:
            if (not isinstance(point, list) or len(point) != 2 or not all(map(number, point))
                    or not bounds[0] <= point[0] <= bounds[2] or not bounds[1] <= point[1] <= bounds[3]):
                raise ValueError('Contour coordinates outside finite tile bounds')


def build(c2_dir, c1_path, rights_path, *, region, synthetic):
    """Write viewer-manifest.json beside existing C2 assets, refusing overwrite.

    Hashes pin supplied declarations/assets, not proof that C1 generated C2 or
    that source receipts, counts, topology, science or legal rights were accepted.
    """
    region = text(region, 'region')
    if type(synthetic) is not bool:
        raise ValueError('Explicit synthetic boolean required')
    root = Path(c2_dir)
    if root.is_symlink():
        raise ValueError('C2 directory cannot be a symlink')
    root = root.resolve(strict=True)
    target = root / 'viewer-manifest.json'
    if target.exists() or target.is_symlink():
        raise FileExistsError('Use a C2 directory without viewer-manifest.json')
    c2_path = local_file(root, 'manifest.json')
    geo_path = local_file(root, 'contours.geojson')
    c1_path, rights_path = Path(c1_path), Path(rights_path)
    c2, c1, rights = map(read_json, (c2_path, c1_path, rights_path))
    if (type(c2.get('schema_version')) is not int or c2['schema_version'] != 1
            or c2.get('status') != 'review_required' or c2.get('tile_scheme') != 'XYZ'
            or c2.get('contour_crs') != 'EPSG:4326'
            or c2.get('value_convention') != 'elevation_positive_up'):
        raise ValueError('Unsupported C2 manifest contract')
    if not synthetic and any(m.get('fixture_only') is True or m.get('synthetic') is True
                             for m in (c2, c1, rights)):
        raise ValueError('Synthetic fixture cannot be labelled measured')
    sources, codes = joined_sources(c1, rights)
    bounds, assets = tiles_and_bounds(root, c2)
    check_contours(read_json(geo_path), c2, codes, bounds)
    result = dict(
        schemaVersion=1, region=region, synthetic=synthetic, bounds=bounds,
        center=[(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2],
        zoom=c2['zoom'], tileZoom=c2['zoom'], tileSize=256,
        terrain=TERRAIN, contours=VECTOR, contourLayer='contours', sources=sources,
        status='review_required', publicationHeld=True, navigation=NOT_FOR_NAVIGATION,
        limitations=['Input provenance/counts are declarations, not independent source verification.',
                     'C2 topology retained unchanged; no datum, scientific or publication acceptance.',
                     'All contributors remain held pending source and owner/counsel review.'],
        provenance=dict(c1Sha256=digest(c1_path), rightsSha256=digest(rights_path),
                        c2Sha256=digest(c2_path), contoursSha256=digest(geo_path), assets=assets))
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n'
    with target.open('x', encoding='utf-8') as stream:
        stream.write(payload)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2-dir', type=Path, required=True)
    parser.add_argument('--c1-manifest', type=Path, required=True)
    parser.add_argument('--rights-manifest', type=Path, required=True)
    parser.add_argument('--region', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--synthetic', action='store_true')
    mode.add_argument('--measured', action='store_true')
    args = parser.parse_args(argv)
    try:
        build(args.c2_dir, args.c1_manifest, args.rights_manifest,
              region=args.region, synthetic=args.synthetic)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        parser.exit(2, f'coast_manifest: {exc}\n')
    print('Built viewer-manifest.json: review_required; publication held; not for navigation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
