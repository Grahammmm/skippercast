"""Opt-in cached C1 regional QA; no acquisition or publication.

Statistics and source comparisons stream in strips. Only the boolean void mask
and its int32 4-connected labels are regional arrays (hard cap 150M cells).
PNG slopes use a one-cell halo, the original C4 light, and no interpolation.
"""
from __future__ import annotations

from contextlib import ExitStack
from itertools import combinations
import json
import math
from pathlib import Path
import shutil
import struct
import zlib

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from scipy import ndimage

if __package__:
    from .coast_qa import LABEL, digest, local, name
else:
    from coast_qa import LABEL, digest, local, name

MAX_CELLS = 150_000_000
MAX_SIDE = 20_000
STRIP_ROWS = 64
RESERVE_BYTES = 250 * 1024**3
LIMITATIONS = [
    'Hole components include land, unsurveyed water and the enclosing projected rectangle; no water mask.',
    'Overlap RMS is a source-grid difference, not vertical accuracy or boundary continuity.',
    'Unstated source datums and zero offsets remain unresolved; no geodetic datum conversion.',
    '10 m output spacing is not source accuracy or independent observation spacing.',
    'Research diagnostics only: no rights clearance, publication or navigation acceptance.',
]


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def read_values(dataset, window):
    a = dataset.read(1, window=window, masked=True, out_dtype='float64')
    return np.where(np.ma.getmaskarray(a) | ~np.isfinite(a.data), np.nan, a.data)


def accumulator():
    return dict(n=0, total=0.0, squares=0.0, minimum=None, maximum=None)


def update(acc, values):
    values = values[np.isfinite(values)]
    if not values.size:
        return
    acc['n'] += int(values.size)
    acc['total'] += float(values.sum(dtype=np.float64))
    acc['squares'] += float(np.square(values).sum(dtype=np.float64))
    low, high = float(values.min()), float(values.max())
    acc['minimum'] = low if acc['minimum'] is None else min(acc['minimum'], low)
    acc['maximum'] = high if acc['maximum'] is None else max(acc['maximum'], high)


def summarize(acc):
    n = acc['n']
    mean = acc['total'] / n if n else None
    return dict(cells=n, minimum_m=acc['minimum'], maximum_m=acc['maximum'], mean_m=mean,
                rms_m=math.sqrt(acc['squares'] / n) if n else None,
                stddev_m=math.sqrt(max(0, acc['squares'] / n - mean * mean)) if n else None)


def hole_components(void):
    """Same four-neighbour semantics as coast_qa.holes, across all strip edges."""
    labels, count = ndimage.label(void)  # default 2-D cross = four connectivity
    counts = np.bincount(labels.ravel())
    h, w = void.shape
    result = []
    for ident, box in enumerate(ndimage.find_objects(labels, max_label=count), 1):
        rows, cols = box
        result.append(dict(cells=int(counts[ident]),
                           pixel_bbox=[cols.start, rows.start, cols.stop, rows.stop],
                           touches_boundary=(rows.start == 0 or cols.start == 0 or rows.stop == h or cols.stop == w)))
    return result


def png_chunk(file, kind, data):
    file.write(struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data)))


def write_png(path, width, height, strips, channels=2):
    """PNG stream with filter 0; tiny bounded strips, no Pillow dependency."""
    with path.open('xb') as file:
        file.write(b'\x89PNG\r\n\x1a\n')
        png_chunk(file, b'IHDR', struct.pack('>IIBBBBB', width, height, 8, {2: 4, 4: 6}[channels], 0, 0, 0))
        png_chunk(file, b'tEXt', b'Warning\0NOT FOR NAVIGATION; research preview; review required')
        compressor = zlib.compressobj(6)
        rows_written = 0
        for pixels in strips:
            if pixels.shape[1:] != (width, channels) or pixels.dtype != np.uint8:
                raise ValueError('Invalid PNG strip')
            rows_written += pixels.shape[0]
            raw = np.zeros((pixels.shape[0], 1 + width * channels), dtype=np.uint8)
            raw[:, 1:] = pixels.reshape(pixels.shape[0], -1)
            encoded = compressor.compress(raw.tobytes())
            if encoded:
                png_chunk(file, b'IDAT', encoded)
        if rows_written != height:
            raise ValueError('Wrong PNG height')
        png_chunk(file, b'IDAT', compressor.flush())
        png_chunk(file, b'IEND', b'')


def shade(center, left, right, north, south, cell):
    valid = np.isfinite(center)
    neighbours = [np.where(np.isfinite(a), a, center) for a in (left, right, north, south)]
    left, right, north, south = neighbours
    dx, dy = (right-left)/(2*cell), (north-south)/(2*cell)
    az, alt = math.radians(315), math.radians(45)
    light = math.sin(az)*math.cos(alt), math.cos(az)*math.cos(alt), math.sin(alt)
    level = np.clip((-dx*light[0]-dy*light[1]+light[2])/np.sqrt(dx*dx+dy*dy+1), 0, 1)
    result = np.zeros((*center.shape, 2), dtype=np.uint8)
    result[:, :, 0] = np.rint(255 * np.where(valid, level, 0)).astype(np.uint8)
    result[:, :, 1] = valid.astype(np.uint8) * 255
    return result


def hillshade_png(target, path, box=None):
    c0, r0, c1, r1 = box or (0, 0, target.width, target.height)
    def strips():
        for row in range(r0, r1, STRIP_ROWS):
            stop = min(row + STRIP_ROWS, r1)
            x0, x1 = max(0, c0-1), min(target.width, c1+1)
            y0, y1 = max(0, row-1), min(target.height, stop+1)
            a = read_values(target, Window(x0, y0, x1-x0, y1-y0))
            a = np.pad(a, ((int(row == 0), int(stop == target.height)),
                           (int(c0 == 0), int(c1 == target.width))), mode='edge')
            yield shade(a[1:-1, 1:-1], a[1:-1, :-2], a[1:-1, 2:],
                        a[:-2, 1:-1], a[2:, 1:-1], target.res[0])
    write_png(path, c1-c0, r1-r0, strips())


def validate_grid(target):
    if target.count != 1 or target.driver != 'GTiff':
        raise ValueError('Expected single-band GeoTIFF')
    if (not target.crs or not target.crs.is_projected or target.crs.linear_units != 'metre'
            or target.transform.b or target.transform.d or target.transform.a <= 0
            or target.transform.e >= 0 or target.res[0] != target.res[1]):
        raise ValueError('Expected north-up square metre grid')
    if target.width * target.height > MAX_CELLS or max(target.shape) > MAX_SIDE:
        raise ValueError('Grid exceeds bounded regional QA cap')
    if target.scales[0] != 1 or target.offsets[0] != 0:
        raise ValueError('Stored scale/offset unsupported')


def segment_packet(manifest_path, output, ident):
    doc = json.loads(manifest_path.read_text())
    if (doc.get('schema_version') != 1 or doc.get('units') != 'm'
            or doc.get('value_convention') != 'elevation_positive_up'):
        raise ValueError('Expected C1 metre elevation manifest')
    sources = doc['sources']
    if not 1 <= len(sources) <= 16:
        raise ValueError('Expected 1..16 sources')
    ids = [name(s['id']) for s in sources]
    codes = [s['code'] for s in sources]
    if len(set(ids)) != len(ids) or sorted(codes) != list(range(1, len(sources)+1)):
        raise ValueError('Source ids/codes must be unique with contiguous positive codes')
    paths = {}
    receipts = []
    for role in ('elevation', 'contributor', 'support_count'):
        ref = doc['outputs'][role]
        p = local(ref['path'], manifest_path.parent)
        actual = digest(p)
        if actual != ref['sha256']:
            raise ValueError(f'{role} hash mismatch')
        paths[role] = p
        receipts.append(dict(role=role, path=str(p), sha256=actual, bytes=p.stat().st_size))
    native_paths = []
    for source in sources:
        p = local(source['path'], manifest_path.parent)
        actual = digest(p)
        if actual != source['sha256']:
            raise ValueError('Source hash mismatch')
        if (source.get('units') != 'm' or source['value_convention'] not in {'elevation_positive_up', 'depth_positive_down'}
                or not math.isfinite(source['vertical_offset_m'])):
            raise ValueError('Invalid source normalization')
        native_paths.append(p)
        receipts.append(dict(role=source['id'], path=str(p), sha256=actual, bytes=p.stat().st_size))
    with ExitStack() as stack:
        stack.enter_context(rasterio.Env(GDAL_CACHEMAX=256*1024**2, GDAL_NUM_THREADS='2'))
        target, contributor, support = [stack.enter_context(rasterio.open(paths[k]))
                                        for k in ('elevation', 'contributor', 'support_count')]
        validate_grid(target)
        for ds in (contributor, support):
            validate_grid(ds)
            if (ds.shape, ds.crs, ds.transform) != (target.shape, target.crs, target.transform):
                raise ValueError('C1 output grids do not align')
        warps = []
        for p in native_paths:
            ds = stack.enter_context(rasterio.open(p))
            if (ds.driver != 'GTiff' or ds.count != 1 or not ds.crs
                    or ds.scales[0] != 1 or ds.offsets[0] != 0):
                raise ValueError('Expected unscaled native GeoTIFF with CRS')
            warps.append(stack.enter_context(WarpedVRT(ds, crs=target.crs, transform=target.transform,
                width=target.width, height=target.height, resampling=Resampling.nearest,
                dtype='float64', nodata=float('nan'), tolerance=1e-9, warp_mem_limit=64)))
        h, w = target.shape
        void = np.empty((h, w), dtype=np.bool_)
        global_acc = accumulator()
        winning = [accumulator() for _ in sources]
        native_counts = [0] * len(sources)
        pair_acc = {pair: accumulator() for pair in combinations(range(len(sources)), 2)}
        pair_peak = {pair: None for pair in pair_acc}
        overlap_cells, max_support = 0, 0
        checks = dict(mask_mismatches=0, source_support_count_mismatches=0, selected_source_value_mismatches=0,
                      contributor_code_mismatches=0)
        for row in range(0, h, STRIP_ROWS):
            window = Window(0, row, w, min(STRIP_ROWS, h-row))
            z = read_values(target, window)
            c, support_values = contributor.read(1, window=window), support.read(1, window=window)
            valid = np.isfinite(z)
            void[row:row+int(window.height)] = ~valid
            update(global_acc, z)
            checks['mask_mismatches'] += int(np.count_nonzero((valid != (c > 0)) | (valid != (support_values > 0))))
            checks['contributor_code_mismatches'] += int(np.count_nonzero(~np.isin(c, [0, *codes])))
            overlap_cells += int(np.count_nonzero(support_values > 1))
            max_support = max(max_support, int(support_values.max()))
            warped_values = []
            counted_support = np.zeros(z.shape, dtype=np.uint16)
            for i, (source, warp) in enumerate(zip(sources, warps)):
                a = read_values(warp, window)
                a = a * (-1 if source['value_convention'] == 'depth_positive_down' else 1) + source['vertical_offset_m']
                mask = np.isfinite(a)
                native_counts[i] += int(mask.sum())
                counted_support += mask
                use = c == source['code']
                update(winning[i], z[use])
                checks['selected_source_value_mismatches'] += int(np.count_nonzero(use & (a.astype('float32') != z)))
                warped_values.append(a)
            checks['source_support_count_mismatches'] += int(np.count_nonzero(counted_support != support_values))
            for pair, acc in pair_acc.items():
                i, j = pair
                delta = warped_values[i] - warped_values[j]
                update(acc, delta)
                if np.isfinite(delta).any():
                    flat = int(np.nanargmax(np.abs(delta)))
                    rr, cc = np.unravel_index(flat, delta.shape)
                    candidate = dict(absolute_delta_m=float(abs(delta[rr, cc])),
                                     delta_m=float(delta[rr, cc]), pixel=[int(cc), row+int(rr)])
                    if pair_peak[pair] is None or candidate['absolute_delta_m'] > pair_peak[pair]['absolute_delta_m']:
                        pair_peak[pair] = candidate
        holes = hole_components(void)
        del void
        total = w*h
        stat = summarize(global_acc)
        stats = dict(grid_cells=total, valid_cells=stat['cells'], hole_cells=total-stat['cells'],
                     valid_fraction=stat['cells']/total, minimum_elevation_m=stat['minimum_m'],
                     maximum_elevation_m=stat['maximum_m'], mean_elevation_m=stat['mean_m'],
                     stddev_elevation_m=stat['stddev_m'], overlap_cells=overlap_cells, max_support=max_support)
        stats['valid_area_km2'] = stats['valid_cells'] * target.res[0]**2 / 1e6
        stats['hole_area_km2'] = stats['hole_cells'] * target.res[0]**2 / 1e6
        checks['hole_component_sum_matches'] = sum(v['cells'] for v in holes) == stats['hole_cells']
        checks['manifest_stats_match'] = all(stats[k] == doc['stats'][k] for k in
                                             ('grid_cells', 'valid_cells', 'hole_cells', 'overlap_cells'))
        coverage = []
        for i, s in enumerate(sources):
            measured = summarize(winning[i])
            datum = s.get('vertical_datum', 'unstated')
            coverage.append(dict(id=s['id'], code=s['code'], contributor_cells=measured['cells'],
                source_support_cells=native_counts[i], area_km2=measured['cells']*target.res[0]**2/1e6,
                percent_of_grid=100*measured['cells']/total,
                percent_of_valid=100*measured['cells']/stat['cells'] if stat['cells'] else None,
                selected_elevation=measured, vertical_datum=datum,
                datum_unresolved=s.get('datum_unresolved', False) or str(datum).lower() in {'unstated', 'unknown', ''},
                vertical_offset_m=s['vertical_offset_m'], offset_note=s.get('offset_note', ''),
                vertical_transform_status=s.get('vertical_transform_status', 'explicit_constant_only_not_a_geodetic_transform'),
                native_resolution_m=s.get('native_resolution_m'), citation=s.get('citation'),
                rights=s.get('rights'), attribution=s.get('attribution')))
        checks['manifest_contributor_counts_match'] = all(
            v['contributor_cells'] == doc['contributor_cells'][str(v['code'])] for v in coverage)
        seams = []
        for (i, j), acc in pair_acc.items():
            measured = summarize(acc)
            seams.append(dict(sources=[ids[i], ids[j]], overlap_cells=acc['n'],
                status='measured' if acc['n'] else 'unavailable', rms_m=measured['rms_m'],
                mean_delta_m=measured['mean_m'], stddev_delta_m=measured['stddev_m'],
                minimum_delta_m=measured['minimum_m'], maximum_delta_m=measured['maximum_m'],
                maximum_absolute_delta=pair_peak[(i, j)],
                datum_unresolved=coverage[i]['datum_unresolved'] or coverage[j]['datum_unresolved'],
                caveat='Difference is first source minus second after explicit constants, not datum accuracy.',
                reason=None if acc['n'] else 'No jointly valid source cells on mosaic grid'))
        # Reserve output only after every input and all numerical diagnostics succeeded.
        output.mkdir(parents=True, exist_ok=False)
        full_image = f'{ident}-hillshade.png'
        hillshade_png(target, output/full_image)
        step = max(1, math.ceil(max(w, h)/1800))
        oh, ow = math.ceil(h/step), math.ceil(w/step)
        with rasterio.open(output/full_image) as image:
            pixels = image.read(out_shape=(2, oh, ow), resampling=Resampling.nearest).transpose(1, 2, 0)
        overview = f'{ident}-hillshade-overview.png'
        write_png(output/overview, ow, oh, [pixels])
        codes_preview = contributor.read(1, out_shape=(oh, ow), resampling=Resampling.nearest)
        palette = np.array([[0, 0, 0, 0]] + [[(67+i*79)%256, (157+i*47)%256, (211+i*37)%256, 255]
                                          for i in range(len(sources))], dtype=np.uint8)
        coverage_image = f'{ident}-contributors.png'
        write_png(output/coverage_image, ow, oh, [palette[codes_preview]], channels=4)
        images = [dict(path=full_image, pixel_bbox=[0, 0, w, h], sampling='native 10 m if target is 10 m'),
                  dict(path=overview, pixel_bbox=[0, 0, w, h], sampling='nearest display overview, not statistics'),
                  dict(path=coverage_image, pixel_bbox=[0, 0, w, h], sampling='nearest display overview',
                       legend=[dict(code=s['code'], id=s['id'], rgba=palette[s['code']].tolist()) for s in sources])]
        # Reproducible close-ups: worst measured overlap and one central winning cell per source.
        centers = [(f'overlap-{i}-{j}', p['pixel']) for (i, j), p in pair_peak.items() if p]
        for s in sources:
            points = np.argwhere(codes_preview == s['code'])
            if points.size:
                rr, cc = points[len(points)//2]
                centers.append((s['id'], [int((cc+.5)*w/ow), int((rr+.5)*h/oh)]))
        for label, (cx, cy) in centers:
            left, top = max(0, min(cx-500, w-1000)), max(0, min(cy-500, h-1000))
            box = [left, top, min(w, left+1000), min(h, top+1000)]
            filename = f'{ident}-{label}-detail.png'
            hillshade_png(target, output/filename, box)
            images.append(dict(path=filename, pixel_bbox=box, sampling='native target grid; 1-cell halo'))
        checks['passed'] = (all(value == 0 for key, value in checks.items() if key.endswith('mismatches'))
                            and all(value for key, value in checks.items() if key.endswith('_matches') or key.endswith('_match')))
        return dict(id=ident, stats=stats, hole_count=len(holes), holes=holes, seam_rms=seams,
                    sources=coverage, hillshade=full_image, images=images, consistency=checks,
                    grid=dict(width=w, height=h, crs=str(target.crs), transform=list(target.transform)[:6],
                              bounds=list(target.bounds), resolution_m=target.res[0]),
                    limitations=doc.get('limitations', []) + LIMITATIONS, inputs=receipts)


def packet(config, output):
    """One admitted C1 segment per regional packet; never silently downsample stats."""
    config, output = Path(config).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    doc = json.loads(config.read_text())
    if len(doc.get('segments', [])) != 1 or 'manifest' not in doc['segments'][0]:
        raise ValueError('Regional path requires exactly one C1 segment')
    ancestor = output.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < RESERVE_BYTES + 2*1024**3:
        raise ValueError('Insufficient disk reserve for regional QA')
    segment = doc['segments'][0]
    region, ident = name(doc['region']), name(segment['id'])
    manifest = local(segment['manifest'], config.parent)
    manifest_hash = digest(manifest)
    result = segment_packet(manifest, output, ident)
    report = dict(schema='coast-region-qa-v1', region=region, status='review_required', navigation=LABEL,
        processing='bounded-regional-v1', limits=dict(max_cells=MAX_CELLS, max_side=MAX_SIDE, strip_rows=STRIP_ROWS,
        max_sources=16, disk_reserve_bytes=RESERVE_BYTES), limitations=LIMITATIONS,
        segments=[result], inputs=[dict(segment=ident, manifest_sha256=manifest_hash, path=str(manifest))],
        config_sha256=digest(config), software=dict(numpy=np.__version__, rasterio=rasterio.__version__,
        gdal=rasterio.__gdal_version__), code_sha256={p.name: digest(p) for p in
        (Path(__file__), Path(__file__).with_name('coast_qa.py'))})
    dump(output/'qa.json', report)
    lines = [LABEL, f'Region: {region}; segment: {ident}', 'Status: review_required', *LIMITATIONS,
             'Full native grid; statistics were not downsampled.', json.dumps(result['stats']),
             f"Four-connected void components: {result['hole_count']}; full list in qa.json",
             'Source coverage (contributor/winning pixels; overlapping support is listed separately):']
    lines += [json.dumps(row) for row in result['sources']]
    lines += ['Pairwise source differences:', *[json.dumps(row) for row in result['seam_rms']],
              'Consistency checks: ' + json.dumps(result['consistency']),
              'Hillshades: azimuth 315 degrees, altitude 45 degrees, z factor 1; transparent nodata.',
              *[json.dumps(row) for row in result['images']]]
    (output/'QA.txt').write_text('\n'.join(lines)+'\n')
    dump(output/'run-config.json', doc)
    return report
