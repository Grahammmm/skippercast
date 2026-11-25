#!/usr/bin/env python3
"""Report North C's configured release bounds and preview centers, not coverage."""

import argparse
import json
from pathlib import Path

from skippercast.platform.contracts import bbox
from skippercast.relief.package import decode_document, validate_schema

ROOT = Path(__file__).resolve().parents[2]
NORTH_C = ('trinidad-klamath', 'crescent-city')
OREGON_LATITUDE = 42.0
KM_PER_LATITUDE_DEGREE = 111.195  # mean meridional distance on a spherical Earth


def _read(path):
    return decode_document(path.read_bytes())


def camera_reach(root: Path) -> dict:
    """Read only configured previews; do not resolve styles or synthesize cameras."""
    schema = _read(root / 'schemas/sc-render-v1.schema.json')
    release_regions = {}
    centers = []
    for region_id in NORTH_C:
        directory = root / 'regions' / region_id
        region = _read(directory / 'region.json')
        if region.get('id') != region_id:
            raise ValueError(f'{region_id}/region.json: region id mismatch')
        bounds = bbox(region['bounds'])
        release_regions[region_id] = {'name': region['name'], 'bounds_wsen': bounds}

        render = _read(directory / 'render.json')
        validate_schema(render, schema)
        if render['region'] != region_id:
            raise ValueError(f'{region_id}/render.json: region id mismatch')
        west, south, east, north = bounds
        for row in render['previews']:
            lon, lat = row['center']
            if not (west <= lon <= east and south <= lat <= north):
                raise ValueError(f"{region_id}/render.json: preview {row['id']} center is outside region bounds")
            centers.append({'region_id': region_id, 'preview_id': row['id'], 'center_lon_lat': row['center']})

    if (release_regions['crescent-city']['bounds_wsen'][3] != OREGON_LATITUDE
            or release_regions['trinidad-klamath']['bounds_wsen'][3] >= OREGON_LATITUDE):
        raise ValueError('North C release bounds must end at the Oregon anchor (42.0 N) in crescent-city')
    if not centers:
        raise ValueError('North C has no configured preview centers')
    northernmost = max(centers, key=lambda row: row['center_lon_lat'][1])
    separation = abs(OREGON_LATITUDE - northernmost['center_lon_lat'][1])
    return {
        'release': {'oregon_anchor_latitude_deg': OREGON_LATITUDE, 'regions': release_regions},
        'preview': {
            'northernmost_center': northernmost,
            'latitude_separation_deg': round(separation, 8),
            'latitude_separation_km_approx': round(separation * KM_PER_LATITUDE_DEGREE, 2),
        },
        'scope': 'Configuration only. Preview centers and views are not coverage evidence.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='checkout containing the region configs')
    args = parser.parse_args(argv)
    try:
        report = camera_reach(args.root)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
