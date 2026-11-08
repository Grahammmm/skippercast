#!/usr/bin/env python3
"""Decode a retained NOAA GFS 10 m wind crop into a private preview; no network.

python research/scripts/map_style/build_wind.py
Input and output stay in ignored var/maplayer-wind-1; never reads region config.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[3]


def decode(path, receipt):
    if hashlib.sha256(path.read_bytes()).hexdigest() != receipt['sha256']:
        raise ValueError('GRIB checksum mismatch')
    with rasterio.open(path) as ds:
        if ds.count != 2 or ds.width < 2 or ds.height < 2:
            raise ValueError('expected two gridded wind components')
        if not (ds.transform.a == .25 and ds.transform.e == -.25):
            raise ValueError('expected north-to-south GFS 0.25 degree grid')
        components = {}
        for band in (1, 2):
            tags = ds.tags(band)
            run = datetime.fromtimestamp(int(tags['GRIB_REF_TIME']), timezone.utc)
            valid = datetime.fromtimestamp(int(tags['GRIB_VALID_TIME']), timezone.utc)
            if (run != datetime.fromisoformat(receipt['run_time'].replace('Z', '+00:00'))
                    or valid != datetime.fromisoformat(receipt['data_time'].replace('Z', '+00:00'))
                    or tags['GRIB_SHORT_NAME'] != '10-HTGL' or tags['GRIB_UNIT'] != '[m/s]'):
                raise ValueError('GRIB level, units or times differ from receipt')
            values = ds.read(band, masked=True)
            if np.ma.getmaskarray(values).any() or not np.isfinite(values).all():
                raise ValueError('missing/nonfinite wind component')
            components[tags['GRIB_ELEMENT']] = values.tolist()
        if set(components) != {'UGRD', 'VGRD'}:
            raise ValueError('missing UGRD/VGRD pair')
        west, north = ds.xy(0, 0)
        return {'schema_version': 1, 'source_id': 'noaa-gfs',
                'run_time': receipt['run_time'], 'data_time': receipt['data_time'],
                'source_url': receipt['source_url'], 'max_age_hours': 18,
                'width': ds.width, 'height': ds.height, 'west': west, 'north': north,
                'resolution_degrees': .25, 'units': 'm/s',
                'u': components['UGRD'], 'v': components['VGRD']}


if __name__ == '__main__':
    folder = ROOT / 'var/maplayer-wind-1'
    receipt = json.loads((folder / 'source-receipt.json').read_text())
    result = decode(folder / 'gfs-wind.grib2', receipt)
    payload = (json.dumps(result, allow_nan=False) + '\n').encode()
    (folder / 'wind-preview.json').write_bytes(payload)
    receipt['preview_sha256'] = hashlib.sha256(payload).hexdigest()
    receipt['grid'] = {'width': result['width'], 'height': result['height'],
                       'west': result['west'], 'north': result['north'], 'resolution_degrees': .25}
    (folder / 'source-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))
