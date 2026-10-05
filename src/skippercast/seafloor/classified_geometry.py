"""Bounded shell/hole representation of valid native classified polygons.

Coordinate transforms approximate edges with straight segments. Point contacts
can become tiny crossings. Only structure-aware representation is considered,
then compared with the unchanged valid native polygon. This is not repair of
invalid native evidence, hole filling, smoothing or additional habitat.
"""
import math

import pyproj
from pyproj import Transformer
import shapely
from shapely import make_valid, segmentize
from shapely.geometry import shape
from shapely.ops import transform, unary_union

VERSION = 'native-classified-geometry-v1'
# Versioned floating representation bounds in projected square metres. These
# are neither survey accuracy nor a new measurement claim; no raster is changed.
MAX_FEATURE_DIFFERENCE_M2 = .002
MAX_UNION_DIFFERENCE_M2 = .01
PROJECTION_VERSION = 'bounded-native-edge-projection-v1'
EDGE_STEPS_M = (10, 2)
MAX_PROJECTED_VERTICES = 1_000_000


def runtime():
    return {'version': VERSION, 'shapely': shapely.__version__,
            'geos': shapely.geos_version_string, 'pyproj': pyproj.__version__,
            'projection_version': PROJECTION_VERSION}


def polygon(geometry):
    value = shape(geometry) if isinstance(geometry, dict) else geometry
    if (value.geom_type not in {'Polygon', 'MultiPolygon'} or value.is_empty
            or not value.is_valid or not math.isfinite(value.area) or value.area <= 0
            or not all(math.isfinite(v) for v in value.bounds)):
        raise ValueError('Invalid classified polygon representation')
    return value


def structure(value):
    # Never use the default linework algorithm, which can interpret hole slivers
    # as filled shells. Native polygons must already be valid before this step.
    return polygon(value if value.is_valid else
                   make_valid(value, method='structure', keep_collapsed=False))


def project(value, source, target):
    return transform(Transformer.from_crs(source, target, always_xy=True).transform, value)


def _geographic(native):
    geo = structure(project(native, 3310, 4326))
    w, s, e, n = geo.bounds
    if not (-180 <= w <= e <= 180 and -90 <= s <= n <= 90):
        raise ValueError('Classified representation must be WGS84')
    return geo


def edge_vertex_count(native, step):
    """Bound allocation before adding collinear vertices to unchanged edges."""
    count = 0
    for part in native.geoms if native.geom_type == 'MultiPolygon' else (native,):
        for ring in (part.exterior, *part.interiors):
            coords = list(ring.coords)
            count += 1 + sum(max(1, math.ceil(math.hypot(b[0]-a[0], b[1]-a[1])/step))
                             for a, b in zip(coords, coords[1:]))
            if count > MAX_PROJECTED_VERTICES:
                raise ValueError('Classified projection exceeds vertex budget')
    return count


def geographic(native):
    """Keep the old faithful representation; bound nonlinear edge conversion.

    Only display conversion gains collinear vertices. The original native
    inventory, feature identity, holes, areas and legal screen stay unchanged.
    No fidelity limit is widened and invalid native evidence is never repaired.
    """
    native = polygon(native)
    failure = None
    for step in (None, *EDGE_STEPS_M):
        if step is None:
            projected_native = native
        else:
            edge_vertex_count(native, step)
            projected_native = segmentize(native, step)
        try:
            geo = _geographic(projected_native)
            fidelity(native, geo)
            return geo
        except ValueError as exc:
            failure = exc
    raise failure


def operational(geometry, crs):
    """Use only after native fidelity verification, and for classified areas."""
    geo = polygon(geometry)
    return structure(project(geo, 4326, crs))


def fidelity(native, geo):
    """Verify WGS, operational native and WebMercator representations together."""
    native, geo = polygon(native), polygon(geo)
    versions = {}
    for crs in (3310, 3857):
        rendered = operational(geo, crs)
        returned = rendered if crs == 3310 else structure(project(rendered, crs, 3310))
        difference = native.symmetric_difference(returned).area
        added = returned.difference(native).area
        if (not math.isfinite(difference) or difference > MAX_FEATURE_DIFFERENCE_M2
                or not math.isfinite(added) or added > MAX_FEATURE_DIFFERENCE_M2):
            raise ValueError('Classified representation exceeds native fidelity bound')
        versions[str(crs)] = {'symmetric_difference_m2': difference,
                             'added_area_m2': added, 'valid': True}
    return versions


def represent(native):
    geo = geographic(native)
    return geo, fidelity(native, geo)


def verify_inventory(candidates, native_inventory):
    """Native boundaries remain private and hash-bound; no IDs or patches split."""
    if native_inventory.get('crs') != 'EPSG:3310' or native_inventory.get('version') != VERSION:
        raise ValueError('Unreviewed classified native geometry inventory')
    native_rows = native_inventory['features']
    ids = [f['properties']['id'] for f in native_rows]
    if len(set(ids)) != len(ids) or ids != [f['properties']['id'] for f in candidates['features']]:
        raise ValueError('Classified representation identity mismatch')
    originals, represented = [], []
    reports = []
    for original, feature in zip(native_rows, candidates['features']):
        native = polygon(original['geometry'])
        p = feature['properties']
        if 'area_ha' in p and (type(p['area_ha']) not in (int, float)
                or not math.isfinite(p['area_ha']) or abs(p['area_ha']*10000-native.area) > 1e-6):
            raise ValueError('Classified native area claim changed')
        expected = geographic(native)
        actual = polygon(feature['geometry'])
        if not expected.equals_exact(actual, 0):
            raise ValueError('Classified canonical representation changed')
        reports.append(fidelity(native, actual))
        originals.append(native)
        represented.append(operational(actual, 3310))
    native_union, display_union = unary_union(originals), unary_union(represented)
    difference = native_union.symmetric_difference(display_union).area
    if not math.isfinite(difference) or difference > MAX_UNION_DIFFERENCE_M2:
        raise ValueError('Classified union exceeds native fidelity bound')
    return {'version': VERSION, 'runtime': runtime(), 'feature_count': len(reports),
            'native_union_area_m2': native_union.area, 'union_symmetric_difference_m2': difference,
            'max_symmetric_difference_m2': max((v['symmetric_difference_m2']
                for r in reports for v in r.values()), default=0),
            'operational_crs': ['EPSG:3310', 'EPSG:3857'],
            'max_feature_difference_m2': MAX_FEATURE_DIFFERENCE_M2,
            'max_union_difference_m2': MAX_UNION_DIFFERENCE_M2}
