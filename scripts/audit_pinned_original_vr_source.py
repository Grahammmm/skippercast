"""Download and inspect one SHA-pinned original NOAA VR BAG for camera review."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from scripts.inspect_noaa_bag_grids import download, inspect_file
from skippercast.platform.bottom_targets import source_url_allowed


def audit(spec, cache, *, fetcher=download):
    url, survey = spec['bag_url'], spec['survey_id']
    if (spec.get('status') != 'research-only' or not source_url_allowed(url)
            or not url.endswith('/' + survey + '_MB_VR_MLLW_1of1.bag')
            or not 0 < spec['bag_bytes'] <= 550_000_000
            or len(spec['bag_sha256']) != 64
            or any(c not in '0123456789abcdef' for c in spec['bag_sha256'])):
        raise ValueError('Unreviewed original BAG source identity')
    path = cache / (survey + '-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.bag')
    if not path.is_file():
        fetcher(url, path, spec['bag_bytes'])
    if path.stat().st_size != spec['bag_bytes']:
        raise ValueError('Original BAG size changed')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != spec['bag_sha256']:
        raise ValueError('Original BAG digest changed')
    native = inspect_file(path, survey)
    if (native['metadata_status'] != 'mllw-product-uncertainty-reviewed-by-adapter'
            or native['refinement_grids_at_most_4m'] <= 0):
        raise ValueError('Original BAG has no reviewed fine MLLW/product-uncertainty cells')
    row = {'survey_id': survey, 'url': url, 'source_report_url': spec['report_url'],
           'file_sha256': digest, 'file_bytes': spec['bag_bytes'], 'status': 'ok',
           'inspected_at': datetime.now(timezone.utc).isoformat(), **native}
    return {'schema_version': 1, 'scope': 'noaa-original-bag-native-overview-audit',
            'collected_at': datetime.now(timezone.utc).isoformat(),
            'method': 'SHA-pinned original NOAA BAG opened for embedded MLLW/product uncertainty, valid overview cells and native fine-grid geometry; fishing target and route remain unqualified.',
            'selection': 'One explicit reviewed original VR BAG; no extrapolation to other surveys.',
            'max_bytes': spec['bag_bytes'], 'file_count': 1, 'inspected_count': 1,
            'mllw_metadata_count': 1, 'health': {'status': 'ok', 'issues': []},
            'files': [row]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path('catalog/original-vr-camera-review-sources.json'))
    parser.add_argument('--survey-id', required=True)
    parser.add_argument('--cache', type=Path, default=Path('var/noaa-native-cache'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest.get('schema_version') != 1 or manifest.get('scope') != 'pinned-original-noaa-vr-camera-source-reviews':
        raise ValueError('Wrong pinned original survey manifest')
    matches = [row for row in manifest['sources'] if row.get('survey_id') == args.survey_id]
    if len(matches) != 1:
        raise ValueError('Exactly one reviewed survey ID required')
    result = audit(matches[0], args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temp.replace(args.output)
    print(f"{args.survey_id}: {result['files'][0]['refinement_grids_at_most_4m']} fine native grids")


if __name__ == '__main__':
    main()
