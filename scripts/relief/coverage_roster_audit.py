"""Compare a saved Coverage page index with the checkout's release roster."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from scripts.relief.coast_coverage import load_regions


def _selectable(row: dict) -> bool:
    """Check the display fields required by dist/coverage-map.js:coverageModel."""
    name, bounds = row.get('name'), row.get('fishing_bounds')
    if (
        not isinstance(name, str) or not name.strip()
        or row.get('status') not in ('active', 'preview')
        or not isinstance(bounds, list) or len(bounds) != 4
        or any(type(value) not in (int, float) for value in bounds)
    ):
        return False
    west, south, east, north = bounds
    return -180 <= west < east <= 180 and -90 <= south < north <= 90


def audit_roster(release_root: Path, index_fixture: Path) -> dict:
    """Check exact release membership against an explicitly supplied local fixture.

    Count matching IDs before filtering display fields so a malformed second row
    cannot hide a duplicate. Row positions in the report are zero-based. The
    fixture's active/preview field describes public selection, not live relief;
    neither the app coverage snapshot nor a relief pointer is used as a substitute.
    """
    release_ids = set(load_regions(release_root)['release'])
    index = json.loads(index_fixture.read_text(encoding='utf-8'))
    if not isinstance(index, dict) or not isinstance(index.get('regions'), list):
        raise ValueError('Coverage index fixture must contain a regions array')

    counts: Counter[str] = Counter()
    invalid_rows = []
    invalid_release_ids = set()
    selectable = []
    for position, row in enumerate(index['regions']):
        region_id = row.get('id') if isinstance(row, dict) else None
        # Use canonical slug identity as in coast_coverage, not display names or
        # the frontend's looser shape check for IDs in links.
        if not isinstance(region_id, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', region_id):
            invalid_rows.append(position)
            continue
        is_release = region_id in release_ids
        if is_release:
            counts[region_id] += 1
        if not _selectable(row):
            invalid_rows.append(position)
            if is_release:
                invalid_release_ids.add(region_id)
            continue
        status = row['status']
        kind = 'non_release_preview' if status == 'preview' else 'non_release'
        selectable.append({'id': region_id, 'name': row['name'], 'public_status': status,
                           'kind': 'release' if is_release else kind})

    missing = sorted(release_ids - counts.keys())
    duplicates = {region_id: counts[region_id] for region_id in sorted(counts) if counts[region_id] > 1}
    return {
        'release_roster_ok': not (missing or duplicates or invalid_release_ids),
        'release_ids': sorted(release_ids),
        'missing_release_ids': missing,
        'duplicate_release_ids': duplicates,
        'invalid_release_ids': sorted(invalid_release_ids),
        'invalid_rows': invalid_rows,
        'selectable_rows': selectable,
        'm9_live_state': 'not_evaluated',
    }
