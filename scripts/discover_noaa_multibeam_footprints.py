#!/usr/bin/env python3
"""Discover NCEI multibeam survey footprints in Central Coast browse sectors.

Footprints are catalog leads, not measured 25–300 ft cells or fishing areas.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from scripts.build_central_source_queue import SECTORS


LAYER = "https://gis.ngdc.noaa.gov/arcgis/rest/services/multibeam_footprints/MapServer/0"
FIELDS = "OBJECTID,NCEI_ID,SURVEY_ID,PLATFORM,SOURCE,INSTRUMENT,SURVEY_YEAR,START_TIME,END_TIME,DOWNLOAD_URL"


def fetch_json(url):
    with urlopen(url, timeout=40) as response:
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


def discover(sectors, fetch=fetch_json):
    lookup = {row["id"]: row for row in sectors if row["id"] in SECTORS}
    if set(lookup) != set(SECTORS):
        raise ValueError("Central Coast browse-sector inventory incomplete")
    metadata, metadata_sha = fetch(LAYER + "?f=json")
    field_names = {row.get("name") for row in metadata.get("fields", [])}
    if (metadata.get("geometryType") != "esriGeometryPolygon"
            or metadata.get("maxRecordCount", 0) < 2000
            or not set(FIELDS.split(",")) <= field_names):
        raise ValueError("NOAA multibeam footprint layer schema changed")
    rows = [query(lookup[sector], fetch) for sector in SECTORS]
    return {"schema_version": 1, "scope": "noaa-ncei-central-multibeam-footprint-discovery",
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_layer": LAYER, "source_layer_schema_sha256": metadata_sha,
            "status": "complete-catalog-query",
            "unique_footprint_object_ids": len({item["object_id"] for row in rows for item in row["footprints"]}),
            "sectors": rows, "fishing_target": False, "exportable": False,
            "limitations": "Footprints may cross a browse box without measured cells at 25–300 ft; raw and processed files need native resolution, datum, uncertainty, source-age, rights and habitat checks. Repeated survey IDs/footprints across sectors are not new mapped area."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sectors", type=Path, default=Path("dist/data/coastal-sectors.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = discover(json.loads(args.sectors.read_text())["sectors"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print([(row["sector_id"], row["footprint_lead_count"]) for row in result["sectors"]])


if __name__ == "__main__":
    main()
