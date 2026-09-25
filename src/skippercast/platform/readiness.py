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
    variable_depth = read_json(root / 'dist/data/noaa-vr-native-depth-expanded-review.json')
    regular_depth = read_json(root / 'dist/data/noaa-regular-native-depth-review.json')
    discovery = read_json(root / 'dist/data/noaa-survey-discovery.json')
    seabed_samples = read_json(root / 'dist/data/noaa-seabed-samples-sector-review.json')
    deepwater = read_json(root / 'dist/data/noaa-central-deepwater-native-depth-screen.json')
    if (deepwater.get('scope') != 'noaa-original-central-coast-vr-depth-band-screen'
            or deepwater.get('depth_band_ft_mllw') != [25, 200]
            or {row['survey_id'] for row in deepwater.get('sources', [])} != {'H13089', 'H13151'}
            or any(row['raw_cells_in_25_to_200_ft_mllw_band'] != 0
                   or row['nearshore_depth_lead'] is not False
                   for row in deepwater['sources'])):
        raise ValueError('The bounded central deepwater exclusion changed')
    deepwater_ids = {row['survey_id'] for row in deepwater['sources']}
    survey_holds = read_json(root / 'catalog/noaa-survey-lead-holds.json')
    if (survey_holds.get('scope') != 'reviewed-noaa-survey-fishing-lead-holds'
            or survey_holds.get('schema_version') != 1):
        raise ValueError('Reviewed NOAA survey holds are missing')
    held_by_id = {row['survey_id']: row for row in survey_holds['holds']}
    if len(held_by_id) != len(survey_holds['holds']):
        raise ValueError('Duplicate NOAA survey hold')
    csumb_series = [read_json(root / f'catalog/csumb-{series}-source-leads.json')
                    for series in ('scc', 'bss')]
    usgs_map_areas = read_json(root / 'catalog/usgs-ds781-source-leads.json')
    usgs_metadata = read_json(root / 'catalog/usgs-ds781-metadata-review.json')
    packages = {row['id']: row for row in read_json(root / 'dist/regions/index.json')['regions']}
    drafts = []
    for path in sorted((root / 'regions').glob('*/region.json')):
        region = read_json(path)
        if region['status'] == 'draft':
            drafts.append(region)
    fine_original_leads = {row['id']: [] for row in sectors}
    depth_excluded_leads = {row['id']: [] for row in sectors}
    for path in sorted((root / 'catalog/candidates').glob('*.json')):
        candidate = read_json(path)
        spatial = candidate.get('spatial', {})
        resolution = spatial.get('resolution_m')
        if (candidate.get('access_status') != 'accessible'
                or not isinstance(resolution, (int, float)) or isinstance(resolution, bool)
                or resolution > 10 or spatial.get('resolution_basis') != 'inspected'
                or not spatial.get('bounds')
                or not {'bathymetry', 'substrate'} & set(candidate.get('need_ids', []))):
            continue
        for sector_id in candidate.get('sector_ids', []):
            if sector_id not in fine_original_leads:
                raise ValueError(f'Unknown sector for original-grid candidate: {sector_id}')
            screen = spatial.get('native_depth_screen')
            if screen and screen['limit_ft'] == 200 and screen['cells_within_limit'] == 0:
                depth_excluded_leads[sector_id].append(candidate['id'])
            else:
                fine_original_leads[sector_id].append(candidate['id'])
    native_by_id = {row['sector_id']: row for row in native['sectors']}
    variable_by_id = {row['sector_id']: row for row in variable_depth['sectors']}
    regular_by_id = {row['sector_id']: row for row in regular_depth['sectors']}
    discovery_by_id = {row['sector_id']: row for row in discovery['sectors']}
    seabed_by_id = {row['sector_id']: row for row in seabed_samples['sectors']}
    expected = {row['id'] for row in sectors}
    csumb_by_sector = {ident: set() for ident in expected}
    usgs_by_sector = {ident: [] for ident in expected}
    if len(usgs_map_areas.get('map_areas', [])) < 35:
        raise ValueError('USGS DS 781 map-area source inventory is incomplete')
    metadata_by_archive = {row['archive_url']: row for row in usgs_metadata.get('records', [])}
    priority_archives = [product['archive_url'] for area in usgs_map_areas['map_areas']
                         for product in area.get('products', [])
                         if product['kind'] in {'bathymetry', 'seafloor-character'}]
    if (usgs_metadata.get('scope') != 'usgs-ds781-original-fgdc-metadata-triage'
            or len(priority_archives) != len(metadata_by_archive)
            or set(priority_archives) != set(metadata_by_archive)):
        raise ValueError('USGS DS 781 metadata triage does not match catalog priority products')
    for area in usgs_map_areas['map_areas']:
        reviewed = [metadata_by_archive[p['archive_url']] for p in area.get('products', [])
                    if p['kind'] in {'bathymetry', 'seafloor-character'}]
        for sector_id in area['planning_sector_ids']:
            if sector_id not in usgs_by_sector:
                raise ValueError('USGS map-area lead has unknown planning sector')
            usgs_by_sector[sector_id].append({
                'name': area['name'], 'catalog_url': area['catalog_url'],
                'priority_product_status': area['priority_product_status'],
                'bathymetry_product_links': sum(p['kind'] == 'bathymetry' for p in area.get('products', [])),
                'seafloor_character_product_links': sum(p['kind'] == 'seafloor-character' for p in area.get('products', [])),
                'habitat_product_links': sum(p['kind'] == 'habitat' for p in area.get('products', [])),
                'fgdc_metadata_reviewed': sum(p['status'] == 'reviewed' for p in reviewed),
                'fgdc_metadata_unavailable': sum(p['status'] != 'reviewed' for p in reviewed),
                'explicit_public_domain_metadata': sum(p.get('rights_evidence') == 'explicit-public-domain-redistribution'
                                                       for p in reviewed),
                'bathymetry_datum_declarations': sorted({p['vertical_datum_declared'] or 'not declared'
                    for p in reviewed if p['kind'] == 'bathymetry' and p['status'] == 'reviewed'}),
            })
    for series, packet in zip(('scc', 'bss'), csumb_series):
        if packet.get('series') != series or packet.get('survey_count') != len(packet.get('surveys', [])):
            raise ValueError(f'CSUMB {series} source-lead roster is incomplete')
        for survey in packet['surveys']:
            if survey.get('status') != 'source-lead-only' or not set(survey['sector_ids']) <= expected:
                raise ValueError('CSUMB survey lead has unknown sector or promotion status')
            for sector_id in survey['sector_ids']:
                csumb_by_sector[sector_id].add(survey['survey_id'])
    if (len(sectors) != 19 or variable_depth['scope'] != 'california-expanded-original-vr-depth-inventory'
            or variable_depth['survey_file_count'] != len(variable_depth['files'])
            or regular_depth['status'] != 'ok'
            or len(native_by_id) != len(native['sectors'])
            or len(variable_by_id) != len(variable_depth['sectors'])
            or len(regular_by_id) != len(regular_depth['sectors'])
            or len(discovery_by_id) != len(discovery['sectors'])
            or seabed_samples['scope'] != 'california-historical-nos-seabed-sample-sector-audit'
            or len(seabed_by_id) != len(seabed_samples['sectors'])
            or any(set(rows) != expected for rows in
                   (native_by_id, variable_by_id, regular_by_id, discovery_by_id, seabed_by_id))):
        raise ValueError('A statewide readiness input is missing or has duplicate sectors')
    rows = []
    for sector in sectors:
        ident = sector['id']
        lead = native_by_id[ident]
        found = discovery_by_id[ident]
        if found['status'] != 'ok':
            raise ValueError(f'Survey discovery is incomplete for {ident}')
        excluded_deepwater = sorted(deepwater_ids & {row['id'] for row in found['surveys']})
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
        source_leads = sorted(fine_original_leads[ident])
        held_files = lead['held_substrate_overlap_screen_bboxes']
        variable_files = variable_by_id[ident]['source_files_with_eligible_cells']
        regular_files = regular_by_id[ident]['source_files_with_eligible_cells']
        variable_file_rows = [row for row in variable_depth['files']
                              if row.get('sectors', {}).get(ident, {}).get('depth_uncertainty_eligible_cells', 0) > 0]
        if len(variable_file_rows) != variable_files:
            raise ValueError('Variable-depth sector file count does not match source rows')
        held_variable_rows = []
        for row in variable_file_rows:
            hold = held_by_id.get(row['survey_id'])
            if hold:
                if (hold.get('disposition') != 'withhold_from_fishing_promotion'
                        or row['source_report_url'] != hold['report_url']):
                    raise ValueError('Variable-depth survey hold source mismatch')
                held_variable_rows.append(row)
        unheld_variable_files = variable_files - len(held_variable_rows)
        # These are file-envelope leads, not a count of verified seabed cells.
        if min(points, candidate_files, held_files, variable_files, regular_files) < 0:
            raise ValueError('Negative coverage count')
        if candidate_files:
            next_step = 'Review original native cells, independent substrate, chart hazards and access for the in-sector file leads.'
        elif unheld_variable_files or regular_files:
            next_step = 'Find independent original substrate overlap in the measured, depth-qualified native cells; do not infer reef from depth alone.'
        else:
            next_step = 'Find original fine-resolution depth and independent substrate within the actual sector water; sampled files yielded no eligible cells.'
        if source_leads and not (candidate_files or variable_files or regular_files):
            next_step = ('Audit the listed original fine-resolution source leads at native cells, reconcile chart datum and uncertainty, '
                         'then screen substrate, MPAs, hazards and local rules; the bounded NOAA sample yielded no qualified depth cells.')
        if csumb_by_sector[ident] and not (source_leads or candidate_files or variable_files or regular_files):
            next_step = ('Inspect the original CSUMB survey archives, per-file metadata and measured-cell masks; '
                         'then reconcile chart datum, uncertainty, substrate, MPAs, hazards, route and rules before any target.')
        if (not (source_leads or candidate_files or variable_files or regular_files or csumb_by_sector[ident])
                and any(area['bathymetry_product_links'] or area['seafloor_character_product_links']
                        for area in usgs_by_sector[ident])):
            next_step = ('Open the linked USGS original grid and metadata for this planning area; verify measured-cell footprint, '
                         'datum, uncertainty and class semantics before any seabed or fishing-target import.')
        if held_files or held_variable_rows:
            next_step += ' Reconcile held survey hazards before any target promotion.'
        if excluded_deepwater:
            next_step += (' Broad catalog hits ' + ', '.join(excluded_deepwater) +
                          ' have zero original MLLW cells in 25–200 ft; search other nearshore sources.')
        rows.append({
            'sector_id': ident, 'coast': sector['coast'], 'name': sector['name'],
            'bounds': sector['bounds'], 'package_overlaps': package_rows,
            'unpublished_draft_package_ids': draft_ids,
            'published_candidate_points_in_band': points,
            'status': 'partial-local-targets' if points else 'source-review-only',
            'noaa_catalog_survey_leads': lead['catalog_survey_leads'],
            'csumb_catalog_survey_lead_ids': sorted(csumb_by_sector[ident]),
            'usgs_ds781_map_area_leads': sorted(usgs_by_sector[ident], key=lambda area: area['name']),
            'original_bag_bbox_leads': lead['georeferenced_bag_bboxes_intersecting_sector'],
            'native_variable_depth_file_leads': variable_files,
            'held_variable_depth_file_leads': len(held_variable_rows),
            'held_variable_depth_survey_ids': sorted({row['survey_id'] for row in held_variable_rows}),
            'unheld_variable_depth_file_leads': unheld_variable_files,
            'native_regular_depth_file_leads': regular_files,
            'historical_noaa_seabed_samples': seabed_by_id[ident]['historical_sample_count'],
            'native_substrate_review_file_leads': candidate_files,
            'accessible_inspected_fine_source_candidate_ids': source_leads,
            'native_depth_excluded_source_candidate_ids': sorted(depth_excluded_leads[ident]),
            'held_file_leads': held_files,
            'native_review_survey_ids': lead['screen_survey_ids'],
            'held_survey_ids': lead['held_survey_ids'],
            'native_depth_excluded_survey_ids': excluded_deepwater,
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
        'historical_seabed_samples_retrieved_at': seabed_samples['retrieved_at'],
        'limitations': [
            'BAG envelope leads still come from a bounded <=100 MB audit. The separate variable-depth file count includes previously screened larger surveys; neither count is unique surveyed area or eligible fishing spots.',
            'Native-depth counts are files with some measured cells passing the 25–200 ft and product-uncertainty screen; they are not reef cells and may cover only a small part of a sector.',
            'Variable-depth source counts include reviewed held surveys for audit completeness; use the separate held and unheld counts before choosing a survey for further research.',
            'Points in a latitude band do not establish complete sector coverage; islands and bays require separate local review.',
            'A zero source lead means no qualifying file in this bounded audit, not no reef or fish.',
            'CSUMB catalog-report envelopes are discovery leads only; they are not measured-cell footprints or fishing areas.',
            'USGS DS 781 map-area associations follow broad place names, not inspected original grid footprints. Linked products are acquisition leads, not surveyed area or fishable marks.',
            'USGS FGDC metadata rights, spacing and datum values are source descriptions only; a public-domain statement does not validate raster coverage, chart depth or fishing use.',
            'Historical NOAA seabed sample counts are sparse point records, not surveyed area, precise rock positions or current fish.',
            'Every target still requires current legal and safety review; this queue does not grant fishing or navigation clearance.',
        ],
        'sectors': rows,
    })
