"""Validate a discovery lead without approving it for publication."""
from datetime import datetime
from datetime import date
import math
from pathlib import Path
import re
from .contracts import REPO, ID, bbox, load_catalogs, load_region, public_url, read_json


def text(value, name, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def validate_candidate(data, root=REPO):
    fields = {"schema_version", "id", "name", "need_ids", "documentation_url", "access_url", "access_status", "rights", "spatial", "temporal", "evidence", "limitations", "producer", "variables", "units", "provenance"}
    location_keys = {"region_ids", "sector_ids"} & set(data)
    if (set(data) != fields | location_keys or not location_keys or data["schema_version"] != 1
            or isinstance(data["schema_version"], bool)):
        raise ValueError("Candidate fields must match source-candidate.schema.json")
    if not ID.fullmatch(data["id"]):
        raise ValueError("Invalid source candidate id")
    text(data["name"], "name")
    text(data["producer"]["name"], "producer name")
    public_url(data["producer"]["url"])
    variables = data["variables"]
    if not isinstance(variables, list) or not variables or any(not isinstance(v, str) or not v.strip() for v in variables) or len(variables) != len(set(variables)):
        raise ValueError("Variables must be distinct nonempty names")
    if not isinstance(data["units"], dict) or set(data["units"]) != set(variables):
        raise ValueError("Every variable needs a unit or explicit null")
    for variable, unit in data["units"].items(): text(unit, variable + " unit", nullable=True)
    provenance = data["provenance"]
    text(provenance["access_service"], "access service", nullable=True)
    if provenance["raw_sha256"] is not None and not re.fullmatch(r"[a-f0-9]{64}", provenance["raw_sha256"]):
        raise ValueError("Invalid raw response digest")
    if not isinstance(provenance["transformations"], list): raise ValueError("Transformations must be a list")
    for value in provenance["transformations"]: text(value, "transformation")
    needs, _ = load_catalogs(root)
    for key in (*sorted(location_keys), "need_ids"):
        values = data[key]
        if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values) or len(values) != len(set(values)):
            raise ValueError(f"{key} must contain distinct identifiers")
    for region in data.get("region_ids", []):
        load_region(region, root)
    if "sector_ids" in data:
        sector_ids = {row["id"] for row in read_json(Path(root) / "catalog/coastal-sectors.json")["sectors"]}
        if not set(data["sector_ids"]) <= sector_ids:
            raise ValueError("Unknown California discovery sector")
    if not set(data["need_ids"]) <= needs.keys():
        raise ValueError("Unknown data need")
    public_url(data["documentation_url"])
    if data["access_url"] is not None:
        public_url(data["access_url"])
    if data["access_status"] not in {"not-tested", "accessible", "partial", "blocked", "unavailable"}:
        raise ValueError("Invalid access status")
    rights = data["rights"]
    for key in ("license", "terms_url"):
        text(rights[key], key, nullable=True)
    if not isinstance(rights["redistribution_reviewed"], bool):
        raise ValueError("Rights review must be a boolean")
    if rights["terms_url"]:
        public_url(rights["terms_url"])
    if rights["redistribution_reviewed"] and (not rights["license"] or not rights["terms_url"]):
        raise ValueError("Reviewed rights require a license and supporting terms")
    spatial = data["spatial"]
    if spatial["bounds"] is not None:
        bbox(spatial["bounds"])
    resolution = spatial["resolution_m"]
    if resolution is not None and (isinstance(resolution, bool) or not isinstance(resolution, (float, int)) or not math.isfinite(resolution) or resolution <= 0):
        raise ValueError("Resolution must be a positive number or null")
    for key in ("horizontal_crs", "vertical_datum"):
        text(spatial[key], key, nullable=True)
    if spatial.get("footprint_kind", "unknown") not in {"catalog-envelope", "survey-track-envelope", "valid-cell-envelope", "valid-data-mask", "measured-geometry", "unknown"}:
        raise ValueError("Unknown footprint interpretation")
    if spatial.get("resolution_basis", "unknown") not in {"advertised", "inspected", "unknown"}:
        raise ValueError("Unknown resolution basis")
    if spatial.get("footprint_url"):
        public_url(spatial["footprint_url"])
    screen = spatial.get("native_depth_screen")
    if screen is not None:
        if set(screen) != {"limit_ft", "shallowest_depth_m", "cells_within_limit", "datum", "basis"}:
            raise ValueError("Native depth screen fields are incomplete")
        for key in ("limit_ft", "shallowest_depth_m"):
            value = screen[key]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or (key == "limit_ft" and value == 0):
                raise ValueError("Native depth screen has invalid values")
        if isinstance(screen["cells_within_limit"], bool) or not isinstance(screen["cells_within_limit"], int) or screen["cells_within_limit"] < 0:
            raise ValueError("Native depth screen cell count is invalid")
        text(screen["datum"], "native depth datum")
        text(screen["basis"], "native depth screen basis")
    interval = []
    for key in ("coverage_start", "coverage_end"):
        value = data["temporal"].get(key)
        if value:
            if len(value) == 10:
                parsed = date.fromisoformat(value)
            else:
                instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if instant.tzinfo is None: raise ValueError("Coverage instants need a timezone")
                parsed = instant.date()
            interval.append(parsed)
    if len(interval) == 2 and interval[0] > interval[1]:
        raise ValueError("Coverage interval is reversed")
    for key in ("source_time", "checked_at"):
        value = data["temporal"][key]
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Timestamps must include their timezone")
    text(data["temporal"]["update_cadence"], "update_cadence", nullable=True)
    if data["access_status"] != "not-tested" and not data["temporal"]["checked_at"]:
        raise ValueError("An access claim needs an actual checked_at timestamp")
    if not isinstance(data["evidence"], list) or not data["evidence"]:
        raise ValueError("Supporting evidence is required")
    for evidence in data["evidence"]:
        public_url(evidence["url"])
        text(evidence["supports"], "supports")
    if not isinstance(data["limitations"], list) or not data["limitations"]:
        raise ValueError("Document limitations, including unknowns")
    for limit in data["limitations"]:
        text(limit, "limitation")
    return {"candidate_id": data["id"], "valid": True, "publication_approved": False,
            "next_step": "Review coverage, variables and redistribution before changing a regional binding."}
