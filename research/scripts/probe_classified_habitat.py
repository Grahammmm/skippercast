"""Bounded private proof of classified rugose rock beyond existing terrain patches.

Reuses a completed run and pinned depth/class sources. No new coverage, grades,
publication or fishing export is granted. Class 2 (mixed sediment/rock) remains
excluded from this narrow proof. This is not the production habitat extractor.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes, geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform
from rasterio.windows import Window, from_bounds
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import unary_union, transform

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor.coverage import cell_geometry
from skippercast.seafloor.io import sha256
from skippercast.seafloor.manifest import load_manifest
from skippercast.seafloor.normalized import verify_review
from skippercast.seafloor.resolution_profile import fine_detail_valid
from skippercast.seafloor.source_ingest import ingest
from skippercast.seafloor.substrate import resolve_bindings, verify_sources, class_reader
from skippercast.seafloor.screen import load_snapshot, exclusion_polygon


def candidate_mask(depth, valid, classes, inside):
    """Explicit interpreted rugose rock over valid nominal 25–300ft depth."""
    return (valid & inside & np.isfinite(depth) & (depth >= 7.62)
            & (depth <= 91.44) & (classes == 3))


def polygons(mask, affine):
    return [shape(g) for g, value in shapes(mask.astype('uint8'), mask=mask,
                                           transform=affine, connectivity=4) if value]


def components(geometry):
    if geometry.geom_type == 'Polygon':
        return [geometry]
    return [polygon for part in geometry.geoms
            if part.geom_type in {'Polygon','MultiPolygon','GeometryCollection'}
            for polygon in components(part)]


def probe(root, reach, source_id, output, *, edge=512, max_pixels=25_000_000):
    root, output = Path(root), Path(output)
    if not 16 <= edge <= 1024 or not 1 <= max_pixels <= 25_000_000:
        raise ValueError('Invalid bounded processing limit')
    folder = root/'var/seafloor/reaches'/reach
    run = read_json(folder/'run.json')
    for name in ('cells.json', 'candidates.geojson'):
        if run['outputs'][name] != sha256(folder/name):
            raise ValueError('Completed physical output hash mismatch')
    manifest = load_manifest(root)
    row = next(s for s in manifest['surveys'] if s['id'] == source_id)
    if (row['status'] != 'usable' or row.get('habitat_quality_hold') or row.get('terrain_support')
            or row not in run['inputs']['sources']):
        raise ValueError('Proof requires an unchanged qualified depth source without terrain holds')
    binding = resolve_bindings(read_json(root/'catalog/habitat-rules.json'), manifest).get(source_id)
    if binding is None or binding != run['inputs']['substrate_bindings'].get(source_id):
        raise ValueError('No unchanged reviewed classification binding')
    verify_sources({source_id: binding}, root=root)
    receipt, _, _ = ingest(row, row['adapter_review']['requested_bounds_wgs84'], root=root, fetch=False)
    cache = root/'var/seafloor/cache'/row['sha256']
    paths = sorted(p.with_suffix('.tif') for p in cache.glob('*.json')
                   if read_json(p).get('cog_sha256') == receipt['cog_sha256'] and p.with_suffix('.tif').exists())
    if not paths:
        raise ValueError('Missing verified normalized source')
    path = paths[0]
    if sha256(path) != receipt['cog_sha256']:
        raise ValueError('Depth cache hash mismatch')
    verify_review(receipt, row['adapter_review'], path)
    cells = read_json(folder/'cells.json')['cells']
    support = unary_union([cell_geometry(c) for c in cells if c['tier'] == 1 and c['source_id'] == source_id])
    if support.is_empty:
        raise ValueError('No qualifying selected source cells')
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    to_geo = Transformer.from_crs(3310, 4326, always_xy=True).transform
    existing = unary_union([transform(project, shape(f['geometry']))
                            for f in read_json(folder/'candidates.geojson')['features']])
    pieces, pixels = [], 0
    with rasterio.open(path) as original:
        affine, width, height = calculate_default_transform(original.crs, 3310,
            original.width, original.height, *original.bounds, resolution=row['resolution_m'])
        with WarpedVRT(original, crs='EPSG:3310', transform=affine, width=width, height=height,
                       resampling=Resampling.nearest, nodata=np.nan) as vrt:
            window = from_bounds(*support.bounds, transform=affine).round_offsets().round_lengths()
            window = window.intersection(Window(0, 0, width, height))
            if window.width*window.height > max_pixels:
                raise ValueError('Proof window exceeds pixel bound; choose a smaller reach/source')
            with class_reader(binding, (height, width), affine, root=root) as read:
                for y in range(int(window.row_off), int(window.row_off+window.height), edge):
                    for x in range(int(window.col_off), int(window.col_off+window.width), edge):
                        tile = Window(x, y, min(edge, window.col_off+window.width-x),
                                      min(edge, window.row_off+window.height-y))
                        data = vrt.read(1, window=tile, masked=True).astype('float32')
                        depth = data.filled(np.nan)
                        valid = fine_detail_valid(depth, ~np.ma.getmaskarray(data) & np.isfinite(depth), row)
                        tr = vrt.window_transform(tile)
                        inside = geometry_mask([mapping(support)], depth.shape, tr, invert=True)
                        mask = candidate_mask(depth, valid, read(tile), inside)
                        pixels += int(mask.sum())
                        pieces.extend(polygons(mask, tr))
                        if len(pieces) > 100_000:
                            raise ValueError('Proof polygon budget exceeded; use a smaller window')
    # Dissolving tile-edge fragments before minimum area prevents artificial splits.
    classified = unary_union(pieces).intersection(support)
    additional = classified.difference(existing)
    patches = [p for p in components(additional) if p.area >= 1000]
    state = load_snapshot(root, reach)
    restrictions = [(s['id'], unary_union([transform(project, exclusion_polygon(f['geometry']))
                     for f in s['features']])) for s in state['layers']] if state['status'] == 'ready' else []
    features, spatial_eligible = [], []
    for index, patch in enumerate(patches):
        geo = transform(to_geo, patch)
        reasons = list(state['reasons'])
        if state['status'] == 'ready':
            if not shape(state['scope']).covers(geo):
                reasons.append('screen-outside-coverage')
            reasons.extend('overlap-'+name for name, exclusion in restrictions if patch.intersects(exclusion))
        if not reasons:
            spatial_eligible.append(patch)
        features.append({'type': 'Feature', 'geometry': mapping(geo), 'properties': {
            'id': f'private-classified-{reach}-{index}', 'publication_prohibited': True,
            'exportable': False, 'terrain_grade': 'unknown', 'species_fit': 'unranked',
            'source_id': source_id, 'classification_source_id': binding['row']['id'],
            'basis': 'Original interpreted rugose rock/boulder class over valid nominal depth; no terrain rank or fish presence inferred.',
            'screen_reasons': reasons, 'area_m2': patch.area}})
    atomic_json(output/'private-classified-candidates.geojson', {'type':'FeatureCollection','features':features})
    report = {'version': 1, 'reach': reach, 'depth_source_id': source_id,
        'depth_source_sha256': row['sha256'], 'classification_source_id': binding['row']['id'],
        'classification_source_sha256': binding['row']['sha256'],
        'baseline_run_sha256': sha256(folder/'run.json'), 'read_pixel_limit': max_pixels,
        'tile_edge': edge, 'polygon_fragment_limit':100_000, 'class3_valid_depth_pixels': pixels,
        'class3_valid_selected_area_km2': classified.area/1e6,
        'outside_existing_physical_area_km2': additional.area/1e6,
        'additional_private_patches': len(patches),
        'preliminary_spatial_eligible_patches':len(spatial_eligible),
        'preliminary_spatial_eligible_area_km2':sum(p.area for p in spatial_eligible)/1e6,
        'screen_status':state['status'], 'new_measured_area_km2':0, 'published_locations':0,
        'publication_prohibited':True, 'exportable':False,
        'geometry_sha256':sha256(output/'private-classified-candidates.geojson'),
        'next_step':'Independently review original class semantics and depth masks, then implement a separate unranked classified-habitat admission path with current full-polygon screening. This probe cannot publish.'}
    atomic_json(output/'proof.json', report, indent=2)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root','reach','source','output'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--edge', type=int, default=512)
    parser.add_argument('--max-pixels', type=int, default=25_000_000)
    args = parser.parse_args()
    print(json.dumps(probe(args.root,args.reach,args.source,args.output,
                           edge=args.edge,max_pixels=args.max_pixels),indent=2))
