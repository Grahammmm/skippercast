"""Native valid-pixel footprints and disjoint 250 m cell coverage.

Footprints are projected to EPSG:3310 before area/intersection calculations.
An absent interpolation mask stays unknown; explicit filled pixels are excluded.
"""
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.features import shapes
from rasterio.windows import Window
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union
import shapely

from .raster import chunks


def cell_geometry(cell):
    prefix, x, y = cell['id'].split(':')
    if prefix != '3310':
        raise ValueError('Planning cell must use EPSG:3310')
    x, y = int(x)*250, int(y)*250
    return box(x, y, x+250, y+250)


def priority(row):
    year = row['year'] if isinstance(row['year'], int) else -1
    # A fine display grid containing upsampled deep pixels is not uniformly
    # fine evidence. Rank its overlap conservatively at the coarser resolution.
    profile = row.get('resolution_profile')
    resolution = profile['coarse_resolution_m'] if profile else row['resolution_m']
    return resolution, -year, row['id']


def valid_depth(depth, mask, interpolated=None):
    valid = mask & np.isfinite(depth) & (depth > 0) & (depth <= 91.44)
    if interpolated is not None:
        valid &= ~interpolated
    return valid


def footprint(path, reviewed_bounds, *, clip=None):
    """Polygonize normalized source pixels, not its bounding box or an overview."""
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    # Densify geographic bounds before projection; they delimit the reviewed window.
    review = transform(project, shapely.segmentize(box(*reviewed_bounds), .001))
    if clip is not None:
        review = review.intersection(clip)
    pieces = []
    with rasterio.open(path) as source:
        if source.descriptions[0] != 'depth_m_positive_down':
            raise ValueError('Coverage requires normalized positive-down depth')
        to_grid = Transformer.from_crs(source.crs, 3310, always_xy=True).transform
        for window in chunks(Window(0, 0, source.width, source.height)):
            tr = source.window_transform(window)
            bounds = rasterio.windows.bounds(window, source.transform)
            projected = transform(to_grid, shapely.segmentize(box(*bounds), 100))
            if not projected.intersects(review):
                continue
            depth = source.read(1, window=window, masked=True)
            valid = valid_depth(depth.filled(np.nan), ~np.ma.getmaskarray(depth))
            for geometry, value in shapes(valid.astype('uint8'), mask=valid, transform=tr):
                if value:
                    part = transform(to_grid, shapely.segmentize(shape(geometry), 100)).intersection(review)
                    if not part.is_empty:
                        pieces.append(part)
    return unary_union(pieces)


def classify_cells(cells, sources):
    """Choose finest, then newest single qualifying source; never sum overlaps.

Tier-1 band area is the reference-band share of classified cells, not a claim
that every square meter was surveyed. Exact selected valid footprint is separate.
"""
    ordered = sorted(sources, key=lambda s: priority(s['row']))
    output = []
    for cell in cells:
        square = cell_geometry(cell)
        candidates = []
        for source in ordered:
            if not square.intersects(source['geometry']):
                continue
            area = min(62500.0, square.intersection(source['geometry']).area)
            if area > 1e-6:
                candidates.append((source, area))
        qualified = [(s, a) for s, a in candidates if a >= 62500*.25 - 1e-6]
        chosen = qualified[0] if qualified else (candidates[0] if candidates else None)
        out = dict(cell, tier=1 if qualified else 0,
                   source_id=chosen[0]['row']['id'] if chosen else 'unknown',
                   valid_area_m2=round(chosen[1], 6) if chosen else 0,
                   valid_fraction=round(chosen[1]/62500, 8) if chosen else 0,
                   available_source_ids=list(dict.fromkeys(s['row']['id'] for s, _ in candidates)),
                   interpolation_mask='unknown' if chosen else 'not-applicable')
        output.append(out)
    return output
