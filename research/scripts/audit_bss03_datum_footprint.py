"""Probe NOAA VDatum over private BSS03 research blocks; never qualify depth."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape

from research.scripts.audit_bss03_access_blocks import fingerprint
from research.scripts.audit_csumb_vdatum_bridge import assess, request


def compile_review(blocks, access, *, get=None):
    if (blocks.get('scope') != 'private-bss03-camera-100m-research-blocks'
            or blocks.get('crs') != 'EPSG:26910'
            or len(blocks.get('features', [])) != 3
            or access.get('scope') != 'bss03-original-camera-100m-access-triage'
            or access.get('private_block_fingerprint') != fingerprint(blocks['features'])):
        raise ValueError('Private Block 03 footprint or access receipt changed')
    project = Transformer.from_crs('EPSG:26910', 'EPSG:4326', always_xy=True)
    private_samples = []
    for index, feature in enumerate(blocks['features']):
        geom = shape(feature['geometry'])
        if geom.is_empty or not geom.is_valid or abs(geom.area - 10_000) > 0.1:
            raise ValueError('Research footprint is not a valid 100 m square')
        minx, miny, maxx, maxy = geom.bounds
        for label, x, y in (
                ('southwest', minx, miny), ('southeast', maxx, miny),
                ('northwest', minx, maxy), ('northeast', maxx, maxy),
                ('center', geom.centroid.x, geom.centroid.y)):
            lon, lat = (round(value, 7) for value in project.transform(x, y))
            url, digest, payload = request(lon, lat, 'NAD83_2011', get=get)
            result = assess(payload, lon, lat, 'NAD83_2011')
            private_samples.append({'block_index': index, 'sample': label,
                                    'longitude': lon, 'latitude': lat,
                                    'request_url': url, 'response_sha256': digest,
                                    **result})
    available = [s for s in private_samples if s['status'] == 'sample_available']
    if len(available) != len(private_samples):
        raise ValueError('VDatum unavailable at one or more research-footprint samples')
    offsets = [s['offset_m'] for s in available]
    errors = [s['vdatum_uncertainty_m'] for s in available]
    report = {
        'schema_version': 1,
        'scope': 'bss03-private-footprint-vdatum-diagnostic',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'source_access_receipt': 'data/bss03-camera-access-triage.json',
        'private_block_fingerprint': access['private_block_fingerprint'],
        'block_count': 3, 'sample_count': len(available),
        'sample_design': 'four corners and center of each private 100 m research block',
        'source_vertical_datum': 'NAVD88 Geoid09',
        'source_horizontal_crs': 'EPSG:26910 (NAD83 / UTM zone 10N)',
        'source_horizontal_realization_verified': False,
        'assumed_api_source_frame': 'NAD83_2011',
        'api_target_frame': 'IGS14 / MLLW',
        'vdatum_offset_m_min': min(offsets),
        'vdatum_offset_m_max': max(offsets),
        'vdatum_transform_uncertainty_m_max': max(errors),
        'original_product_uncertainty_verified': False,
        'mllw_raster_converted': False,
        'upper_bounded_mllw_depth_verified': False,
        'qualified_waypoints': 0,
        'fishing_target': False, 'exportable': False,
        'limitations': [
            'The source NAD83 realization and epoch are unspecified. NAD83_2011 API probes are diagnostic assumptions, not source-grid transformations.',
            'Five samples per 100 m block do not define a correction field for each original 2 m bathymetry cell.',
            'VDatum transformation uncertainty is not the original CARIS/CUBE total propagated bathymetric uncertainty.',
            'Research block geometry and sample coordinates stay private; no navigable location or 1–3 fishing rank is released.',
        ],
    }
    private = {'scope': 'private-bss03-vdatum-responses',
               'checked_at': report['checked_at'], 'samples': private_samples}
    return report, private


def stable(report):
    return {k: v for k, v in report.items() if k != 'checked_at'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks', type=Path, default=Path('var/review/bss03-camera-100m-blocks.geojson'))
    parser.add_argument('--access', type=Path, default=Path('research/receipts/bss03-camera-access-triage.json'))
    parser.add_argument('--output', type=Path, default=Path('research/receipts/bss03-footprint-vdatum-diagnostic.json'))
    parser.add_argument('--private', type=Path, default=Path('var/review/bss03-vdatum-responses.json'))
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    report, private = compile_review(json.loads(args.blocks.read_text()),
                                     json.loads(args.access.read_text()))
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit('VDatum footprint diagnostic changed; review before publishing')
    for path in (args.output, args.private):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    args.private.write_text(json.dumps(private, indent=2) + '\n')
    print(json.dumps({'sample_count': report['sample_count'],
                      'depth_qualified': report['upper_bounded_mllw_depth_verified']}))


if __name__ == '__main__':
    main()
