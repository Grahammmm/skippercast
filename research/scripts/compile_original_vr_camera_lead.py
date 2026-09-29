"""Publish coordinate-free evidence for an original NOAA VR BAG/camera lead.

This joins separately audited native cells, complete-footprint MPAs, historical
camera overlap, NBS comparison and hazard proximity without promoting targets.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def compile_review(audit, native, mpa, camera, reconciliation, hazards):
    originals = audit.get('files', [])
    native_files = native.get('files', [])
    if (len(originals) != 1 or len(native_files) != 1
            or audit.get('health', {}).get('status') != 'ok' or native.get('status') != 'ok'):
        raise ValueError('One successful original BAG and native-cell audit required')
    original, measured = originals[0], native_files[0]
    survey = original['survey_id']
    digest = original['file_sha256']
    if (original.get('status') != 'ok' or original.get('metadata_status') != 'mllw-product-uncertainty-reviewed-by-adapter'
            or original.get('vertical_datum') != 'MLLW' or original.get('uncertainty_type') != 'productUncert'
            or measured.get('status') != 'ok' or measured.get('survey_id') != survey
            or measured.get('bag_sha256') != digest
            or mpa.get('survey_id') != survey or mpa.get('bag_sha256') != digest
            or camera.get('survey_id') != survey or camera.get('bag_sha256') != digest
            or reconciliation.get('original_survey_id') != survey
            or reconciliation.get('original_bag_sha256') != digest
            or hazards.get('survey_id') != survey or hazards.get('original_bag_sha256') != digest):
        raise ValueError('Original survey identity or source digest changed')
    if (mpa.get('fishing_target') is not False or camera.get('fishing_target') is not False
            or reconciliation.get('fishing_target') is not False or hazards.get('fishing_target') is not False
            or hazards.get('present_chart_and_route_cleared') is not False):
        raise ValueError('Research reviews must not claim target or chart clearance')
    protection = mpa['counts']
    if (protection['fine_grid_centers_in_region'] != sum(protection[k] for k in
            ('fully_inside_mpa', 'intersects_mpa', 'outside_mpa'))
            or not 0 < protection['fine_grid_centers_in_region'] <= original['refinement_grids_at_most_4m']):
        raise ValueError('Incomplete native-grid MPA accounting')
    original_windows = sum(row['historical_camera_windows'] for row in reconciliation['comparison']
                           if row['nbs_status'] == 'locally_qualified_90pct'
                           and row['original_bag_status'] == 'original_locally_qualified_90pct')
    if original_windows != hazards['original_qualified_historical_camera_windows']:
        raise ValueError('Camera/hazard review counts disagree')
    source_counts = measured['counts']
    return {'schema_version': 1, 'scope': 'original-vr-camera-held-source-lead',
        'compiled_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'survey_id': survey, 'original_bag_url': original['url'],
        'original_bag_sha256': digest, 'original_report_url': original['source_report_url'],
        'source_vertical_datum': 'MLLW', 'source_uncertainty_type': 'productUncert',
        'native_resolution_m_range': original['refinement_resolution_range_m'],
        'native_fine_grids': original['refinement_grids_at_most_4m'],
        'measured_native_cell_associations': source_counts['measured_native_cells'],
        'depth_uncertainty_eligible_cell_associations': source_counts['depth_uncertainty_eligible_cells'],
        'regional_mpa_grid_screen': protection,
        'historical_camera_window_screen': camera['counts'],
        'historical_camera_interior_bottom_classes': camera['matched_bottom_classes']['native_grid_interior'],
        'selected_nbs_tile': reconciliation['tile'],
        'selected_nbs_rocky_camera_windows': reconciliation['counts']['rocky_camera_windows_in_tile_envelope'],
        'nbs_and_original_bag_qualified_rocky_windows': original_windows,
        'report_danger_count': hazards['historical_report_dangers'],
        'enc_danger_layers_queried': hazards['enc_query_layers'],
        'enc_danger_features_in_scope': hazards['enc_features'],
        'minimum_historical_danger_distance_m_range': hazards['minimum_historical_danger_distance_m_range'],
        'minimum_charted_danger_distance_m_range': hazards['minimum_charted_danger_distance_m_range'],
        'minimum_mpa_distance_m_range': hazards['minimum_mpa_distance_m_range'],
        'cdfw_mpa_retrieved_at': hazards['cdfw_mpa_retrieved_at'],
        'report_danger_review_hold': True, 'present_chart_and_route_cleared': False,
        'habitat_footprint_verified': False, 'fishing_target': False, 'exportable': False,
        'limitations': [
            'Native cell totals are survey/sector workload associations and can overlap; they are not unique mapped seafloor area or complete fishing depth clearance.',
            'Historical camera windows are correlated transect records, not separate reefs, present fish counts or exact hard-bottom polygons.',
            'The bounded selected ENC danger classes, historical report positions and dated MPA geometry do not certify a present chart, safe route, every closure or trip-date legal take.',
            'The original descriptive report has no bottom samples and lists historical dangers; independent substrate footprint and site review remain open.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('audit', 'native', 'mpa', 'camera', 'reconciliation', 'hazards', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--verify', type=Path,
                        help='Reviewed public baseline; changed source evidence fails for review')
    args = parser.parse_args()
    result = compile_review(*(json.loads(getattr(args, key).read_text()) for key in
        ('audit', 'native', 'mpa', 'camera', 'reconciliation', 'hazards')))
    if args.verify:
        baseline = json.loads(args.verify.read_text())
        stable = lambda packet: {key: value for key, value in packet.items()
                                 if key not in ('compiled_at', 'cdfw_mpa_retrieved_at')}
        if stable(result) != stable(baseline):
            raise ValueError('Original VR camera source evidence changed; review before publication')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, indent=2) + '\n')
    temp.replace(args.output)
    print(json.dumps({'survey_id': result['survey_id'],
        'native_grids': result['native_fine_grids'],
        'original_qualified_rocky_windows': result['nbs_and_original_bag_qualified_rocky_windows']}))


if __name__ == '__main__':
    main()
