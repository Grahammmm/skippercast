"""Bounded, no-fill point-bin diagnostics; no catalog or publication credit.

Input coordinates are already in a reviewed metric CRS, depth positive down.
Supply ALL accepted contributors before depth masking, including above-water
and deep returns. Bin spacing is a processing choice, not native resolution.
Counts are returns, not independent observations or full-bin insonification.
"""
import math

import numpy as np

MAX_POINTS = 4_000_000
MAX_PIXELS = 2_000_000


def bin_points(points, *, spacing=5., bounds=None):
    """Floor-registered half-open bins, upper depth median, sample residual RMS.

    Supplied bounds must align with the zero-anchored metric lattice. Points on
    the east/north boundary are outside. No edge clamping, fill or depth filter.
    Dispersion around the median is NOT calibrated uncertainty or sample SD.
    """
    a = np.asarray(points, dtype='float64')
    if (a.ndim != 2 or a.shape[1] != 3 or len(a) > MAX_POINTS
            or not np.isfinite(a).all()):
        raise ValueError('Expected bounded finite metric XYZ/depth contributors')
    if type(spacing) not in (int, float) or not math.isfinite(spacing) or spacing <= 0:
        raise ValueError('Expected finite positive processing spacing')
    if bounds is None:
        if not len(a):
            raise ValueError('Empty contributors require explicit bounds')
        lo = np.floor(a[:, :2].min(axis=0)/spacing)*spacing
        hi = (np.floor(a[:, :2].max(axis=0)/spacing)+1)*spacing
        bounds = (*lo, *hi)
    b = np.asarray(bounds, dtype='float64')
    if b.shape != (4,) or not np.isfinite(b).all():
        raise ValueError('Invalid metric bin bounds')
    with np.errstate(over='ignore', invalid='ignore'):
        lattice = b/spacing
    if not np.isfinite(lattice).all() or np.max(np.abs(lattice)) > 2**52:
        raise ValueError('Excessive bin lattice coordinates')
    if not np.allclose(lattice, np.rint(lattice), rtol=0, atol=1e-9):
        raise ValueError('Bounds must align with the zero-anchored bin lattice')
    xmin, ymin, xmax, ymax = b
    w, h = int(round((xmax-xmin)/spacing)), int(round((ymax-ymin)/spacing))
    if min(w, h) <= 0 or w*h > MAX_PIXELS:
        raise ValueError('Invalid or excessive processing grid dimensions')
    inside = ((a[:, 0] >= xmin) & (a[:, 0] < xmax)
              & (a[:, 1] >= ymin) & (a[:, 1] < ymax))
    chosen = a[inside]
    # Absolute lattice coordinates make full-grid and tiled ownership identical.
    col = np.floor(chosen[:, 0]/spacing).astype('int64')-int(round(lattice[0]))
    bottom = np.floor(chosen[:, 1]/spacing).astype('int64')-int(round(lattice[1]))
    if np.any((col < 0) | (col >= w) | (bottom < 0) | (bottom >= h)):
        raise ValueError('Ambiguous floating boundary; do not clamp contributors')
    keys = (h-1-bottom)*w+col
    order = np.lexsort((chosen[:, 2], keys))
    keys, depth = keys[order], chosen[order, 2]
    ids, starts, counts = np.unique(keys, return_index=True, return_counts=True)
    total = h*w
    count = np.zeros(total, dtype='int64'); count[ids] = counts
    median = np.full(total, np.nan); median[ids] = depth[starts+counts//2]
    low = np.full(total, np.nan); low[ids] = depth[starts]
    high = np.full(total, np.nan); high[ids] = depth[starts+counts-1]
    dispersion = np.full(total, np.nan)
    if len(ids):
        sums = np.add.reduceat((depth-np.repeat(median[ids], counts))**2, starts)
        dispersion[ids] = np.sqrt(sums/np.maximum(counts-1, 1))
    return {'bounds': b.tolist(), 'spacing_m': float(spacing),
            'input_count': len(a), 'inside_count': len(chosen),
            **{k: v.reshape(h, w) for k, v in
               [('count', count), ('median_depth', median), ('min_depth', low),
                ('max_depth', high), ('median_residual_rms', dispersion)]}}


def supported_bins(grid, *, minimum_returns=3, maximum_depth=91.44):
    """Depth mask AFTER binning; any contributor at/above zero or too deep holds.

    This engineering count gate alone does not establish habitat-scale support.
    """
    if (isinstance(minimum_returns, bool) or not isinstance(minimum_returns, int)
            or minimum_returns < 1 or isinstance(maximum_depth, bool)
            or not math.isfinite(maximum_depth) or maximum_depth <= 0):
        raise ValueError('Invalid diagnostic support limits')
    return ((grid['count'] >= minimum_returns)
            & np.isfinite(grid['median_depth'])
            & (grid['min_depth'] > 0) & (grid['max_depth'] <= maximum_depth))


def verify_reference(points, grid):
    """Reconcile every bin with a separate Python dictionary/sort calculation."""
    xmin, ymin, xmax, ymax = grid['bounds']; spacing = grid['spacing_m']
    h, w = grid['count'].shape; groups = {}
    for x, y, depth in points:
        if xmin <= x < xmax and ymin <= y < ymax:
            key = (h-1-(math.floor(y/spacing)-round(ymin/spacing)),
                   math.floor(x/spacing)-round(xmin/spacing))
            groups.setdefault(key, []).append(float(depth))
    if sum(len(v) for v in groups.values()) != grid['inside_count']:
        raise ValueError('Reference contributor count differs')
    if len(groups) != np.count_nonzero(grid['count']):
        raise ValueError('Reference occupied-bin count differs')
    for key, values in groups.items():
        values.sort(); n = len(values); median = values[n//2]
        rms = math.sqrt(math.fsum((v-median)**2 for v in values)/max(n-1, 1))
        expected = {'count': n, 'median_depth': median, 'min_depth': values[0],
                    'max_depth': values[-1], 'median_residual_rms': rms}
        for field, value in expected.items():
            if not math.isclose(float(grid[field][key]), value, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(f'Reference {field} parity failed')
    empty = grid['count'] == 0
    if any(not np.isnan(grid[field][empty]).all() for field in
           ('median_depth', 'min_depth', 'max_depth', 'median_residual_rms')):
        raise ValueError('Missing bins must remain missing')
    return {'checked_bins': len(groups), 'checked_contributors': grid['inside_count'],
            'mismatches': 0, 'method': 'independent-dictionary-sort-fsum-v1'}
