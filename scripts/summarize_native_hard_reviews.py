"""Publish provenance and coverage of native-cell reviews without fishing coordinates."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def summarize(paths):
    surveys = []
    for path in paths:
        review = json.loads(Path(path).read_text())
        if review.get('scope') != 'native-noaa-usgs-hard-bottom-review':
            raise ValueError(f'{path}: not a native hard-bottom review')
        features = review['features']
        if any(item['properties'].get('fishing_target') is not False or
               item['properties'].get('exportable') is not False for item in features):
            raise ValueError(f'{path}: candidate fishing geometry must remain unpublished')
        counts = review['counts']
        if counts['retained_components'] != len(features):
            raise ValueError(f'{path}: component count mismatch')
        surveys.append({
            'survey_id': review['survey_id'], 'survey_dates': review['survey_dates'],
            'compiled_at': review['compiled_at'],
            'noaa_bag_url': review['noaa_bag_url'], 'noaa_bag_sha256': review['noaa_bag_sha256'],
            'survey_report_url': review['survey_report_url'],
            'survey_report_sha256': review['survey_report_sha256'],
            'usgs_sources': review['usgs_sources'],
            'cdfw_mpa_retrieved_at': review['cdfw_mpa_retrieved_at'],
            'native_resolution_m': review['native_resolution_m'],
            'maximum_planning_depth_ft': review['maximum_planning_depth_ft'],
            'bag_tracking_history': review['bag_tracking_history'],
            'counts': counts,
            'retained_component_area_m2': sum(f['properties']['area_m2'] for f in features),
            'fishing_target': False, 'legal_clearance': False, 'exportable': False,
        })
    ids = [x['survey_id'] for x in surveys]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate survey in review summary')
    return {'schema_version': 1, 'scope': 'native-noaa-usgs-review-summary',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'surveys': sorted(surveys, key=lambda x: x['survey_id']),
            'limitations': ['Historical review components are not fishing waypoints, verified fish habitat, or safe navigation areas.',
                            'Regional and federal closures, current hazards, current local rules, route and trip conditions require separate review.',
                            'Component counts and areas may overlap between surveys and must not be summed as unique coast coverage.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = summarize(args.review)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, indent=2) + '\n')
    temp.replace(args.output)
    print(f"Reviewed {len(result['surveys'])} source surveys")


if __name__ == '__main__':
    main()
