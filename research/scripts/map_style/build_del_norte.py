#!/usr/bin/env python3
"""Private first-sector MAPSTYLE-3b slice; cached F00562 only, no network.

Run with --bag <retained F00562_MB_1m_MLLW_1of2.bag>. Outputs stay in var/.
This is nominal terrain, not habitat classification or navigation-qualified depth.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds
from pyproj import CRS

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from scripts import build_bathy_tiles as bt
from skippercast.platform.bottom_targets import bag_metadata, sha256


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bag', required=True, type=Path)
    args = p.parse_args()
    review = json.loads((ROOT / 'dist/data/noaa-regular-native-depth-review.json').read_text())
    row = next(r for r in review['files'] if r['bag_url'].endswith('/F00562_MB_1m_MLLW_1of2.bag'))
    digest = sha256(args.bag)
    if digest != row['bag_sha256']:
        raise ValueError('cached BAG differs from the retained native-depth audit')
    out = ROOT / 'var/seafloor/bathy-del-norte'
    out.mkdir(parents=True, exist_ok=True)
    with rasterio.open(args.bag) as ds:
        metadata = bag_metadata(ds.tags(ns='xml:BAG')['xml:BAG'], 'F00562')
        if metadata['metadata_sha256'] != row['metadata_sha256']:
            raise ValueError('BAG metadata differs from retained audit')
        if ds.res != (1.0, 1.0) or ds.count != 2 or ds.scales != (1.0, 1.0) or ds.offsets != (0.0, 0.0):
            raise ValueError('expected original regular 1 m elevation/uncertainty BAG')
        crs = CRS(ds.crs)
        if crs.is_compound:
            crs = crs.sub_crs_list[0]
        if crs.is_bound:
            crs = crs.source_crs
        geo = transform_bounds(crs, 'EPSG:4326', *ds.bounds, densify_pts=21)
        if not (41.7 <= geo[1] < geo[3] <= 42):
            raise ValueError('source not contained in first inventory sector Del Norte')
        a = ds.read(1, masked=True)
        valid = ~np.ma.getmaskarray(a) & np.isfinite(a.data) & (a.data <= 0) & (a.data >= -bt.SHALLOW_M)
        # Apply native depth/nodata mask BEFORE warp averaging. No invented coverage.
        depth = np.where(valid, a.data, bt.NODATA).astype('float32')
        with rasterio.open(out / 'native.tif', 'w', driver='GTiff', width=ds.width, height=ds.height,
                           count=1, dtype='float32', crs=crs, transform=ds.transform,
                           nodata=bt.NODATA, compress='deflate') as target:
            target.write(depth, 1)
        bounds3310 = transform_bounds(crs, 'EPSG:3310', *ds.bounds, densify_pts=21)
    # Empty background: never carry the Morro survey or invent deeper context here.
    with rasterio.open(out / 'background.tif', 'w', driver='GTiff', width=2, height=2, count=1,
                       dtype='float32', crs='EPSG:3310', transform=from_bounds(*bounds3310, 2, 2),
                       nodata=bt.NODATA) as target:
        target.write(np.full((2, 2), bt.NODATA, 'float32'), 1)
    entry = {'id': 'noaa-f00562-1m-1of2', 'path': str(out / 'native.tif'), 'resolution_m': 1,
             'source_file': 'F00562_MB_1m_MLLW_1of2.bag', 'archive_sha256': digest,
             'survey_id': 'F00562', 'survey_dates': row['survey_dates'],
             'vertical_datum': 'nominal MLLW; realization not verified', 'release_date': None,
             'depth_semantics': 'positive-up elevation metres; nominal 0–91.44 m depth; no tide correction',
             'source_url': row['bag_url']}
    manifest = out / 'native-manifest.json'
    manifest.write_text(json.dumps([entry], indent=2) + '\n')
    archive = bt.output_for('medium', out)
    bt.build(out / 'background.tif', archive, 8, 15,
             native_sources=bt.load_native_manifest(manifest), label='Del Norte coast — NOAA F00562')
    receipt = {'sector': 'del-norte', 'inventory_order': 1, 'survey': {k: v for k, v in entry.items() if k != 'path'},
               'native_shallow_cells': int(valid.sum()), 'nominal_cell_area_m2': int(valid.sum()),
               'archive_sha256': sha256(archive),
               'archive_bytes': archive.stat().st_size,
               'limits': ['NOT FOR NAVIGATION', 'No substrate classification, no hard-bottom inference',
                          'No uncertainty qualification; no coverage percentage',
                          'Static 2008 survey, not current depth; no vertical transformation']}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
