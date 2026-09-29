"""Merge independently screened NOAA VR-BAG receipts into a statewide source inventory.

Counts describe measured cells within approximate browse envelopes, not fish
habitat, complete survey coverage, or unique seabed area. Overlapping surveys
remain separate source-cell counts and are never summed into square kilometers.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


COUNT_KEYS = ('fine_native_grids', 'measured_native_cells',
              'depth_uncertainty_eligible_cells')


def merge(reviews, sectors):
    expected = {row['id'] for row in sectors['sectors']}
    if len(expected) != len(sectors['sectors']) or len(expected) < 19:
        raise ValueError('Complete nonduplicate California sector catalog required')
    files = []
    seen = set()
    for review in reviews:
        if (review.get('scope') != 'california-original-vr-native-depth-review'
                or review.get('status') != 'ok'
                or review.get('survey_file_count') != len(review.get('files', []))
                or {row['sector_id'] for row in review.get('sectors', [])} != expected):
            raise ValueError('Incomplete or failed original BAG review')
        for row in review['files']:
            if row.get('status') != 'ok' or row.get('gdal_geolocation_probes', 0) < 1:
                raise ValueError('Unverified native BAG file')
            identity = (row['survey_id'], row['bag_url'])
            if identity in seen:
                raise ValueError('Duplicate original BAG across reviews: ' + row['survey_id'])
            seen.add(identity)
            if not set(row.get('sectors', {})) <= expected:
                raise ValueError('Original BAG assigned to unknown sector')
            files.append(row)
    result = []
    for sector in sectors['sectors']:
        ident = sector['id']
        contributors = [row for row in files if row['sectors'].get(ident, {}).get(
            'depth_uncertainty_eligible_cells', 0) > 0]
        result.append({'sector_id': ident,
                       'survey_ids_with_eligible_cells': sorted({r['survey_id'] for r in contributors}),
                       'source_files_with_eligible_cells': len(contributors),
                       **{key: sum(row['sectors'].get(ident, {}).get(key, 0)
                                   for row in files) for key in COUNT_KEYS}})
    return {'schema_version': 1, 'scope': 'california-expanded-original-vr-depth-inventory',
            'merged_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'source_review_count': len(reviews), 'survey_file_count': len(files),
            'source_review_times': [r['screened_at'] for r in reviews],
            'sectors': result,
            'files': [{'survey_id': r['survey_id'], 'bag_url': r['bag_url'],
                       'bag_sha256': r['bag_sha256'], 'survey_dates': r['survey_dates'],
                       'source_report_url': r['source_report_url'],
                       'counts': r['counts'], 'sectors': r['sectors']}
                      for r in sorted(files, key=lambda row: (row['survey_id'], row['bag_url']))],
            'fishing_target': False, 'exportable': False,
            'limitations': [
                'Only explicitly screened original NOAA MLLW BAG files are counted; other or unavailable surveys remain gaps.',
                'A survey rectangle or name does not establish depth coverage. Browse-sector assignment uses native supergrid centers.',
                'The same seafloor may appear in overlapping surveys; cell counts are workloads, not unique coverage or area.',
                'No substrate, fish presence, current chart, MPA/GEA, access route or local species rules are established by this depth inventory.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, action='append')
    parser.add_argument('--manifest', type=Path,
                        help='Reviewed repo-relative input list for repeatable statewide refreshes')
    parser.add_argument('--sectors', type=Path, default=Path('dist/data/coastal-sectors.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = list(args.review or [])
    if args.manifest:
        manifest = json.loads(args.manifest.read_text())
        if (manifest.get('scope') != 'california-original-vr-depth-review-inputs'
                or not manifest.get('review_files')
                or len(set(manifest['review_files'])) != len(manifest['review_files'])):
            raise ValueError('Incomplete or duplicate native-depth review manifest')
        for name in manifest['review_files']:
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or path.suffix != '.json':
                raise ValueError('Native-depth review path must be repo-relative JSON')
            paths.append(path)
    if not paths:
        parser.error('Supply --manifest or at least one --review')
    result = merge([json.loads(p.read_text()) for p in paths],
                   json.loads(args.sectors.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temp.replace(args.output)
    print(result['survey_file_count'], 'original BAG files merged')


if __name__ == '__main__':
    main()
