"""Mask-aware terrain derivatives for measured grids in metric EPSG:3310.

Depth is positive down. BPI is neighboring mean depth minus local depth, so
raised ground is positive. Square windows approximate the named BPI radii.
"""
import numpy as np
from scipy.ndimage import binary_erosion, uniform_filter


def mean_full(values, valid, size):
    count = uniform_filter(valid.astype('float64'), size, mode='constant', cval=0)
    total = uniform_filter(np.where(valid, values, 0).astype('float64'), size, mode='constant', cval=0)
    return np.where(count >= 1-1e-10, total, np.nan)


def derivatives(depth, valid, resolution_m):
    if resolution_m <= 0 or depth.ndim != 2 or depth.shape != valid.shape:
        raise ValueError('Invalid terrain grid')
    good = valid & np.isfinite(depth)
    supported = binary_erosion(good, structure=np.ones((3, 3)), border_value=0)
    # Invalid values cannot contaminate accepted derivatives: all 3x3 neighbors are required.
    dy, dx = np.gradient(np.where(good, depth, 0).astype('float64'), resolution_m)
    length = np.sqrt(1 + dx*dx + dy*dy)
    slope = np.where(supported, np.degrees(np.arctan(np.hypot(dx, dy))), np.nan)
    nx, ny, nz = dx/length, dy/length, 1/length
    resultant = np.sqrt(sum(mean_full(v, supported, 3)**2 for v in (nx, ny, nz)))
    vrm = np.clip(1-resultant, 0, 1)
    result = {'slope_deg': slope, 'vrm': vrm}
    for name, radius in [('bpi_fine_m', 25), ('bpi_broad_m', 100)]:
        size = 2*max(1, round(radius/resolution_m))+1
        result[name] = np.where(good, mean_full(depth, good, size)-depth, np.nan)
    return result


def summarize(layers, inside):
    summary = {}
    for key, values in layers.items():
        sample = values[inside & np.isfinite(values)]
        summary[key] = {'count': int(sample.size),
                        'min': float(sample.min()) if sample.size else 'unknown',
                        'max': float(sample.max()) if sample.size else 'unknown',
                        'mean': float(sample.mean()) if sample.size else 'unknown',
                        'p80': float(np.percentile(sample, 80)) if sample.size else 'unknown'}
    return summary
