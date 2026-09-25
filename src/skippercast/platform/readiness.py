"""Build an honest, actionable coverage queue for every California browse sector.

The source audits are discovery evidence. Their counts never become target
coordinates or proof that an entire sector has been surveyed.
"""
from pathlib import Path

from .contracts import REPO, atomic_json, read_json


def compile_readiness(root=REPO):
    root = Path(root)
    sectors = read_json(root / 'dist/data/coastal-sectors.json')['sectors']
    native = read_json(root / 'dist/data/noaa-native-sector-review.json')
    variable_depth = read_json(root / 'dist/data/noaa-vr-native-depth-review.json')
    regular_depth = read_json(root / 'dist/data/noaa-regular-native-depth-review.json')
    discovery = read_json(root / 'dist/data/noaa-survey-discovery.json')
    packages = {row['id']: row for row in read_json(root / 'dist/regions/index.json')['regions']}
    drafts = []
    for path in sorted((root / 'regions').glob('*/region.json')):
        region = read_json(path)
        if region['status'] == 'draft':
            drafts.append(region)
    native_by_id = {row['sector_id']: row for row in native['sectors']}
    variable_by_id = {row['sector_id']: row for row in variable_depth['sectors']}
    regular_by_id = {row['sector_id']: row for row in regular_depth['sectors']}
    discovery_by_id = {row['sector_id']: row for row in discovery['sectors']}
    expected = {row['id'] for row in sectors}
    if (len(sectors) != 19 or variable_depth['status'] != 'ok' or regular_depth['status'] != 'ok'
            or len(native_by_id) != len(native['sectors'])
            or len(variable_by_id) != len(variable_depth['sectors'])
            or len(regular_by_id) != len(regular_depth['sectors'])
            or len(discovery_by_id) != len(discovery['sectors'])
            or any(set(rows) != expected for rows in
                   (native_by_id, variable_by_id, regular_by_id, discovery_by_id))):
        raise ValueError('A statewide readiness input is missing or has duplicate sectors')
    rows = []
    for sector in sectors:
        ident = sector['id']
        lead = native_by_id[ident]
        found = discovery_by_id[ident]
        if found['status'] != 'ok':
            raise ValueError(f'Survey discovery is incomplete for {ident}')
        package_rows = []
        for package_id in sector['partial_package_ids']:
            if package_id not in packages:
                raise ValueError(f'Unknown published package {package_id}')
            package_rows.append({'id': package_id, 'status': packages[package_id]['status']})
        west, south, east, north = sector['bounds']
        draft_ids = sorted(draft['id'] for draft in drafts
                           if (draft['fishing_bounds'][0] <= east and draft['fishing_bounds'][2] >= west
                               and draft['fishing_bounds'][1] < north and draft['fishing_bounds'][3] > south))
        points = sector['published_candidate_points']
        candidate_files = lead['eligible_for_native_substrate_review_bboxes']
        held_files = lead['held_substrate_overlap_screen_bboxes']
        variable_files = variable_by_id[ident]['source_files_with_eligible_cells']
        regular_files = regular_by_id[ident]['source_files_with_eligible_cells']
        # These are file-envelope leads, not a count of verified seabed cells.
        if min(points, candidate_files, held_files, variable_files, regular_files) < 0:
            raise ValueError('Negative coverage count')
        if candidate_files:
            next_step = 'Review original native cells, independent substrate, chart hazards and access for the in-sector file leads.'
        elif variable_files or regular_files:
            next_step = 'Find independent original substrate overlap in the measured, depth-qualified native cells; do not infer reef from depth alone.'
        else:
            next_step = 'Find original fine-resolution depth and independent substrate within the actual sector water; sampled files yielded no eligible cells.'
        if held_files:
            next_step += ' Reconcile held survey hazards before any target promotion.'
        rows.append({
            'sector_id': ident, 'coast': sector['coast'], 'name': sector['name'],
            'bounds': sector['bounds'], 'package_overlaps': package_rows,
            'unpublished_draft_package_ids': draft_ids,
            'published_candidate_points_in_band': points,
            'status': 'partial-local-targets' if points else 'source-review-only',
            'noaa_catalog_survey_leads': lead['catalog_survey_leads'],
            'original_bag_bbox_leads': lead['georeferenced_bag_bboxes_intersecting_sector'],
            'native_variable_depth_file_leads': variable_files,
            'native_regular_depth_file_leads': regular_files,
            'native_substrate_review_file_leads': candidate_files,
            'held_file_leads': held_files,
            'native_review_survey_ids': lead['screen_survey_ids'],
            'held_survey_ids': lead['held_survey_ids'],
            'next_source_step': next_step,
            'remaining_promotion_gates': [
                'native measured depth, datum, uncertainty and footprint',
                'independent original substrate and local habitat confirmation',
                'current chart hazards, approach and access',
                'current MPA and other exclusion geometry',
                'species, date and method-specific local regulations',
                'site review before score, drift or export',
            ],
        })
    return atomic_json(root / 'dist/data/california-atlas-readiness.json', {
        'schema_version': 1,
        'scope': 'California outer-coast source promotion queue; latitude bands are discovery partitions, not fishing or regulation boundaries.',
        'source_audit_at': native['audit_collected_at'],
        'survey_discovery_at': discovery['last_complete_scan_at'],
        'limitations': [
            'BAG counts are intersecting file envelopes from a bounded <=100 MB audit, not unique surveyed area or eligible fishing spots.',
            'Native-depth counts are files with some measured cells passing the 25–200 ft and product-uncertainty screen; they are not reef cells and may cover only a small part of a sector.',
            'Points in a latitude band do not establish complete sector coverage; islands and bays require separate local review.',
            'A zero source lead means no qualifying file in this bounded audit, not no reef or fish.',
            'Every target still requires current legal and safety review; this queue does not grant fishing or navigation clearance.',
        ],
        'sectors': rows,
    })
