"""Private native-cell panels for source-bound terrain review, never publication.

Read existing physical candidates and checked originals; do not recompute ranks,
modify masks, clear holds or infer substrate from a rough-terrain interpretation.
Requires the seafloor runtime plus optional matplotlib (audited with 3.10.6).
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from shapely.geometry import shape
from shapely.ops import transform

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor.io import sha256
from skippercast.seafloor.normalized import verify_review
from skippercast.seafloor.terrain_support import native_reader, classify


def source_object(root, row):
    folder = root/'var/seafloor/cache'/row['sha256']
    for path in sorted(folder.glob('*.json')):
        receipt = read_json(path)
        if (receipt.get('source_id') != row['id']
                or receipt.get('requested_bounds_wgs84') != row['adapter_review']['requested_bounds_wgs84']
                or not path.with_suffix('.tif').is_file()):
            continue
        raster = path.with_suffix('.tif')
        if sha256(raster) != receipt['cog_sha256']:
            raise ValueError('Stored COG differs from receipt')
        verify_review(receipt, row['adapter_review'], raster)
        return {'row': row, 'path': raster, 'receipt': receipt}
    raise ValueError('Checked normalized raster unavailable: '+row['id'])


def window_for(bounds, dataset):
    raw = from_bounds(*bounds, transform=dataset.transform)
    x0, y0 = max(0, int(np.floor(raw.col_off))), max(0, int(np.floor(raw.row_off)))
    x1 = min(dataset.width, int(np.ceil(raw.col_off+raw.width)))
    y1 = min(dataset.height, int(np.ceil(raw.row_off+raw.height)))
    if x1 <= x0 or y1 <= y0 or (x1-x0)*(y1-y0) > 8_000_000:
        raise ValueError('Empty or oversized diagnostic native window')
    return Window(x0, y0, x1-x0, y1-y0)


def audit(root, reaches, source_ids, output, halo_m=120, stage='private', panel_limit=None):
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError('Keep prior audits; choose a new output directory')
    output.mkdir(parents=True)
    rows = {r['id']: r for r in read_json(root/'catalog/surveys.json')['surveys']}
    features, inputs = [], {}
    for reach in reaches:
        folder = root/'var/seafloor'/('private-reaches' if stage == 'private' else 'reaches')/reach
        run = read_json(folder/'run.json')
        path = folder/'candidates.geojson'
        if sha256(path) != run['outputs']['candidates.geojson']:
            raise ValueError('Candidate file differs from retained physical receipt')
        inputs[reach] = {'run_sha256': sha256(folder/'run.json'),
                         'candidates_sha256': sha256(path), 'input_hash': run['input_hash']}
        features += [f for f in read_json(path)['features']
                     if set(f['properties']['source_ids']) & set(source_ids)]
    features.sort(key=lambda f: (f['properties']['source_ids'], -f['properties']['area_ha']))
    if panel_limit is not None and panel_limit < 1:
        raise ValueError('Panel limit must be positive')
    panel_indices = set(np.linspace(0, len(features)-1,
        min(panel_limit or len(features), len(features))).astype(int)) if features else set()
    results, pages = [], []
    with ExitStack() as stack:
        datasets = {}
        for source_id in source_ids:
            source = source_object(root, rows[source_id])
            datasets[source_id] = (stack.enter_context(rasterio.open(source['path'])),
                                  stack.enter_context(native_reader(source, root=root)))
        figure = None; panel_number = 0
        for index, feature in enumerate(features):
            props = feature['properties']; source_id = props['source_ids'][0]
            if props['source_ids'] != [source_id] or source_id not in datasets:
                raise ValueError('Diagnostic expects one explicitly selected native depth source')
            depth_ds, class_ds = datasets[source_id]
            poly = transform(Transformer.from_crs(4326, depth_ds.crs, always_xy=True).transform,
                             shape(feature['geometry']))
            bounds = poly.buffer(halo_m).bounds
            win = window_for(bounds, depth_ds)
            depth = depth_ds.read(1, window=win, masked=True)
            affine = depth_ds.window_transform(win)
            class_win = from_bounds(*rasterio.windows.bounds(win, depth_ds.transform), transform=class_ds.transform)
            class_win = class_win.round_offsets().round_lengths()
            if (class_ds.crs != depth_ds.crs or class_ds.window_transform(class_win) != affine
                    or int(class_win.width) != depth.shape[1] or int(class_win.height) != depth.shape[0]):
                raise ValueError('Native diagnostic would require resampling')
            classes = class_ds.read(1, window=class_win, masked=True, boundless=True)
            valid = ~np.ma.getmaskarray(depth) & np.isfinite(depth.data)
            class_valid = ~np.ma.getmaskarray(classes)
            rough = classify(classes.data, class_valid)
            inside = geometry_mask([poly], out_shape=depth.shape, transform=affine, invert=True)
            selected = valid & inside
            yy, xx = np.indices(depth.shape)
            # Context-plane residual is a diagnostic, not the production score.
            design = np.column_stack((xx[valid], yy[valid], np.ones(valid.sum())))
            fit = np.linalg.lstsq(design, depth.data[valid].astype('float64'), rcond=None)[0]
            residual = np.ma.array(depth.data-(fit[0]*xx+fit[1]*yy+fit[2]), mask=~valid)
            record = {'id': props['id'], 'source_id': source_id, 'reach': props['reach'],
                'area_ha': props['area_ha'], 'candidate_native_center_cells': int(inside.sum()),
                'valid_depth_center_cells': int(selected.sum()),
                'rough_center_cells': int((selected & rough).sum()),
                'class_nodata_center_cells': int((selected & ~class_valid).sum()),
                'depth_min_m': float(depth.data[selected].min()),
                'depth_max_m': float(depth.data[selected].max()),
                'plane_residual_rms_context_m': float(np.sqrt(np.mean(residual.compressed()**2))),
                'production_terrain': props['terrain'], 'fit': props['fit'], 'exportable': False}
            results.append(record)
            if index not in panel_indices:
                continue
            if panel_number % 3 == 0:
                figure, axes = plt.subplots(3, 3, figsize=(13, 12), constrained_layout=True)
            line = panel_number % 3
            left, bottom, right, top = rasterio.windows.bounds(win, depth_ds.transform)
            extent = [0, right-left, 0, top-bottom]
            outer = [poly] if poly.geom_type == 'Polygon' else list(poly.geoms)
            views = [depth, residual, np.where(class_valid, rough.astype('float32'), np.nan)]
            scale = max(.25, float(np.percentile(np.abs(residual.compressed()), 98)))
            for col, (values, title, cmap) in enumerate(zip(views,
                    ('Measured depth · m, positive down', 'Context-plane residual · m', 'Original class · beige smooth / navy rough'),
                    ('viridis', 'RdBu_r', ListedColormap(['#e3d8bd', '#123e57'])))):
                ax = axes[line, col]
                kwargs = {'vmin':-scale, 'vmax':scale} if col == 1 else ({'vmin':0, 'vmax':1} if col == 2 else {})
                artist = ax.imshow(values, extent=extent, origin='upper', cmap=cmap, interpolation='nearest', **kwargs)
                for part in outer:
                    x, y = part.exterior.xy; ax.plot(np.array(x)-left, np.array(y)-bottom, color='#d7357a', lw=1)
                ax.set_title(title, fontsize=9)
                ax.set_xlabel('East · m'); ax.set_ylabel('North · m')
                if col < 2: figure.colorbar(artist, ax=ax, shrink=.8)
            axes[line, 0].text(0, 1.12,
                f"{index+1}. {source_id} · {props['id'].split('-')[-1]} · {props['area_ha']:.3f} ha",
                transform=axes[line, 0].transAxes, fontsize=10, weight='bold')
            if panel_number % 3 == 2 or index == max(panel_indices):
                for empty in range(line+1, 3):
                    for ax in axes[empty]: ax.set_visible(False)
                figure.suptitle('PRIVATE terrain review · pink = candidate outline · gray/blank = missing\nNative cells without resampling; interpretation shares the survey. No legal clearance or fish-presence claim.', fontsize=11)
                path = output/f'page-{panel_number//3+1:02d}.png'
                figure.savefig(path, dpi=135); plt.close(figure)
                pages.append({'file':path.name, 'sha256':sha256(path)})
            panel_number += 1
    receipt = {'reviewed_at':datetime.now(timezone.utc).isoformat(), 'script_sha256':sha256(__file__),
        'private':True, 'exportable':False, 'inputs':inputs, 'context_halo_m':halo_m,
        'candidate_stage':stage, 'panel_feature_ids':[features[i]['properties']['id'] for i in sorted(panel_indices)],
        'panel_selection':'All, or uniformly spaced indices sorted by source ID and descending area; numeric diagnostics cover every feature.',
        'method':'Native-center diagnostics and original support; no resampling, rank change or release decision.',
        'features':results, 'pages':pages}
    atomic_json(output/'audit.json', receipt, indent=2)
    print(json.dumps({'features':len(results), 'pages':len(pages), 'output':str(output)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reach', action='append', required=True)
    parser.add_argument('--source', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=('private', 'standard'), default='private')
    parser.add_argument('--panel-limit', type=int)
    args = parser.parse_args()
    audit(args.root, args.reach, args.source, args.output, stage=args.stage, panel_limit=args.panel_limit)
