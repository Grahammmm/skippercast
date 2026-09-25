"""Screen unpublished San Pedro habitat outlines against NOAA's 50-fm RCA line.

This is a dated research/legal-context screen, not a determination of lawful
fishing at a precise position. The Federal Register and current CDFW notices
control if they disagree with NOAA's mapping CSV.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
from zipfile import ZipFile

from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform


ARCHIVE_URL = 'https://www.fisheries.noaa.gov/s3/2026-09/rca-lines-latlongs-august-2026.zip'
REVIEWED_ARCHIVE_SHA256 = 'afcede8ce6678f344b819a44567871ee872e39b70bba663afc0775424051a122'
CSV_NAME = '50 fm_01012025.csv'


def _signed_side(line, point):
    station = line.project(point)
    before = line.interpolate(max(0, station - 10))
    after = line.interpolate(min(line.length, station + 10))
    return (after.x - before.x) * (point.y - before.y) - (after.y - before.y) * (point.x - before.x)


def audit(archive_bytes, context, *, margin_m=100):
    digest = sha256(archive_bytes).hexdigest()
    if digest != REVIEWED_ARCHIVE_SHA256:
        raise ValueError('NOAA RCA archive changed; review official revision before screening')
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        rows = list(csv.DictReader(io.TextIOWrapper(archive.open(CSV_NAME), encoding='utf-8-sig')))
    coast = [row for row in rows if row['area_name'] == '50-fm (91-m) Contour - Coastwide']
    if not coast or len(coast) < 175:
        raise ValueError('Expected coastwide 50-fm coordinate sequence missing')
    # The published coastwide file repeats IDs 74/75 far north of this scope.
    # Check the relevant mainland run rather than asserting a global sequence.
    local = [row for row in coast if 160 <= int(row['id_area']) <= 180]
    if [int(row['id_area']) for row in local] != list(range(160, 181)):
        raise ValueError('San Pedro mainland 50-fm coordinate sequence changed')
    project = Transformer.from_crs('EPSG:4326', 'EPSG:32611', always_xy=True).transform
    line = transform(project, LineString([(float(row['lon_dd']), float(row['lat_dd'])) for row in coast]))
    # Inland Los Angeles is an unambiguous shoreward reference for this mainland shelf.
    reference = transform(project, Point(-118.25, 33.90))
    reference_side = _signed_side(line, reference)
    if reference_side == 0:
        raise ValueError('Cannot orient the mainland 50-fm line')
    screens = []
    for feature in context['features']:
        footprint = shape(feature['geometry'])
        if not footprint.is_valid or footprint.is_empty:
            raise ValueError('Invalid original-rock outline')
        if not footprint.bounds[0] >= -118.29 or not footprint.bounds[2] <= -118.17 or not footprint.bounds[1] >= 33.60 or not footprint.bounds[3] <= 33.71:
            raise ValueError('Original-rock outline outside reviewed San Pedro scope')
        projected = transform(project, footprint)
        distance = projected.distance(line)
        side = _signed_side(line, projected.representative_point())
        classification = 'boundary-review' if distance <= margin_m or side == 0 else ('shoreward' if side * reference_side > 0 else 'seaward')
        screens.append({'context_id': feature['properties']['id'],
                        'nearest_50fm_line_m': round(distance, 1),
                        'relative_to_legal_50fm_line': classification,
                        'fishing_target': False, 'exportable': False})
    return {'schema_version': 1, 'scope_id': 'san-pedro-ds552-original-rock',
            'source_url': ARCHIVE_URL, 'source_archive_sha256': digest,
            'boundary_file': CSV_NAME, 'boundary_effective_date_in_filename': '2025-01-01',
            'projected_crs': 'EPSG:32611', 'review_margin_m': margin_m,
            'outlines': screens,
            'shoreward_count': sum(s['relative_to_legal_50fm_line'] == 'shoreward' for s in screens),
            'seaward_count': sum(s['relative_to_legal_50fm_line'] == 'seaward' for s in screens),
            'boundary_review_count': sum(s['relative_to_legal_50fm_line'] == 'boundary-review' for s in screens),
            'status': 'research-screen-only',
            'limitations': 'This bounded mainland RCA line screen is not fishing permission. Check current CDFW seasonal rules, in-season changes and the controlling federal coordinates; no area is a qualified target or chartplotter export.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.archive.read_bytes(), json.loads(args.context.read_text()))
    result['audited_at'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(args.output)
    print(json.dumps({key: result[key] for key in ('shoreward_count', 'seaward_count', 'boundary_review_count')}))


if __name__ == '__main__':
    main()
