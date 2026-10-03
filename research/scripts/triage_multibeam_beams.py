#!/usr/bin/env python3
"""Check official mblist beam tables against verified native acquisition gaps.

Research only: irregular soundings do not establish gridded coverage, habitat,
source qualification, publication permission or fishing locations.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

from research.scripts.discover_noaa_multibeam_footprints import gap_sectors

COLUMNS = ['beam_longitude', 'beam_latitude', 'positive_down_depth_m',
           'beam_flag', 'epoch_s', 'ping_number', 'beam_number']
MAX_BYTES = 256_000_000
MAX_ROWS = 2_000_000
MAX_GAP_QUERY_BYTES = 32_000_000


def load_native_gap_query(path, expected_sha256):
    """Use a coordinator-pinned research mask without copying its raster cache.

    The pin proves the selected snapshot's identity, not that its inputs remain
    current. Rebuild/recheck the native snapshot before claiming new coverage.
    """
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('Saved native gap query requires an explicit SHA256 pin')
    path = Path(path)
    if path.stat().st_size > MAX_GAP_QUERY_BYTES:
        raise ValueError('Saved native gap query exceeds read bound')
    with path.open('rb') as stream:
        raw = stream.read(MAX_GAP_QUERY_BYTES + 1)
    if len(raw) > MAX_GAP_QUERY_BYTES:
        raise ValueError('Saved native gap query exceeds read bound')
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Saved native gap query hash mismatch')
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError('Malformed saved native gap query')
    snapshot, groups = payload.get('coverage_snapshot'), payload.get('groups')
    hashes = ('cells_sha256', 'physical_input_hash', 'checkpoint_sha256',
              'native_support_inputs_sha256', 'native_support_sha256', 'retained_run_sha256')
    if (not isinstance(snapshot, dict)
            or not isinstance(snapshot.get('reach'), str) or not snapshot['reach']
            or any(not re.fullmatch('[0-9a-f]{64}', str(snapshot.get(key, ''))) for key in hashes)):
        raise ValueError('Saved gap query lacks checked native snapshot identity')
    deep_keys = ('measured_deep_mask_sha256', 'measured_deep_method', 'excluded_non_target_query_m2')
    deep_area = snapshot.get('excluded_non_target_query_m2')
    if any(key in snapshot for key in deep_keys) and (
            not re.fullmatch('[0-9a-f]{64}', str(snapshot.get('measured_deep_mask_sha256', '')))
            or snapshot.get('measured_deep_method') != 'valid-native-depth-above-91.44m-v1'
            or isinstance(deep_area, bool) or not isinstance(deep_area, (float, int))
            or not math.isfinite(deep_area) or deep_area < 0):
        raise ValueError('Saved gap query has invalid measured-deep identity')
    if not isinstance(groups, list) or len(groups) > 10_000:
        raise ValueError('Malformed or excessive saved gap groups')
    seen = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError('Malformed saved gap group')
        ident, geometry = group.get('id'), group.get('query_geometry')
        if (not isinstance(ident, str)
                or not re.fullmatch(re.escape(snapshot['reach']) + r'-gap-\d{4,}', ident)
                or ident in seen):
            raise ValueError('Duplicate or mixed-reach saved gap group')
        if (not isinstance(geometry, dict)
                or geometry.get('spatialReference') != {'wkid': 3310}):
            raise ValueError('Saved gap query must use EPSG3310')
        esri_polygon(geometry)  # Validate topology; never repair or discard holes.
        seen.add(ident)
    return groups, snapshot


def validate_reader_receipt(metadata):
    command = metadata.get('command')
    binary_hash = metadata.get('binary_sha256', '')
    if (not isinstance(binary_hash, str) or not re.fullmatch('[0-9a-f]{64}', binary_hash)
            or not isinstance(command, list) or not all(isinstance(v, str) for v in command)):
        raise ValueError('Missing official reader command/hash')
    indexes = [i for i, value in enumerate(command) if Path(value).name == 'mblist']
    if len(indexes) != 1:
        raise ValueError('Receipt is not an mblist beam export')
    options = command[indexes[0]+1:]
    allowed = {'-MA', '-OXYzFMN#', '-V', '-P1', '-K1', '-U0', '-U2'}
    if (options.count('-MA') != 1 or options.count('-OXYzFMN#') != 1
            or len([v for v in options if re.fullmatch(r'-F[1-9][0-9]*', v)]) != 1
            or len([v for v in options if v.startswith('-I') and len(v) > 2]) != 1
            or any(v not in allowed and not re.fullmatch(r'-F[1-9][0-9]*', v)
                   and not (v.startswith('-I') and len(v) > 2) for v in options)):
        raise ValueError('Reader export must preserve beam positions, meters and sampling')


def esri_polygon(geometry):
    """Honor Esri clockwise exteriors and counterclockwise holes, without repair."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    rings = geometry.get('rings', [])
    shells, holes = [], []
    if not rings:
        raise ValueError('Missing query polygon rings')
    for ring in rings:
        if len(ring) < 4 or ring[0] != ring[-1]:
            raise ValueError('Unclosed query polygon ring')
        polygon = Polygon(ring)
        if not polygon.is_valid or polygon.area == 0:
            raise ValueError('Invalid query polygon ring')
        # GEOS orientation avoids cancellation for tiny slivers at large
        # projected coordinates. A naive shoelace sum can reverse their sign.
        (holes if polygon.exterior.is_ccw else shells).append(polygon)
    if not shells:
        raise ValueError('Query polygon has no exterior')
    assigned = [[] for _ in shells]
    for hole in holes:
        owners = [i for i, shell in enumerate(shells) if shell.covers(hole)]
        if not owners:
            raise ValueError('Query hole is outside exteriors')
        assigned[min(owners, key=lambda i: shells[i].area)].append(hole.exterior.coords)
    result = unary_union([Polygon(shell.exterior.coords, inside)
                          for shell, inside in zip(shells, assigned)])
    if result.is_empty or not result.is_valid:
        raise ValueError('Invalid query polygon')
    return result


def triage(table, receipt, coverage_folder=None, *, cache_root=None, table_kind='shallow',
           gap_query=None, gap_query_sha256=None,
           exclude_measured_deep=False, max_bytes=MAX_BYTES, max_rows=MAX_ROWS):
    import numpy as np
    import shapely
    from shapely.ops import unary_union
    from pyproj import Transformer

    table, receipt = Path(table), Path(receipt)
    if receipt.stat().st_size > 1_000_000:
        raise ValueError('Beam receipt exceeds read bound')
    receipt_raw = receipt.read_bytes()
    metadata = json.loads(receipt_raw)
    if not isinstance(metadata, dict):
        raise ValueError('Malformed beam receipt')
    if metadata.get('columns') != COLUMNS:
        raise ValueError('Unexpected beam columns or depth units')
    validate_reader_receipt(metadata)
    if table_kind not in ('all', 'shallow'):
        raise ValueError('Unknown beam table kind')
    key = 'shallow_sha256' if table_kind == 'shallow' else 'stdout_sha256'
    expected = metadata.get(key, '')
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('Missing checked beam table hash')
    count_key = 'good_nominal_shallow_rows' if table_kind == 'shallow' else 'rows'
    expected_rows = metadata.get(count_key)
    if type(expected_rows) is not int or not 0 <= expected_rows <= max_rows:
        raise ValueError('Missing or excessive beam row count')

    if gap_query is not None:
        if coverage_folder is not None or cache_root is not None or exclude_measured_deep:
            raise ValueError('Saved gap query cannot be mixed with cache-based mask options')
        sectors, snapshot = load_native_gap_query(gap_query, gap_query_sha256)
    else:
        if coverage_folder is None or gap_query_sha256 is not None:
            raise ValueError('Choose a coverage folder or a pinned saved native gap query')
        sectors, snapshot = gap_sectors(Path(coverage_folder), cache_root=cache_root,
                                       exclude_measured_deep=exclude_measured_deep)
    polygons = [(s['id'], esri_polygon(s['query_geometry'])) for s in sectors]
    gaps = unary_union([g for _, g in polygons])
    project = Transformer.from_crs(4326, 3310, always_xy=True)
    rows = byte_count = good = inside_count = rejected_flag = rejected_depth = 0
    per_sector = {ident: 0 for ident, _ in polygons}
    low, high = math.inf, -math.inf
    bounds = [math.inf, math.inf, -math.inf, -math.inf]
    digest = hashlib.sha256()
    chunk = []

    def consume():
        nonlocal inside_count, low, high
        if not chunk:
            return
        a = np.asarray(chunk)
        x, y = project.transform(a[:, 0], a[:, 1])
        mask = shapely.intersects_xy(gaps, x, y)
        chosen = a[mask]
        inside_count += len(chosen)
        if len(chosen):
            low, high = min(low, float(chosen[:, 2].min())), max(high, float(chosen[:, 2].max()))
            bounds[0] = min(bounds[0], float(chosen[:, 0].min()))
            bounds[1] = min(bounds[1], float(chosen[:, 1].min()))
            bounds[2] = max(bounds[2], float(chosen[:, 0].max()))
            bounds[3] = max(bounds[3], float(chosen[:, 1].max()))
        for ident, polygon in polygons:
            per_sector[ident] += int(shapely.intersects_xy(polygon, x, y).sum())
        chunk.clear()

    opener = gzip.open if table.suffix == '.gz' else open
    with opener(table, 'rb') as stream:
        while line := stream.readline(min(max_bytes + 1, 4097)):
            byte_count += len(line)
            if byte_count > max_bytes or len(line) > 4096:
                raise ValueError('Beam table exceeds byte/line bound')
            digest.update(line)
            if not line.strip():
                continue
            rows += 1
            if rows > max_rows:
                raise ValueError('Beam table exceeds row bound')
            try:
                values = [float(v) for v in line.split()]
            except ValueError as error:
                raise ValueError('Malformed beam table') from error
            if len(values) != 7 or not all(math.isfinite(v) for v in values):
                raise ValueError('Malformed or nonfinite beam row')
            lon, lat, depth, flag, epoch, ping, beam = values
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError('Invalid beam coordinates')
            if not all(v >= 0 and v.is_integer() for v in (flag, ping, beam)):
                raise ValueError('Invalid beam flag or identifier')
            if flag != 0:
                rejected_flag += 1
            elif not 0 < depth <= 91.44:
                rejected_depth += 1
            else:
                good += 1
                chunk.append((lon, lat, depth))
                if len(chunk) == 10_000:
                    consume()
            if table_kind == 'shallow' and (flag != 0 or not 0 < depth <= 91.44):
                raise ValueError('Shallow subset contains invalid/deep beams')
    consume()
    if digest.hexdigest() != expected or rows != expected_rows:
        raise ValueError('Beam table hash or row count mismatch')
    return {'schema_version': 1, 'scope': 'original-multibeam-beam-gap-triage',
            'observed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'beam_receipt_sha256': hashlib.sha256(receipt_raw).hexdigest(),
            'beam_table_sha256': digest.hexdigest(), 'table_kind': table_kind,
            **({'gap_query_sha256': gap_query_sha256} if gap_query is not None else {}),
            'coverage_snapshot': snapshot, 'evaluated_beam_rows': rows,
            'good_nominal_shallow_rows': good,
            'rejected_flag_rows': rejected_flag, 'rejected_depth_rows': rejected_depth,
            'good_shallow_rows_in_gaps': inside_count,
            'by_gap_group': {k: v for k, v in per_sector.items() if v},
            'gap_depth_min_m': low if inside_count else None,
            'gap_depth_max_m': high if inside_count else None,
            'gap_beam_bounds_wgs84': bounds if inside_count else None,
            'fishing_target': False, 'exportable': False,
            'new_measured_km2': 0, 'new_physical_candidates': 0, 'new_public_locations': 0,
            'limitations': ['Soundings are acquisition evidence, not gridded area or habitat.',
                            'Source datum, uncertainty, navigation and rights require separate review.',
                            'Overlapping soundings are not independent survey evidence.',
                            'Shallow-only tables cannot assess excluded beam quality.',
                            *(['Pinned research snapshot is not proof of current coverage; '
                               'recheck its native inputs before processing or publication.']
                              if gap_query is not None else [])]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--beam-table', type=Path, required=True)
    parser.add_argument('--beam-receipt', type=Path, required=True)
    parser.add_argument('--table-kind', choices=('all', 'shallow'), default='shallow')
    masks = parser.add_mutually_exclusive_group(required=True)
    masks.add_argument('--coverage-folder', type=Path)
    masks.add_argument('--native-gap-query', type=Path,
                       help='Private saved groups/coverage_snapshot from checked native gap_sectors')
    parser.add_argument('--native-gap-query-sha256', help='Required coordinator pin for the saved mask')
    parser.add_argument('--cache-root', type=Path)
    parser.add_argument('--exclude-measured-deep', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = triage(args.beam_table, args.beam_receipt, args.coverage_folder,
                    cache_root=args.cache_root, table_kind=args.table_kind,
                    gap_query=args.native_gap_query, gap_query_sha256=args.native_gap_query_sha256,
                    exclude_measured_deep=args.exclude_measured_deep)
    from skippercast.platform.contracts import atomic_json
    atomic_json(args.output, result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
