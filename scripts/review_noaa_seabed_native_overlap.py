"""Cross-check sparse NOAA seabed descriptions against exact native MLLW cells.

Source point coordinates remain in ignored var/ pages. Public output contains only
sector counts. A point description is never a reef footprint or a fishing target.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.windows import Window
from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union

from scripts.audit_noaa_seabed_samples import validate_pages, sector_for
from skippercast.platform.bottom_targets import cells_qualified

ROCK_WORD = re.compile(r'\b(rock|boulder|cobble|bedrock)\b', re.I)


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def review(raw_dir, sample_audit, regular_audit, cache, sectors, mpa_snapshot, bodega_context,
           *, now=None):
    now = now or datetime.now(timezone.utc)
    pages, shas = [], []
    for path in sorted(raw_dir.glob('page-*.geojson')):
        shas.append(digest(path))
        pages.append(json.loads(path.read_text()))
    if (sample_audit['scope'] != 'california-historical-nos-seabed-sample-sector-audit'
            or shas != sample_audit['page_sha256'] or len(pages) != len(shas)
            or regular_audit['scope'] != 'california-original-regular-native-depth-review'
            or regular_audit['status'] != 'ok'
            or regular_audit['survey_file_count'] != len(regular_audit['files'])):
        raise ValueError('Historical sample or original BAG source review changed')
    samples = validate_pages(pages, sample_audit['bounded_original_sample_count'])
    rock = [row for row in samples if ROCK_WORD.search(str(row['properties'].get('DESCRP') or ''))]
    if len(rock) != sum(row['uncurated_description_rock_word_count'] for row in sample_audit['sectors']):
        raise ValueError('Original free-text rock description count changed')
    mpa = mpa_snapshot['sources']['mpas']
    features = mpa['data']['geojson']['features']
    checked = datetime.fromisoformat(mpa['data_retrieved_at'].replace('Z', '+00:00'))
    if (mpa['status'] != 'ok' or len(features) != mpa['data']['feature_count']
            or len(features) < 100 or not 0 <= (now - checked).total_seconds() <= 36 * 3600):
        raise ValueError('Fresh, complete CDFW MPA geometry is required')
    to_meters = Transformer.from_crs('EPSG:4326', 'EPSG:3310', always_xy=True).transform
    protected = unary_union([transform(to_meters, shape(feature['geometry']))
                             for feature in features]).buffer(100)
    indexed = {}
    for feature in rock:
        ident = feature['properties']['OBJECTID']
        lon, lat = feature['geometry']['coordinates']
        sector = sector_for(lon, lat, sectors)
        indexed[ident] = {'point': Point(lon, lat), 'sector': sector,
                          'mpa_buffer': protected.intersects(transform(to_meters, Point(lon, lat))),
                          'envelopes': 0, 'measured': False, 'qualified': False,
                          'matched_hard_outline': False, 'nearest_hard_m': None}
    envelope_hits = 0
    measured_file_hits = 0
    qualified_file_hits = 0
    source_files_with_hits = set()
    for file in regular_audit['files']:
        if file['status'] != 'ok':
            raise ValueError('Reviewed original BAG file has a failed audit')
        url = file['bag_url']
        name = file['survey_id'] + '-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.bag'
        path = cache / name
        if not path.is_file():
            raise ValueError('Exact original BAG cache file missing: ' + name)
        with rasterio.open(path) as raster:
            crs = CRS.from_wkt(raster.crs.to_wkt())
            parts = crs.sub_crs_list
            if (raster.driver != 'BAG' or raster.count != 2 or len(parts) != 2
                    or parts[1].name not in ('MLLW depth', 'Mean Lower Low Water')
                    or max(raster.res) > 4):
                raise ValueError('Original BAG datum, bands or resolution changed: ' + name)
            project = Transformer.from_crs('EPSG:4326', parts[0], always_xy=True)
            hits = []
            for ident, record in indexed.items():
                x, y = project.transform(record['point'].x, record['point'].y)
                if raster.bounds.left <= x <= raster.bounds.right and raster.bounds.bottom <= y <= raster.bounds.top:
                    row, col = raster.index(x, y)
                    if 0 <= row < raster.height and 0 <= col < raster.width:
                        hits.append((ident, row, col))
            if not hits:
                continue
            if digest(path) != file['bag_sha256']:
                raise ValueError('Original NOAA BAG bytes changed: ' + name)
            source_files_with_hits.add(name)
            for ident, row, col in hits:
                record = indexed[ident]
                record['envelopes'] += 1
                envelope_hits += 1
                values = raster.read((1, 2), window=Window(col, row, 1, 1))[:, 0, 0]
                elevation, uncertainty = map(float, values)
                if not (np.isfinite(elevation) and np.isfinite(uncertainty)
                        and elevation < 0 and uncertainty > 0 and elevation > -9000):
                    continue
                record['measured'] = True
                measured_file_hits += 1
                if cells_qualified(np.array([[elevation]]), np.array([[uncertainty]]),
                                   max(raster.res))[0, 0]:
                    record['qualified'] = True
                    qualified_file_hits += 1
    if (bodega_context['scope'] != 'sf-native-noaa-usgs-hard-bottom-context'
            or any(f['properties'].get('fishing_target') is not False
                   for f in bodega_context['features'])):
        raise ValueError('Reviewed independent Bodega class context changed')
    hard_shapes = [shape(f['geometry']) for f in bodega_context['features']]
    hard_meters = [transform(to_meters, geom) for geom in hard_shapes]
    for record in indexed.values():
        if record['qualified'] and record['sector'] == 'bodega-reyes':
            record['matched_hard_outline'] = any(g.covers(record['point']) for g in hard_shapes)
            record['nearest_hard_m'] = min(g.distance(transform(to_meters, record['point']))
                                           for g in hard_meters) if hard_meters else None
    summaries = []
    for sector in sectors:
        records = [r for r in indexed.values() if r['sector'] == sector['id']]
        summaries.append({'sector_id': sector['id'],
                          'uncurated_rock_word_samples': len(records),
                          'inside_mpa_or_100m_buffer': sum(r['mpa_buffer'] for r in records),
                          'within_audited_regular_bag_envelope': sum(r['envelopes'] > 0 for r in records),
                          'on_measured_native_cell': sum(r['measured'] for r in records),
                          'on_25_to_200ft_qualified_native_cell': sum(r['qualified'] for r in records),
                          'qualified_outside_mpa_buffer': sum(r['qualified'] and not r['mpa_buffer'] for r in records),
                          'qualified_inside_reviewed_bodega_hard_outline': sum(r['qualified'] and r['matched_hard_outline'] for r in records),
                          'nearest_reviewed_bodega_hard_outline_m_rounded_100':
                          round(min(r['nearest_hard_m'] for r in records if r['nearest_hard_m'] is not None) / 100) * 100
                          if any(r['nearest_hard_m'] is not None for r in records) else None})
    return {'schema_version': 1, 'scope': 'nos-rock-description-versus-original-noaa-depth-triage',
            'sample_page_sha256': shas,
            'regular_bag_review_scope': regular_audit['scope'],
            'cdfw_mpa_retrieved_at': mpa['data_retrieved_at'],
            'source_files_with_envelope_hits': len(source_files_with_hits),
            'file_envelope_hits': envelope_hits,
            'measured_file_cell_hits': measured_file_hits,
            'qualified_file_cell_hits': qualified_file_hits,
            'sectors': summaries,
            'fishing_target': False, 'exportable': False,
            'limitations': [
                'Free-text rock words are uncurated historical point descriptions, not mapped hard-bottom polygons or present fish.',
                'NOS sample positions have unresolved accuracy; an exact raster-cell join cannot validate the sample location or its original source method.',
                'Overlapping NOAA BAG files and resolutions are correlated; counts of file hits are not distinct seabed sites.',
                'A qualifying cell does not qualify surrounding water, chart hazards, legal access, a route, a fishery or a fishing waypoint.',
                'Only the existing reviewed Bodega original hard-class outlines are checked for footprint corroboration here; zero does not exclude other independent rock mapping.'
            ]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw-dir', type=Path, default=Path('var/review/noaa-seabed-samples'))
    p.add_argument('--samples', type=Path, default=Path('dist/data/noaa-seabed-samples-sector-review.json'))
    p.add_argument('--regular', type=Path, default=Path('dist/data/noaa-regular-native-depth-review.json'))
    p.add_argument('--cache', type=Path, default=Path('var/noaa-native-cache'))
    p.add_argument('--sectors', type=Path, default=Path('dist/data/coastal-sectors.json'))
    p.add_argument('--mpas', type=Path, default=Path('var/qualification-current/coastal/latest.json'))
    p.add_argument('--bodega', type=Path, default=Path('dist/data/sf-native-hard-context.geojson'))
    p.add_argument('--output', type=Path, default=Path('dist/data/noaa-seabed-samples-native-overlap-review.json'))
    a = p.parse_args()
    data = review(a.raw_dir, json.loads(a.samples.read_text()), json.loads(a.regular.read_text()),
                  a.cache, json.loads(a.sectors.read_text())['sectors'],
                  json.loads(a.mpas.read_text()), json.loads(a.bodega.read_text()))
    data['regular_bag_review_sha256'] = digest(a.regular)
    data['bodega_original_hard_context_sha256'] = digest(a.bodega)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps({'rock_word_samples': sum(s['uncurated_rock_word_samples'] for s in data['sectors']),
                      'qualified_outside_mpa_buffer': sum(s['qualified_outside_mpa_buffer'] for s in data['sectors'])}))


if __name__ == '__main__':
    main()
