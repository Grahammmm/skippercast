"""Report native NOAA review leads by California browse sector.

The envelope test is only triage: a BAG bounding box can contain unsurveyed
water. This report must never be interpreted as seafloor coverage or targets.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from shapely.geometry import box


def envelope(request_url):
    value = parse_qs(urlparse(request_url).query).get('geometry', [])
    if len(value) != 1:
        raise ValueError('Discovery sector lacks exact request envelope')
    coordinates = [float(x) for x in value[0].split(',')]
    if len(coordinates) != 4 or not coordinates[0] < coordinates[2] or not coordinates[1] < coordinates[3]:
        raise ValueError('Invalid discovery request envelope')
    return box(*coordinates)


def build(audit, discovery, sectors, overlap, holds=None):
    if audit.get('scope') != 'noaa-original-bag-native-overview-audit':
        raise ValueError('Wrong original NOAA BAG audit')
    if discovery.get('scope') != 'noaa-bag-survey-discovery':
        raise ValueError('Wrong NOAA sector discovery')
    if overlap.get('scope') != 'statewide-native-depth-substrate-overlap-leads':
        raise ValueError('Wrong native substrate screen')
    holds = holds or {'schema_version': 1, 'scope': 'reviewed-noaa-survey-fishing-lead-holds', 'holds': []}
    if holds.get('schema_version') != 1 or holds.get('scope') != 'reviewed-noaa-survey-fishing-lead-holds':
        raise ValueError('Wrong reviewed NOAA survey hold registry')
    held = {}
    for item in holds['holds']:
        ident = item['survey_id']
        if (ident in held or item.get('disposition') != 'withhold_from_fishing_promotion'
                or not item.get('reason') or len(item.get('report_sha256', '')) != 64
                or not item.get('report_url', '').startswith('https://data.ngdc.noaa.gov/')):
            raise ValueError('Invalid or duplicate NOAA survey lead hold')
        if any(c not in '0123456789abcdef' for c in item['report_sha256']):
            raise ValueError('Invalid original NOAA report fingerprint')
        held[ident] = item
    for lead in overlap['leads']:
        hold = held.get(lead.get('survey_id'))
        if hold and lead.get('source_report_url') != hold['report_url']:
            raise ValueError('NOAA survey hold does not match the screened report')
    source_by_id = {sector['sector_id']: sector for sector in discovery['sectors']}
    if len(source_by_id) != len(discovery['sectors']):
        raise ValueError('Duplicate discovery sector')
    screened = {lead['url'] for lead in overlap['leads']}
    rows = []
    for sector in sectors['sectors']:
        item = source_by_id.get(sector['id'])
        if not item or item['status'] != 'ok':
            rows.append({'sector_id': sector['id'], 'status': 'unavailable', 'issue': (item or {}).get('issue', 'missing discovery')})
            continue
        region = envelope(item['request_url'])
        survey_ids = {survey['id'] for survey in item['surveys']}
        associated = [f for f in audit['files'] if f['survey_id'] in survey_ids]
        georeferenced = [f for f in associated if f['status'] == 'ok' and box(*f['raster_bounds_wgs84']).intersects(region)]
        candidates = [f for f in georeferenced if f['metadata_status'] == 'mllw-product-uncertainty-reviewed-by-adapter'
                      and max(f['overview_resolution_m']) <= 4 and f['variable_refinement_records'] == 0]
        overlap_leads = [f for f in candidates if f['url'] in screened]
        withheld = [f for f in overlap_leads if f['survey_id'] in held]
        eligible_overlap = [f for f in overlap_leads if f['survey_id'] not in held]
        refinement_leads = [f for f in georeferenced
                            if f['metadata_status'] == 'mllw-product-uncertainty-reviewed-by-adapter'
                            and f.get('refinement_grids_at_most_4m', 0) > 0]
        rows.append({
            'sector_id': sector['id'], 'name': sector['name'], 'coast': sector['coast'], 'status': 'review-leads',
            'catalog_survey_leads': len(survey_ids), 'audited_bag_files_associated_with_surveys': len(associated),
            'georeferenced_bag_bboxes_intersecting_sector': len(georeferenced),
            'regular_4m_or_finer_mllw_product_uncertainty_bboxes': len(candidates),
            'substrate_overlap_screen_bboxes': len(overlap_leads),
            'screen_survey_ids': sorted({f['survey_id'] for f in overlap_leads}),
            'held_substrate_overlap_screen_bboxes': len(withheld),
            'held_survey_ids': sorted({f['survey_id'] for f in withheld}),
            'eligible_for_native_substrate_review_bboxes': len(overlap_leads) - len(withheld),
            'eligible_substrate_review_bag_urls': sorted(f['url'] for f in eligible_overlap),
            'variable_resolution_4m_refinement_bboxes': len(refinement_leads),
            'refinement_survey_ids': sorted({f['survey_id'] for f in refinement_leads}),
            'not_in_sector_bbox_count': sum(f['status'] == 'ok' for f in associated) - len(georeferenced),
        })
    return {
        'schema_version': 1, 'scope': 'california-native-bag-sector-review-leads',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'audit_collected_at': audit['collected_at'], 'discovery_collected_at': discovery['collected_at'],
        'max_audited_file_bytes': audit['max_bytes'],
        'audited_bag_files': audit['file_count'], 'audited_georeferenced_bag_files': audit['inspected_count'],
        'audit_health': audit['health'],
        'method': 'Intersect each original BAG geographic bounding box with the exact NOAA discovery request envelope for each browse sector, then count strictly reviewed regular-grid, substrate-screen and variable-resolution metadata leads separately. Survey-catalog associations alone do not count as in-sector grids.',
        'reviewed_lead_holds': [{'survey_id': ident, 'reason': item['reason'], 'report_url': item['report_url'],
                                 'report_sha256': item['report_sha256']} for ident, item in sorted(held.items())],
        'limitations': [
            'A geographic bounding box includes unsurveyed water; these counts are not area coverage.',
            'Only MLLW-named BAG files within the selected download size were audited; other NOAA surveys and USGS sources remain outside this count.',
            'Variable-resolution native refinements need a separate cell-level compiler; a coarse BAG overview is not proof of poor native resolution.',
            'Substrate overlap is a 4 m lead screen, not native geology, a legal fishing coordinate, or a catch prediction.',
            'Current MPAs, groundfish exclusions, other closures, hazards and local rules must be verified before any promotion.'
        ],
        'sectors': rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, default=Path('var/noaa-native-audit-100mb-refined.json'))
    parser.add_argument('--discovery', type=Path, default=Path('dist/data/noaa-survey-discovery.json'))
    parser.add_argument('--sectors', type=Path, default=Path('catalog/coastal-sectors.json'))
    parser.add_argument('--overlap', type=Path, default=Path('var/native-depth-overlap-leads-100mb.json'))
    parser.add_argument('--holds', type=Path, default=Path('catalog/noaa-survey-lead-holds.json'))
    parser.add_argument('--output', type=Path, default=Path('var/native-sector-review-leads.json'))
    args = parser.parse_args()
    result = build(*(json.loads(path.read_text()) for path in (args.audit, args.discovery, args.sectors, args.overlap, args.holds)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print('sector BAG review leads:', [(r['sector_id'], r.get('substrate_overlap_screen_bboxes', 0)) for r in result['sectors']])


if __name__ == '__main__':
    main()
