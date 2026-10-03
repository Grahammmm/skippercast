#!/usr/bin/env python3
"""Discover NCEI multibeam survey footprints in Central Coast browse sectors.

Footprints are catalog leads, not measured shore–300 ft cells or fishing areas.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from research.scripts.build_central_source_queue import SECTORS


LAYER = "https://gis.ngdc.noaa.gov/arcgis/rest/services/multibeam_footprints/MapServer/0"
FIELDS = "OBJECTID,NCEI_ID,SURVEY_ID,PLATFORM,SOURCE,INSTRUMENT,SURVEY_YEAR,START_TIME,END_TIME,DOWNLOAD_URL"


def fetch_json(url):
    # Disconnected cell polygons can exceed intermediary GET URL limits.
    endpoint, separator, parameters = url.partition("?")
    request = (Request(endpoint, data=parameters.encode(),
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
               if separator and len(url.encode()) > 6000 else url)
    with urlopen(request, timeout=40) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("NOAA footprint response exceeds reviewed size")
    result = json.loads(raw)
    if not isinstance(result, dict) or "error" in result:
        raise ValueError("NOAA footprint service returned an error")
    return result, hashlib.sha256(raw).hexdigest()


def query(sector, fetch=fetch_json):
    west, south, east, north = sector["bounds"]
    if not (-125 <= west < east <= -118 and 34 <= south < north <= 38):
        raise ValueError("Sector outside reviewed Central Coast bounds")
    common = {"where": "1=1", "geometry": ",".join(map(str, (west, south, east, north))),
              "geometryType": "esriGeometryEnvelope", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "f": "json"}
    if "query_geometry" in sector:
        common.update(geometry=json.dumps(sector["query_geometry"], separators=(",", ":")),
                      geometryType="esriGeometryPolygon", inSR=3310)
    count_url = LAYER + "/query?" + urlencode({**common, "returnCountOnly": "true"})
    count, count_sha = fetch(count_url)
    expected = count.get("count")
    if not isinstance(expected, int) or not 0 <= expected <= 2000:
        raise ValueError("NOAA footprint count is missing or exceeds one complete page")
    data_url = LAYER + "/query?" + urlencode({**common, "outFields": FIELDS,
                                               "returnGeometry": "false",
                                               "orderByFields": "OBJECTID ASC"})
    data, data_sha = fetch(data_url)
    features = data.get("features")
    if (not isinstance(features, list) or len(features) != expected or
            data.get("exceededTransferLimit")):
        raise ValueError("NOAA footprint query is incomplete")
    rows = []
    seen = set()
    for feature in features:
        attr = feature.get("attributes", {})
        oid = attr.get("OBJECTID")
        url = attr.get("DOWNLOAD_URL")
        if (not isinstance(oid, int) or oid in seen or
                (url is not None and urlparse(url).scheme != "https")):
            raise ValueError("Invalid or duplicate NOAA footprint feature")
        seen.add(oid)
        rows.append({"object_id": oid, "ncei_id": attr.get("NCEI_ID"),
                     "survey_id": attr.get("SURVEY_ID"),
                     "survey_year": attr.get("SURVEY_YEAR"),
                     "platform": attr.get("PLATFORM"), "source": attr.get("SOURCE"),
                     "instrument": attr.get("INSTRUMENT"),
                     "start_time_ms": attr.get("START_TIME"),
                     "end_time_ms": attr.get("END_TIME"),
                     "download_url": url})
    return {"sector_id": sector["id"], "bounds": sector["bounds"],
            "request_url": data_url, "raw_sha256": data_sha,
            "count_request_url": count_url, "count_raw_sha256": count_sha,
            "footprint_lead_count": len(rows), "footprints": rows}


def validate_layer(fetch):
    metadata, metadata_sha = fetch(LAYER + "?f=json")
    field_names = {row.get("name") for row in metadata.get("fields", [])}
    if (metadata.get("geometryType") != "esriGeometryPolygon"
            or metadata.get("maxRecordCount", 0) < 2000
            or not set(FIELDS.split(",")) <= field_names):
        raise ValueError("NOAA multibeam footprint layer schema changed")
    return metadata_sha


def discover(sectors, fetch=fetch_json):
    lookup = {row["id"]: row for row in sectors if row["id"] in SECTORS}
    if set(lookup) != set(SECTORS):
        raise ValueError("Central Coast browse-sector inventory incomplete")
    metadata_sha = validate_layer(fetch)
    rows = [query(lookup[sector], fetch) for sector in SECTORS]
    return {"schema_version": 1, "scope": "noaa-ncei-central-multibeam-footprint-discovery",
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_layer": LAYER, "source_layer_schema_sha256": metadata_sha,
            "status": "complete-catalog-query",
            "unique_footprint_object_ids": len({item["object_id"] for row in rows for item in row["footprints"]}),
            "sectors": rows, "fishing_target": False, "exportable": False,
            "limitations": "Footprints may cross a browse box without measured cells at shore–300 ft; raw and processed files need native resolution, datum, uncertainty, source-age, rights and habitat checks. Repeated survey IDs/footprints across sectors are not new mapped area."}


def gap_sectors(folder, max_cells=128):
    """Bound catalog queries to hash-checked zero-native-support cells.

    The reference band is provisional. These are acquisition priorities, not
    proof of shallow water, an exact remaining-area denominator or fish sites.
    Partial-support cells need a native mask; never label their full square a gap.
    """
    from pyproj import Transformer
    from shapely.geometry import box
    from shapely.ops import transform, unary_union
    from shapely.geometry.polygon import orient

    if isinstance(max_cells, bool) or not isinstance(max_cells, int) or not 1 <= max_cells <= 256:
        raise ValueError("Gap query batch must contain 1–256 planning cells")
    folder = Path(folder)
    cells_path = folder / "coverage-cells.json"
    if cells_path.stat().st_size > 100_000_000:
        raise ValueError("Coverage snapshot exceeds read bound")
    raw = cells_path.read_bytes()
    checkpoint_raw = (folder / "coverage-checkpoint.json").read_bytes()
    checkpoint = json.loads(checkpoint_raw)
    if not isinstance(checkpoint, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(checkpoint.get("physical_input_hash", ""))):
        raise ValueError("Coverage checkpoint lacks physical input identity")
    digest = hashlib.sha256(raw).hexdigest()
    if checkpoint.get("cells_sha256") != digest:
        raise ValueError("Coverage checkpoint hash mismatch")
    payload = json.loads(raw)
    reach, cells = payload.get("reach"), payload.get("cells")
    if not isinstance(reach, str) or not reach or not isinstance(cells, list):
        raise ValueError("Coverage snapshot lacks reach/cells")
    pending, seen = [], set()
    for cell in cells:
        ident = cell.get("id")
        parts = ident.split(":") if isinstance(ident, str) else []
        if len(parts) != 3 or parts[0] != "3310" or ident in seen or cell.get("reach") != reach:
            raise ValueError("Invalid, duplicate or mixed-reach planning cell")
        try:
            x, y = int(parts[1]), int(parts[2])
        except ValueError as error:
            raise ValueError("Planning cell coordinates must be integers") from error
        if ident != f"3310:{x}:{y}":
            raise ValueError("Noncanonical planning cell coordinates")
        seen.add(ident)
        band, valid = cell.get("band_area_m2"), cell.get("valid_area_m2")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) or not 0 <= v <= 62500 for v in (band, valid)):
            raise ValueError("Invalid planning cell area")
        if valid == 0 and band > 0:
            if cell.get("source_id") != "unknown" or cell.get("available_source_ids") != [] or cell.get("tier") != 0:
                raise ValueError("Zero-area cell has contradictory native support")
            pending.append((ident, x, y))
    pending.sort(key=lambda row: (row[2], row[1]))
    project = Transformer.from_crs(3310, 4326, always_xy=True).transform
    groups = []
    for start in range(0, len(pending), max_cells):
        batch = pending[start:start + max_cells]
        polygon = unary_union([box(x*250, y*250, (x+1)*250, (y+1)*250) for _, x, y in batch])
        polygons = [polygon] if polygon.geom_type == "Polygon" else list(polygon.geoms)
        rings = []
        for part in polygons:
            part = orient(part, sign=-1.0)  # Esri exterior clockwise, holes anticlockwise.
            rings.append(list(map(list, part.exterior.coords)))
            rings.extend(list(map(list, ring.coords)) for ring in part.interiors)
        groups.append({"id": f"{reach}-gap-{start//max_cells+1:04d}",
                       "bounds": list(transform(project, polygon).bounds),
                       "query_geometry": {"rings": rings, "spatialReference": {"wkid": 3310}},
                       "planning_cell_ids": [row[0] for row in batch]})
    return groups, {"reach": reach, "cells_sha256": digest,
                    "physical_input_hash": checkpoint["physical_input_hash"],
                    "checkpoint_sha256": hashlib.sha256(checkpoint_raw).hexdigest(),
                    "zero_support_cell_count": len(pending),
                    "partial_support_cells_excluded": sum(0 < c["valid_area_m2"] < 62500 for c in cells)}


def discover_gaps(folder, fetch=fetch_json, max_cells=128, max_groups=3, start_group=0, resume_from=None):
    if isinstance(max_groups, bool) or not isinstance(max_groups, int) or not 1 <= max_groups <= 50:
        raise ValueError("Gap query run must contain 1–50 groups")
    if isinstance(start_group, bool) or not isinstance(start_group, int) or start_group < 0:
        raise ValueError("Gap start group must be a nonnegative integer")
    groups, receipt = gap_sectors(folder, max_cells)
    if resume_from is not None:
        previous = json.loads(Path(resume_from).read_text())
        if (previous.get("scope") != "noaa-ncei-zero-native-support-discovery"
                or previous.get("status") != "complete-bounded-query"
                or previous.get("coverage_snapshot") != receipt
                or previous.get("query_batch_cells") != max_cells
                or isinstance(previous.get("next_group"), bool)
                or not isinstance(previous.get("next_group"), int)
                or not 0 <= previous["next_group"] <= len(groups)):
            raise ValueError("Resume receipt differs from checked coverage snapshot or batching")
        if start_group not in (0, previous["next_group"]):
            raise ValueError("Resume cursor conflicts with requested start group")
        start_group = previous["next_group"]
    elif start_group:
        raise ValueError("Nonzero start group requires a checked resume receipt")
    if start_group > len(groups):
        raise ValueError("Gap start group exceeds checked snapshot")
    selected = groups[start_group:start_group+max_groups]
    metadata_sha = validate_layer(fetch) if selected else None
    rows = []
    for sector in selected:
        row = query(sector, fetch)
        row["planning_cell_ids"] = sector["planning_cell_ids"]
        rows.append(row)
    return {"schema_version": 1, "scope": "noaa-ncei-zero-native-support-discovery",
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_layer": LAYER, "source_layer_schema_sha256": metadata_sha,
            "coverage_snapshot": receipt, "group_count": len(groups),
            "query_batch_cells": max_cells, "start_group": start_group,
            "next_group": start_group+len(rows),
            "queried_group_count": len(rows), "remaining_group_count": len(groups)-start_group-len(rows),
            "status": "complete-bounded-query", "sectors": rows,
            "unique_footprint_object_ids": len({i["object_id"] for row in rows for i in row["footprints"]}),
            "fishing_target": False, "exportable": False, "new_measured_km2": 0,
            "limitations": "Hash-checked coverage snapshot; not a claim of current coverage unless inputs remain current. Zero-support 250 m planning cells use a provisional reference band, not verified local depths. Catalog intersection requires native depth/support/rights review. Partial-support cells are excluded; no whole-cell gap-area or habitat credit."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sectors", type=Path, default=Path("dist/data/coastal-sectors.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coverage-folder", type=Path, help="Checked reach coverage snapshot; overrides browse sectors")
    parser.add_argument("--max-cells", type=int, default=128)
    parser.add_argument("--max-groups", type=int, default=3)
    parser.add_argument("--resume-from", type=Path, help="Continue a bounded receipt only if coverage hashes and batch size match")
    args = parser.parse_args()
    result = (discover_gaps(args.coverage_folder, max_cells=args.max_cells, max_groups=args.max_groups, resume_from=args.resume_from)
              if args.coverage_folder else discover(json.loads(args.sectors.read_text())["sectors"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print([(row["sector_id"], row["footprint_lead_count"]) for row in result["sectors"]])


if __name__ == "__main__":
    main()
