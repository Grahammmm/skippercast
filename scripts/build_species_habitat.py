"""Build soft-bottom search areas from the documented USGS survey inputs.

Usage: python scripts/build_species_habitat.py /path/to/waypoint-research
Requires numpy, scipy, rasterio, shapely, pyproj. Raw surveys stay outside Git.
The input candidate-pool.json records the three public USGS releases and paths.
Search circles are analysis windows, not complete habitat boundaries or catches.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from scipy.ndimage import distance_transform_edt
from shapely.geometry import shape, mapping, Point
from shapely.ops import transform
from pyproj import Transformer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("research", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sources = json.loads((args.research / "data/candidate-pool.json").read_text())["sources"]
    to_utm = Transformer.from_crs(4326, 32610, always_xy=True).transform
    to_geo = Transformer.from_crs(32610, 4326, always_xy=True).transform
    closed = json.loads((args.research / "data/closed-area-screen.geojson").read_text())
    exclusions = transform(to_utm, shape(closed["features"][0]["geometry"])).buffer(505)
    areas = []
    for src in sources:
        if src["key"] not in {"PointBuchon", "MorroBay", "PointEstero"}:
            continue
        with rasterio.open(args.research / src["analysis_file"]) as ds:
            depth = ds.read(1) / .3048
            cls = ds.read(7)
            mask = (cls == 1) & (depth >= 30) & (depth <= 190)
            distance = distance_transform_edt(mask) * 10
            rows, cols = np.where(distance >= 220)
            points = [(int(r), int(c)) for r, c in zip(rows[::40], cols[::40])]
            points.sort(key=lambda rc: (abs(float(depth[rc]) - 70), rc))
            chosen = []
            buckets = {"shallow": 0, "deeper": 0}
            for r, c in points:
                x, y = ds.xy(r, c)
                p = Point(x, y)
                if any(p.distance(prev) < 1300 for prev in chosen):
                    continue
                bucket = "shallow" if depth[r, c] <= 90 else "deeper"
                if buckets[bucket] >= 6:
                    continue
                poly = p.buffer(200, quad_segs=12)
                if poly.intersects(exclusions):
                    continue
                # Validate the whole analysis window against native rasters.
                native = []
                soft_fraction = None
                for key in ["bath", "substrate"]:
                    with rasterio.open(src[key]) as nd:
                        proj = Transformer.from_crs(32610, nd.crs, always_xy=True, allow_ballpark=False).transform
                        npoly = transform(proj, poly)
                        win = from_bounds(*npoly.bounds, transform=nd.transform).round_offsets().round_lengths()
                        data = nd.read(1, window=win, boundless=True, masked=True)
                        inside = geometry_mask([mapping(npoly)], data.shape, nd.window_transform(win), all_touched=True, invert=True)
                        if not inside.any() or np.ma.getmaskarray(data)[inside].any():
                            native = []
                            break
                        values = np.asarray(data)[inside]
                        if key == "bath":
                            depths = -values / .3048
                            native = [float(depths.min()), float(depths.max())]
                        else:
                            soft_fraction = float(np.mean(values == 1))
                if not native or native[0] < 25 or native[1] > 195 or soft_fraction is None or soft_fraction < .95:
                    continue
                chosen.append(p)
                buckets[bucket] += 1
                lon, lat = to_geo(x, y)
                areas.append({
                    "id": f"SOFT-{len(areas)+1:03d}", "source_id": src["key"],
                    "label": src["area"] + (" shallow sediment" if bucket == "shallow" else " outer sediment"),
                    "latitude": round(lat, 6), "longitude": round(lon, 6),
                    "depth_ft": [round(native[0], 1), round(native[1], 1)],
                    "soft_bottom_percent": round(soft_fraction * 100, 1),
                    "species": ["dungeness"] + (["halibut"] if native[1] <= 100 else []),
                    "geometry": mapping(transform(to_geo, poly)),
                    "source_url": src["source_url"], "survey_year": src["survey_year"],
                    "datum": "MLLW", "radius_m": 200,
                    "evidence": "USGS class 1: soft, flat sediment. Native depth and classification checked across the circle. Not a catch site.",
                })
            print(src["key"], buckets)
    output = {"schema_version": 1, "built_date": "2026-09-21", "areas": areas,
              "method": "200 m search circles, at least 95% native class-1 soft sediment, whole-circle native depths 25–195 ft MLLW, at least 505 m from the September 16 closure screen. Halibut subset has maximum circle depth <=100 ft. Circles are partial search windows, not sediment boundaries. No catch-based ranking."}
    (root / "dist/data/species-habitat.json").write_text(json.dumps(output, separators=(",", ":")) + "\n")
    print(len(areas), "areas written")


if __name__ == "__main__":
    main()
