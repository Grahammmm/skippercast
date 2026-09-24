"""Qualification primitives for measured, uncertainty-aware bottom habitat.

Native measurements and habitat evidence are independent requirements. This is
not a catch-probability model or a substitute for a nautical chart. GIS imports
are deferred so metadata/receipt validation remains usable by the core runtime.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


VERSION = "native-bag-habitat-v1"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_url_allowed(url: str) -> bool:
    p = urlparse(url)
    return (p.scheme == "https" and p.hostname == "data.ngdc.noaa.gov"
            and p.port in (None, 443) and not p.username and not p.password
            and p.path.startswith("/platforms/ocean/nos/coast/"))


def target_prefix(config: dict) -> str:
    prefix = config.get("target_prefix")
    if not isinstance(prefix,str) or not re.fullmatch(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*",prefix) or not 2 <= len(prefix) <= 32:
        raise ValueError("A reviewed uppercase target_prefix is required")
    return prefix


def bag_metadata(xml: str, survey_id: str) -> dict:
    """Read the embedded datum and native uncertainty meaning; fail closed."""
    if len(xml.encode()) > 1_000_000 or "<!DOCTYPE" in xml.upper():
        raise ValueError("Unsupported BAG metadata")
    root = ET.fromstring(xml)
    leaves = [(e.tag.rsplit("}", 1)[-1], (e.text or "").strip()) for e in root.iter()]
    codes = [text for name, text in leaves if name == "CharacterString"]
    horizontal = next((v for v in codes if v.startswith("PROJCS[")), None)
    vertical = next((v for v in codes if v.startswith("VERT_CS[")), None)
    if not horizontal or not vertical or not re.search(r'VERT_DATUM\["(?:MLLW(?: depth)?|Mean Lower Low Water)"', vertical):
        raise ValueError("A named MLLW vertical datum is required; unknown/ellipsoid grids are held")
    if not any(survey_id in v for v in codes):
        raise ValueError("Survey identity does not match the reviewed source")
    uncertainty = next((v for k, v in leaves if k == "BAG_VertUncertCode"), None)
    if uncertainty != "productUncert":
        raise ValueError("The reviewed adapter requires BAG productUncert semantics")
    dates = {k: v for k, v in leaves if k in ("beginPosition", "endPosition")}
    if not dates.get("beginPosition") or not dates.get("endPosition"):
        raise ValueError("Survey acquisition dates are required")
    return {"horizontal_wkt": horizontal, "vertical_wkt": vertical,
            "vertical_datum": "MLLW", "uncertainty_type": uncertainty,
            "survey_start": dates["beginPosition"], "survey_end": dates["endPosition"],
            "metadata_sha256": hashlib.sha256(xml.encode()).hexdigest()}


def cells_qualified(elevation, uncertainty, resolution_m: float, *, limit_ft=200,
                    minimum_ft=25, planning_margin_m=2, maximum_uncertainty_m=1):
    """All conditions apply per native cell, before any footprint aggregation.

The explicit 2 m planning allowance is not a water-level forecast. Product
uncertainty is used as supplied; no unverified confidence interval is invented.
"""
    import numpy as np
    if not all(math.isfinite(v) and v >= 0 for v in
               (limit_ft, minimum_ft, planning_margin_m, maximum_uncertainty_m)):
        raise ValueError("Invalid depth qualification policy")
    if limit_ft <= minimum_ft or not (0 < resolution_m <= 4):
        return np.zeros(np.shape(elevation), dtype=bool)
    a, u = np.asarray(elevation), np.asarray(uncertainty)
    if a.shape != u.shape:
        raise ValueError("Depth and uncertainty arrays must match")
    return (np.isfinite(a) & np.isfinite(u) & (a < 0) & (u > 0)
            & (u <= maximum_uncertainty_m) & (-a >= minimum_ft * .3048)
            & (-a + u + planning_margin_m <= limit_ft * .3048))


def vr_transform(outer_left, outer_bottom, coarse_x, coarse_y, row, col, meta):
    """Native supergrid affine, checked against GDAL's BAG subdataset reader.

HDF5 rows run south to north; callers flip arrays before this north-up affine.
    """
    from affine import Affine
    dx, dy = float(meta["resolution_x"]), float(meta["resolution_y"])
    x = outer_left + col * coarse_x + float(meta["sw_corner_x"]) - dx / 2
    y = outer_bottom + row * coarse_y + float(meta["sw_corner_y"]) + (int(meta["dimensions_y"]) - .5) * dy
    return Affine(dx, 0, x, 0, -dy, y)


def fresh_closures(data: dict, *, minimum_features: int, region_id="southern-california", now=None) -> None:
    if data.get("region_id") != region_id or len(data.get("features", [])) < minimum_features:
        raise ValueError("Incomplete or wrong-region closure geometry")
    now = now or datetime.now(timezone.utc)
    try:
        checked = datetime.fromisoformat(data["checked_at"].replace("Z", "+00:00"))
        age = (now - checked).total_seconds()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Closure acquisition timestamp is missing or invalid") from exc
    if not 0 <= age <= 36 * 3600:
        raise ValueError("Closure snapshot is stale or future-dated")
    for feature in data["features"]:
        geometry=feature.get("geometry",{})
        kind=geometry.get("type")
        coordinates=geometry.get("coordinates")
        if kind not in ("Polygon","MultiPolygon") or not isinstance(coordinates,list) or not coordinates:
            raise ValueError("Closure geometry must contain full polygons")
        polygons=[coordinates] if kind=="Polygon" else coordinates
        for polygon in polygons:
            if not polygon:
                raise ValueError("Closure polygon has no rings")
            for ring in polygon:
                if not isinstance(ring,list) or len(ring)<4 or ring[0]!=ring[-1]:
                    raise ValueError("Closure ring is incomplete")
                for point in ring:
                    if (not isinstance(point,(list,tuple)) or len(point)<2
                        or not all(isinstance(v,(float,int)) and math.isfinite(v) for v in point[:2])
                        or not -180<=point[0]<=180 or not -90<=point[1]<=90):
                        raise ValueError("Closure coordinates must be finite WGS84 positions")


def terrain_metrics(x, y, elevation, native_cell_m, *, hard_area_m2):
    """Transparent habitat screening metrics, explicitly uncalibrated to catches.

Use one sample per 4 m analysis bin so dense 1 m cells cannot dominate a nearby
4 m survey. The plane residual measures roughness after removing broad slope.
    """
    import numpy as np
    x, y, z = np.asarray(x), np.asarray(y), np.asarray(elevation)
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(z) & (z < 0)
    x, y, z = x[ok], y[ok], z[ok]
    if len(z) < 20:
        raise ValueError("Insufficient native samples for a terrain rank")
    bins = np.column_stack((np.floor(x/4), np.floor(y/4))).astype("int64")
    _, inv = np.unique(bins, axis=0, return_inverse=True)
    count = np.bincount(inv)
    xx = np.bincount(inv, weights=x) / count
    yy = np.bincount(inv, weights=y) / count
    zz = np.bincount(inv, weights=z) / count
    A = np.column_stack((xx - xx.mean(), yy - yy.mean(), np.ones(len(xx))))
    plane, *_ = np.linalg.lstsq(A, zz, rcond=None)
    residual = float(np.sqrt(np.mean((zz - A @ plane)**2)))
    relief = float(np.percentile(zz, 95) - np.percentile(zz, 5))
    # Physical habitat indicators, not a model fitted to catch success.
    # Smooth saturation preserves distinctions among complex sites instead of
    # assigning every large/rough patch 100. The constants are explicit design
    # scales for comparison, not ecologically fitted optimums.
    components = {"relief": 35 * relief / (relief + 12),
                  "complexity": 40 * residual / (residual + 2),
                  "hard_area": 25 * hard_area_m2 / (hard_area_m2 + 50000)}
    score = round(sum(components.values()))
    return {"habitat_score": score, "habitat_grade": "A" if score >= 75 else "B" if score >= 55 else "C",
            "grade_thresholds":{"A":75,"B":55},
            "relief_90_percent_m": round(relief, 3), "plane_residual_rms_m": round(residual, 3),
            "slope_degrees": round(math.degrees(math.atan(math.hypot(plane[0], plane[1]))), 2),
            "analysis_cell_m": 4, "analysis_samples": int(len(zz)),
            "native_resolution_max_m": float(max(native_cell_m)),
            "score_components": {k: round(v, 3) for k, v in components.items()},
            "score_method": "35×R/(R+12m) + 40×C/(C+2m) + 25×A/(A+5ha); R=p95−p05 relief, C=plane residual RMS, A=qualified hard area within250m",
            "score_type": "uncalibrated-habitat-rank", "catch_probability": None}


def contained_outline(geometry, minimum_area_m2=2500):
    """Reduce geometry size without extending into unsupported data or closures."""
    from shapely import make_valid
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    if geometry.is_empty:
        return geometry
    simple = geometry.buffer(-1).simplify(1, preserve_topology=True).intersection(geometry)
    if not simple.is_valid:
        simple = make_valid(simple)
    parts = list(simple.geoms) if hasattr(simple, "geoms") else [simple]
    from shapely.ops import unary_union
    return unary_union([p for p in parts if p.geom_type == "Polygon" and p.area >= minimum_area_m2])
