"""Publish provenance and coverage of native-cell reviews without fishing coordinates."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

if __package__:
    from .summarize_original_camera_chart_lead import (
        count, iso_date, measurement, pair, project, public_id, sha256, source_url, timestamp,
    )
else:  # Keep the documented `python research/scripts/...` invocation working.
    from summarize_original_camera_chart_lead import (
        count, iso_date, measurement, pair, project, public_id, sha256, source_url, timestamp,
    )


def _resolution(value, field):
    result = pair(value, field, measurement)
    if min(result) <= 0:
        raise ValueError(f'{field}: expected positive cell sizes')
    return result


def _acquisition_date(value, field):
    # NOAA's BAG metadata also records time of acquisition without an offset.
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?', value):
        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f'{field}: expected an ISO acquisition date or datetime') from None
        return value
    return iso_date(value, field)


def _usgs_sources(value, field):
    if not isinstance(value, list):
        raise ValueError(f'{field}: expected a source list')
    result = []
    for source in value:
        if not isinstance(source, dict) or len(ids := {'block_id', 'release_id'} & source.keys()) != 1:
            raise ValueError(f'{field}: expected one block or release identifier per source')
        ident, = ids
        result.append(project(source, {
            ident: public_id,
            'archive_url': source_url, 'archive_sha256': sha256,
            'metadata_url': source_url, 'metadata_sha256': sha256,
            'original_resolution_m': _resolution,
        }))
    return result


def _tracking_history(value, field):
    return project(value, {
        'original_values_before_manual_edits': count,
        'depth_values_changed_in_current_grid': count,
        'maximum_depth_revision_m': measurement,
    })


def summarize(paths):
    surveys = []
    for path in paths:
        review = json.loads(Path(path).read_text())
        if not isinstance(review, dict) or review.get('scope') != 'native-noaa-usgs-hard-bottom-review':
            raise ValueError(f'{path}: not a native hard-bottom review')
        features = review.get('features')
        if not isinstance(features, list) or any(
            not isinstance(item, dict) or not isinstance(item.get('properties'), dict)
            or item['properties'].get('fishing_target') is not False
            or item['properties'].get('exportable') is not False for item in features
        ):
            raise ValueError(f'{path}: candidate fishing geometry must remain unpublished')
        counts = project(review.get('counts'), {
            'hard_cells_after_inset': count,
            'depth_uncertainty_qualified_cells': count,
            'hard_depth_cells_after_mpa_gea_historical_hazard_screen': count,
            'retained_components': count,
        })
        if counts['retained_components'] != len(features):
            raise ValueError(f'{path}: component count mismatch')
        area = sum(measurement(item['properties'].get('area_m2'), 'area_m2') for item in features)
        surveys.append({
            **project(review, {
                'survey_id': public_id, 'survey_dates': lambda v, f: pair(v, f, _acquisition_date),
                'compiled_at': timestamp,
                'noaa_bag_url': source_url, 'noaa_bag_sha256': sha256,
                'survey_report_url': source_url, 'survey_report_sha256': sha256,
                'usgs_sources': _usgs_sources,
                'cdfw_mpa_retrieved_at': timestamp, 'noaa_federal_areas_retrieved_at': timestamp,
                'native_resolution_m': _resolution, 'maximum_planning_depth_ft': measurement,
                'bag_tracking_history': _tracking_history,
            }),
            'counts': counts,
            'retained_component_area_m2': measurement(area, 'retained_component_area_m2'),
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
