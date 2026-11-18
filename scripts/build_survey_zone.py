#!/usr/bin/env python3
"""Build offline R5c zone.geojson and detail.geojson for one region.

Inputs: region.json (id, WGS84 bounds), reviewed WGS84 ocean-water polygons
(as a GeoJSON FeatureCollection, including water outside the region), and a
statewide coarse GeoTIFF in EPSG:3310 (metres, elevation positive up). The
zone is the water portion of the coarse 0–300 ft band buffered by 1 km,
then clipped back to water and to the region. The coarse grid defines scope;
it does not count as relief data unless it also contributes to the mosaic.

The public mosaic directory supplies aligned EPSG:3310 elevation.tif,
contributor.tif (0 = no data), and manifest.json (segment, sources with
id/code/resolution_m). Pass support_class.tif with --support, or omit it to
treat all valid cells as uncertified. selection.json supplies sources keyed
by id in a sources array: rights_class, label, and optional name and date.
A compiled source has label='compiled' or provenance='compiled' alongside
label='estimated'. Date is the input source date, not the build time.

Outputs are RFC 7946 FeatureCollections. In detail, tier drives display;
grid_tier='4-16m-compiled' on an estimated feature records its grid family
without giving it a measured label. No-data features have tier='none'.
"""

import argparse
import math
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.windows import Window, from_bounds
from shapely.geometry import MultiPolygon, box, mapping, shape

from skippercast.platform.contracts import atomic_json, read_json

CRS = "EPSG:3310"
DEPTH_LIMIT_M = 91.44
BUFFER_M = 1000


def _project(geom, src, dst):
    transform = Transformer.from_crs(src, dst, always_xy=True)
    return shapely.transform(geom, transform.transform, interleaved=False)


def _polygons(geom):
    if geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield geom
    elif geom.geom_type in {"MultiPolygon", "GeometryCollection"}:
        for part in geom.geoms:
            yield from _polygons(part)


def _raster_polygons(values, transform):
    for geometry, code in shapes(values, mask=values != 0, transform=transform):
        polygon = shape(geometry)
        # Polygonization can give a self-touch at corners of raster holes.
        yield int(code), polygon if polygon.is_valid else shapely.make_valid(polygon)


def _window(grid, bounds):
    win = from_bounds(*bounds, transform=grid.transform)
    c0, r0 = max(0, math.floor(win.col_off)), max(0, math.floor(win.row_off))
    c1 = min(grid.width, math.ceil(win.col_off + win.width))
    r1 = min(grid.height, math.ceil(win.row_off + win.height))
    return Window(c0, r0, c1 - c0, r1 - r0) if c0 < c1 and r0 < r1 else None


def _open_grid(stack, path):
    if not path.is_file():
        raise ValueError(f"Expected a local raster file: {path.name}")
    grid = stack.enter_context(rasterio.open(path, driver="GTiff"))
    t = grid.transform
    if grid.crs != CRS or grid.count != 1 or t.b != 0 or t.d != 0 or t.a <= 0 or t.e >= 0:
        raise ValueError(f"{path.name} must be a north-up, single-band {CRS} raster")
    return grid


def _mapping_zone(coarse, water, bounds):
    # Read the halo before the regional clip: the contour across the region
    # edge can affect the zone inside it.
    win = _window(coarse, bounds.buffer(BUFFER_M).bounds)
    if win is None:
        return MultiPolygon()
    depth = coarse.read(1, window=win, masked=True)
    # Compare in the raster's precision (a Float32 -91.44 is slightly below
    # the Float64 literal). Keep nodata out independently of its stored value.
    band = ((depth.data >= -DEPTH_LIMIT_M) & (depth.data <= 0) & ~np.ma.getmaskarray(depth)).astype("uint8")
    shoal = shapely.union_all([geom for _, geom in _raster_polygons(band, coarse.window_transform(win))])
    shoal = shapely.union_all(list(_polygons(shoal.intersection(water))))
    return shoal.buffer(BUFFER_M).intersection(water).intersection(bounds)


def _water(path):
    document = read_json(path)
    if document["type"] != "FeatureCollection":
        raise ValueError("Water must be a WGS84 GeoJSON FeatureCollection")
    polygons = [shape(feature["geometry"]) for feature in document["features"]]
    if not polygons or any(p.is_empty or not p.is_valid or p.geom_type not in {"Polygon", "MultiPolygon"}
                           for p in polygons):
        raise ValueError("Water must contain valid, nonempty polygons")
    return _project(shapely.union_all(polygons), "EPSG:4326", CRS)


def _detail(zone, elevation, contributor, support, manifest, selection):
    win = _window(elevation, zone.bounds) if not zone.is_empty else None
    if win is None:
        return []
    codes = contributor.read(1, window=win, masked=True).filled(0)
    depth = elevation.read(1, window=win, masked=True)
    valid = codes != 0
    if np.any(valid & (np.ma.getmaskarray(depth) | ~np.isfinite(depth.data))):
        raise ValueError("Mosaic contributor has no aligned elevation")
    classes = support.read(1, window=win, masked=True).filled(0) if support else None
    if classes is not None and np.any(classes > 3):
        raise ValueError("Unknown per-cell support class")

    # Vectorize the contributor plus a single eligibility bit. Source labels
    # can veto a measured label, but only class 3 can make a cell eligible.
    deep = depth.data < -20
    certified = (classes == 3) if classes is not None else False
    metadata = {row["id"]: row for row in selection["sources"]}
    sources = {row["code"]: row for row in manifest["sources"]}
    if len(metadata) != len(selection["sources"]) or len(sources) != len(manifest["sources"]):
        raise ValueError("Duplicate selection source ID or mosaic contributor code")
    labels = np.zeros(65536, dtype="uint8")
    properties = {}
    for code in np.flatnonzero(np.bincount(codes.ravel())):
        if not code:
            continue
        source = sources.get(code)
        if source is None:
            raise ValueError(f"Mosaic contributor {code} is missing from the manifest")
        row = metadata.get(source["id"])
        if not row or row.get("rights_class") != "public":
            raise ValueError(f"Mosaic contributor {code} has no public selection row")
        grid_m = source["resolution_m"]
        if not math.isfinite(grid_m) or grid_m <= 0:
            raise ValueError(f"Mosaic contributor {code} has invalid grid spacing")
        compiled = "compiled" in (row.get("label"), row.get("provenance"))
        estimate = dict(source=row.get("name") or source["id"], sources=[source["id"]],
                        date=row.get("date"), grid_m=grid_m, tier="estimated")
        if compiled and 4 <= grid_m <= 16:
            estimate["grid_tier"] = "4-16m-compiled"
        properties[2 * code] = estimate
        if row.get("label") == "measured" and row.get("provenance", "measured") == "measured":
            tier = "1m-measured" if grid_m <= 1 else "2m" if grid_m <= 2 else "5m" if grid_m <= 5 else None
            if tier:
                labels[code] = 1 if grid_m <= 1 else 2
                properties[2 * code + 1] = dict(estimate, tier=tier)

    tier_flags = labels[codes]
    measured = certified & ((tier_flags == 1) | ((tier_flags == 2) & deep))
    groups = defaultdict(list)
    for code, polygon in _raster_polygons(codes.astype("int32") * 2 + measured, elevation.window_transform(win)):
        groups[code].append(polygon)
    return [(shapely.union_all(groups[code]).intersection(zone), properties[code]) for code in sorted(groups)]


def _feature(geom, props):
    # Zero tolerance removes redundant collinear vertices without generalizing
    # any footprint or dropping holes. Normalize order before writing GeoJSON.
    geom = shapely.union_all(list(_polygons(geom))).simplify(0, preserve_topology=True)
    if geom.is_empty:
        return None
    geom = _project(geom.normalize(), CRS, "EPSG:4326")
    return dict(type="Feature", geometry=mapping(shapely.orient_polygons(geom)), properties=props)


def build(region_path, coarse_path, water_path, mosaic, selection_path, output, *,
          coarse_source, coarse_date=None, support_path=None):
    region = read_json(region_path)
    bounds = _project(box(*region["bounds"]).segmentize(0.02), "EPSG:4326", CRS)
    manifest = read_json(mosaic / "manifest.json")
    selection = read_json(selection_path)
    if manifest["segment"] != region["id"] or selection["region"] != region["id"]:
        raise ValueError("Region, mosaic and selection must identify the same region")
    water = _water(water_path).intersection(bounds.buffer(BUFFER_M))
    with ExitStack() as stack:
        coarse = _open_grid(stack, coarse_path)
        elevation = _open_grid(stack, mosaic / "elevation.tif")
        contributor = _open_grid(stack, mosaic / "contributor.tif")
        support = _open_grid(stack, support_path) if support_path is not None else None
        for grid, dtype in [(contributor, "uint16"), (support, "uint8")]:
            if grid is not None and (grid.shape != elevation.shape or grid.transform != elevation.transform
                                     or grid.dtypes[0] != dtype):
                raise ValueError("Contributor and support grids must be aligned with mosaic elevation (uint16/uint8)")
        zone = _mapping_zone(coarse, water, bounds)
        detail = _detail(zone, elevation, contributor, support, manifest, selection)
    none = zone.difference(shapely.union_all([geom for geom, _ in detail]))
    detail.append((none, dict(tier="none", sources=[], date=None)))
    zone_props = dict(sources=[coarse_source], date=coarse_date, limit_ft=300, buffer_m=BUFFER_M)
    for name, features in [("zone", [(zone, zone_props)]), ("detail", detail)]:
        collection = dict(type="FeatureCollection", region=region["id"], navigation="NOT FOR NAVIGATION",
                          features=[f for geom, props in features if (f := _feature(geom, props)) is not None])
        atomic_json(output / f"{name}.geojson", collection, unique_tmp=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag in ("region", "coarse", "water", "mosaic", "selection", "output"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--support", type=Path, help="aligned support_class.tif; omit to treat cells as uncertified")
    parser.add_argument("--coarse-source", required=True, help="source id for the statewide coarse grid")
    parser.add_argument("--coarse-date", help="source date for the statewide coarse grid, if known")
    args = parser.parse_args()
    try:
        build(args.region, args.coarse, args.water, args.mosaic, args.selection, args.output,
              coarse_source=args.coarse_source, coarse_date=args.coarse_date, support_path=args.support)
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(1, f"build_survey_zone: {exc}\n")


if __name__ == "__main__":
    main()
