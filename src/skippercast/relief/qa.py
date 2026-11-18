"""R7: measure the packaged relief bytes, then hand them to the review envelope.

Take fixed-camera shots with `region.py shots` (it runs qa_shots.mjs under a receipt) first, then pass
its shots.json here; a pack that the capture stage did not produce for this release is refused, and
each capture must show the navigation notice and rendered Chart pixels.
Mosaic elevation (NAVD88, positive up), contributor IDs and support classes
must be outputs of the packaged tile producer's elevation input (see _bind_evidence). For z16–17,
--fine-proof Z PATH
is a three-band raster (support class, elevation m positive up, native spacing
m) on that zoom's exact EPSG:3857 pixel lattice, from the current tile producer.
It describes the final contributing support after any resampling/blending;
no summary or nominal resolution can substitute for it. Unproved paint fails.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import ExitStack
import math
import mmap
from pathlib import Path
import struct
import warnings

from skippercast.paths import repo_root
from skippercast.platform.depth_contours import FT_V2, V2_MINZOOM, V2_NATIVE_ZOOM
from skippercast.relief import package, receipts
from skippercast.seafloor.rough_first import read_tiles

ARCHIVE_BUDGET = 1_500_000_000
DETAIL = package.LAYERS + 'detail.geojson'
CONTOURS = package.LAYERS + 'contours.geojson'
DEVICES = {'desktop': [1200, 800], 'phone': [390, 844]}
THEMES = ('dark', 'light')
WEB_HALF = 20037508.342789244
MEASURED_TIERS = {'1m-measured', '2m', '5m'}
NOTICE_MIN = (100, 10)  # px: the smallest box that can hold the NOT FOR NAVIGATION line


def _json(path):
    return package.decode_document(path.read_bytes())


def _inside(inner, outer, tolerance=0):
    w, s, e, n = inner
    ow, os, oe, on = outer
    return ow - tolerance <= w < e <= oe + tolerance and os - tolerance <= s < n <= on + tolerance


def _collection(root, layer, region):
    doc = _json(package.artifact_path(root, layer))
    if (doc.get('type') != 'FeatureCollection' or doc.get('region') != region
            or not isinstance(doc.get('features'), list)):
        raise ValueError(f'invalid regional GeoJSON: {layer}')
    return doc['features']


def _contour_counts(root, region):
    doc = _json(package.artifact_path(root, CONTOURS))
    provenance = doc.get('provenance', {})
    metric = 'contour_count_by_interval_ft'
    if (doc.get('type') != 'FeatureCollection' or provenance.get('region_id') != region
            or provenance.get('set') != FT_V2 or provenance.get('units') != 'ft'
            or provenance.get('publication_held') or not isinstance(doc.get('features'), list)):
        raise ValueError(f'{metric}: expected public regional ft-v2 contours')
    intervals = {8: '60', 11: '30', 13: '10', 15: '5'}
    counts = Counter()
    for feature in doc['features']:
        props = feature['properties']
        if props.get('kind') in ('survey-edge', 'unresolved-area'):
            continue
        depth = props.get('depth_ft')
        start = V2_MINZOOM.get(depth) if type(depth) is int else None
        if props.get('kind') != 'contour' or start is None or props.get('minzoom') not in (start, max(start, V2_NATIVE_ZOOM)):
            raise ValueError(f'{metric}: invalid contour depth or start zoom')
        # The native z14 replacement inherits its depth tier, not a new interval.
        counts[intervals[start]] += 1
    return dict(counts)


def _detail_count(features, elevation, support):
    import numpy as np
    from rasterio.features import geometry_mask, geometry_window
    from rasterio.warp import transform_geom
    from rasterio.errors import WindowError
    from shapely import STRtree
    from shapely.geometry import shape, mapping, box
    from rasterio.windows import Window, bounds

    parts = []
    for feature in features:
        props = feature['properties']
        tier = props.get('tier')
        if tier not in MEASURED_TIERS:
            continue
        geometry = shape(transform_geom('EPSG:4326', elevation.crs, feature['geometry']))
        if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon', 'MultiPolygon'):
            raise ValueError('measured_label_uncertified_cells: invalid measured footprint')
        parts.append((tier, geometry))
    if not parts:
        return 0
    extent = box(*elevation.bounds).buffer(0.001)
    if any(not extent.covers(geom) for _, geom in parts):
        raise ValueError('measured_label_uncertified_cells: measured footprint outside evidence grid')
    # Union per window: a cell with conflicting/repeated labels counts once.
    tree = STRtree([geom for _, geom in parts])
    windows = set()
    for _, geom in parts:
        try:
            window = geometry_window(elevation, [mapping(geom)])
        except WindowError:
            raise ValueError('measured_label_uncertified_cells: no evidence below measured footprint') from None
        for r in range(int(window.row_off) // 512, math.ceil((window.row_off + window.height) / 512)):
            for c in range(int(window.col_off) // 512, math.ceil((window.col_off + window.width) / 512)):
                windows.add((r, c))
    count = 0
    for r, c in sorted(windows):
        win = Window(c * 512, r * 512, min(512, elevation.width - c * 512), min(512, elevation.height - r * 512))
        ids = tree.query(box(*bounds(win, elevation.transform)), predicate='intersects')
        if not len(ids):
            continue
        depth = elevation.read(1, window=win, masked=True).astype('float32').filled(np.nan)
        cert = support.read(1, window=win, masked=True).filled(0) == 3 if support else False
        invalid = np.zeros(depth.shape, dtype=bool)
        for tiers, bad in (({'1m-measured'}, (~np.isfinite(depth)) | (depth > 0) | ~np.asarray(cert)),
                           ({'2m', '5m'}, (~np.isfinite(depth)) | (depth >= -20) | ~np.asarray(cert))):
            geoms = [mapping(parts[i][1]) for i in ids if parts[i][0] in tiers]
            if geoms:
                invalid |= bad & geometry_mask(geoms, depth.shape, elevation.window_transform(win), invert=True)
        count += int(np.count_nonzero(invalid))
    return count


def _lstar(rgb):
    import numpy as np

    srgb = rgb.astype('float32') / 255
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    y = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return np.where(y > (6 / 29) ** 3, 116 * np.cbrt(y) - 16, (29 / 3) ** 3 * y)


def _tile_grid(z, x, y):
    from affine import Affine

    cell = 2 * WEB_HALF / (256 << z)
    return Affine(cell, 0, -WEB_HALF + x * 256 * cell, 0, -cell, WEB_HALF - y * 256 * cell)


def _fine_pixels(ds, grid):
    import numpy as np
    from rasterio.windows import Window

    if ds is None:
        return False
    # Exact pixel lattice; averaging evidence could turn two invalid cells into a valid one.
    col, row = ~ds.transform @ (grid.c, grid.f)
    if (ds.count != 3 or ds.crs.to_epsg() != 3857 or not math.isclose(ds.transform.a, grid.a, abs_tol=1e-9)
            or not math.isclose(ds.transform.e, grid.e, abs_tol=1e-9) or ds.transform.b or ds.transform.d
            or abs(col - round(col)) > 1e-5 or abs(row - round(row)) > 1e-5):
        raise ValueError('z16plus_uncertified_pixels: fine evidence not aligned to the tile pixel lattice')
    proof = ds.read(window=Window(round(col), round(row), 256, 256), boundless=True, masked=True)
    cls, depth, spacing = proof.astype('float32').filled(np.nan)
    return (cls == 3) & (depth >= -20) & (depth <= 0) & (spacing > 0) & (spacing <= 1)


def _raster_metrics(path, release, region_bounds, elevation, contributor, fine):
    import numpy as np
    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import transform_bounds

    sizes = defaultdict(list)
    painted = transparent = land = land_paint = outside = uncertified = unevidenced = seam_n = 0
    seam_max = 0.0
    edges = {}

    def step(a, b):
        nonlocal seam_n, seam_max
        ac, al = a
        bc, bl = b
        edge = (ac > 0) & (bc > 0) & (ac != bc) & np.isfinite(al) & np.isfinite(bl)
        seam_n += int(np.count_nonzero(edge))
        if edge.any():
            seam_max = max(seam_max, float(np.max(np.abs(al[edge] - bl[edge]))))

    archive_size = path.stat().st_size
    if archive_size > ARCHIVE_BUDGET:
        return {'archive_bytes': archive_size, 'archive_budget_bytes': ARCHIVE_BUDGET}, ['archive_bytes']
    with path.open('rb') as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as archive:
        # read_tiles handles root/leaf directories and deduplicated runs. A view keeps
        # payloads in the mapped archive instead of making another archive-sized copy.
        view = memoryview(archive)
        tiles = {}
        try:
            tiles = read_tiles(view)
            if not tiles or archive[98:100] != bytes([1, 2]):
                raise ValueError('expected a nonempty PNG PMTiles archive')
            root_offset, root_length, meta_offset, meta_length = struct.unpack_from('<4Q', archive, 8)
            if not (127 <= root_offset < root_offset + root_length <= meta_offset
                    < meta_offset + meta_length <= archive_size):
                raise ValueError('invalid PMTiles metadata span')
            from gzip import decompress
            meta = package.decode_document(decompress(archive[meta_offset:meta_offset + meta_length]))
            header_zooms = list(archive[100:102])
            header_bounds = [v / 1e7 for v in struct.unpack_from('<4i', archive, 102)]
            rw, rs, re, rn = transform_bounds('EPSG:4326', 'EPSG:3857', *region_bounds)
            seam_zoom = max((z for z, _, _ in tiles if z <= 13), default=None)
            for (z, x, y), blob in sorted(tiles.items()):
                sizes[z].append(len(blob))
                with warnings.catch_warnings(), MemoryFile(bytes(blob), ext='.png') as memory:
                    warnings.simplefilter('ignore', NotGeoreferencedWarning)
                    with memory.open(driver='PNG') as tile:
                        channels = [c.name for c in tile.colorinterp]
                        if (tile.shape != (256, 256) or tile.dtypes[0] != 'uint8'
                                or channels not in (['red', 'green', 'blue'], ['red', 'green', 'blue', 'alpha'])):
                            raise ValueError('expected a 256×256 8-bit RGB or RGBA tile')
                        rgb = tile.read([1, 2, 3])
                        opaque = tile.read(4) != 0 if tile.count == 4 else tile.dataset_mask() != 0
                grid = _tile_grid(z, x, y)
                with WarpedVRT(elevation, crs='EPSG:3857', transform=grid, width=256, height=256,
                               dtype='float32', nodata=float('nan')) as vrt:
                    elevation_m = vrt.read(1)
                # Nodata and cells outside the evidence grid warp to NaN, which is neither land nor
                # sea. Such paint has no land-mask proof and fails on its own, instead of silently
                # counting as non-land.
                has_evidence = np.isfinite(elevation_m)
                is_land = has_evidence & (elevation_m > 3)  # MB-01: +3 m NAVD88 mask
                painted += int(np.count_nonzero(opaque))
                unevidenced += int(np.count_nonzero(opaque & ~has_evidence))
                transparent += int(np.count_nonzero(~opaque))
                land += int(np.count_nonzero(is_land))
                land_paint += int(np.count_nonzero(opaque & is_land))
                lon_x = grid.c + (np.arange(256) + 0.5) * grid.a
                lat_y = grid.f + (np.arange(256) + 0.5) * grid.e
                in_box = ((lat_y[:, None] >= rs) & (lat_y[:, None] <= rn)
                          & (lon_x >= rw) & (lon_x <= re))
                outside += int(np.count_nonzero(opaque & ~in_box))
                if z >= 16:
                    proof = _fine_pixels(fine.get(z), grid) if z in (16, 17) else False
                    uncertified += int(np.count_nonzero(opaque & ~np.asarray(proof)))
                if z == seam_zoom:
                    with WarpedVRT(contributor, crs='EPSG:3857', transform=grid, width=256, height=256,
                                   nodata=0) as vrt:
                        codes = vrt.read(1)
                    light = np.where(opaque, _lstar(rgb), np.nan)
                    step((codes[:-1], light[:-1]), (codes[1:], light[1:]))
                    step((codes[:, :-1], light[:, :-1]), (codes[:, 1:], light[:, 1:]))
                    if (x - 1, y) in edges:
                        step(edges[x - 1, y][0], (codes[:, 0], light[:, 0]))
                    if (x, y - 1) in edges:
                        step(edges[x, y - 1][1], (codes[0], light[0]))
                    edges[x, y] = ((codes[:, -1].copy(), light[:, -1].copy()),
                                   (codes[-1].copy(), light[-1].copy()))
        finally:
            # Keep views from escaping and holding the mapping open even on failure.
            for blob in tiles.values():
                blob.release()
            view.release()
    declared = release['bounds']
    bounds_ok = (_inside(declared, region_bounds) and all(abs(a - b) <= 5.1e-8 for a, b in zip(header_bounds, declared))
                 and outside == 0)
    def size_summary(values):
        values.sort()
        return dict(count=len(values), p50=values[math.ceil(len(values) * .5) - 1],
                    p90=values[math.ceil(len(values) * .9) - 1])

    metrics = dict(land_leak_pct=100 * land_paint / land if land else 0.0, land_pixels=land,
                   painted_land_pixels=land_paint, transparent_share=transparent / (painted + transparent),
                   painted_pixels=painted, painted_without_land_evidence=unevidenced,
                   bounds_vs_region=dict(ok=bounds_ok, archive=header_bounds, declared=declared, region=region_bounds, painted_outside=outside),
                   seam_delta_lstar={'max': round(seam_max, 6) if seam_n else None, 'edge_pairs': seam_n,
                                     'zoom': seam_zoom, 'basis': 'mosaic contributor boundaries'},
                   z16plus_uncertified_pixels=uncertified, archive_bytes=archive_size, archive_budget_bytes=ARCHIVE_BUDGET,
                   tile_bytes_by_zoom={str(z): size_summary(v) for z, v in sorted(sizes.items())},
                   navigation_archive=package.DISCLAIMER in str(meta.get('description', '')),
                   zooms_ok=([min(sizes), max(sizes)] == [release['minzoom'], release['maxzoom']]
                             == header_zooms and max(sizes) <= 17))
    failures = [name for name, failed in (
        ('land_leak_pct', land_paint), ('painted_without_land_evidence', unevidenced),
        ('painted_pixels', not painted), ('bounds_vs_region', not bounds_ok),
        ('seam_delta_lstar', seam_max > 3 + 1e-5), ('z16plus_uncertified_pixels', uncertified),
        ('zooms_ok', not metrics['zooms_ok'])) if failed]
    return metrics, failures


def _current_upstream(region, row):
    """The verified current receipt that a receipt's upstream row names."""
    verdict = receipts.check(region, row['stage'], row.get('scope'))
    if not verdict.done or verdict.receipt['generation'] != row['generation']:
        raise ValueError(f'{row["stage"]}: upstream receipt is not done and current')
    return verdict.receipt


def _bind_evidence(region, package_receipt, archive, evidence):
    """Require every evidence raster to belong to the producer of the packaged tiles.

    The packaged relief.pmtiles must be an output of exactly one current upstream receipt of the
    package (the tile producer). QA's elevation must be that producer's own elevation input, byte for
    byte. Contributor and support must come from the receipt that produced that elevation; fine-zoom
    proofs from that receipt or from the tile producer. Another current public stage's rasters, or a
    proof of different source data, cannot certify these tiles.
    """
    def owns(doc, ref):
        return any((o['path'], o['sha256']) == ref for o in doc['outputs'])

    makers = [doc for doc in (_current_upstream(region, row) for row in package_receipt['upstream'])
              if owns(doc, (package.ARCHIVE, archive['sha256']))]
    if len(makers) != 1 or makers[0].get('scope') not in (None, 'public'):
        raise ValueError('elevation: the packaged tiles have no single current public tile producer')
    tile = makers[0]
    pinned = [i for i in tile['inputs'] if i['role'] == 'elevation']
    if len(pinned) != 1 or evidence['elevation'] != (pinned[0]['path'], pinned[0]['sha256']):
        raise ValueError("elevation: not the packaged tile producer's elevation input")
    mosaics = [doc for doc in (_current_upstream(region, row) for row in tile['upstream'])
               if owns(doc, evidence['elevation'])]
    if len(mosaics) != 1 or mosaics[0].get('scope') not in (None, 'public'):
        raise ValueError('elevation: the tile producer input has no single current public producer')
    for role, ref in evidence.items():
        owners = (mosaics[0],) if role in ('contributor', 'support') else (mosaics[0], tile)
        if role != 'elevation' and not any(owns(doc, ref) for doc in owners):
            raise ValueError(f'{role}: not an output of the packaged tile producer or its elevation producer')


def _capture_outputs(region, manifest, digest, package_generation):
    """Outputs of the current capture-stage receipt that the pack must come from.

    A pack is accepted as MB-08 evidence only when `region.py shots` (the repo capture script run under
    a receipt) produced it from this exact release; a hand-built or foreign pack has no such receipt.
    """
    verdict = receipts.check(region, 'shots')
    doc = verdict.receipt
    if (not verdict.done or doc is None or doc.get('scope') is not None
            or {(u['stage'], u.get('scope'), u['generation']) for u in doc['upstream']}
            != {('package', None, package_generation)}
            or not any(i['role'] == 'release' and i['sha256'] == digest for i in doc['inputs'])):
        raise ValueError('shots: pack is not from the current capture stage receipt for this release')
    outputs = {o['path']: o['sha256'] for o in doc['outputs']}
    if outputs.get(region.record(manifest)) != receipts.sha256_file(manifest):
        raise ValueError('shots: shots.json is not an output of the capture stage receipt')
    return outputs


def _check_rendering(data, row):
    """Decode a capture and require visible chart content and an inked navigation notice.

    The capture script records the notice element's box. Pixels must show text-like ink there and
    non-uniform rendering elsewhere, so a blank or placeholder image cannot carry the claim.
    """
    import numpy as np
    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile

    width, height = DEVICES[row['device']]
    with warnings.catch_warnings(), MemoryFile(data, ext='.png') as memory:
        warnings.simplefilter('ignore', NotGeoreferencedWarning)
        with memory.open(driver='PNG') as image:
            if image.dtypes[0] != 'uint8' or image.count not in (3, 4) or image.shape != (height, width):
                raise ValueError('shots: expected an 8-bit RGB or RGBA capture at the viewport size')
            rgb = image.read([1, 2, 3])
    box = row.get('notice_box')
    if (not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box)
            or box[2] < NOTICE_MIN[0] or box[3] < NOTICE_MIN[1] or box[0] < 0 or box[1] < 0
            or box[0] + box[2] > width or box[1] + box[3] > height):
        raise ValueError('shots: capture has no usable navigation notice box')
    x, y, w, h = box
    light = _lstar(rgb)
    notice = light[y:y + h, x:x + w]
    ink = np.abs(notice - np.median(notice)) > 25  # lettering against its panel
    if not 0.02 <= ink.mean() <= 0.6:
        raise ValueError('shots: capture shows no navigation notice text in its notice box')
    chart = np.ones(light.shape, dtype=bool)
    chart[y:y + h, x:x + w] = False
    rest = light[chart]
    packed = (rgb[0].astype('uint32') << 16) | (rgb[1].astype('uint32') << 8) | rgb[2]
    colours = np.unique(packed[chart]).size
    if (np.abs(rest - np.median(rest)) > 3).mean() < 0.002 or colours < 8:
        raise ValueError('shots: capture shows no rendered Chart content')


def _shots(region, manifest, digest, release, out_dir, package_generation):
    doc = _json(manifest)
    if doc.get('release_sha256') != digest:
        raise ValueError('release_sha256: screenshot pack refers to another release')
    if doc.get('renderer') != 'mb08-chart' or type(doc.get('shots')) is not list:
        raise ValueError('shots: expected labelled MB-08 Chart evidence')
    outputs = _capture_outputs(region, manifest, digest, package_generation)
    photos, seen, hashes = [], set(), set()
    lo, hi = release['minzoom'], release['maxzoom']
    cameras = sorted({z for z in (lo, 10, 13, 15, hi) if lo <= z <= hi})
    center = doc.get('center')
    w, s, e, n = release['bounds']
    if (doc.get('cameras') != cameras or not isinstance(center, list) or len(center) != 2
            or not w <= center[0] <= e or not s <= center[1] <= n):
        raise ValueError('shots: missing fixed release cameras or camera outside release')
    expected = {(z, t, d) for z in cameras for t in THEMES for d in DEVICES}
    (out_dir / 'shots').mkdir()
    for row in doc['shots']:
        z, t, d = key = (row['zoom'], row['theme'], row['device'])
        relative = f'shots/{t}-{d}-z{z}.png'
        if (key not in expected or key in seen or row['path'] != relative or row['viewport'] != DEVICES[d]
                or row.get('navigation_visible') is not True):
            raise ValueError('shots: invalid, duplicate or unlabelled camera/theme/device shot')
        path = package.artifact_path(manifest.parent, relative)
        data = path.read_bytes()
        sha = receipts.sha256_bytes(data)
        if (row['sha256'] != sha or data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
                or list(struct.unpack_from('>II', data, 16)) != DEVICES[d]):
            raise ValueError('shots: bytes, format or viewport differs from the shot inventory')
        if outputs.get(region.record(path)) != sha or sha in hashes:
            raise ValueError('shots: capture is not a distinct output of the capture stage receipt')
        _check_rendering(data, row)
        (out_dir / relative).write_bytes(data)
        photos.append(row)
        seen.add(key)
        hashes.add(sha)
    if seen != expected:
        raise ValueError('shots: missing camera/theme/device combinations')
    return {'renderer': doc['renderer'], 'center': center, 'cameras': cameras, 'entries': photos}


def _narrative_row(region, digest, target):
    """One consumable localfeed row. The queue owner alone appends it (R8 feeder)."""
    key = f'map-{region}-qa-{digest}'
    body = (f'Read ONLY {target / "qa.json"}. Write {target.parent.parent / "qwen" / digest / "qwen.md"}. '
            'Create its parent directory if needed. Start with Review required — non-blocking narrative. '
            'Report observations from the metrics only. Do not change QA, approve anything or infer missing measurements.')
    if any(c in body for c in '\t\r\n'):
        raise ValueError('invalid localfeed path')
    return f'{key}\tskippercast\tLocal: narrative relief QA for {region} (review required)\t{body}\n'


def main(argv=None):
    parser = package.stage_parser('qa')
    parser.add_argument('--generation', required=True)
    parser.add_argument('--release-sha256', required=True, help='expected exact package hash')
    for flag in ('elevation', 'contributor', 'shots'):
        parser.add_argument(f'--{flag}', type=Path, required=True)
    parser.add_argument('--support', type=Path, help='mosaic support_class.tif; absent means no measured cells')
    parser.add_argument('--fine-proof', action='append', nargs=2, metavar=('ZOOM', 'PATH'), default=[])
    parser.add_argument('--upstream', action='append', required=True, help='public evidence producer stage[:scope]')
    args = parser.parse_args(argv)
    try:
        if not all(package.is_sha256(v) for v in (args.generation, args.release_sha256)):
            raise ValueError('invalid release generation or sha256')
        region = package.stage_region(args.out, args.region, 'qa')
        refs = [receipts.Ref('package'), *(receipts.Ref.parse(v) for v in args.upstream)]
        if (len(set(refs)) != len(refs) or any(r.scope not in (None, 'public') or
                r.stage in {'qa', 'envelope', 'publish'} for r in refs)):
            raise ValueError('QA needs unique public evidence producer receipts')
        fine_paths = {int(z): Path(p) for z, p in args.fine_proof}
        if len(fine_paths) != len(args.fine_proof) or fine_paths.keys() - {16, 17}:
            raise ValueError('fine evidence takes at most one raster per z16 or z17')
    except ValueError as exc:
        parser.error(str(exc))
    gen = args.generation
    release_rel = f'release/{gen}/release.json'
    contract = repo_root() / 'regions' / region.id / 'region.json'
    evidence = {'elevation': args.elevation, 'contributor': args.contributor,
                **{f'proof_z{z}': p for z, p in fine_paths.items()}}
    if args.support:
        evidence['support'] = args.support
    inputs = {**evidence, 'shots': args.shots, 'region': contract}
    current = {}

    def plan(upstream):
        current.update(upstream)
        return receipts.Plan([receipts.Input(path, role) for role, path in inputs.items()],
                             params={'release_generation': gen, 'release_sha256': args.release_sha256})

    def build(out_dir):
        pending = receipts.read_receipt(region.receipt_path('qa'))
        if pending is None:
            raise ValueError('QA attempt has no receipt')
        pin = {row['role']: row['sha256'] for row in pending['inputs']}
        upstream = current['package']
        raw = package.artifact_path(region.dir, release_rel).read_bytes()
        digest = receipts.sha256_bytes(raw)
        if (upstream['generation'] != gen or digest != args.release_sha256 or not any(
                r['path'] == release_rel and r['sha256'] == digest for r in upstream['outputs'])):
            raise ValueError('release_sha256: release does not match the current package receipt and expected hash')
        release = package.decode_document(raw)
        if (release.get('schema'), release.get('region'), release.get('generation')) != (package.RELEASE_SCHEMA, region.id, gen):
            raise ValueError('release_sha256: wrong release identity')
        layers = package.release_layers(release)
        for row in layers:
            if package.layer_record(region.dir, row['path']) != row:
                raise ValueError(f'layer_sha256: {row["path"]} does not match release')
        _bind_evidence(region, upstream, next(r for r in layers if r['path'] == package.ARCHIVE),
                       {role: (region.record(path), pin[role]) for role, path in evidence.items()})
        bounds = _json(contract)['bounds']
        metrics, failures = {}, []
        sources = release.get('sources')
        metrics['sources_all_public'] = bool(release.get('private') is False and isinstance(sources, list) and sources
            and all(s.get('rights_class') == 'public' and s.get('rights', {}).get('public_display') == 'allowed' for s in sources))
        if not metrics['sources_all_public']:
            failures.append('sources_all_public')
        else:
            import rasterio

            paths = {row['path'] for row in layers}
            if DETAIL not in paths:
                raise ValueError('measured_label_uncertified_cells: release has no detail layer')
            if CONTOURS not in paths:
                raise ValueError('contour_count_by_interval_ft: release has no contour layer')
            with ExitStack() as stack:
                elevation, contributor = (stack.enter_context(rasterio.open(p)) for p in (args.elevation, args.contributor))
                support = stack.enter_context(rasterio.open(args.support)) if args.support else None
                for grid in (contributor, support):
                    if grid is not None and (grid.shape, grid.crs, grid.transform) != (elevation.shape, elevation.crs, elevation.transform):
                        raise ValueError('mosaic evidence grids are not aligned')
                fine = {z: stack.enter_context(rasterio.open(p)) for z, p in fine_paths.items()}
                raster, failures = _raster_metrics(package.artifact_path(region.dir, package.ARCHIVE),
                                                    release, bounds, elevation, contributor, fine)
                metrics.update(raster)
                detail = _collection(region.dir, DETAIL, region.id)
                metrics['measured_label_uncertified_cells'] = _detail_count(detail, elevation, support)
                if metrics['measured_label_uncertified_cells']:
                    failures.append('measured_label_uncertified_cells')
            metrics['contour_count_by_interval_ft'] = _contour_counts(region.dir, region.id)
            if 'navigation_archive' in raster:
                metrics['not_for_navigation'] = release.get('disclaimer') == package.DISCLAIMER and raster['navigation_archive']
                if not metrics['not_for_navigation']:
                    failures.append('not_for_navigation')
        photos = _shots(region, args.shots, digest, release, out_dir, gen)
        # Catch evidence drift during QA; the envelope will independently rehash all release layers.
        for role, path in inputs.items():
            if receipts.sha256_file(path) != pin[role]:
                raise ValueError(f'{role}: input changed during QA')
        doc = dict(schema='sc-relief-qa/1', status='FAIL' if failures else 'PASS', region=region.id,
                   generation=gen, release_sha256=digest, metrics=metrics, failures=failures,
                   shots=photos,
                   narrative={'review_required': True, 'blocking': False, 'queue_row': 'localfeed.tsv'})
        (out_dir / 'qa.json').write_bytes(receipts.canonical(doc))
        if failures:
            raise ValueError(', '.join(failures))
        (out_dir / 'localfeed.tsv').write_text(_narrative_row(region.id, digest, region.dir / 'qa' / gen), encoding='utf-8')
        return metrics

    code = receipts.stage_digest([('qa.py', Path(__file__)),
        ('pmtiles_reader', Path(read_tiles.__code__.co_filename)),
        ('contour_contract', Path(__file__).parent.parent / 'platform/depth_contours.py')])
    run = receipts.StageRun(region, 'qa', build, code, upstream=refs, plan=plan, target=f'qa/{gen}')
    result = receipts.run_stage(run)
    print(result.line())
    return result.exit_code
