#!/usr/bin/env python3
"""Compare NCEI multibeam cruise footprints with survey tracklines at Monterey outlines.

Both layers are discovery data: a track centerline is not the acoustic swath,
measured cell, vertical datum, total uncertainty or fishable area.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
SERVICES = {
    "footprint": "https://gis.ngdc.noaa.gov/arcgis/rest/services/multibeam_footprints/MapServer/0/query",
    "trackline": "https://gis.ngdc.noaa.gov/arcgis/rest/services/web_mercator/multibeam_dynamic/MapServer/0/query",
}
FIELDS = {
    "footprint": "OBJECTID,NCEI_ID,SURVEY_ID,SURVEY_YEAR,INSTRUMENT,DOWNLOAD_URL",
    "trackline": "OBJECTID,NGDC_ID,SURVEY_ID,SURVEY_YEAR,INSTRUMENT,DOWNLOAD_URL",
}
FILTER = "1=1"


def esri_polygon(geometry):
    kind = geometry["type"]
    if kind == "Polygon":
        rings = geometry["coordinates"]
    elif kind == "MultiPolygon":
        rings = [ring for polygon in geometry["coordinates"] for ring in polygon]
    else:
        raise ValueError(f"Unexpected research geometry: {kind}")
    return {"rings": rings, "spatialReference": {"wkid": 4326}}


def arcgis_request(endpoint, geometry, fields, where, user_agent):
    polygon = esri_polygon(geometry)
    params = {
        "where": where,
        "geometry": json.dumps(polygon, sort_keys=True, separators=(",", ":"), allow_nan=False),
        "geometryType": "esriGeometryPolygon", "inSR": str(polygon["spatialReference"]["wkid"]),
        "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
        "returnGeometry": "false", "f": "json",
    }
    # Hash the exact canonical POST parameters and full service/layer URL.
    body = urlencode(sorted(params.items())).encode()
    fingerprint = hashlib.sha256(endpoint.encode() + b"\n" + body).hexdigest()
    request = Request(endpoint, data=body, headers={
        "User-Agent": user_agent,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    return request, fingerprint


def _query_cache_receipt(fingerprint, raw):
    return {"request_sha256": fingerprint, "response_sha256": hashlib.sha256(raw).hexdigest()}


def read_query_cache(path, fingerprint, limit):
    try:
        receipt = json.loads(path.with_suffix(".request.json").read_bytes())
        with path.open("rb") as source:
            raw = source.read(limit + 1)
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(f"Missing or invalid NCEI query cache binding: {path.name}") from exc
    if len(raw) > limit or receipt != _query_cache_receipt(fingerprint, raw):
        raise ValueError(f"NCEI query cache does not match request or response: {path.name}")
    return raw


def write_query_cache(path, fingerprint, raw):
    # Keep original response bytes; a partial write or mixed pair fails digest validation.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.with_suffix(".request.json").write_text(json.dumps(_query_cache_receipt(fingerprint, raw)))


def query(root, ident, geometry, kind, fetch):
    path = root / "var/review/ncei-monterey-tracklines" / f"{ident}-{kind}.json"
    request, fingerprint = arcgis_request(SERVICES[kind], geometry, FIELDS[kind], FILTER,
                                          "SkipperCast-original-survey-lead-audit/1.0")
    if fetch:
        with urlopen(request, timeout=45) as response:
            raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError("NCEI query response exceeds bounded size")
    else:
        raw = read_query_cache(path, fingerprint, 3_000_000)
    payload = json.loads(raw)
    if payload.get("error") or payload.get("exceededTransferLimit") or not isinstance(payload.get("features"), list):
        raise ValueError(f"NCEI {kind} service returned incomplete results at {ident}")
    if len(payload["features"]) >= 2000:
        raise ValueError(f"NCEI {kind} page limit reached at {ident}")
    rows = []
    for feature in payload["features"]:
        item = feature.get("attributes") or {}
        ident_value = item.get("SURVEY_ID")
        url = item.get("DOWNLOAD_URL")
        year = item.get("SURVEY_YEAR")
        if (not isinstance(ident_value, str) or len(ident_value) > 100
                or not isinstance(url, str) or urlsplit(url).hostname not in {"www.ngdc.noaa.gov", "www.ncei.noaa.gov"}
                or urlsplit(url).scheme != "https"
                or not isinstance(year, (int, float)) or not 1900 <= year <= 2100):
            raise ValueError(f"Unexpected NCEI survey attributes at {ident}")
        rows.append({
            "object_id": item["OBJECTID"], "ncei_id": item.get("NGDC_ID") or item.get("NCEI_ID"),
            "survey_id": ident_value, "survey_year": int(year),
            "instrument": item.get("INSTRUMENT"), "download_url": url,
        })
    if fetch:
        write_query_cache(path, fingerprint, raw)
    return sorted(rows, key=lambda row: row["object_id"]), hashlib.sha256(raw).hexdigest()


def build(root, fetch=False):
    matrix_path = root / "research/receipts/monterey-300-source-evidence-matrix.json"
    context_path = root / "research/receipts/usgs-offshore-monterey-hard-context.geojson"
    matrix = json.loads(matrix_path.read_text())
    if matrix.get("outline_count") != 17:
        raise ValueError("Reviewed Monterey outline set changed")
    features = {f["properties"]["id"]: f for f in json.loads(context_path.read_text())["features"]}
    outlines = []
    for research in matrix["review_order"]:
        ident = research["context_id"]
        geometry = features[ident]["geometry"]
        footprint, footprint_sha = query(root, ident, geometry, "footprint", fetch)
        trackline, trackline_sha = query(root, ident, geometry, "trackline", fetch)
        footprint_ids = {item["survey_id"] for item in footprint}
        trackline_ids = {item["survey_id"] for item in trackline}
        outlines.append({
            "context_id": ident,
            "historical_rockfish_positive_windows": research["historical_rockfish_positive_windows"],
            "prior_mpa_or_gea_hold": research["mapped_protected_area_or_gea_buffer"],
            "prior_enc_danger_hold": research["mapped_enc_danger_buffer"],
            "footprint_response_sha256": footprint_sha,
            "trackline_response_sha256": trackline_sha,
            "footprint_survey_ids": sorted(footprint_ids),
            "trackline_survey_ids": sorted(trackline_ids),
            "footprint_only_survey_ids": sorted(footprint_ids - trackline_ids),
            "trackline_surveys": trackline,
            "survey_has_native_200_300ft_cells_verified": False,
            "chart_datum_and_upper_error_verified": False,
            "fishing_target": False, "exportable": False,
        })
    source_2009 = "CentralMontereyBay"
    priority = {row["context_id"][-3:]: row for row in outlines}
    if (set(priority) != {item["context_id"][-3:] for item in matrix["review_order"]}
            or any(source_2009 not in priority[i]["trackline_survey_ids"] for i in ("023", "046"))):
        raise ValueError("Highest-priority historical camera survey leads changed")
    all_footprints = {ident for row in outlines for ident in row["footprint_survey_ids"]}
    all_tracks = {ident for row in outlines for ident in row["trackline_survey_ids"]}
    return {
        "schema_version": 1, "scope": "monterey-17-ncei-footprint-vs-trackline-survey-leads",
        "service_query_urls": SERVICES,
        "research_matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "research_context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        "outlines_reviewed": len(outlines),
        "unique_footprint_survey_ids": len(all_footprints),
        "unique_trackline_survey_ids": len(all_tracks),
        "camera_positive_outlines_with_2009_central_monterey_trackline": sum(
            row["historical_rockfish_positive_windows"] > 0 and source_2009 in row["trackline_survey_ids"]
            for row in outlines),
        "highest_priority_023_and_046_trackline_survey_ids": {
            ident: priority[ident]["trackline_survey_ids"] for ident in ("023", "046")},
        "outlines": outlines, "fishing_target": False, "exportable": False,
        "next_acquisition": "Inspect original 2009 CentralMontereyBay survey line files and processing; test valid beams and metadata-derived depth at the actual research cells. The NCEI trackline is a centerline lead, not an acoustic swath. Trace NOAA 2013 merge point-source IDs separately and obtain per-cell MLLW and conservative upper uncertainty before any release.",
        "limitations": [
            "A broad cruise polygon can intersect an outline even where that cruise has no trackline; polygon hits are not evidence of measured cells.",
            "A generalized centerline can miss an adjacent acoustic swath, and a crossing centerline does not establish valid beams or the 200–300 ft band. Only original sounding or gridded valid-cell review can do so.",
            "NCEI trackline year and survey ID do not map NOAA 2013 merge point_source_id to the contributing acoustic source.",
            "The research outlines are not navigable fishing patches; no legal, MPA, hazard, route, independent substrate, fish-presence or rank gate is cleared by these catalog results.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, default=Path("research/receipts/monterey-17-ncei-trackline-leads.json"))
    args = parser.parse_args()
    report = build(args.root.resolve(), args.fetch)
    if args.verify:
        old = json.loads(args.verify.read_text())
        if report != {key: value for key, value in old.items() if key != "checked_at"}:
            raise ValueError("NCEI footprint or trackline lead changed; hold for review")
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    path = args.root / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"NCEI footprint/trackline review: {report['outlines_reviewed']} outlines; zero fishing targets")


if __name__ == "__main__":
    main()
