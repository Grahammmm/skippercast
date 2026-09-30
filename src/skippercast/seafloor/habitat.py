"""Deterministic rough-bottom candidates, held until the separate legal screen.

Each source is processed separately at its native spacing: neither a source
offset nor its no-data edge can become a false reef. The bounded reach window
fails explicitly above 20 million pixels instead of silently downsampling.
"""
import hashlib
import math

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes, geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform
from rasterio.windows import from_bounds, Window
from scipy.ndimage import binary_closing, label, find_objects
import shapely
from shapely.geometry import shape, mapping
from shapely.ops import transform, unary_union
from pyproj import Transformer

from skippercast.atlas.scoring import habitat_score, habitat_grade
from skippercast.platform.contracts import public_url
from .coverage import cell_geometry
from .resolution_profile import fine_detail_valid
from .substrate import read_classes
from .terrain import derivatives


def validate_rules(rules):
    def band(value):
        return (isinstance(value, list) and len(value) == 2
                and all(type(x) in (float, int) and math.isfinite(x) for x in value)
                and 0 <= value[0] < value[1])
    if (not rules['rule_version'] or not band(rules['depth_m'])
            or rules['depth_m'][1] > 91.44 or not 0 < rules['vrm_percentile'] < 100
            or not 0 < rules['metric_minimum_support_fraction'] <= 1
            or rules['minimum_patch_m2'] < 1000
            or rules['vrm_zero_epsilon'] <= 0 or rules['bpi_zero_epsilon_m'] <= 0):
        raise ValueError('Invalid habitat rule bounds')
    for species in rules['species'].values():
        if not band(species['planning_depth_m']) or not species['evidence'] or not species['evidence_scope']:
            raise ValueError('Species depth band requires bounded cited evidence')
        public_url(species['source_url'])
    return rules


def source_grid(source, cells, binding, *, root):
    selected = [cell_geometry(c) for c in cells if c['tier'] == 1
                and c['source_id'] == source['row']['id']]
    if not selected:
        return None
    support = unary_union(selected).intersection(source['geometry'])
    with rasterio.open(source['path']) as original:
        affine, width, height = calculate_default_transform(original.crs, 3310,
            original.width, original.height, *original.bounds, resolution=source['row']['resolution_m'])
        with WarpedVRT(original, crs='EPSG:3310', transform=affine, width=width,
                height=height, resampling=Resampling.nearest, nodata=np.nan) as vrt:
            window = from_bounds(*support.buffer(255).bounds, transform=affine).round_offsets().round_lengths()
            window = window.intersection(Window(0, 0, width, height))
            if window.width*window.height > 20_000_000:
                raise ValueError('Habitat window exceeds 20 million pixels; split the reach, never downsample')
            data = vrt.read(1, window=window, masked=True).astype('float32')
            affine = vrt.window_transform(window)
    depth = data.filled(np.nan)
    if min(depth.shape) < 3:
        return None
    valid = ~np.ma.getmaskarray(data) & np.isfinite(depth)
    valid = fine_detail_valid(depth, valid, source['row'])
    depth = np.where(valid, depth, np.nan)
    inside = geometry_mask([mapping(support)], depth.shape, affine, invert=True) & valid
    terrain = derivatives(depth, valid, source['row']['resolution_m'])
    # Keep only the two extraction layers after computing the shared derivatives.
    terrain = {key: terrain[key].astype('float32') for key in ('vrm', 'bpi_fine_m')}
    classes = read_classes(binding, depth.shape, affine, root=root)
    return {'depth': depth, 'valid': valid, 'inside': inside, 'terrain': terrain,
            'classes': classes, 'affine': affine, 'support': support,
            'source': source, 'binding': binding}


def thresholds(grids, rules):
    result = {}
    for key in ('vrm', 'bpi_fine_m'):
        samples = [g['terrain'][key][g['inside'] & np.isfinite(g['terrain'][key])
                    & (g['depth'] > 0) & (g['depth'] <= 91.44)] for g in grids]
        values = np.concatenate(samples) if samples else np.array([])
        result[key+'_samples'] = int(values.size)
        result[key] = (float(np.percentile(values, rules['vrm_percentile'])) if key == 'vrm'
                       else float(np.std(values, dtype='float64'))) if values.size else 'unknown'
    return result


def rough_mask(depth, valid, inside, terrain, classes, limits, rules):
    eligible = (valid & inside & (depth >= rules['depth_m'][0])
                & (depth <= rules['depth_m'][1]) & (classes != 1))
    rough = np.zeros(depth.shape, bool)
    if limits['vrm'] != 'unknown':
        # A mathematically flat plane has percentile 0: >=0 must not call it reef.
        rough |= (terrain['vrm'] >= limits['vrm']) & (terrain['vrm'] > rules['vrm_zero_epsilon'])
    if limits['bpi_fine_m'] != 'unknown':
        rough |= terrain['bpi_fine_m'] > max(limits['bpi_fine_m'], rules['bpi_zero_epsilon_m'])
    rough &= eligible
    closed = binary_closing(rough, structure=np.ones((3, 3)))
    # Closing may fill a one-pixel gap, but never a missing-depth/soft/out-of-band pixel.
    return (rough | closed) & eligible


def species_fit(minimum_m, maximum_m, grade, species):
    low, high = species['planning_depth_m']
    if low <= minimum_m <= maximum_m <= high and grade in {'A', 'B'}:
        return 3
    if maximum_m >= low and minimum_m <= high:
        return 2
    return 1


def polygonal(geometry):
    """Discard collapsed lines from topology repairs; never buffer missing area."""
    if geometry.geom_type == 'Polygon':
        return geometry
    return unary_union([polygonal(part) for part in geometry.geoms
                        if part.geom_type in {'Polygon', 'MultiPolygon', 'GeometryCollection'}])


def patch_metrics(grid, point, rough, rules):
    """Original atlas metrics, explicit neighborhood sizes and support fraction.

    210/250 m squares are total widths; rough area uses a 250 m radius.
    Grading is withheld below 80% valid depth support in either square.
    Rugose fraction uses reviewed class 3 where known, terrain where unknown.
    """
    col, row = (~grid['affine'])*(point.x, point.y)
    radius = math.ceil(250/grid['source']['row']['resolution_m'])+1
    iy, ix = int(row), int(col)
    ys = slice(max(0, iy-radius), min(grid['depth'].shape[0], iy+radius+1))
    xs = slice(max(0, ix-radius), min(grid['depth'].shape[1], ix+radius+1))
    yy, xx = np.indices(grid['depth'][ys, xs].shape)
    x, y = grid['affine']*(xx+xs.start+.5, yy+ys.start+.5)
    x, y = x-point.x, y-point.y
    depth, valid = grid['depth'][ys, xs], grid['valid'][ys, xs]
    resolution = grid['source']['row']['resolution_m']
    small = (np.abs(x) <= 105) & (np.abs(y) <= 105)
    large = (np.abs(x) <= 125) & (np.abs(y) <= 125)
    # Compare to the full requested area, including data outside the read window.
    support = min(1., (valid & small).sum()*resolution**2/210**2,
                         (valid & large).sum()*resolution**2/250**2)
    if support < rules['metric_minimum_support_fraction'] or (valid & large).sum() < 20:
        return None, float(support)
    fit = valid & large
    matrix = np.column_stack((x[fit], y[fit], np.ones(fit.sum())))
    coefficients = np.linalg.lstsq(matrix, depth[fit], rcond=None)[0]
    residual = depth[fit]-matrix@coefficients
    classes = grid['classes'][ys, xs]
    hard = np.where(classes > 0, classes == 3, rough[ys, xs])
    values = depth[valid & small]
    metrics = {'relief_210m_m': float(np.ptp(values)),
        'rugose_or_bedrock_fraction_210m': float(hard[valid & small].mean()),
        'plane_residual_rms_250m_m': float(np.sqrt(np.mean(residual**2))),
        'rough_habitat_within_250m_ha': float((rough[ys, xs] & (x*x+y*y <= 250**2)).sum()*resolution**2/10000)}
    score = habitat_score(metrics)
    return {**metrics, 'score': score, 'grade': habitat_grade(score)}, float(support)


def extract_grid(grid, limits, rules, reach):
    rough = rough_mask(grid['depth'], grid['valid'], grid['inside'], grid['terrain'],
                       grid['classes'], limits, rules)
    labels, _ = label(rough, structure=np.ones((3, 3)))
    slices = find_objects(labels)
    counts = np.bincount(labels.ravel())
    source = grid['source']['row']
    resolution = source['resolution_m']
    kept = {i for i, count in enumerate(counts) if i and count*resolution**2 >= rules['minimum_patch_m2']}
    polygons = {}
    for geometry, ident in shapes(labels.astype('int32'), mask=np.isin(labels, list(kept)),
                                   transform=grid['affine'], connectivity=8):
        polygons[int(ident)] = shapely.make_valid(shape(geometry))
    to_geo = Transformer.from_crs(3310, 4326, always_xy=True).transform
    features = []
    for ident, polygon in sorted(polygons.items()):
        polygon = polygon.intersection(grid['support'])
        # The outline cannot gain unsupported area through simplification.
        polygon = polygon.simplify(resolution/2, preserve_topology=True).intersection(polygon)
        polygon = polygonal(shapely.make_valid(polygon))
        if polygon.area < rules['minimum_patch_m2']:
            continue
        ys, xs = slices[ident-1]
        mask = labels[ys, xs] == ident
        depths = grid['depth'][ys, xs][mask]
        metrics, support = patch_metrics(grid, polygon.representative_point(), rough, rules)
        binding = grid['binding']
        categories = grid['classes'][ys, xs][mask]
        fit = {key: species_fit(float(depths.min()), float(depths.max()), metrics['grade'], value)
               if metrics else 'unknown' for key, value in rules['species'].items()}
        ident_hash = hashlib.sha256(source['id'].encode()+shapely.normalize(polygon).wkb).hexdigest()[:16]
        properties = {'id': f"sc-hab-{reach['id']}-{ident_hash}", 'reach': reach['id'],
            'region': reach.get('region', 'unknown'), 'tier': 1, 'status': 'held',
            'hold_reasons': ['legal-screen-pending'] + ([] if metrics else ['metric-support-incomplete']),
            'exportable': False, 'area_ha': polygon.area/10000, 'source_ids': [source['id']],
            'source_year': source['year'], 'resolution_m': resolution,
            'vertical_datum': source['vertical_datum'], 'depth_basis': 'nominal',
            'depth_min_ft': float(depths.min())/.3048, 'depth_max_ft': float(depths.max())/.3048,
            'interpolation_mask': 'unknown', 'terrain': metrics or 'unknown',
            'metric_support_fraction': support, 'fit': fit,
            'substrate': {'source_id': binding['row']['id'] if binding else 'unknown',
                'same_survey_as_depth': binding['binding']['same_survey_as_depth'] if binding else 'unknown',
                'known_fraction': float((categories > 0).mean()),
                'hard_rugose_fraction': float((categories == 3).mean()),
                'independent_confirmation': False},
            'independent_evidence': [], 'screen': {'status': 'pending'},
            'rule_version': rules['rule_version'],
            'label': f"Held: legal screen pending. Habitat candidate; nominal depth ({source['vertical_datum']}); verify on your sounder."
                     + (' Broad area, not an individual pile.' if resolution > 4 else '')}
        # Projected point-touching components can acquire rounding intersections
        # in longitude/latitude. Repair again in the output CRS without buffering.
        geographic = polygonal(shapely.make_valid(transform(to_geo, polygon)))
        features.append({'type': 'Feature', 'properties': properties, 'geometry': mapping(geographic)})
    return features


def build_candidates(sources, cells, bindings, rules, reach, *, root):
    grids = []
    for source in sources:
        grid = source_grid(source, cells, bindings.get(source['row']['id']), root=root)
        if grid:
            grids.append(grid)
    limits = thresholds(grids, rules)
    features = [feature for grid in grids for feature in extract_grid(grid, limits, rules, reach)]
    selected = [(g['source']['row']['id'], g['support']) for g in grids]
    seams = [{'source_ids': [a, b], 'shared_selected_boundary_m': ga.boundary.intersection(gb.boundary).length,
              'distance_m': ga.distance(gb)} for i, (a, ga) in enumerate(selected) for b, gb in selected[i+1:]]
    return {'type': 'FeatureCollection', 'features': features,
            'rule_version': rules['rule_version'], 'thresholds': limits, 'survey_seams': seams,
            'status': 'held-for-legal-screen', 'exportable': False}


def compare_atlas(atlas, candidates, scope, coverage=None):
    """Compare area outlines, never pretend the atlas's point count is polygon count."""
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    generated = unary_union([transform(project, shape(f['geometry'])) for f in candidates['features']])
    results = []
    for area in atlas.get('areas', []):
        original = transform(project, shape(area['geometry'])).intersection(scope)
        if original.is_empty or original.area <= 0:
            continue
        fraction = generated.intersection(original).area/original.area
        surveyed = coverage.intersection(original).area/original.area if coverage is not None else None
        results.append({'id': area['id'], 'target_ids': area.get('target_ids', []),
                        'overlap_fraction': fraction, 'reproduced': fraction >= .5,
                        'survey_coverage_fraction': surveyed if surveyed is not None else 'unknown',
                        'difference': 'reproduced' if fraction >= .5 else
                            'coverage-incomplete' if surveyed is not None and surveyed < .95 else
                            'roughness-substrate-or-minimum-patch-rule'})
    return {'atlas_target_count': len(atlas.get('targets', [])), 'atlas_outline_count': len(atlas.get('areas', [])),
            'applicable_outline_count': len(results), 'reproduced_count': sum(r['reproduced'] for r in results),
            'threshold': .5, 'denominator': 'Original outline portion inside this reach; missing survey coverage counts as a miss.',
            'areas': results}
