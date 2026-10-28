"""Bounded offline regional QA packets. NOT FOR NAVIGATION; review required.

Input: {region, segments:[{id, mosaic, sources:[{id,path}]}]} for aligned
metre/elevation-positive-up ESRI ASCII fixtures, or {id, manifest} for a C1
coast_mosaic.py manifest. Relative paths resolve against the containing JSON.
No acquisition, model calls, publication or scientific acceptance occurs here.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from itertools import combinations
import json
import math
from pathlib import Path
import re
import struct
import zlib

LIMIT = 1_000_000
LABEL = 'NOT FOR NAVIGATION — research preview; review required'


def local(value, base):
    if not isinstance(value, str) or '://' in value or value.startswith('/vsi'):
        raise ValueError('Only local files are accepted')
    p = (base / value).resolve()
    if not p.is_file() or p.suffix.lower() not in {'.json', '.asc', '.tif', '.tiff', '.bag'}:
        raise ValueError('Expected local JSON, ASCII grid, TIFF or BAG')
    return p


def digest(path):
    h = sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Identifiers must be safe names')
    return value


def ascii_grid(path):
    with path.open() as f:
        header = dict(f.readline().lower().split() for _ in range(6))
        w, h = int(header['ncols']), int(header['nrows'])
        if w < 1 or h < 1 or w * h > LIMIT:
            raise ValueError('Grid exceeds bounded QA cell cap')
        cell = float(header['cellsize'])
        x, y = float(header['xllcorner']), float(header['yllcorner'])
        if not all(math.isfinite(v) for v in (cell, x, y)) or cell <= 0:
            raise ValueError('Invalid metre grid geometry')
        nodata = float(header['nodata_value'])
        rows = [[float(v) for v in line.split()] for line in f if line.strip()]
    if len(rows) != h or any(len(row) != w for row in rows):
        raise ValueError('Grid dimensions differ from payload')
    rows = [[v if math.isfinite(v) and v != nodata else None for v in row] for row in rows]
    return rows, (w, h, x, y, cell)


def holes(rows):
    """Four-connected invalid components, including boundary voids, not water gaps."""
    h, w = len(rows), len(rows[0])
    seen, result = set(), []
    for r in range(h):
        for c in range(w):
            if rows[r][c] is not None or (r, c) in seen:
                continue
            stack = [(r, c)]
            seen.add((r, c))
            count, r0, r1, c0, c1, edge = 0, r, r, c, c, False
            while stack:
                rr, cc = stack.pop()
                count += 1
                r0, r1, c0, c1 = min(r0, rr), max(r1, rr), min(c0, cc), max(c1, cc)
                edge |= rr in (0, h - 1) or cc in (0, w - 1)
                for nr, nc in ((rr-1, cc), (rr+1, cc), (rr, cc-1), (rr, cc+1)):
                    if 0 <= nr < h and 0 <= nc < w and rows[nr][nc] is None and (nr, nc) not in seen:
                        seen.add((nr, nc))
                        stack.append((nr, nc))
            result.append(dict(cells=count, pixel_bbox=[c0, r0, c1+1, r1+1], touches_boundary=edge))
    return result


def statistics(rows):
    values = [v for row in rows for v in row if v is not None]
    total = len(rows) * len(rows[0])
    return dict(grid_cells=total, valid_cells=len(values), hole_cells=total-len(values),
                valid_fraction=len(values)/total, minimum_elevation_m=min(values) if values else None,
                maximum_elevation_m=max(values) if values else None,
                mean_elevation_m=math.fsum(values)/len(values) if values else None)


def seams(sources):
    result = []
    for (a, ar), (b, br) in combinations(sources, 2):
        delta = [av-bv for ra, rb in zip(ar, br) for av, bv in zip(ra, rb)
                 if av is not None and bv is not None]
        n = len(delta)
        result.append(dict(sources=[a, b], overlap_cells=n, status='measured' if n else 'unavailable',
                           rms_m=math.sqrt(math.fsum(d*d for d in delta)/n) if n else None,
                           mean_delta_m=math.fsum(delta)/n if n else None,
                           reason=None if n else 'No jointly valid source cells on mosaic grid'))
    return result


def hillshade(rows, cell):
    """Tier-1 light geometry: azimuth 315, altitude 45; gray+alpha PNG.

    Adapted from coast-local-screen local_screen.py hillshade_png/encode_png.
    No contrast stretch; nodata neighbours use the centre (no false cliffs).
    Native-size output keeps pixels traceable to the hole list.
    """
    h, w = len(rows), len(rows[0])
    az, alt = math.radians(315), math.radians(45)
    light = math.sin(az)*math.cos(alt), math.cos(az)*math.cos(alt), math.sin(alt)
    pixels = bytearray()
    for r, row in enumerate(rows):
        pixels.append(0)
        for c, z in enumerate(row):
            if z is None:
                pixels.extend((0, 0))
                continue
            def at(rr, cc):
                v = rows[max(0, min(h-1, rr))][max(0, min(w-1, cc))]
                return z if v is None else v
            dx = (at(r, c+1)-at(r, c-1))/(2*cell)
            dy = (at(r-1, c)-at(r+1, c))/(2*cell)
            shade = max(0, min(1, (-dx*light[0]-dy*light[1]+light[2])/math.sqrt(dx*dx+dy*dy+1)))
            pixels.extend((round(255*shade), 255))
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag+data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 4, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(pixels), 9)) + chunk(b'IEND', b''))


def c1_grids(path):
    """C1 adapter: hash-pinned native sources, nearest warp then sign/offset.

    This fixture-qualified bounded adapter deliberately refuses large real runs.
    C1 deletes warped intermediates, so overlap cannot be inferred from final
    contributor boundaries; original sources must still exist to measure RMS.
    """
    import numpy as np
    import rasterio
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling
    manifest = json.loads(path.read_text())
    if manifest.get('schema_version') != 1 or manifest.get('units') != 'm' or manifest.get('value_convention') != 'elevation_positive_up':
        raise ValueError('Expected C1 metre elevation manifest')
    ref = manifest['outputs']['elevation']
    mosaic = local(ref['path'], path.parent)
    if digest(mosaic) != ref['sha256']:
        raise ValueError('Mosaic hash mismatch')
    def as_rows(data):
        return [[float(v) if not masked and math.isfinite(float(v)) else None
                 for v, masked in zip(row.data, mask)]
                for row, mask in zip(data, np.ma.getmaskarray(data))]
    with rasterio.open(mosaic) as target:
        if target.width * target.height > LIMIT:
            raise ValueError('Grid exceeds bounded QA cell cap; real-region runs not qualified')
        if target.crs is None or not target.crs.is_projected or target.crs.linear_units != 'metre' or target.transform.b or target.transform.d:
            raise ValueError('Expected north-up metre grid')
        rows = as_rows(target.read(1, masked=True))
        sources = []
        for source in manifest['sources']:
            p = local(source['path'], path.parent)
            if digest(p) != source['sha256']:
                raise ValueError('Source hash mismatch')
            convention = source['value_convention']
            offset = source['vertical_offset_m']
            if convention not in {'elevation_positive_up', 'depth_positive_down'} or not math.isfinite(offset):
                raise ValueError('Invalid source normalization')
            with rasterio.open(p) as native:
                if native.driver not in {'GTiff', 'BAG'} or native.scales[0] != 1 or native.offsets[0] != 0:
                    raise ValueError('Unsupported source driver or stored scale/offset')
                with WarpedVRT(native, crs=target.crs, transform=target.transform,
                               width=target.width, height=target.height,
                               resampling=Resampling.nearest, dtype='float64', nodata=float('nan'),
                               tolerance=1e-9) as warped:
                    data = warped.read(1, masked=True)
            data = data * (-1 if convention == 'depth_positive_down' else 1) + offset
            sources.append((name(source['id']), as_rows(data)))
        geometry = (target.width, target.height, target.bounds.left, target.bounds.bottom, target.res[0])
    return rows, geometry, sources, manifest.get('limitations', [])


def packet(config, output):
    config, output = Path(config).resolve(), Path(output).resolve()
    doc = json.loads(config.read_text())
    region = name(doc['region'])
    if not doc.get('segments'):
        raise ValueError('At least one segment required')
    # Validate and compute before writing any normal packet.
    segments, images, inputs, ids = [], {}, [], set()
    for segment in doc['segments']:
        ident = name(segment['id'])
        if ident in ids:
            raise ValueError('Duplicate segment')
        ids.add(ident)
        if 'manifest' in segment:
            p = local(segment['manifest'], config.parent)
            rows, geometry, sources, limitations = c1_grids(p)
            inputs.append(dict(segment=ident, manifest_sha256=digest(p)))
        else:
            p = local(segment['mosaic'], config.parent)
            rows, geometry = ascii_grid(p)
            sources = []
            for source in segment['sources']:
                sp = local(source['path'], config.parent)
                sr, sg = ascii_grid(sp)
                if sg != geometry:
                    raise ValueError('Source and mosaic grids must align exactly')
                sources.append((name(source['id']), sr))
                inputs.append(dict(segment=ident, source=source['id'], sha256=digest(sp)))
            limitations = ['Synthetic ASCII fixture: metre horizontal/elevation units assumed explicitly.']
            inputs.append(dict(segment=ident, mosaic_sha256=digest(p)))
        if len({s[0] for s in sources}) != len(sources):
            raise ValueError('Duplicate source id')
        voids = holes(rows)
        image = f'{ident}-hillshade.png'
        images[image] = hillshade(rows, geometry[4])
        segments.append(dict(id=ident, stats=statistics(rows), hole_count=len(voids), holes=voids,
                             seam_rms=seams(sources), hillshade=image, limitations=limitations))
    report = dict(schema='coast-region-qa-v1', region=region, status='review_required', navigation=LABEL,
                  limitations=['Hole list includes land and unsurveyed water; no water mask.',
                               'Overlap RMS measures grid differences, not datum accuracy or seam continuity.',
                               'Bounded fixture-qualified tool; no real-region processing acceptance.'],
                  segments=segments, inputs=inputs, config_sha256=digest(config))
    output.mkdir(parents=True, exist_ok=False)
    for filename, data in images.items():
        (output / filename).write_bytes(data)
    (output / 'qa.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    lines = [LABEL, f'Region: {region}', 'Status: review_required', *report['limitations']]
    for s in segments:
        lines += [f"Segment {s['id']}: {json.dumps(s['stats'])}", f"Holes: {json.dumps(s['holes'])}",
                  f"Seam RMS: {json.dumps(s['seam_rms'])}", f"Hillshade: {s['hillshade']}"]
    (output / 'QA.txt').write_text('\n'.join(lines)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region-config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = packet(args.region_config, args.output)
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
