"""Explicit opt-in orchestration for isolated noncentral reference scopes."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from pyproj import Transformer
from rasterio.transform import Affine
from shapely.geometry import mapping

from skippercast.platform.contracts import REPO, atomic_json, read_json
from . import reference
from .grid import assign_reaches, cell_counts, make_reaches, mosaic_reference
from .io import sha256
from .scope_paths import resolve_scope

def build(root=REPO, *, fetch=False, region=None, scope_config=None, scope_id=None):
    root = Path(root).resolve()
    if scope_config is None:
        raise ValueError('Scoped grid construction requires an explicit scope config')
    config, paths = resolve_scope(root, scope_config=scope_config, scope_id=scope_id)
    if paths.is_central_default:
        raise ValueError('Use the retained central grid builder for the Central Coast scope')
    config_path = paths.config_path
    ledger_path = paths.ledger_path
    region = region or config['id']
    if ledger_path.exists() and read_json(ledger_path)['stage'] != 'M1-reference-baseline':
        raise ValueError('Reference rebuild cannot overwrite a processed survey ledger')
    if region != config['id'] and region not in {r['id'] for r in config['regions']}:
        raise ValueError('Unknown seafloor region')
    # Rebuild the shared scope even when a regional ledger view is requested;
    # independently built geographic grids must never shift cell ownership.
    cache = paths.reference_dir
    cache.mkdir(parents=True, exist_ok=True)
    spine = reference.planning_spine(config, cache, fetch)
    reaches = make_reaches(config, spine)
    pin, tiles = reference.scheme_tiles(config, root, cache, fetch)
    sampled = reference.samples(tiles, cache, config['tile_sample_m'], fetch)
    input_document = {'config_sha256': sha256(config_path), 'scheme_sha256': pin['scheme_sha256'],
                      'rule_version': config['rule_version'],
                      'implementation_sha256': {name: sha256(Path(__file__).parent / name)
                                                for name in ('scoped_grid.py', 'grid.py', 'reference.py', 'io.py', 'scope_paths.py')},
                      'requirements_sha256': sha256(root / 'requirements-survey.txt'),
                      'samples': [{'tile': t['id'], 'sha256': r['sample_sha256']}
                                  for t, (_, r) in zip(tiles, sampled)]}
    input_hash = hashlib.sha256(json.dumps(input_document, sort_keys=True).encode()).hexdigest()
    receipt_path = paths.build_receipt_path
    reaches_path = paths.reaches_path
    cells_path = paths.cells_path
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
               'source_config': config_path.relative_to(root).as_posix(),
               'reaches': sorted(reaches, key=lambda r: r['order'])}
    atomic_json(reaches_path, catalog, indent=2)
    atomic_json(cells_path, {'input_hash': input_hash, 'cells': cells})
    atomic_json(ledger_path, ledger, indent=2)
    atomic_json(receipt_path, {'input_hash': input_hash, 'inputs': input_document,
                             'output_hashes': {p.name: sha256(p) for p in outputs}}, indent=2)
    return ledger, False
