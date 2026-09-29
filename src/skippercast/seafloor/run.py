"""M3 original survey coverage, terrain and held habitat candidates."""
from datetime import datetime, timezone
import hashlib
import json
from time import monotonic
from pathlib import Path
from contextlib import ExitStack

import numpy as np
import shapely
from pyproj import Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform
from rasterio.windows import from_bounds
from shapely.geometry import box
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import REPO, atomic_json, read_json
from .coverage import cell_geometry, classify_cells, footprint
from .ingest import ingest
from .io import sha256
from .manifest import load_manifest
from .terrain import derivatives, summarize
from .habitat import build_candidates, compare_atlas, validate_rules
from .substrate import resolve_bindings, verify_sources
from .screen import load_snapshot, input_identity, screen_candidates
from .resolution_profile import fine_detail_valid

VERSION = 'native-coverage-habitat-v1'


def terrain_cells(cells, sources):
    result = []
    footprints = {s['row']['id']: s['geometry'] for s in sources}
    with ExitStack() as stack:
        readers = {}
        for source in sources:
            row = source['row']
            original = stack.enter_context(rasterio.open(source['path']))
            affine, width, height = calculate_default_transform(
                original.crs, 3310, original.width, original.height, *original.bounds,
                resolution=row['resolution_m'])
            vrt = stack.enter_context(WarpedVRT(original, crs='EPSG:3310', transform=affine,
                width=width, height=height, resampling=Resampling.nearest, nodata=np.nan))
            readers[row['id']] = (vrt, row)
        for cell in cells:
            if cell['tier'] != 1:
                continue
            source, row = readers[cell['source_id']]
            square = cell_geometry(cell)
            # Extra pixels support broad BPI without trusting clipped borders.
            window = from_bounds(*square.buffer(104).bounds, transform=source.transform).round_offsets().round_lengths()
            window = window.intersection(rasterio.windows.Window(0, 0, source.width, source.height))
            data = source.read(1, window=window, masked=True).astype('float64')
            depth = data.filled(np.nan)
            if min(depth.shape) < 3:
                continue
            valid = ~np.ma.getmaskarray(data) & np.isfinite(depth)
            valid = fine_detail_valid(depth, valid, row)
            depth = np.where(valid, depth, np.nan)
            yy, xx = np.indices(depth.shape)
            affine = source.window_transform(window)
            x, y = affine * (xx+.5, yy+.5)
            w, s, e, n = square.bounds
            inside = (x >= w) & (x < e) & (y >= s) & (y < n) & valid & (depth > 0) & (depth <= 91.44)
            inside &= shapely.contains_xy(footprints[cell['source_id']], x, y)
            summary = summarize(derivatives(depth, valid, source.res[0]), inside)
            result.append({'cell_id': cell['id'], 'source_id': cell['source_id'],
                           'resolution_m': source.res[0], 'terrain': summary})
    return result


def apply_ledger(root, reach_id, summary):
    path = root / 'dist/data/seafloor-ledger.json'
    ledger = read_json(path)
    for row in ledger['reaches']:
        row.setdefault('selected_valid_km2', 0)
        if row['id'] == reach_id:
            row.update(summary)
    ledger['stage'] = 'M3-habitat-screen'
    ledger['reference_cells_sha256'] = sha256(root / 'var/seafloor/reference/cells.json')
    ledger['coverage_method'] = (
        'Tier 1 credits the provisional reference-band area in cells where one usable original source '
        'covers at least 25% of the full 250 m square at nominal 0–300 ft. '
        'It is a cell classification, not a claim that the entire credited area is surveyed. '
        'selected_valid_km2 separately sums selected native footprint intersections. '
        'Known filled pixels are excluded; absent producer interpolation masks remain unknown. '
        'Tier 2 measures the deduplicated footprint of graded habitat polygons passing a current '
        'whole-polygon spatial restriction screen. It is a subset of mapped cells, not additional surveyed area.')
    keys = list(ledger['totals']) + ([] if 'selected_valid_km2' in ledger['totals'] else ['selected_valid_km2'])
    ledger['totals'] = {key: round(sum(r[key] for r in ledger['reaches']), 6) for key in keys}
    atomic_json(path, ledger, indent=2)


def run(reach_id, *, root=REPO, force=False, fetch=False):
    started = monotonic()
    root = Path(root)
    catalog = read_json(root / 'catalog/reaches.json')
    reach = next((r for r in catalog['reaches'] if r['id'] == reach_id), None)
    if reach is None:
        raise ValueError('Unknown reach')
    baseline_path = root / 'var/seafloor/reference/cells.json'
    baseline = read_json(baseline_path)
    reference_receipt = read_json(root / 'var/seafloor/reference/run.json')
    if (baseline['input_hash'] != catalog['input_hash']
            or reference_receipt['input_hash'] != catalog['input_hash']
            or reference_receipt['output_hashes']['cells.json'] != sha256(baseline_path)):
        raise ValueError('Reference grid does not match verified baseline')
    cells = [c for c in baseline['cells'] if c['reach'] == reach_id]
    scope = unary_union([cell_geometry(c) for c in cells])
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    sources = []
    manifest = load_manifest(root)
    for row in manifest['surveys']:
        if row['status'] != 'usable' or row['kind'] != 'bathymetry':
            continue
        bounds = row['adapter_review']['requested_bounds_wgs84']
        if not transform(project, box(*bounds)).intersects(scope):
            continue
        receipt, _, _ = ingest(row, bounds, root=root, fetch=fetch)
        if receipt['cog_sha256'] != row['adapter_review']['cog_sha256']:
            raise ValueError('Normalized source differs from reviewed manifest')
        folder = root / 'var/seafloor/cache' / row['sha256']
        paths = [p.with_suffix('.tif') for p in folder.glob('*.json')
                 if read_json(p).get('cog_sha256') == receipt['cog_sha256']
                 and p.with_suffix('.tif').exists()]
        if not paths:
            raise ValueError('Reviewed normalized source not found')
        selected_path = sorted(paths)[0]
        if sha256(selected_path) != receipt['cog_sha256']:
            raise ValueError('Selected normalized COG failed hash verification')
        sources.append({'row': row, 'path': selected_path, 'receipt': receipt})
    rules = validate_rules(read_json(root / 'catalog/habitat-rules.json'))
    bindings = resolve_bindings(rules, manifest)
    source_ids = {s['row']['id'] for s in sources}
    bindings = {key: value for key, value in bindings.items() if key in source_ids}
    verify_sources(bindings, root=root, fetch=fetch)
    atlas_path = root / 'dist/data/atlas.json'
    screen = load_snapshot(root, reach_id)
    inputs = {'rule_version': VERSION, 'reach_id': reach_id,
              'reference_cells_sha256': sha256(baseline_path),
              'reaches_sha256': sha256(root / 'catalog/reaches.json'),
              'sources': [s['row'] for s in sources],
              'habitat_rules': rules, 'substrate_bindings': bindings,
              'screen': input_identity(screen),
              'atlas_sha256': sha256(atlas_path),
              'scoring_sha256': sha256(Path(__file__).parents[1] / 'atlas/scoring.py'),
              'requirements_sha256': sha256(root / 'requirements-survey.txt'),
              'implementation': {n: sha256(Path(__file__).parent / n)
                                 for n in ('coverage.py', 'terrain.py', 'run.py', 'habitat.py', 'substrate.py',
                                           'screen.py', 'resolution_profile.py')}}
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    folder = root / 'var/seafloor/reaches' / reach_id
    receipt_path = folder / 'run.json'
    outputs = [folder / name for name in ('cells.json', 'terrain.json', 'habitat.geojson', 'atlas-comparison.json',
                                        'held.geojson', 'candidates.geojson')]
    if receipt_path.exists() and not force:
        previous = read_json(receipt_path)
        if previous['input_hash'] == digest and all(p.exists() for p in outputs):
            if previous['outputs'] != {p.name: sha256(p) for p in outputs}:
                raise ValueError('Reach outputs failed hash verification')
            apply_ledger(root, reach_id, previous['ledger_summary'])
            return previous, True
    coverage_started = monotonic()
    for source in sources:
        source['geometry'] = footprint(source['path'], source['receipt']['requested_bounds_wgs84'], clip=scope)
    classified = classify_cells(cells, sources)
    coverage_seconds = monotonic() - coverage_started
    terrain_started = monotonic()
    terrain = terrain_cells(classified, sources)
    terrain_seconds = monotonic() - terrain_started
    habitat_started = monotonic()
    candidates = build_candidates(sources, classified, bindings, rules, reach, root=root)
    selected_coverage = unary_union([source['geometry'].intersection(unary_union([
        cell_geometry(c) for c in classified if c['tier'] == 1 and c['source_id'] == source['row']['id']]))
        for source in sources])
    comparison = compare_atlas(read_json(atlas_path), candidates, scope, selected_coverage)
    habitat, held, screened = screen_candidates(candidates, screen)
    habitat_seconds = monotonic() - habitat_started
    tier1 = sum(c['band_area_m2'] for c in classified if c['tier'] == 1)/1e6
    band = sum(c['band_area_m2'] for c in classified)/1e6
    used = sorted({c['source_id'] for c in classified if c['source_id'] != 'unknown'})
    summary = {'status': 'habitat-screened' if screen['status'] == 'ready' else 'habitat-held-for-screen', 'tier0_km2': round(band-tier1, 9),
        'tier1_km2': round(tier1, 9), 'tier2_km2': 0, 'tier3_km2': 0,
        'selected_valid_km2': round(sum(c['valid_area_m2'] for c in classified)/1e6, 9),
        'surveys_used': used, 'last_survey_run': datetime.now(timezone.utc).isoformat(),
        'coverage_rule_version': VERSION, 'survey_run_hash': digest,
        **screened,
        'habitat_rule_version': rules['rule_version'], 'roughness_thresholds': candidates['thresholds'],
        'atlas_comparison': {key: value for key, value in comparison.items() if key != 'areas'},
        'note': 'Original survey coverage and ranked habitat candidates. Full polygons screened against dated spatial '
                'restrictions; missing evidence or overlaps held. Publication remains M4. '
                'Season, gear and current notices still apply. Unknown interpolation masks remain unknown.'}
    atomic_json(outputs[0], {'reach': reach_id, 'input_hash': digest, 'cells': classified})
    atomic_json(outputs[1], {'reach': reach_id, 'input_hash': digest, 'cells': terrain,
        'method': 'Nearest native-spacing projection into EPSG:3310 for derivatives; no cross-source blending. '
                  '3x3 VRM; BPI square windows approximate 25/100 m radii. Full valid neighborhoods required.'})
    atomic_json(outputs[2], habitat)
    atomic_json(outputs[3], comparison)
    atomic_json(outputs[4], held)
    atomic_json(outputs[5], candidates)
    receipt = {'input_hash': digest, 'inputs': inputs, 'ledger_summary': summary,
               'timings_seconds': {'coverage': coverage_seconds, 'terrain': terrain_seconds, 'habitat': habitat_seconds,
                                   'total': monotonic() - started},
               'outputs': {p.name: sha256(p) for p in outputs},
               'source_receipts': [s['receipt'] for s in sources]}
    atomic_json(receipt_path, receipt, indent=2)
    apply_ledger(root, reach_id, summary)
    return receipt, False
