"""Compare synthetic footprint geometry with selected SoCal region boxes.

This offline diagnostic uses only the top-level configured bounds. Even a full
match describes extent, not measured survey coverage or permission to release.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry

from skippercast.platform.contracts import bbox
from skippercast.relief.package import decode_document

# The three inputs for this comparison, not a child or release registry.
_SCOPE_IDS = ("southern-california", "santa-barbara-channel", "san-diego")


@dataclass(frozen=True)
class ScopeExtent:
    status: Literal["no_evidence", "no_overlap", "partial", "full"]
    intersection: BaseGeometry
    residual: BaseGeometry


@dataclass(frozen=True)
class ExtentReport:
    evidence_region_id: str | None
    scopes: dict[str, ScopeExtent]


def compare_scope_extent(
    root: Path,
    footprint: Polygon | MultiPolygon | None,
    *,
    evidence_region_id: str | None = None,
) -> ExtentReport:
    """Compare a WGS84 (lon, lat) footprint with each box independently.

    The caller's label is provenance only. None means no evidence was supplied,
    not that no surveys exist. Residual is the part of the scope box not covered
    by the supplied footprint. Boundary-only contact is not areal overlap.
    """
    if footprint is not None and (
        not isinstance(footprint, (Polygon, MultiPolygon))
        or footprint.is_empty
        or not footprint.is_valid
    ):
        raise ValueError("Expected a valid, nonempty synthetic polygon footprint")

    scopes = {}
    for scope_id in _SCOPE_IDS:
        config = root / "regions" / scope_id / "region.json"
        region = decode_document(config.read_bytes())
        if region.get("id") != scope_id:
            raise ValueError(f"Region directory and id differ for {scope_id}")
        extent = box(*bbox(region.get("bounds")))
        if footprint is None:
            scopes[scope_id] = ScopeExtent("no_evidence", GeometryCollection(), extent)
            continue
        intersection = extent.intersection(footprint)
        residual = extent.difference(footprint)
        status = "no_overlap" if intersection.area == 0 else "full" if residual.is_empty else "partial"
        scopes[scope_id] = ScopeExtent(status, intersection, residual)
    return ExtentReport(evidence_region_id, scopes)
