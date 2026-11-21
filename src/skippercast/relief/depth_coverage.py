"""Area by depth band and survey support on an aligned water lattice."""

import numpy as np

# Fixed NAVD88 elevations in metres (positive up).
_ELEVATION_66FT = -20.1168
_ELEVATION_300FT = -91.44
# The finite nodata value written by relief.normalize for Float32 survey grids.
_SURVEY_NODATA = -np.finfo(np.float32).max


def _depth_bands(elevation):
    return (
        (elevation >= _ELEVATION_66FT) & (elevation <= 0),
        (elevation >= _ELEVATION_300FT) & (elevation < _ELEVATION_66FT),
    )


def depth_coverage(elevation, support, water, *, cell_area_m2, coarse=None) -> dict:
    """Summarize survey coverage in m² from same-shape arrays and one cell area.

    66 ft belongs to the shallow band; 300 ft belongs to the deeper band.
    Land and depths beyond 300 ft are omitted from both band areas. Missing
    survey elevations use only the coarse grid to assign a band; missing coarse
    elevations (nonfinite or no grid) go in ``unknown-band``. ``deepest_m`` is a
    positive-down depth from the survey alone, including water deeper than 300 ft.
    """
    elevation, support, water = np.asarray(elevation), np.asarray(support), np.asarray(water, dtype=bool)
    coarse = None if coarse is None else np.asarray(coarse)
    if (support.shape != elevation.shape or water.shape != elevation.shape
            or (coarse is not None and coarse.shape != elevation.shape)):
        raise ValueError('elevation, support, water and coarse must share one lattice')

    valid = np.isfinite(elevation) & (elevation != _SURVEY_NODATA)
    surveyed = water & valid & (elevation <= 0)
    measured = surveyed & (support == 3)
    estimated = surveyed & (support != 3)
    unsurveyed = water & ~valid
    survey_bands = _depth_bands(elevation)
    if coarse is None:
        coarse_bands = (False, False)
        unknown = unsurveyed
    else:
        coarse_bands = _depth_bands(coarse)
        unknown = unsurveyed & ~np.isfinite(coarse)

    area = float(cell_area_m2)
    bands = {
        name: {
            'measured_m2': np.count_nonzero(survey_band & measured) * area,
            'estimated_m2': np.count_nonzero(survey_band & estimated) * area,
            'unsurveyed_m2': np.count_nonzero(coarse_band & unsurveyed) * area,
        }
        for name, survey_band, coarse_band in zip(('0-66ft', '66-300ft'), survey_bands, coarse_bands)
    }
    bands['unknown-band'] = {
        'measured_m2': 0.0,
        'estimated_m2': 0.0,
        'unsurveyed_m2': np.count_nonzero(unknown) * area,
    }
    return {
        'bands': bands,
        'deepest_m': -float(elevation[surveyed].min()) if surveyed.any() else None,
        'reaches_300ft': bool(np.any(surveyed & (elevation <= _ELEVATION_300FT))),
    }
