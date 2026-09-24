"""Locate original USGS bathymetry review leads without granting fishing depth.

Native single-band TIFFs have no per-cell product-uncertainty grid. Original
vertical-reference XML can be structured, merely mentioned in prose, or
missing. This ledger exposes those distinctions across all 19 browse sectors.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.summarize_native_sector_leads import envelope


def build(metadata_sets, audit_sets, discovery, sectors):
    expected_meta = {'usgs-state-waters-native-metadata', 'usgs-state-waters-doi-native-metadata'}
    expected_audit = {'usgs-state-waters-native-grid-audit', 'usgs-state-waters-doi-native-grid-audit'}
    if {x.get('scope') for x in metadata_sets} != expected_meta or {x.get('scope') for x in audit_sets} != expected_audit:
        raise ValueError('Both original USGS metadata and raster audit types are required')
    if any(x.get('health', {}).get('status') != 'ok' for x in metadata_sets):
        raise ValueError('Incomplete original USGS XML audits')
    if any(x.get('health', {}).get('status') not in {'ok', 'degraded'} for x in audit_sets):
        raise ValueError('Original USGS native-grid audit status is unavailable')
    if discovery.get('scope') != 'noaa-bag-survey-discovery' or discovery.get('health', {}).get('status') != 'ok':
        raise ValueError('Complete California sector request envelopes required')
    source_sectors = {r['sector_id']: r for r in discovery['sectors']}
    if len(sectors['sectors']) != 19 or len(source_sectors) != 19:
        raise ValueError('Incomplete California sector index')
    meta = {r['metadata_url']: r for packet in metadata_sets for r in packet['records'] if r['kind'] == 'bathymetry'}
    audited = [r for packet in audit_sets for r in packet['products'] if r['kind'] == 'bathymetry']
    sources = []
    failures = []
    for row in audited:
        if row['status'] != 'ok':
            failures.append({'archive_url': row['archive_url'], 'issue': row.get('issue', 'native raster unavailable')})
            continue
        record = meta.get(row['metadata_url'])
        if (not record or record['status'] != 'ok'
                or row['metadata_sha256'] != record['xml_sha256']
                or row['archive_url'] != record.get('archive_url', row['archive_url'])):
            raise ValueError('Original bathymetry and XML receipt mismatch')
        bounds = row['raster_bounds_wgs84']
        if len(bounds) != 4 or not (-125 < bounds[0] < bounds[2] < -115 and 30 < bounds[1] < bounds[3] < 43):
            raise ValueError('Invalid original raster geographic bounds')
        if max(row['native_resolution']) > 20 or row['valid_pixels'] <= 0:
            raise ValueError('Unsupported original raster grid')
        sources.append({'id': row.get('release_id') or row.get('block_id'),
                        'title': record.get('title') or row.get('study_areas', [''])[0],
                        'archive_url': row['archive_url'], 'archive_sha256': row['archive_sha256'],
                        'metadata_url': row['metadata_url'], 'metadata_sha256': row['metadata_sha256'],
                        'raster_bounds_wgs84': bounds, 'native_resolution_m': row['native_resolution'],
                        'valid_native_pixels': row['valid_pixels'],
                        'declared_vertical_datum': record.get('native_vertical_datum_declared'),
                        'structured_vertical_datum_code': record.get('native_vertical_datum_code'),
                        'vertical_datum_evidence': record.get('vertical_datum_evidence', 'unknown'),
                        'vertical_datum_mentions': record.get('vertical_datum_mentions', []),
                        'has_per_cell_product_uncertainty': False,
                        'depth_qualified_for_fishing': False,
                        'reason_withheld': 'Original single-band raster has no per-cell product-uncertainty grid; MLLW conversion and its uncertainty have not been independently verified.'})
    sources.sort(key=lambda r: (r['id'], r['metadata_url']))
    if not sources:
        raise ValueError('No audited original bathymetry grids')
    output_sectors = []
    for item in sectors['sectors']:
        reviewed = source_sectors.get(item['id'])
        if not reviewed or reviewed['status'] != 'ok':
            raise ValueError('Unreviewed sector request envelope: ' + item['id'])
        area = envelope(reviewed['request_url'])
        matching = [i for i, source in enumerate(sources)
                    if box(*source['raster_bounds_wgs84']).intersects(area)]
        output_sectors.append({'sector_id': item['id'], 'name': item['name'],
                               'coast': item['coast'], 'intersecting_source_indices': matching,
                               'source_grid_bbox_count': len(matching),
                               'depth_qualified_source_count': 0})
    return {'schema_version': 1, 'scope': 'california-usgs-original-bathymetry-datum-ledger',
            'compiled_at': datetime.now(timezone.utc).isoformat(),
            'status': 'degraded' if failures else 'ok', 'unavailable_original_grids': failures,
            'source_grid_count': len(sources),
            'method': 'Hash-matched original USGS DS781 XML and single-band native GeoTIFF audits. Original raster bounding boxes intersect exact NOAA discovery request envelopes; an intersecting box is a review lead, not surveyed area.',
            'limitations': ['No source in this ledger is qualified as an MLLW fishing depth or a spot.',
                            'A datum mentioned in free text is not an authoritative output-datum declaration.',
                            'Original USGS single-band grids lack the per-cell product-uncertainty band required by the current fishing-target gate.',
                            'A source can intersect several sectors; bounds include nodata and cannot be summed as mapped seafloor.',
                            'Failed original downloads remain unavailable and cannot be counted as mapped coverage.',
                            'Island sources can overlap broad mainland browse envelopes; these sector lists are only source leads.'],
            'sectors': output_sectors, 'sources': sources}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--legacy-metadata', type=Path, default=Path('var/usgs-map-metadata-vertical.json'))
    p.add_argument('--doi-metadata', type=Path, default=Path('var/usgs-doi-metadata-vertical.json'))
    p.add_argument('--legacy-audit', type=Path, default=Path('var/usgs-native-audit.json'))
    p.add_argument('--doi-audit', type=Path, default=Path('var/usgs-doi-native-audit.json'))
    p.add_argument('--discovery', type=Path, default=Path('dist/data/noaa-survey-discovery.json'))
    p.add_argument('--sectors', type=Path, default=Path('catalog/coastal-sectors.json'))
    p.add_argument('--output', type=Path, default=Path('dist/data/usgs-depth-datum-ledger.json'))
    a = p.parse_args()
    read = lambda name: json.loads(getattr(a, name).read_text())
    result = build([read('legacy_metadata'), read('doi_metadata')],
                   [read('legacy_audit'), read('doi_audit')], read('discovery'), read('sectors'))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = a.output.with_suffix(a.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temporary.replace(a.output)
    print(f"{result['source_grid_count']} original bathymetry source grids, 0 depth-qualified fishing sources")


if __name__ == '__main__':
    main()
