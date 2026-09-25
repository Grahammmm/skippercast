"""Measure each Cape Mendocino research outline against original eligible BAG cells.

An outline-wide depth distribution is evidence about historical seafloor, not
navigation clearance, a fishing waypoint, or a guarantee that every part of the
display polygon has measured hard bottom.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import box, mapping, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from screen_vr_original_hard import screen


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def audit(root=ROOT):
    source_path = root / 'dist/data/cape-mendocino-native-hard-context.geojson'
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    if (source.get('scope') != 'northern-native-noaa-usgs-hard-bottom-context'
            or not source.get('features')
            or any(f['properties'].get('fishing_target') is not False for f in source['features'])):
        raise ValueError('Expected non-target original-grid context outlines')
    to_native = Transformer.from_crs('EPSG:4326', 'EPSG:26910', always_xy=True).transform
    polygons = [transform(to_native, shape(f['geometry'])) for f in source['features']]
    if any(not g.is_valid or g.is_empty for g in polygons):
        raise ValueError('Invalid research geometry')
    tree = STRtree(polygons)
    values = defaultdict(list)
    counts = defaultdict(int)
    area = defaultdict(float)

    def collect(mask, depth, affine, crs):
        if crs.to_epsg() != 26910:
            raise ValueError('Original H11975 horizontal CRS changed')
        height, width = mask.shape
        footprint = box(affine.c, affine.f + affine.e * height,
                        affine.c + affine.a * width, affine.f)
        for index in tree.query(footprint):
            index = int(index)
            polygon = polygons[index]
            if not polygon.intersects(footprint):
                continue
            inside = rasterize([(mapping(polygon), 1)], out_shape=mask.shape,
                               transform=affine, dtype='uint8').astype(bool)
            selected = mask & inside
            n = int(selected.sum())
            if not n:
                continue
            sampled = -depth[selected].astype('float64') / .3048
            if not np.isfinite(sampled).all() or np.any((sampled < 25) | (sampled > 200)):
                raise ValueError('Depth outside the original-cell policy screen')
            values[index].append(sampled)
            counts[index] += n
            area[index] += n * abs(affine.a * affine.e)

    bag_packet = read(root / 'var/noaa-h11975-native-audit.json')
    bag = bag_packet['files'][0]
    if bag['survey_id'] != 'H11975' or bag['file_sha256'] != source['features'][0]['properties']['noaa_bag_sha256']:
        raise ValueError('Original H11975 source identity changed')
    usgs = read(root / 'var/usgs-doi-native-audit-eureka.json')
    substrate = next((row for row in usgs['products'] if row.get('release_id') == 'P9U0SUGL'
                      and row.get('kind') == 'seafloor_character' and row.get('status') == 'ok'), None)
    if substrate is None:
        raise ValueError('Original USGS hard-bottom class unavailable')
    result = screen(bag, substrate, read(root / 'var/usgs-doi-metadata-eureka.json'),
                    root / 'var/noaa-native-cache', root / 'var/usgs-doi-native-cache',
                    read(root / 'var/qualification-current/coastal/latest.json'),
                    read(root / 'var/noaa-federal-areas.json'),
                    read(root / 'catalog/noaa-survey-hazards.json'),
                    root / 'var/noaa-report-cache', mask_callback=collect)
    previous = read(root / 'dist/data/noaa-h11975-cape-mendocino-hard-depth-screen.json')
    for key in ('bag_sha256', 'usgs_archive_sha256', 'survey_report_sha256', 'counts'):
        if result[key] != previous[key]:
            raise ValueError('Original-cell screen changed: ' + key)
    outlines = []
    for index, feature in enumerate(source['features']):
        depths = np.concatenate(values[index]) if values[index] else np.empty(0)
        if not len(depths):
            raise ValueError('Published historical outline has no matching eligible original cell')
        outlines.append({
            'id': feature['properties']['id'],
            'qualified_original_cells': counts[index],
            'qualified_original_cell_area_m2': round(area[index], 1),
            'sampled_original_depth_ft': {
                'minimum': round(float(depths.min()), 1),
                'p05': round(float(np.percentile(depths, 5)), 1),
                'median': round(float(np.median(depths)), 1),
                'p95': round(float(np.percentile(depths, 95)), 1),
                'maximum': round(float(depths.max()), 1),
            },
            'fishing_target': False,
            'exportable': False,
        })
    return {
        'schema_version': 1,
        'scope': 'h11975-research-outline-original-depth-distributions',
        'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'context_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'bag_sha256': result['bag_sha256'],
        'usgs_archive_sha256': result['usgs_archive_sha256'],
        'mpa_screened_at': result['mpa_retrieved_at'],
        'federal_screened_at': result['federal_areas_retrieved_at'],
        'outline_count': len(outlines),
        'outlines': outlines,
        'limitations': [
            'Original 2008–2009 measured cells are historical; they do not predict present catch.',
            'Values summarize eligible original cells inside an inset display outline, not a continuous depth surface or charted safe-water envelope.',
            'The source screen excludes buffered MPAs, federal GEAs and pinned historical DTONs; current chart, route and local method/date rules still need separate clearance.',
        ],
    }


if __name__ == '__main__':
    report = audit()
    target = ROOT / 'dist/data/h11975-research-outline-original-depths.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(report['outline_count'], 'historical original-cell depth distributions; zero fishing targets')
