"""Test exact original NOAA VR-BAG refinements for the nearshore depth band.

Use this bounded source triage when a survey-track envelope crosses a sector.
It identifies deep-water false leads without making fishing or chart claims.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import h5py
import numpy as np

from skippercast.platform.bottom_targets import bag_metadata, sha256


MAX_BYTES = 50_000_000
DEPTH_MIN_M, DEPTH_MAX_M = 25 * .3048, 200 * .3048


def source_path(record, cache):
    return cache / (record['survey_id'] + '-' + hashlib.sha256(record['url'].encode()).hexdigest()[:16] + '.bag')


def acquire(record, cache, fetch):
    url = record['url']
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname != 'data.ngdc.noaa.gov'
            or not parts.path.endswith(f"/{record['survey_id']}_MB_VR_MLLW.bag")
            or not 0 < record['file_bytes'] <= MAX_BYTES):
        raise ValueError('Unreviewed or oversized original BAG URL')
    path = source_path(record, cache)
    if not path.is_file():
        if not fetch:
            raise FileNotFoundError(f'Missing original NOAA BAG: {path.name}')
        cache.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.partial')
        try:
            with urlopen(Request(url, headers={'User-Agent': 'SkipperCast native depth source review/1.0'}),
                         timeout=90) as response, temporary.open('wb') as output:
                if response.status != 200 or urlsplit(response.url).hostname != parts.hostname:
                    raise ValueError('Original NOAA BAG redirected or failed')
                copied = 0
                while chunk := response.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > MAX_BYTES:
                        raise ValueError('Original NOAA BAG exceeds bound')
                    output.write(chunk)
            if copied != record['file_bytes'] or sha256(temporary) != record['file_sha256']:
                raise ValueError('Downloaded NOAA BAG changed')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if path.stat().st_size != record['file_bytes'] or sha256(path) != record['file_sha256']:
        raise ValueError('Original NOAA BAG size or checksum changed')
    return path


def screen(record, cache, fetch=False):
    path = acquire(record, cache, fetch)
    with h5py.File(path, 'r') as bag:
        root = bag['BAG_root']
        metadata = bag_metadata(root['metadata'][:].tobytes().decode().rstrip('\0'),
                                record['survey_id'])
        if metadata['metadata_sha256'] != record['metadata_sha256'] or metadata['vertical_datum'] != 'MLLW':
            raise ValueError('Original BAG metadata or MLLW datum changed')
        grids = root['varres_metadata'][:]
        values = root['varres_refinements']
        if (grids.ndim != 2 or values.ndim != 2 or values.shape[0] != 1
                or not {'index', 'dimensions_x', 'dimensions_y', 'resolution_x', 'resolution_y'} <= set(grids.dtype.names or ())
                or not {'depth', 'depth_uncrt'} <= set(values.dtype.names or ())):
            raise ValueError('Original variable-resolution layout changed')
        active = (grids['dimensions_x'] > 0) & (grids['dimensions_y'] > 0)
        selected = grids[active]
        if not len(selected):
            raise ValueError('No original refinement grids')
        starts = selected['index'].astype('int64')
        ends = starts + selected['dimensions_x'].astype('int64') * selected['dimensions_y'].astype('int64')
        order = np.argsort(starts)
        if (starts[order][0] != 0 or np.any(starts[order][1:] != ends[order][:-1])
                or ends[order][-1] > values.shape[1]):
            raise ValueError('Original refinement cells are incomplete or overlapping')
        resolution = np.maximum(selected['resolution_x'], selected['resolution_y'])
        if not np.all(np.isfinite(resolution) & (resolution > 0)):
            raise ValueError('Invalid original grid resolution')
        valid_count = 0
        nearshore_count = 0
        min_elevation = float('inf')
        max_elevation = float('-inf')
        for start in range(0, values.shape[1], 500_000):
            batch = values[0, start:min(start + 500_000, values.shape[1])]
            depth = batch['depth']
            valid = depth[np.isfinite(depth) & (depth < 0) & (depth > -3000)]
            if not len(valid):
                continue
            valid_count += len(valid)
            nearshore_count += int(np.count_nonzero((valid <= -DEPTH_MIN_M) & (valid >= -DEPTH_MAX_M)))
            min_elevation = min(min_elevation, float(valid.min()))
            max_elevation = max(max_elevation, float(valid.max()))
        if not valid_count:
            raise ValueError('Original refinement array has no measured underwater depth')
        return {'survey_id': record['survey_id'], 'bag_url': record['url'],
                'bag_sha256': record['file_sha256'], 'metadata_sha256': record['metadata_sha256'],
                'survey_start': record['survey_start'], 'survey_end': record['survey_end'],
                'source_report_url': record['source_report_url'],
                'original_refinement_grids': len(selected),
                'original_refinement_records': int(values.shape[1]),
                'measured_depth_cells': valid_count,
                'shallowest_elevation_m_mllw': round(max_elevation, 3),
                'deepest_elevation_m_mllw': round(min_elevation, 3),
                'minimum_native_resolution_m': round(float(resolution.min()), 3),
                'maximum_native_resolution_m': round(float(resolution.max()), 3),
                'raw_cells_in_25_to_200_ft_mllw_band': nearshore_count,
                'nearshore_depth_lead': nearshore_count > 0,
                'fishing_target': False, 'exportable': False}


def compile_review(manifest, cache, fetch=False):
    if (manifest.get('scope') != 'noaa-original-central-coast-deepwater-bag-review-inputs'
            or {row.get('survey_id') for row in manifest.get('sources', [])} != {'H13089', 'H13151'}
            or len(manifest['sources']) != 2):
        raise ValueError('Expected two pinned Central Coast original BAGs')
    rows = [screen(record, cache, fetch) for record in manifest['sources']]
    return {'schema_version': 1, 'scope': 'noaa-original-central-coast-vr-depth-band-screen',
            'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'source_manifest': 'catalog/noaa-central-deepwater-source-screen.json',
            'depth_band_ft_mllw': [25, 200], 'sources': rows,
            'fishing_target': False, 'exportable': False,
            'limitations': [
                'Original survey-track and BAG envelopes cross broad sectors but are not measured nearshore coverage.',
                'A positive depth-band count would still need actual cell position, product uncertainty, native resolution, substrate, legal and chart review before a target.',
                'This source triage does not score fishing, identify chart hazards, clear MPAs or substitute for current nautical charts.',
            ]}


def stable(report):
    return {key: value for key, value in report.items() if key != 'reviewed_at'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, default=Path('catalog/noaa-central-deepwater-source-screen.json'))
    p.add_argument('--cache', type=Path, default=Path('var/noaa-native-cache'))
    p.add_argument('--fetch', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--verify', type=Path)
    args = p.parse_args()
    report = compile_review(json.loads(args.manifest.read_text()), args.cache, args.fetch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit('Original NOAA depth band changed; review before publishing')
    print(json.dumps({'original_bags': len(report['sources']),
                      'nearshore_source_leads': sum(row['nearshore_depth_lead'] for row in report['sources'])}))


if __name__ == '__main__':
    main()
