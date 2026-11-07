#!/usr/bin/env python3
"""Explicit, bounded private refresh from NOAA NOMADS. Never scheduled/published here."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from urllib.parse import urlencode
from urllib.request import urlopen

from build_wind import ROOT, decode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='UTC model cycle YYYYMMDDHH')
    parser.add_argument('--hour', type=int, default=0, help='forecast lead hours')
    parser.add_argument('--bounds', type=float, nargs=4, default=[-123, 34, -119, 37],
                        metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'))
    args = parser.parse_args()
    run = datetime.strptime(args.run, '%Y%m%d%H').replace(tzinfo=timezone.utc)
    west, south, east, north = args.bounds
    if (run.hour not in (0, 6, 12, 18) or not 0 <= args.hour <= 120
            or not -180 <= west < east <= 180 or not -85 <= south < north <= 85
            or east - west > 6 or north - south > 6):
        parser.error('expected GFS cycle, 0..120 h lead and a crop at most 6° × 6°')
    params = {'file': f'gfs.t{run:%H}z.pgrb2.0p25.f{args.hour:03d}',
              'lev_10_m_above_ground': 'on', 'var_UGRD': 'on', 'var_VGRD': 'on',
              'subregion': '', 'leftlon': west % 360, 'rightlon': east % 360,
              'toplat': north, 'bottomlat': south, 'dir': f'/gfs.{run:%Y%m%d}/{run:%H}/atmos'}
    url = 'https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?' + urlencode(params)
    folder = ROOT / 'var/maplayer-wind-1'
    folder.mkdir(parents=True, exist_ok=True)
    errors = []
    for attempt in (1, 2):
        try:
            with urlopen(url, timeout=90) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000 or not raw.startswith(b'GRIB'):
                raise ValueError(f'oversize or non-GRIB response: {raw[:120]!r}')
            receipt = {'source_id': 'noaa-gfs', 'source_url': url,
                       'run_time': run.isoformat(), 'data_time': (run + timedelta(hours=args.hour)).isoformat(),
                       'forecast_hour': args.hour, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                       'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                       'attempts': attempt, 'prior_errors': errors}
            partial = folder / 'gfs-wind.part'
            partial.write_bytes(raw)
            preview = decode(partial, receipt)
            payload = (json.dumps(preview, allow_nan=False) + '\n').encode()
            receipt['preview_sha256'] = hashlib.sha256(payload).hexdigest()
            # Commit locally only after both component bands and timestamps validate.
            partial.replace(folder / 'gfs-wind.grib2')
            (folder / 'wind-preview.json').write_bytes(payload)
            (folder / 'source-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps(receipt, indent=2))
            return
        except Exception as error:
            errors.append(f'attempt {attempt}: {type(error).__name__}: {error}')
            print(errors[-1], flush=True)
    (folder / 'fetch-errors.json').write_text(json.dumps({'url': url, 'errors': errors}, indent=2) + '\n')
    raise SystemExit('STOP: two NOAA attempts failed; see private fetch-errors.json')


if __name__ == '__main__':
    main()
