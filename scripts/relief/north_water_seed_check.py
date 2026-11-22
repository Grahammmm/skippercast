"""Qualify an explicit seed against an offline candidate water polygon."""

from shapely.geometry import MultiPolygon, Point, Polygon


def check_seed(water: Polygon | MultiPolygon, seed: Point) -> dict:
    """Report strict containment in the supplied geometry, not shoreline quality.

    Inputs are valid, nonempty 2D shapes in the same coordinate system. No
    reprojection, snapping, seed selection or geometry repair is performed.
    Component indices are zero-based in input order (0 for a single Polygon).
    Bounds and planar areas use input units and squared input units respectively.
    A hole interior is outside; either kind of ring boundary is ambiguous.
    Components that only touch the seed are still unseeded.
    """
    if (not isinstance(water, (Polygon, MultiPolygon)) or water.is_empty
            or water.has_z or water.has_m or not water.is_valid):
        raise ValueError('expected valid, nonempty 2D candidate water geometry')
    if (not isinstance(seed, Point) or seed.is_empty
            or seed.has_z or seed.has_m or not seed.is_valid):
        raise ValueError('expected a valid, nonempty 2D seed point')

    parts = water.geoms if isinstance(water, MultiPolygon) else (water,)
    containing = None
    boundary = []
    unseeded = []
    for index, part in enumerate(parts):
        if part.contains(seed):
            # Valid multipart geometry cannot have overlapping interiors.
            containing = index
        else:
            if part.touches(seed):
                boundary.append(index)
            unseeded.append({'index': index, 'bounds': list(part.bounds), 'planar_area': part.area})

    return {
        'status': 'pass' if containing is not None else 'ambiguous' if boundary else 'outside',
        'containing_component_index': containing,
        'boundary_component_indices': boundary,
        'unseeded_components': unseeded,
    }
