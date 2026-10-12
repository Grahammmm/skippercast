"""Geographic 5 km EPSG:3310 segments on the 250 m planning lattice."""
import math

CELL_M = 5000
PLANNING_M = 250


def segment(x0, y0, *, region):
    if x0 % CELL_M or y0 % CELL_M:
        raise ValueError("segment origin must be on the 5 km lattice")
    return {"schema": "coastal-segment-v1", "segment_id": f"seg:3310:{x0}:{y0}:{CELL_M}",
            "region": region, "crs": "EPSG:3310", "bbox": [x0, y0, x0+CELL_M, y0+CELL_M]}


def from_projected_bbox(bbox, *, region):
    west, south, east, north = bbox
    if not all(math.isfinite(x) for x in bbox) or west >= east or south >= north:
        raise ValueError("invalid projected bbox")
    return [segment(x, y, region=region)
            for x in range(math.floor(west/CELL_M)*CELL_M, math.ceil(east/CELL_M)*CELL_M, CELL_M)
            for y in range(math.floor(south/CELL_M)*CELL_M, math.ceil(north/CELL_M)*CELL_M, CELL_M)]


def from_bbox(bbox, *, region):
    """Transform CRS84 bounds, densifying edges rather than treating degrees as metres."""
    from pyproj import Transformer
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("invalid CRS84 bbox")
    transform = Transformer.from_crs("OGC:CRS84", "EPSG:3310", always_xy=True)
    projected = transform.transform_bounds(*bbox, densify_pts=41)
    records = from_projected_bbox(projected, region=region)
    inverse = Transformer.from_crs("EPSG:3310", "OGC:CRS84", always_xy=True)
    for record in records:
        record["bbox_crs84"] = list(inverse.transform_bounds(*record["bbox"], densify_pts=41))
    return records


def planning_cells(record):
    x0, y0, _, _ = record["bbox"]
    return [(x, y) for x in range(x0, x0+CELL_M, PLANNING_M)
            for y in range(y0, y0+CELL_M, PLANNING_M)]


def reaches_for(record, reaches):
    """Return reach IDs whose reviewed projected bounds have positive-area overlap."""
    a, b, c, d = record["bbox"]
    return sorted(r["id"] for r in reaches if r.get("crs") == "EPSG:3310"
                  and max(a, r["bbox"][0]) < min(c, r["bbox"][2])
                  and max(b, r["bbox"][1]) < min(d, r["bbox"][3]))
