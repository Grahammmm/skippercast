"""Independent readback of a C4 packet; native sampling uses pyproj, not WarpedVRT.

No downloads, publication or source writes. This verifier is run explicitly on
cached inputs; it is not collected as a test and does not require live CI data.
"""
import argparse
from hashlib import sha256
from itertools import combinations
import json
import math
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import rowcol
from rasterio.windows import Window


def digest(path):
    h = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


class VerificationError(RuntimeError):
    """A packet disagrees with its inputs; raised explicitly so `python -O` cannot skip it."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def verify(packet, manifest_path):
    packet, manifest_path = Path(packet), Path(manifest_path)
    report = json.loads((packet/'qa.json').read_text())
    segment = report['segments'][0]
    manifest = json.loads(manifest_path.read_text())
    require(report['inputs'][0]['manifest_sha256'] == digest(manifest_path), 'manifest sha256 mismatch')
    require(segment['consistency']['passed'], f"packet consistency failed: {segment['consistency']}")
    input_hashes = {}
    for entry in segment['inputs']:
        path = Path(entry['path'])
        actual = digest(path)
        require(actual == entry['sha256'], f"input sha256 mismatch: {entry['role']}")
        input_hashes[entry['role']] = actual
    paths = {key: manifest_path.parent/value['path'] for key, value in manifest['outputs'].items()}
    counts = np.zeros(len(manifest['sources'])+1, dtype=np.int64)
    coords = []
    valid_cells, overlap_cells, alpha_errors = 0, 0, 0
    with rasterio.open(paths['elevation']) as elevation, rasterio.open(paths['contributor']) as contributor, \
            rasterio.open(paths['support_count']) as support, rasterio.open(packet/segment['hillshade']) as image:
        require(image.shape == elevation.shape and image.count == 2, 'hillshade shape or band count mismatch')
        for start in range(0, elevation.height, 256):
            window = Window(0, start, elevation.width, min(256, elevation.height-start))
            values = elevation.read(1, window=window, masked=True)
            valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
            c = contributor.read(1, window=window)
            n = support.read(1, window=window)
            require(np.array_equal(valid, c > 0), f'contributor mask mismatch in rows {start}+')
            require(np.array_equal(valid, n > 0), f'support_count mask mismatch in rows {start}+')
            counts += np.bincount(c.ravel(), minlength=len(counts))
            valid_cells += int(valid.sum())
            alpha_errors += int(np.count_nonzero((image.read(2, window=window) > 0) != valid))
            r, col = np.where(n > 1)
            overlap_cells += len(r)
            if len(r):
                coords.append((r+start, col))
        require(valid_cells == segment['stats']['valid_cells'], 'valid_cells mismatch')
        require(overlap_cells == segment['stats']['overlap_cells'], 'overlap_cells mismatch')
        require(alpha_errors == 0, f'hillshade alpha mismatches: {alpha_errors}')
        require(sum(h['cells'] for h in segment['holes']) == int(counts[0]), 'hole cell total mismatch')
        require(all(s['contributor_cells'] == counts[s['code']] for s in segment['sources']),
                'contributor cell counts mismatch')
        if coords:
            rr = np.concatenate([x[0] for x in coords])
            cc = np.concatenate([x[1] for x in coords])
        else:
            rr, cc = np.array([], dtype=int), np.array([], dtype=int)
        xs, ys = elevation.transform * (cc+.5, rr+.5)
        values_by_source = []
        for source in manifest['sources']:
            result = np.full(rr.shape, np.nan)
            with rasterio.open(manifest_path.parent/source['path']) as native:
                xx, yy = Transformer.from_crs(elevation.crs, native.crs, always_xy=True).transform(xs, ys)
                nr, nc = rowcol(native.transform, xx, yy)
                nr, nc = np.asarray(nr, dtype=int), np.asarray(nc, dtype=int)
                inside = (nr >= 0) & (nc >= 0) & (nr < native.height) & (nc < native.width)
                if inside.any():
                    r0, r1 = int(nr[inside].min()), int(nr[inside].max())+1
                    c0, c1 = int(nc[inside].min()), int(nc[inside].max())+1
                    grid = native.read(1, window=Window(c0, r0, c1-c0, r1-r0), masked=True)
                    chosen = grid[nr[inside]-r0, nc[inside]-c0].astype('float64')
                    result[inside] = chosen.filled(np.nan)
            result = result * (-1 if source['value_convention'] == 'depth_positive_down' else 1) + source['vertical_offset_m']
            values_by_source.append(result)
    seams = []
    for i, j in combinations(range(len(values_by_source)), 2):
        delta = values_by_source[i]-values_by_source[j]
        delta = delta[np.isfinite(delta)]
        ids = [manifest['sources'][k]['id'] for k in (i, j)]
        expected = next(s for s in segment['seam_rms'] if s['sources'] == ids)
        require(len(delta) == expected['overlap_cells'], f'seam overlap_cells mismatch: {ids}')
        rms, mean = (float(np.sqrt(np.mean(delta**2))), float(np.mean(delta))) if len(delta) else (None, None)
        if len(delta):
            require(math.isclose(rms, expected['rms_m'], abs_tol=1e-10), f"seam rms mismatch: {ids} {rms} {expected['rms_m']}")
            require(math.isclose(mean, expected['mean_delta_m'], abs_tol=1e-10), f'seam mean delta mismatch: {ids}')
        else:
            require(expected['rms_m'] is None, f'seam rms reported without overlap: {ids}')
        seams.append(dict(sources=ids, overlap_cells=len(delta), rms_m=rms, mean_delta_m=mean))
    pngs = []
    for entry in segment['images']:
        path = packet/entry['path']
        with rasterio.open(path) as ds:
            ds.read()  # Actually decode every image, including its compressed data.
            pngs.append(dict(path=entry['path'], width=ds.width, height=ds.height,
                             channels=ds.count, bytes=path.stat().st_size, sha256=digest(path)))
    return dict(status='PASS', navigation='NOT FOR NAVIGATION; still review_required',
                method='Independent native pixel-center sampling via pyproj and floor indices; no WarpedVRT',
                input_hashes=input_hashes, valid_cells=valid_cells, hole_cells=int(counts[0]),
                contributor_counts=counts.tolist(), overlap_cells=overlap_cells,
                native_hillshade_alpha_mismatches=alpha_errors, pairwise=seams, pngs=pngs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.packet, args.manifest)
    with args.output.open('x') as file:
        json.dump(result, file, indent=2, allow_nan=False)
        file.write('\n')
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
