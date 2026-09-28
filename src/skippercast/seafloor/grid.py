"""Disjoint planning reaches and a provisional shallow-water reference grid.

No BlueTopo pixel is accepted as original-survey coverage or habitat evidence.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds, transform as window_transform
import shapely
from shapely.geometry import LineString, Point, mapping
from shapely.ops import substring, transform

from skippercast.platform.contracts import REPO, atomic_json, read_json
from . import reference
from .io import sha256


def make_reaches(config, spine):
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    unproject = Transformer.from_crs(3310, 4326, always_xy=True).transform
    starts = [0.0] + [spine.project(Point(project(*r['start_anchor'])))
                      for r in config['regions'][1:]] + [spine.length]
    if any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError('Region anchors are not ordered along the coast')
    reaches = []
    for region, start, stop in zip(config['regions'], starts, starts[1:]):
        count = max(1, round((stop - start) / config['reach_length_m']))
        edges = np.linspace(start, stop, count + 1)
        for number, (a, b) in enumerate(zip(edges, edges[1:]), 1):
            line = substring(spine, float(a), float(b))
            reaches.append({'id': f'{region["id"]}-r{number:02}', 'region': region['id'],
                            'start_m': float(a), 'end_m': float(b),
                            'length_m': float(b - a), 'bounds_3310': list(line.bounds),
                            'geometry': mapping(transform(unproject, line))})
    anchor = spine.project(Point(project(*config['priority_anchor'])))
    order = sorted(reaches, key=lambda r: (abs((r['start_m'] + r['end_m']) / 2 - anchor), r['id']))
    for number, reach in enumerate(order, 1):
        reach['order'] = number
    return reaches


def assign_reaches(spine, reaches, x, y):
    """One owner per cell center. Half-open chainage intervals remove shared cells.

    Centers whose closest point is a terminal endpoint are outside this scope.
    """
    distance = shapely.line_locate_point(spine, shapely.points(x, y))
    index = np.searchsorted([r['end_m'] for r in reaches], distance, side='right')
    return np.where((distance > 0) & (distance < spine.length), index, -1)


def classify_reference(elevation):
    """0 unknown/no-data, 1 other valid elevation, 2 provisional 0–100 m band."""
    result = np.zeros(elevation.shape, dtype='uint8')
    valid = np.isfinite(elevation)
    result[valid] = 1
    result[valid & (elevation < 0) & (elevation >= -100)] = 2
    return result


def merge_reference(destination, incoming):
    """Caller supplies coarse/older first; fine valid pixels overwrite, holes do not."""
    valid = incoming != 0
    destination[valid] = incoming[valid]


def cell_counts(mosaic, pixels_per_cell):
    h, w = mosaic.shape
    n = pixels_per_cell
    if h % n or w % n:
        raise ValueError('Reference raster must align to full planning cells')
    blocks = mosaic.reshape(h // n, n, w // n, n)
    return ((blocks == 2).sum(axis=(1, 3)), (blocks == 0).sum(axis=(1, 3)))


def mosaic_reference(config, tiles, sampled):
    pixel = config['reference_pixel_m']
    cell = config['cell_size_m']
    if cell != 250 or pixel != 25 or config['reference_depth_m'] != [0, 100]:
        raise ValueError('Changing the reference rule requires a reviewed rule version')
    west, south, east, north = transform_bounds(4326, 3310, *config['bounds'], densify_pts=41)
    west, south = math.floor(west / cell) * cell, math.floor(south / cell) * cell
    east, north = math.ceil(east / cell) * cell, math.ceil(north / cell) * cell
    affine = Affine(pixel, 0, west, 0, -pixel, north)
    height, width = round((north - south) / pixel), round((east - west) / pixel)
    result = np.zeros((height, width), dtype='uint8')
    # Fine resolution wins; delivery date only resolves equal-resolution compilation overlap.
    ordered = sorted(zip(tiles, sampled), key=lambda pair: (
        -pair[0]['native_resolution_m'], pair[0]['delivered_date'], pair[0]['id']))
    for tile, (path, receipt) in ordered:
        with np.load(path, allow_pickle=False) as sample:
            elevation = sample['elevation']
            source_transform = Affine(*sample['transform'])
            crs = CRS.from_wkt(str(sample['crs'])).to_2d().to_wkt()
            h, w = elevation.shape
            source_bounds = (source_transform.c, source_transform.f + source_transform.e * h,
                             source_transform.c + source_transform.a * w, source_transform.f)
            bounds = transform_bounds(crs, 3310, *source_bounds, densify_pts=21)
            raw = from_bounds(*bounds, transform=affine)
            left, top = max(0, math.floor(raw.col_off)), max(0, math.floor(raw.row_off))
            right = min(width, math.ceil(raw.col_off + raw.width))
            bottom = min(height, math.ceil(raw.row_off + raw.height))
            if right <= left or bottom <= top:
                continue
            window = Window(left, top, right - left, bottom - top)
            incoming = np.zeros((bottom - top, right - left), dtype='uint8')
            reproject(classify_reference(elevation), incoming, src_transform=source_transform,
                      src_crs=crs, dst_transform=window_transform(window, affine),
                      dst_crs='EPSG:3310', resampling=Resampling.nearest,
                      src_nodata=0, dst_nodata=0)
            merge_reference(result[top:bottom, left:right], incoming)
    return result, affine


def build(root=REPO, *, fetch=False, region='central-coast'):
    root = Path(root)
    config_path = root / 'catalog/seafloor-scope.json'
    config = read_json(config_path)
    ledger_path = root / 'dist/data/seafloor-ledger.json'
    if ledger_path.exists() and read_json(ledger_path)['stage'] != 'M1-reference-baseline':
        raise ValueError('Reference rebuild cannot overwrite a processed survey ledger')
    if region != config['id'] and region not in {r['id'] for r in config['regions']}:
        raise ValueError('Unknown seafloor region')
    # Rebuild the shared scope even when a regional ledger view is requested;
    # independently built geographic grids must never shift cell ownership.
    cache = root / 'var/seafloor/reference'
    cache.mkdir(parents=True, exist_ok=True)
    spine = reference.planning_spine(config, cache, fetch)
    reaches = make_reaches(config, spine)
    pin, tiles = reference.scheme_tiles(config, root, cache, fetch)
    sampled = reference.samples(tiles, cache, config['tile_sample_m'], fetch)
    input_document = {'config_sha256': sha256(config_path), 'scheme_sha256': pin['scheme_sha256'],
                      'rule_version': config['rule_version'],
                      'implementation_sha256': {name: sha256(Path(__file__).parent / name)
                                                for name in ('grid.py', 'reference.py', 'io.py')},
                      'requirements_sha256': sha256(root / 'requirements-survey.txt'),
                      'samples': [{'tile': t['id'], 'sha256': r['sample_sha256']}
                                  for t, (_, r) in zip(tiles, sampled)]}
    input_hash = hashlib.sha256(json.dumps(input_document, sort_keys=True).encode()).hexdigest()
    receipt_path = root / 'var/seafloor/reference/run.json'
    reaches_path = root / 'catalog/reaches.json'
    cells_path = root / 'var/seafloor/reference/cells.json'
    outputs = (ledger_path, reaches_path, cells_path)
    if receipt_path.exists():
        previous = read_json(receipt_path)
        if (previous.get('input_hash') == input_hash and all(p.exists() for p in outputs)
                and previous.get('output_hashes') == {p.name: sha256(p) for p in outputs}):
            return read_json(ledger_path), True
    mosaic, affine = mosaic_reference(config, tiles, sampled)
    band, unknown = cell_counts(mosaic, 10)
    row, col = np.nonzero(band)
    x = affine.c + (col + .5) * 250
    y = affine.f - (row + .5) * 250
    owners = assign_reaches(spine, reaches, x, y)
    lon, lat = Transformer.from_crs(3310, 4326, always_xy=True).transform(x, y)
    west, south, east, north = config['bounds']
    inside = (lon >= west) & (lon < east) & (lat >= south) & (lat < north) & (owners >= 0)
    cells = []
    for r, c, xx, yy, owner in zip(row[inside], col[inside], x[inside], y[inside], owners[inside]):
        cells.append({'id': f'3310:{math.floor(xx / 250)}:{math.floor(yy / 250)}',
                      'reach': reaches[owner]['id'], 'tier': 0,
                      'band_area_m2': int(band[r, c]) * 625,
                      'reference_unknown_area_m2': int(unknown[r, c]) * 625})
    by_reach = {r['id']: [] for r in reaches}
    for cell in cells:
        by_reach[cell['reach']].append(cell)
    records = []
    for reach in sorted(reaches, key=lambda r: r['order']):
        group = by_reach[reach['id']]
        area = sum(c['band_area_m2'] for c in group) / 1e6
        records.append({
            'id': reach['id'], 'region': reach['region'], 'order': reach['order'],
            'status': 'unassessed', 'cell_count': len(group), 'band_km2': area,
            'tier0_km2': area, 'tier1_km2': 0, 'tier2_km2': 0, 'tier3_km2': 0,
            'unknown_reference_within_band_cells_km2': sum(c['reference_unknown_area_m2'] for c in group) / 1e6,
            'polygons_by_grade': {'A': 0, 'B': 0, 'C': 0}, 'held_by_reason': {},
            'surveys_used': [], 'last_survey_run': 'unknown', 'habitat_rule_version': 'unknown',
            'note': 'Original surveys not processed; zero is pipeline progress, not evidence of a survey gap.',
        })
    sums = ('cell_count', 'band_km2', 'tier0_km2', 'tier1_km2', 'tier2_km2', 'tier3_km2',
            'unknown_reference_within_band_cells_km2')
    ledger = {
        'schema_version': 1, 'scope': config['id'], 'stage': 'M1-reference-baseline',
        'input_hash': input_hash, 'reference_rule_version': config['rule_version'],
        'reference': {
            'status': 'provisional', 'planning_limit_ft': 300, 'denominator_depth_m': [0, 100],
            'grid_crs': 'EPSG:3310', 'cell_size_m': 250, 'reference_pixel_m': 25,
            'requested_overview_spacing_m': config['tile_sample_m'],
            'source': 'NOAA BlueTopo', 'scheme_url': pin['scheme_url'],
            'scheme_sha256': pin['scheme_sha256'], 'tiles': tiles,
            'method': 'Nearest COG overview samples, classified at nominal -100 to <0 m elevation, nearest reprojected to 25 m; summed within disjoint 250 m cells. Fine valid reference wins; coarse fills remaining holes.',
            'limitations': [
                'Approximate reference area, not measured 0–300 ft coverage. Compilation interpolation and overview averaging are allowed only for this denominator.',
                'Source vertical datums may differ. No vertical conversion or original-contributor validation is claimed.',
                'Nodata remains unknown; missing reference water is not in the denominator. Unknown within boundary cells may include land.',
                'Tile source checksums are publisher identifiers, not verified full downloads. Cached overview samples have separate verified local checksums.',
                'Generalized coastline is an ownership spine only. Terminal endpoint projections are excluded. Region anchors are planning partitions, not legal boundaries.',
            ],
            'outside_reference_band_status': 'unknown',
            'coastline': config['coastline'],
        },
        'totals': {key: round(sum(r[key] for r in records), 6) for key in sums},
        'reaches': records,
    }
    catalog = {'schema_version': 1, 'scope': config['id'], 'grid_crs': 'EPSG:3310',
               'cell_size_m': 250, 'input_hash': input_hash,
               'planning_spine_3310': mapping(spine),
               'ownership': 'Nearest alongshore projection of cell center; half-open reach intervals; terminal projections excluded.',
               'source_config': 'catalog/seafloor-scope.json',
               'reaches': sorted(reaches, key=lambda r: r['order'])}
    atomic_json(reaches_path, catalog, indent=2)
    atomic_json(cells_path, {'input_hash': input_hash, 'cells': cells})
    atomic_json(ledger_path, ledger, indent=2)
    atomic_json(receipt_path, {'input_hash': input_hash, 'inputs': input_document,
                             'output_hashes': {p.name: sha256(p) for p in outputs}}, indent=2)
    return ledger, False
