"""Test original USGS camera windows against populated Big Sur South grid cells."""
import argparse
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
import tarfile
import tempfile
from zipfile import ZipFile

import numpy as np
import rasterio
from pyproj import Transformer

from research.lib.paths import ROOT

from research.scripts.audit_csumb_bss_native import acquire
from research.scripts.audit_usgs_video_observations import load_archive, open_original_zip


CRUISE = 'c0212sc'
SEARCH_RADIUS_M = 100


def near_valid_pixel(mask, grid, x, y, radius_m=SEARCH_RADIUS_M):
    """Find a valid original grid pixel center inside the stated metric radius."""
    row, col = grid.index(x, y)
    pad = int(radius_m / min(grid.res)) + 2
    top, bottom = max(0, row - pad), min(grid.height, row + pad + 1)
    left, right = max(0, col - pad), min(grid.width, col + pad + 1)
    rows, cols = np.where(mask[top:bottom, left:right])
    if not len(rows):
        return False
    rows += top
    cols += left
    cx, cy = grid.transform @ (cols + 0.5, rows + 0.5)
    return bool(np.any(np.hypot(cx - x, cy - y) <= radius_m))


def inspect(bss_spec, video_manifest, bss_cache, video_cache, download_video=False):
    survey_id = bss_spec['survey_id']
    if survey_id not in ('BSS_Block01', 'BSS_Block02', 'BSS_Block03',
                         'BSS_Block08', 'BSS_Block12', 'BSS_Block13'):
        raise ValueError('Only the reviewed original Big Sur South blocks are supported')
    archive = acquire(bss_spec, bss_cache, False)
    raw = load_archive(video_cache, CRUISE, video_manifest['archives'][CRUISE],
                       video_manifest['base_url'], download_video)
    with ZipFile(BytesIO(raw)) as source:
        metadata = source.read(next(name for name in source.namelist()
                                    if name.lower().endswith('metadata.txt'))).decode('utf-8', 'replace')
    if 'Highly variable on the order of 10 meters.' not in metadata:
        raise ValueError('Original camera position accuracy changed')
    camera = open_original_zip(raw)
    grid_path = bss_spec['bathymetry_grid']
    habitat_path = bss_spec['habitat_grid']
    with tarfile.open(archive, 'r:gz') as bundle, tempfile.TemporaryDirectory() as directory:
        members = [m for m in bundle.getmembers() if m.isfile() and
                   (m.name.startswith(grid_path + '/') or m.name.startswith(habitat_path + '/'))]
        if not members or sum(m.size for m in members) > 100_000_000:
            raise ValueError('Unexpected original grid members')
        for member in members:
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe archive member')
            target = Path(directory) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.extractfile(member).read())
        with rasterio.open(Path(directory) / grid_path) as grid, rasterio.open(Path(directory) / habitat_path) as habitat:
            if str(grid.crs) != 'EPSG:26910' or tuple(grid.res) != (2.0, 2.0):
                raise ValueError('Original grid reference changed')
            if habitat.crs != grid.crs or habitat.transform != grid.transform or habitat.shape != grid.shape:
                raise ValueError('Original depth and derived terrain grids do not align')
            mask = grid.read_masks(1) > 0
            depth = grid.read(1)
            terrain = habitat.read(1, masked=True)
            rough = (~np.ma.getmaskarray(terrain)
                     & np.isin(terrain.data, (-1, -31, -101, -201)))
            to_grid = Transformer.from_crs('EPSG:4326', grid.crs, always_xy=True)
            counts = Counter()
            dates = set()
            lines = set()
            observed_depths = []
            for item in camera.iterShapeRecords():
                if not item.shape.points:
                    continue
                x, y = to_grid.transform(*item.shape.points[0])
                if not (grid.bounds.left <= x < grid.bounds.right
                        and grid.bounds.bottom < y <= grid.bounds.top):
                    continue
                counts['camera_records_inside_raster_bounds'] += 1
                row = item.record.as_dict()
                bottom = str(row.get('MAJOR_GEO') or '').strip().lower()
                if bottom:
                    counts['interpreted_bottom_windows'] += 1
                    if bottom in ('rock', 'boulder', 'cobble'):
                        counts['rock_boulder_cobble_windows'] += 1
                    if row.get('rockfish', 0) > 0:
                        counts['rockfish_positive_windows'] += 1
                    if row.get('lingcod', 0) > 0:
                        counts['lingcod_positive_windows'] += 1
                    if row.get('Date_'):
                        dates.add(row['Date_'].isoformat())
                r, c = grid.index(x, y)
                if mask[r, c]:
                    counts['camera_records_on_valid_depth_pixel'] += 1
                    source_depth = float(depth[r, c])
                    if -91.44 <= source_depth < -60.96:
                        counts['camera_windows_in_200_300ft_source_datum_band'] += 1
                        observed_depths.append(source_depth)
                        if bottom in ('rock', 'boulder', 'cobble'):
                            counts['rock_boulder_cobble_windows_in_band'] += 1
                            if rough[r, c]:
                                counts['rock_boulder_cobble_windows_on_derived_rough_class'] += 1
                            else:
                                counts['rock_boulder_cobble_windows_off_derived_rough_class'] += 1
                            if near_valid_pixel(rough, grid, x, y, 10):
                                counts['rock_boulder_cobble_windows_within_10m_of_derived_rough_class'] += 1
                            if near_valid_pixel(rough, grid, x, y, 25):
                                counts['rock_boulder_cobble_windows_within_25m_of_derived_rough_class'] += 1
                        if bottom and row.get('rockfish', 0) > 0:
                            counts['rockfish_positive_windows_in_band'] += 1
                        if bottom and row.get('lingcod', 0) > 0:
                            counts['lingcod_positive_windows_in_band'] += 1
                        if row.get('LINE'):
                            lines.add(str(row['LINE']))
                if near_valid_pixel(mask, grid, x, y):
                    counts['camera_records_within_100m_of_valid_depth_pixel'] += 1
    return {
        'schema_version': 1,
        'scope': survey_id.replace('BSS_Block', 'bss').lower() + '-original-video-vs-populated-grid',
        'survey_id': survey_id, 'survey_archive_url': bss_spec['archive_url'],
        'survey_archive_sha256': bss_spec['archive_sha256'],
        'camera_cruise': CRUISE,
        'camera_archive_url': video_manifest['base_url'] + CRUISE + '_video_observations.zip',
        'camera_archive_sha256': video_manifest['archives'][CRUISE],
        'camera_position_accuracy': 'Highly variable on the order of 10 meters (original metadata)',
        'search_radius_m': SEARCH_RADIUS_M, 'observation_dates': sorted(dates),
        'source_datum': bss_spec['native_vertical_datum'],
        'source_depth_range_m_on_populated_band': [min(observed_depths), max(observed_depths)] if observed_depths else None,
        'distinct_nonempty_camera_line_ids_in_band': len(lines),
        **{key: counts[key] for key in (
            'camera_records_inside_raster_bounds', 'interpreted_bottom_windows',
            'rock_boulder_cobble_windows', 'rockfish_positive_windows',
            'lingcod_positive_windows', 'camera_records_on_valid_depth_pixel',
            'camera_records_within_100m_of_valid_depth_pixel',
            'camera_windows_in_200_300ft_source_datum_band',
            'rock_boulder_cobble_windows_in_band',
            'rock_boulder_cobble_windows_on_derived_rough_class',
            'rock_boulder_cobble_windows_off_derived_rough_class',
            'rock_boulder_cobble_windows_within_10m_of_derived_rough_class',
            'rock_boulder_cobble_windows_within_25m_of_derived_rough_class',
            'rockfish_positive_windows_in_band', 'lingcod_positive_windows_in_band')},
        'independent_observations_on_populated_grid': counts['camera_records_on_valid_depth_pixel'] > 0,
        'rank_effect': 'none', 'fishing_target': False, 'exportable': False,
        'limitations': 'Rectangular raster bounds include nodata. Camera positions have order-10-m error against a 2 m grid, so nominal point-to-pixel joins do not identify an exact rock cell. Adjacent windows on one camera line are correlated, not independent surveys. The 200–300 ft depth screen is original NAVD88 source elevation, not MLLW-qualified fishing depth. Historical fish codes are not catch or current presence. The 100 m search is a proximity screen, not a positioning error bound or biological extrapolation. Product uncertainty, reuse rights and full chart/legal review remain unresolved.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bss-manifest', type=Path, default=ROOT / 'catalog/csumb-bss-native-sources.json')
    parser.add_argument('--survey-id', default='BSS_Block02')
    parser.add_argument('--video-manifest', type=Path, default=ROOT / 'research/catalog/usgs-video-cruises.json')
    parser.add_argument('--bss-cache', type=Path, default=ROOT / 'var/noaa-native-cache')
    parser.add_argument('--video-cache', type=Path, default=ROOT / 'var/usgs-video-cache')
    parser.add_argument('--download-video', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'var/review/bss02-video-grid-overlap.json')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    spec = next(source for source in json.loads(args.bss_manifest.read_text())['sources']
                if source['survey_id'] == args.survey_id)
    receipt = inspect(spec, json.loads(args.video_manifest.read_text()), args.bss_cache,
                      args.video_cache, args.download_video)
    if args.verify and receipt != json.loads(args.verify.read_text()):
        raise ValueError('Original video/grid overlap changed; review before publication')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.partial')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(args.output)
    print(json.dumps({'grid_overlap': receipt['camera_records_on_valid_depth_pixel'],
                      'within_100m': receipt['camera_records_within_100m_of_valid_depth_pixel'],
                      'output': str(args.output)}))


if __name__ == '__main__':
    main()
