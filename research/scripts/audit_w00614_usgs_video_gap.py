"""Check original USGS video points against W00614 measured 200–300 ft cells.

The geographic rectangle is a conservative first rejection test. A point
outside it cannot occur on a qualifying cell; an inside point would require
a subsequent exact cell and positional-uncertainty review.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
from urllib.request import Request, urlopen
import zipfile

import h5py
import numpy as np
import rasterio
import shapefile
from pyproj import Transformer

from research.scripts.screen_vr_native_depth import fine_grid_rows
from skippercast.platform.bottom_targets import cells_qualified, vr_transform


CATALOG = 'https://pubs.usgs.gov/ds/781/video_observations/data_catalog_video_observations.html'
BASE = 'https://pubs.usgs.gov/ds/781/video_observations/data/'
DEPTH_RECEIPT = Path('research/receipts/w00614-original-300-pigeon-monterey-review.json')
BAG_PATH = Path('var/review/W00614_MB_VR_MLLW_1of1.bag')
FILES = (
    'Benthic_Biological_Interpretation.zip', 'c0111sc_video_observations.zip',
    'c0212sc_video_observations.zip', 'c109nc_video_observations.zip',
    'c210nc_video_observations.zip', 'f208nc_video_observations.zip',
    'f307nc_video_observations.zip', 'l908nc_video_observations.zip',
    's1c08sc_video_observations.zip', 's2210mb_video_observations.zip',
    'sw109sc_video_observations.zip', 'z107sc_video_observations.zip',
    'z206sc_video_observations.zip',
)


def fetch(url, max_bytes):
    with urlopen(Request(url, headers={'User-Agent': 'SkipperCast original-source audit/1.0'}),
                 timeout=45) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('Official USGS original source unavailable or redirected')
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError('Official USGS source exceeded download bound')
    return data


def cell_envelope(path, receipt):
    if (hashlib.sha256(path.read_bytes()).hexdigest() != receipt['source_sha256']
            or receipt['survey_id'] != 'W00614'
            or receipt['counts']['depth_uncertainty_qualified_200_300ft_cells'] != 141331):
        raise ValueError('Original W00614 depth source or receipt changed')
    west, south, east, north = float('inf'), float('inf'), -float('inf'), -float('inf')
    count = 0
    with h5py.File(path) as bag, rasterio.open(path) as raster:
        root = bag['BAG_root']
        grids, refinements = root['varres_metadata'][:], root['varres_refinements']
        to_geo = Transformer.from_crs(raster.crs, 'EPSG:4326', always_xy=True)
        sector = receipt['sector_bounds']
        for row, col in fine_grid_rows(grids):
            item = grids[row, col]
            nx, ny = int(item['dimensions_x']), int(item['dimensions_y'])
            transform = vr_transform(raster.bounds.left, raster.bounds.bottom,
                                     *raster.res, int(row), int(col), item)
            center = to_geo.transform(transform.c + nx * float(item['resolution_x']) / 2,
                                      transform.f - ny * float(item['resolution_y']) / 2)
            if not (sector[0] <= center[0] < sector[2] and sector[1] <= center[1] < sector[3]):
                continue
            offset = int(item['index'])
            if offset < 0 or offset + nx * ny > refinements.shape[1]:
                raise ValueError('Original BAG refinement index changed')
            values = refinements[0, offset:offset + nx * ny].reshape(ny, nx)[::-1]
            eligible = cells_qualified(values['depth'], values['depth_uncrt'],
                                       max(item['resolution_x'], item['resolution_y']),
                                       minimum_ft=200, limit_ft=300)
            if not np.any(eligible):
                continue
            iy, ix = np.where(eligible)
            lon, lat = to_geo.transform(transform.c + (ix + .5) * transform.a,
                                        transform.f + (iy + .5) * transform.e)
            west, south = min(west, float(np.min(lon))), min(south, float(np.min(lat)))
            east, north = max(east, float(np.max(lon))), max(north, float(np.max(lat)))
            count += len(ix)
    if count != 141331:
        raise ValueError('Original W00614 qualifying cell count changed')
    return [west, south, east, north], count


def inspect_zip(data, bounds):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = {suffix: [name for name in archive.namelist()
                            if name.lower().endswith('.' + suffix)]
                   for suffix in ('shp', 'shx', 'dbf', 'prj')}
        if any(len(names) != 1 for names in members.values()):
            raise ValueError('Expected one complete original video point shapefile')
        prj = archive.read(members['prj'][0]).decode('latin1')
        if 'GCS_WGS_1984' not in prj:
            raise ValueError('Original USGS video coordinate frame changed')
        reader = shapefile.Reader(shp=io.BytesIO(archive.read(members['shp'][0])),
                                  shx=io.BytesIO(archive.read(members['shx'][0])),
                                  dbf=io.BytesIO(archive.read(members['dbf'][0])))
        if reader.shapeType != shapefile.POINT:
            raise ValueError('Original USGS video geometry is not points')
        west, south, east, north = bounds
        count_inside = count_within_100m = 0
        minimum = float('inf')
        for shape in reader.shapes():
            lon, lat = shape.points[0]
            dx = (lon - min(max(lon, west), east)) * 111_320 * math.cos(math.radians(lat))
            dy = (lat - min(max(lat, south), north)) * 111_320
            distance = math.hypot(dx, dy)
            minimum = min(minimum, distance)
            count_inside += west <= lon <= east and south <= lat <= north
            count_within_100m += distance <= 100
        return {'observation_points': len(reader), 'source_bbox_wgs84': list(reader.bbox),
                'points_in_qualified_cell_center_envelope': count_inside,
                'points_within_100m_of_envelope': count_within_100m,
                'approx_min_distance_to_envelope_m': round(minimum)}


def build(bag=BAG_PATH):
    depth = json.loads(DEPTH_RECEIPT.read_text())
    bounds, cells = cell_envelope(bag, depth)
    catalog = fetch(CATALOG, 1_000_000).decode('latin1')
    discovered = tuple(sorted(set(re.findall(r'video_observations/data/([^"<>]+\.zip)',
                                         catalog, re.I))))
    if discovered != tuple(sorted(FILES)):
        raise ValueError('Official USGS video archive catalog changed')
    archives = []
    for name in FILES:
        raw = fetch(BASE + name, 10_000_000)
        archives.append({'name': name, 'url': BASE + name,
                         'sha256': hashlib.sha256(raw).hexdigest(),
                         **inspect_zip(raw, bounds)})
    if sum(row['points_within_100m_of_envelope'] for row in archives):
        raise ValueError('USGS video observation now needs an exact W00614 cell join')
    return {'schema_version': 1, 'scope': 'w00614-original-usgs-video-observation-gap',
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'catalog_url': CATALOG, 'depth_receipt': str(DEPTH_RECEIPT),
            'bag_sha256': depth['source_sha256'], 'qualified_cells': cells,
            'qualified_cell_center_envelope_wgs84': bounds, 'archives': archives,
            'total_cataloged_point_records_not_deduplicated': sum(
                row['observation_points'] for row in archives),
            'points_on_or_within_100m_of_envelope': 0,
            'independent_substrate_gate_satisfied': False,
            'biological_observation_gate_satisfied': False,
            'qualified_waypoints': 0, 'fishing_target': False, 'exportable': False,
            'limitation': ('The USGS video-point catalog has no observations within '
                           '100 m of the qualifying W00614 cell-center envelope. This '
                           'does not establish absence of rock or fish; another local '
                           'substrate/biological source is required. Rectangle distance '
                           'is an approximate exclusion check, not a positional-error model. '
                           'The aggregate interpretation archive may repeat cruise records; '
                           'the point-record total is not independent sampling effort.')}


def stable(value):
    return {key: val for key, val in value.items() if key != 'checked_at'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bag', type=Path, default=BAG_PATH)
    parser.add_argument('--output', type=Path,
                        default=Path('research/receipts/w00614-usgs-video-observation-gap.json'))
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    report = build(args.bag)
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit('Original USGS video or NOAA depth evidence changed; review before publishing')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f"{report['total_cataloged_point_records_not_deduplicated']} cataloged records; none within 100 m of W00614 cells")


if __name__ == '__main__':
    main()
