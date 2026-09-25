"""Audit the original USGS Point Sur–Point Arguello sediment-thickness grid.

This is an interpolated 50 m geologic context source, never a fishing target,
bottom-depth measurement, exposed-rock assertion, or chartplotter export.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import numpy as np
import rasterio
from pyproj import Transformer


ARCHIVE_URL = ('https://www.sciencebase.gov/catalog/file/get/'
               '5c913811e4b09388245480d2?facet=SedimentThickness_PointSurToPointArguello')
METADATA_URL = ('https://www.sciencebase.gov/catalog/file/get/'
                '5c913811e4b09388245480d2?allowOpen=true&name='
                'SedimentThickness_PointSurToPointArguello_metadata.xml')
# ScienceBase regenerates ZIP entry timestamps on each download. Pin the actual
# GeoTIFF bytes and the stable original XML, not the volatile transport ZIP.
RASTER_SHA256 = 'd0ca4195ae69303216dc41a2f7a9e7f6cc9458564f45622d73547dad5fc2a6e7'
METADATA_SHA256 = '881d93a105be0000753c04b9da5d935a253904501d8fed08d6154fe8abb79a3f'
ENTRY = 'SedimentThickness_PointSurToPointArguello.tif'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fetch(url, limit):
    with urlopen(url, timeout=45) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('USGS source exceeds bounded download')
    return raw


def audit(archive, metadata, sectors):
    raw = Path(archive).read_bytes()
    meta = Path(metadata).read_bytes()
    if sha(meta) != METADATA_SHA256:
        raise ValueError('Original USGS source changed; review before publication')
    if (b'800' not in meta or b'1,000' not in meta or b'50-m grid' not in meta
            or b'public domain' not in meta):
        raise ValueError('USGS metadata no longer supports reviewed interpretation')
    rows = json.loads(Path(sectors).read_text())['sectors']
    groups = [s for s in rows if s['id'] in {'monterey-sur', 'big-sur', 'sur-san-simeon',
                                             'cambria-morro', 'morro-conception'}]
    if len(groups) != 5:
        raise ValueError('Expected five intersecting central browse bands')
    summary = {s['id']: {'valid_cells': 0, 'negative_cells': 0,
                         'nonnegative_at_most_0_1_m_cells': 0,
                         'nonnegative_above_0_1_m_cells': 0} for s in groups}
    with ZipFile(archive) as z:
        if ENTRY not in z.namelist():
            raise ValueError('Expected exact original GeoTIFF in USGS archive')
        raster_raw = z.read(ENTRY)
        if sha(raster_raw) != RASTER_SHA256:
            raise ValueError('Original USGS GeoTIFF changed; review before publication')
        with rasterio.MemoryFile(raster_raw) as memory, memory.open() as ds:
            if ds.crs.to_epsg() != 32610 or ds.res != (50.0, 50.0) or ds.count != 1:
                raise ValueError('Unexpected USGS raster geometry')
            transform = Transformer.from_crs(ds.crs, 'EPSG:4326', always_xy=True)
            valid_total = negative_total = thin_total = 0
            for _, window in ds.block_windows(1):
                values = ds.read(1, window=window, masked=True)
                yy, xx = np.where(~np.ma.getmaskarray(values))
                if len(xx) == 0:
                    continue
                samples = np.asarray(values[yy, xx], dtype='float64')
                if not np.isfinite(samples).all():
                    raise ValueError('Nonfinite original USGS sediment value')
                coords = ds.window_transform(window)
                east = coords.c + (xx + 0.5) * coords.a
                north = coords.f + (yy + 0.5) * coords.e
                _, latitude = transform.transform(east, north)
                valid_total += len(samples)
                negative_total += int(np.count_nonzero(samples < 0))
                thin_total += int(np.count_nonzero((samples >= 0) & (samples <= 0.1)))
                for sector in groups:
                    low, high = sector['latitude']
                    v = samples[(latitude >= low) & (latitude < high)]
                    row = summary[sector['id']]
                    row['valid_cells'] += len(v)
                    row['negative_cells'] += int(np.count_nonzero(v < 0))
                    row['nonnegative_at_most_0_1_m_cells'] += int(np.count_nonzero((v >= 0) & (v <= 0.1)))
                    row['nonnegative_above_0_1_m_cells'] += int(np.count_nonzero(v > 0.1))
            if valid_total != 824580:
                raise ValueError('Original valid-cell count changed')
            outside_bands = valid_total - sum(row['valid_cells'] for row in summary.values())
            if outside_bands < 0:
                raise ValueError('Browse bands overlap the original raster cells')
            return {
                'schema_version': 1, 'source': 'USGS DS 781 / OFR 2018-1158',
                'source_url': 'https://pubs.usgs.gov/of/2018/1158/data_catalog_PointSurToPointArguello.html',
                'archive_url': ARCHIVE_URL, 'transport_archive_sha256': sha(raw),
                'raster_sha256': sha(raster_raw),
                'metadata_url': METADATA_URL, 'metadata_sha256': sha(meta),
                'audited_at': datetime.now(timezone.utc).isoformat(),
                'raster': {'crs': str(ds.crs), 'cell_size_m': 50,
                           'valid_cells': valid_total, 'negative_interpolated_cells': negative_total,
                           'nonnegative_at_most_0_1_m_cells': thin_total,
                           'outside_five_browse_bands_valid_cells': outside_bands},
                'browse_sectors': summary, 'status': 'geologic-context-only',
                'limitations': ('The raster estimates sediment above a glacial transgressive surface, '
                                'not seabed depth, exposed bedrock or fish habitat. Seismic lines are '
                                'typically 800–1,000 m apart between dense trackline samples; a 50 m '
                                'interpolated cell is not a 50 m field observation. Near-zero and '
                                'negative values are not rock-pile detections. Broad latitude bands '
                                'are discovery partitions, not complete survey or fishing-area coverage. '
                                'No point, score, drift, navigation clearance or export follows.')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', default='var/review/usgs-point-sur-arguello-sediment.zip')
    parser.add_argument('--metadata', default='var/review/usgs-point-sur-arguello-sediment-metadata.xml')
    parser.add_argument('--sectors', default='catalog/coastal-sectors.json')
    parser.add_argument('--output', default='var/review/usgs-point-sur-arguello-sediment-audit.json')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    if args.fetch:
        Path(args.archive).parent.mkdir(parents=True, exist_ok=True)
        Path(args.metadata).parent.mkdir(parents=True, exist_ok=True)
        Path(args.archive).write_bytes(fetch(ARCHIVE_URL, 20_000_000))
        Path(args.metadata).write_bytes(fetch(METADATA_URL, 2_000_000))
    result = audit(args.archive, args.metadata, args.sectors)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print(json.dumps({'valid_cells': result['raster']['valid_cells'],
                      'sector_valid_cells': {k: v['valid_cells'] for k, v in result['browse_sectors'].items()}}))


if __name__ == '__main__':
    main()
