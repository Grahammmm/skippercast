"""Measure independent corresponding grid controls; never infer feature alignment."""
import hashlib
import json
import math
from pathlib import Path

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_CELLS = 1024 * 1024


class AlignmentValidityHold(ValueError):
    """Dispatch validity hold; it never changes the immutable measurement."""
    def __init__(self, holds):
        self.holds = sorted(set(holds))
        super().__init__("alignment_dispatch_held:" + ",".join(self.holds))


def identity(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("artifact_byte_bound")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def check_geotiff(path):
    # Reject URL/VRT drivers before GDAL can follow any referenced resources.
    from ..handoff.common import validate_derived_geotiff
    path = Path(path)
    observed = identity(path)
    with path.open("rb") as stream:
        if stream.read(4) not in (b"II*\0", b"MM\0*", b"II+\0", b"MM\0+"):
            raise ValueError("local_geotiff_required")
    validate_derived_geotiff(path.parent, {"path": path.name, **observed}, cap=MAX_FILE_BYTES)


def check_header(dataset):
    if (dataset.driver != "GTiff" or dataset.crs is None
            or dataset.width < 2 or dataset.height < 2
            or dataset.width * dataset.height > MAX_CELLS or len(dataset.files) != 1):
        raise ValueError("unsupported_or_unbounded_raster")
    t = dataset.transform
    if not all(math.isfinite(v) for v in t) or t.a <= 0 or t.e >= 0 or t.b or t.d:
        raise ValueError("north_up_grid_required")


def measure_alignment(terrain_path, imagery_path, control_points, *,
                      minimum_overlap=0.95, maximum_residual_cells=0.5, correspondence=None, root=None, now=None, minimum_valid_until=None):
    """Controls are independently corresponding [column,row] pixel centers.

    A transform round trip cannot establish correspondence. Controls must come
    from an independently known grid mapping or surveyed corresponding features.
    This measures their georeferencing residual, not photogrammetric accuracy.
    """
    import numpy as np
    import rasterio
    from rasterio.warp import transform
    from shapely.geometry import Polygon

    if not (0 < minimum_overlap <= 1 and 0 < maximum_residual_cells < 1):
        raise ValueError("invalid_alignment_threshold")
    if not isinstance(control_points, list) or not 4 <= len(control_points) <= 64:
        raise ValueError("four_to_64_independent_controls_required")
    check_geotiff(terrain_path)
    check_geotiff(imagery_path)
    terrain_id, imagery_id = identity(terrain_path), identity(imagery_path)
    with rasterio.open(terrain_path) as terrain, rasterio.open(imagery_path) as image:
        check_header(terrain)
        check_header(image)
        if not terrain.crs.is_projected or terrain.crs.linear_units != "metre":
            raise ValueError("metric_terrain_crs_required")
        tp, ip, controls = [], [], []
        for point in control_points:
            a, b = point["terrain_pixel"], point["imagery_pixel"]
            if len(a) != 2 or len(b) != 2:
                raise ValueError("invalid_control_shape")
            for pixel, ds in ((a, terrain), (b, image)):
                if (not all(isinstance(v, (int, float)) and math.isfinite(v) for v in pixel)
                        or not 0 <= pixel[0] < ds.width or not 0 <= pixel[1] < ds.height):
                    raise ValueError("control_outside_grid")
            tp.append(a)
            ip.append(b)
            controls.append({"terrain_pixel": list(a), "imagery_pixel": list(b)})
        # Both mappings must span a surface, rather than a single line or corner.
        if any(np.linalg.matrix_rank(np.c_[p, np.ones(len(p))]) < 3 for p in (tp, ip)):
            raise ValueError("noncollinear_controls_required")
        tx, ty = zip(*(terrain.transform @ (c + 0.5, r + 0.5) for c, r in tp))
        ix, iy = zip(*(image.transform @ (c + 0.5, r + 0.5) for c, r in ip))
        ix, iy = transform(image.crs, terrain.crs, ix, iy)
        residuals = [math.hypot(x - u, y - v) for x, y, u, v in zip(tx, ty, ix, iy)]
        # Densify boundary before reprojection; footprint overlap is separate.
        boundary = []
        for x0, y0, x1, y1 in ((0, 0, image.width, 0), (image.width, 0, image.width, image.height),
                                  (image.width, image.height, 0, image.height), (0, image.height, 0, 0)):
            for step in range(16):
                f = step / 16
                boundary.append(image.transform @ (x0 + f * (x1 - x0), y0 + f * (y1 - y0)))
        bx, by = transform(image.crs, terrain.crs, *zip(*boundary))
        footprint = Polygon(zip(bx, by))
        bounds = Polygon([terrain.transform @ p for p in
                          ((0, 0), (terrain.width, 0), (terrain.width, terrain.height), (0, terrain.height))])
        overlap = bounds.intersection(footprint).area / bounds.area
        resolution = min(abs(terrain.transform.a), abs(terrain.transform.e))
        maximum = max(residuals)
        holds = correspondence_holds(correspondence, controls, terrain_id, imagery_id, root=root, now=now)
        if overlap < minimum_overlap:
            holds.append("imagery_footprint_overlap_insufficient")
        if maximum > resolution * maximum_residual_cells:
            holds.append("independent_control_residual_exceeded")
        if minimum_valid_until is not None:
            dispatch_holds = correspondence_holds(correspondence, controls, terrain_id, imagery_id,
                                                  root=root, now=now, minimum_valid_until=minimum_valid_until)
            if dispatch_holds:
                raise AlignmentValidityHold(dispatch_holds)
        return {"schema": "alignment-receipt-v1", "status": "held" if holds else "ready",
                "holds": holds, "terrain": terrain_id, "imagery": imagery_id,
                "control_points": controls, "control_point_convention": "pixel_center",
                "method": "reviewed_corresponding_controls_georeferencing",
                "correspondence": correspondence,
                "photogrammetric_alignment_verified": False,
                "footprint_overlap_fraction": overlap, "minimum_overlap": minimum_overlap,
                "max_residual_m": maximum, "residuals_m": residuals,
                "terrain_resolution_m": resolution, "maximum_residual_cells": maximum_residual_cells,
                "limitations": ["Correspondence requires separately byte-bound observations and independent authority review; no image-feature matching performed."]}


def verify_alignment(receipt, terrain_path, imagery_path, *, root=None, now=None, minimum_valid_until=None):
    measured = measure_alignment(terrain_path, imagery_path, receipt["control_points"],
                                 minimum_overlap=receipt["minimum_overlap"],
                                 maximum_residual_cells=receipt["maximum_residual_cells"],
                                 correspondence=receipt.get("correspondence"), root=root, now=now,
                                 minimum_valid_until=minimum_valid_until)
    if measured != receipt:
        raise ValueError("alignment_receipt_measurement_or_identity_mismatch")
    if measured["status"] != "ready":
        raise ValueError("alignment_held")
    return measured


def correspondence_holds(packet, controls, terrain_id, imagery_id, *, root, now, minimum_valid_until=None):
    """Verify separately supplied observations and review, never author either.

    An independently supplied reviewer attests the observational origin. Numeric
    residuals and a caller boolean cannot establish that origin themselves.
    """
    from ..handoff.common import load, resolve, epoch
    from ..receipts import digest
    if packet is None or root is None or now is None:
        return ["independent_correspondence_evidence_missing"]
    if not isinstance(packet, dict) or set(packet) != {"observations", "review"}:
        raise ValueError("correspondence_packet_invalid")
    for item in packet.values():
        if not isinstance(item, dict) or not {"path", "sha256", "bytes", "contract"} <= item.keys():
            raise ValueError("correspondence_requires_byte_references")
        resolve(root, item, cap=2_000_000)
    observations = load(root, packet["observations"], contract="coastal-correspondence-observations-v1")
    review = load(root, packet["review"], contract="coastal-correspondence-review-v1")
    holds = []
    controls_digest = digest(controls)
    if (observations.get("schema") != "coastal-correspondence-observations-v1"
            or observations.get("method") not in {"surveyed_control_points", "independently_known_grid_mapping"}
            or observations.get("derivation") != "observed_correspondences"
            or not observations.get("producer_id")
            or observations.get("terrain") != terrain_id or observations.get("imagery") != imagery_id
            or observations.get("controls_digest") != controls_digest):
        holds.append("correspondence_observation_binding_invalid")
    evidence = observations.get("source_evidence")
    if not isinstance(evidence, list) or not evidence:
        holds.append("correspondence_source_evidence_missing")
        evidence = []
    for item in evidence:
        resolve(root, item, cap=2_000_000)
    required = sorted({packet["observations"]["sha256"], *[item["sha256"] for item in evidence]})
    if (review.get("schema") != "coastal-correspondence-review-v1"
            or review.get("decision") != "observed_correspondences_accepted"
            or review.get("independent") is not True or not review.get("reviewer_id")
            or review.get("reviewer_id") == observations.get("producer_id")
            or review.get("reviewer_id", "").startswith("coastal.")
            or review.get("observations_sha256") != packet["observations"]["sha256"]
            or review.get("terrain") != terrain_id or review.get("imagery") != imagery_id
            or review.get("controls_digest") != controls_digest
            or review.get("evidence_read_sha256s") != required):
        holds.append("independent_correspondence_review_invalid")
    try:
        if not epoch(review["checked_at"]) <= epoch(now) < epoch(review["valid_until"]):
            holds.append("independent_correspondence_review_expired")
        if minimum_valid_until is not None and epoch(review["valid_until"]) <= epoch(minimum_valid_until):
            holds.append("independent_correspondence_review_insufficient_validity")
    except (KeyError, TypeError, ValueError):
        holds.append("independent_correspondence_review_time_invalid")
    return holds
