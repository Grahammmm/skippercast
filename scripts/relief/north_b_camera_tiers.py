#!/usr/bin/env python3
"""Compare configured North B preview zooms to saved public candidate ceilings.

This is a metadata comparison, not a check for camera support, tile existence,
or the effective maxzoom of any render. No raster references are read.
"""

import argparse
import json
from pathlib import Path
from typing import cast

from skippercast.relief import receipts, render_config
from skippercast.relief.package import artifact_path

NORTH_B = (
    'fort-bragg-point-arena',
    'shelter-cove-north-mendocino',
    'humboldt-bay-cape-mendocino',
)
NATIVE_TABLE = 'select/native.json'


def _saved_ceiling(region):
    """Read only the saved selector metadata, not upstream inputs or outputs."""
    try:
        doc = receipts.read_receipt(region.receipt_path('select'))
        if doc is None:
            return 'missing_receipt', None
        # select is an unscoped stage; its native table is public-only.
        if receipts.validate_receipt(doc, region.id, 'select', None) or doc['status'] != 'ok':
            return 'unusable_receipt', None
        pins = [row for row in doc['outputs'] if row['path'] == NATIVE_TABLE]
        if len(pins) != 1:
            return 'unusable_metadata', None
        data = artifact_path(region.dir, NATIVE_TABLE).read_bytes()
        if len(data) != pins[0]['bytes'] or receipts.sha256_bytes(data) != pins[0]['sha256']:
            return 'unusable_metadata', None
        rows = json.loads(data)
    except (OSError, ValueError):
        return 'unreadable_selection', None
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or row.get('rights_class') != 'public' for row in rows
    ):
        return 'unusable_metadata', None
    ceilings = [z for row in rows if type(z := row.get('max_zoom')) is int and 8 <= z <= 17]
    if not ceilings:
        return 'no_usable_ceilings', None
    return 'recorded', max(ceilings)


def compare_cameras(selection_root: Path) -> dict:
    """Read saved metadata under OUT/<region> and report all configured previews.

    A null review-only flag means comparison was unavailable; false means only
    that the camera did not exceed the greatest recorded candidate ceiling.
    """
    regions = []
    for region_id in NORTH_B:
        status, ceiling = _saved_ceiling(receipts.Region(selection_root, region_id))
        cameras = []
        for camera in render_config.previews(region_id):
            zoom = cast(int, camera['zoom'])  # Validated by the render recipe reader.
            cameras.append({'id': camera['id'], 'zoom': zoom,
                            'review_only_candidate': None if ceiling is None else zoom > ceiling})
        regions.append({'region': region_id, 'selection_status': status,
                        'usable_candidate_ceilings_present': ceiling is not None,
                        'greatest_recorded_candidate_ceiling': ceiling, 'cameras': cameras})
    return {
        'basis': 'Saved public candidate metadata only; camera support and raster tiles were not assessed.',
        'regions': regions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection-root', type=Path, required=True,
                        help='OUT directory containing the saved per-region select receipts and metadata')
    args = parser.parse_args(argv)
    print(json.dumps(compare_cameras(args.selection_root), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
