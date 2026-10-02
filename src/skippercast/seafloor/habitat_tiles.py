"""Native-spacing disk-backed habitat processing with disjoint tile ownership.

Terrain reads include derivative halos; morphology has its own two-pixel halo.
Thresholds use every eligible reach sample, not per-tile percentiles. Components
join across horizontal, vertical and diagonal tile edges before area filtering.
Temporary rasters are implementation scratch, never published source evidence.
"""
from contextlib import contextmanager
import math
from pathlib import Path
import shutil

import numpy as np
import rasterio
from rasterio.features import geometry_mask, shapes
from rasterio.windows import Window
from scipy.ndimage import label, find_objects
from shapely.geometry import mapping, shape, box
from shapely.ops import unary_union
import shapely

from .resolution_profile import fine_detail_valid
from .substrate import class_reader
from .terrain_support import support_reader
from .terrain import derivatives

TILE_EDGE = 1024
MONOLITHIC_PIXELS = 20_000_000


def windows(shape, edge=TILE_EDGE, halo=0):
    height, width = shape
    for y in range(0, height, edge):
        for x in range(0, width, edge):
            core = (slice(y, min(height, y+edge)), slice(x, min(width, x+edge)))
            padded = (slice(max(0, y-halo), min(height, y+edge+halo)),
                      slice(max(0, x-halo), min(width, x+edge+halo)))
            local = (slice(y-padded[0].start, core[0].stop-padded[0].start),
                     slice(x-padded[1].start, core[1].stop-padded[1].start))
            yield core, padded, local


class Scratch:
    """Track mapped arrays so files can be closed on success and exceptions."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.arrays = []
        self.sequence = 0

    def array(self, shape, dtype, fill=0):
        self.sequence += 1
        path = self.directory/f'{self.sequence}.npy'
        required = math.prod(shape)*np.dtype(dtype).itemsize
        if shutil.disk_usage(self.directory).free < required+64*1024**2:
            raise ValueError('Insufficient scratch disk for native habitat processing')
        value = np.lib.format.open_memmap(path, mode='w+', dtype=dtype, shape=shape)
        if fill != 0:
            value[:] = fill
        self.arrays.append(value)
        return value

    def close(self):
        for value in self.arrays:
            value.flush()
            value._mmap.close()
        self.arrays.clear()


@contextmanager
def scratch(directory):
    owner = Scratch(directory)
    try:
        yield owner
    finally:
        owner.close()


def source_grid(vrt, window, source, support, binding, *, root, scratch, edge=TILE_EDGE):
    shape_ = (int(window.height), int(window.width))
    affine = vrt.window_transform(window)
    depth = scratch.array(shape_, 'float32', np.nan)
    valid = scratch.array(shape_, 'bool')
    inside = scratch.array(shape_, 'bool')
    terrain = {key: scratch.array(shape_, 'float32', np.nan) for key in ('vrm', 'bpi_fine_m')}
    classes = scratch.array(shape_, 'uint8')
    resolution = source['row']['resolution_m']
    halo = max(2, round(100/resolution))
    needed = support.buffer(255)
    max_read, read_count = 0, 0
    with class_reader(binding, shape_, affine, root=root) as read_classes, \
            support_reader(source, shape_, affine, root=root) as read_support:
        for core, padded, local in windows(shape_, edge, halo):
            ys, xs = core
            corners = [affine*(xs.start, ys.start), affine*(xs.stop, ys.stop)]
            if not box(*corners[0], *corners[1]).intersects(needed):
                continue
            py, px = padded
            source_window = Window(window.col_off+px.start, window.row_off+py.start,
                                   px.stop-px.start, py.stop-py.start)
            pixels = int(source_window.width*source_window.height)
            if pixels > MONOLITHIC_PIXELS:
                raise ValueError('Derivative halo exceeds bounded native tile capacity')
            max_read = max(max_read, pixels); read_count += 1
            data = vrt.read(1, window=source_window, masked=True).astype('float32')
            values = data.filled(np.nan)
            good = fine_detail_valid(values, ~np.ma.getmaskarray(data) & np.isfinite(values), source['row'])
            values = np.where(good, values, np.nan)
            layers = derivatives(values, good, resolution)
            depth[core], valid[core] = values[local], good[local]
            tile_affine = affine*rasterio.Affine.translation(xs.start, ys.start)
            inside[core] = geometry_mask([mapping(support)], depth[core].shape, tile_affine, invert=True) & good[local]
            if source['row'].get('terrain_support'):
                inside[core] &= read_support(Window(xs.start, ys.start, xs.stop-xs.start, ys.stop-ys.start))
            classes[core] = read_classes(Window(xs.start, ys.start, xs.stop-xs.start, ys.stop-ys.start))
            for key in terrain:
                terrain[key][core] = layers[key][local].astype('float32')
    return {'depth': depth, 'valid': valid, 'inside': inside, 'terrain': terrain,
            'classes': classes, 'affine': affine, 'support': support, 'source': source,
            'binding': binding, 'tiled': True,
            'processing': {'method': 'native-disk-backed-tiles-v1', 'tile_edge_pixels': edge,
                           'window_pixels': math.prod(shape_), 'max_read_pixels': max_read,
                           'read_tiles': read_count}}


def threshold_samples(grid, key, edge=TILE_EDGE):
    for core, _, _ in windows(grid['depth'].shape, edge):
        depth, values = grid['depth'][core], grid['terrain'][key][core]
        mask = grid['inside'][core] & np.isfinite(values) & (depth > 0) & (depth <= 91.44)
        yield values[mask]


def thresholds(grids, rules, scratch, edge=TILE_EDGE):
    result = {}
    for key in ('vrm', 'bpi_fine_m'):
        count = sum(values.size for grid in grids for values in threshold_samples(grid, key, edge))
        result[key+'_samples'] = int(count)
        if not count:
            result[key] = 'unknown'
            continue
        values = scratch.array((count,), np.result_type(*[grid['terrain'][key].dtype for grid in grids]))
        offset = 0
        for grid in grids:
            for chunk in threshold_samples(grid, key, edge):
                values[offset:offset+chunk.size] = chunk
                offset += chunk.size
        if key == 'vrm':
            # Exact percentile, partitioning the expendable disk array in place.
            result[key] = float(np.percentile(values, rules['vrm_percentile'], overwrite_input=True))
        else:
            # Two bounded passes avoid np.std's whole-array float64 temporary.
            size = edge**2
            mean = math.fsum(float(np.sum(values[i:i+size], dtype='float64'))
                             for i in range(0, count, size))/count
            variance = math.fsum(float(np.sum((values[i:i+size].astype('float64')-mean)**2))
                                 for i in range(0, count, size))/count
            result[key] = math.sqrt(variance)
    return result


class Components:
    def __init__(self):
        self.parents = [0]
        self.stats = [None]

    def add(self, stats):
        ident = len(self.parents)
        if ident >= np.iinfo('int32').max:
            raise ValueError('Too many native habitat components')
        self.parents.append(ident); self.stats.append(stats)
        return ident

    def root(self, ident):
        ident = int(ident)
        while self.parents[ident] != ident:
            self.parents[ident] = self.parents[self.parents[ident]]
            ident = self.parents[ident]
        return ident

    def join(self, a, b):
        for left, right in np.unique(np.column_stack((a.ravel(), b.ravel())), axis=0):
            if left and right:
                left, right = self.root(left), self.root(right)
                self.parents[max(left, right)] = min(left, right)


def join_edges(labels, core, components):
    ys, xs = core
    height, width = labels.shape
    if ys.start:
        for delta in (-1, 0, 1):
            low, high = max(xs.start, -delta), min(xs.stop, width-delta)
            components.join(labels[ys.start, low:high], labels[ys.start-1, low+delta:high+delta])
    if xs.start:
        for delta in (-1, 0, 1):
            low, high = max(ys.start, -delta), min(ys.stop, height-delta)
            components.join(labels[low:high, xs.start], labels[low+delta:high+delta, xs.start-1])


def extract_grid(grid, limits, rules, reach, scratch, edge=TILE_EDGE):
    from .habitat import rough_mask, feature_for_patch
    shape_ = grid['depth'].shape
    rough = scratch.array(shape_, 'bool')
    labels = scratch.array(shape_, 'int32')
    resolution = grid['source']['row']['resolution_m']
    minimum = math.ceil(rules['minimum_patch_m2']/resolution**2)
    components = Components()
    for core, padded, local in windows(shape_, edge, 2):
        mask = rough_mask(grid['depth'][padded], grid['valid'][padded], grid['inside'][padded],
                          {k: v[padded] for k, v in grid['terrain'].items()}, grid['classes'][padded], limits, rules)[local]
        rough[core] = mask
        if not mask.any():
            continue
        piece, _ = label(mask, structure=np.ones((3, 3)))
        counts = np.bincount(piece.ravel())
        boundary = set(np.concatenate((piece[0], piece[-1], piece[:, 0], piece[:, -1])).tolist())
        kept = {i for i, count in enumerate(counts) if i and (count >= minimum or i in boundary)}
        slices = find_objects(piece)
        remap = np.zeros(len(counts), 'int32')
        for ident in sorted(kept):
            roi = slices[ident-1]
            selected = piece[roi] == ident
            depths, classes = grid['depth'][core][roi][selected], grid['classes'][core][roi][selected]
            remap[ident] = components.add({'count': int(counts[ident]), 'minimum': float(depths.min()),
                'maximum': float(depths.max()), 'known': int((classes > 0).sum()), 'hard': int((classes == 3).sum())})
        labels[core] = remap[piece]
        join_edges(labels, core, components)
    merged = {}
    for ident, stats in enumerate(components.stats[1:], 1):
        root = components.root(ident)
        if root not in merged:
            merged[root] = dict(stats)
        else:
            value = merged[root]
            for key in ('count', 'known', 'hard'):
                value[key] += stats[key]
            value['minimum'] = min(value['minimum'], stats['minimum'])
            value['maximum'] = max(value['maximum'], stats['maximum'])
    kept = {ident for ident, stats in merged.items() if stats['count'] >= minimum}
    if not kept:
        return []
    lookup = np.array([components.root(i) if components.root(i) in kept else 0
                       for i in range(len(components.parents))], 'int32')
    path = scratch.directory/f'labels-{len(scratch.arrays)}.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=shape_[1], height=shape_[0], count=1,
                       dtype='int32', crs='EPSG:3310', transform=grid['affine'], nodata=0,
                       tiled=True, compress='lzw', BIGTIFF='IF_SAFER') as target:
        for core, _, _ in windows(shape_, edge):
            ys, xs = core
            target.write(lookup[labels[core]], 1, window=Window(xs.start, ys.start, xs.stop-xs.start, ys.stop-ys.start))
    polygons = {}
    with rasterio.open(path) as source:
        for geometry, ident in shapes(rasterio.band(source, 1), connectivity=8):
            if ident:
                polygons.setdefault(int(ident), []).append(shapely.make_valid(shape(geometry)))
    features = []
    for ident, parts in sorted(polygons.items()):
        stats = merged[ident]
        feature = feature_for_patch(grid, unary_union(parts), stats, rough, rules, reach)
        if feature:
            features.append(feature)
    return features
