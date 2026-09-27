"""Check acquisition lineage of the Block A3 product inside a 2007 NOAA archive.

The 2009 delivery metadata and 2007 bathymetry-trackline dates conflict. Do
not assign an acquisition year to individual depth cells without a line-cell
processing crosswalk.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct
import tarfile
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile

from pyproj import Transformer
import shapefile

from scripts.audit_point_buchon_2009_csumb_products import (
    ARCHIVE_BYTES, ARCHIVE_SHA256, ROOT, sha256_file,
)


TRACKLINES_MEMBER = "CC_BlkA3_tracklines.zip"
TRACKLINES_SHA256 = "1f6767482c1cd1d4ac996f4e7591fc4120af4a3c4f1def66a84a1d470feed4b6"
CATALOG = "https://gis.ngdc.noaa.gov/arcgis/rest/services/web_mercator/multibeam_dynamic/MapServer/0/query"


def trackline_summary(archive):
    if archive.stat().st_size != ARCHIVE_BYTES or sha256_file(archive) != ARCHIVE_SHA256:
        raise ValueError("Original NOAA outer archive changed")
    with tarfile.open(archive, "r:gz") as outer:
        package = outer.extractfile(outer.getmember(TRACKLINES_MEMBER)).read()
    if hashlib.sha256(package).hexdigest() != TRACKLINES_SHA256:
        raise ValueError("Original CSUMB Block A3 trackline package changed")
    result = {}
    with ZipFile(BytesIO(package)) as zipped:
        for kind in ("bathy", "all"):
            stem = f"Tracklines/CC_BlockA3_tracklines_{kind}"
            dbf = zipped.read(stem + ".dbf")
            prj = zipped.read(stem + ".prj").decode("ascii", "replace")
            with zipped.open(stem + ".shp") as shp:
                header = shp.read(68)
            if (len(header) != 68 or struct.unpack(">I", header[:4])[0] != 9994
                    or "NAD_1983_UTM_Zone_10N" not in prj):
                raise ValueError("Original trackline geometry or projection changed")
            records = shapefile.Reader(dbf=BytesIO(dbf)).records()
            dates = Counter(row["Date_"] for row in records)
            names = [row["Source"] for row in records]
            if (len(names) != len(set(names)) or any(not name.startswith("MB") for name in names)
                    or any(row["Vessel"] != "VenTresca" for row in records)):
                raise ValueError("Original trackline source identities changed")
            result[kind] = {"count": len(records), "date_counts": dict(sorted(dates.items())),
                            "source_name_sha256": hashlib.sha256("\n".join(sorted(names)).encode()).hexdigest(),
                            "bounds_utm10_m": [round(value, 2) for value in struct.unpack("<4d", header[36:68])],
                            "projection_sha256": hashlib.sha256(prj.encode()).hexdigest()}
    return result


def catalog_review(blocks):
    if (blocks.get("scope") != "private-point-buchon-2009-csumb-100m-research-blocks"
            or blocks.get("crs") != "EPSG:32610" or len(blocks.get("features", [])) != 181):
        raise ValueError("Private block source changed")
    points = [point for item in blocks["features"] for ring in item["geometry"]["coordinates"] for point in ring]
    transform = Transformer.from_crs(32610, 4326, always_xy=True)
    geographic = [transform.transform(x, y) for x, y in points]
    west, south = min(lon for lon, _ in geographic), min(lat for _, lat in geographic)
    east, north = max(lon for lon, _ in geographic), max(lat for _, lat in geographic)
    params = {"geometry": f"{west:.8f},{south:.8f},{east:.8f},{north:.8f}",
              "geometryType": "esriGeometryEnvelope", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects", "outFields": "SURVEY_ID,SURVEY_YEAR,NGDC_ID",
              "returnGeometry": "false", "f": "json"}
    url = CATALOG + "?" + urlencode(params)
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast bounded survey-lineage audit/1.0"}), timeout=30) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("NOAA multibeam catalog query failed")
        data = response.read(100001)
    if len(data) > 100000:
        raise ValueError("NOAA catalog response exceeded bound")
    payload = json.loads(data)
    if payload.get("error") or payload.get("exceededTransferLimit"):
        raise ValueError("NOAA catalog response incomplete")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("NOAA catalog response missing features")
    rows = sorted(({"survey_id": item["attributes"]["SURVEY_ID"],
                    "survey_year": int(item["attributes"]["SURVEY_YEAR"]),
                    "ncei_id": item["attributes"]["NGDC_ID"]} for item in features),
                  key=lambda row: (row["survey_id"], row["survey_year"]))
    return rows


def audit(archive, block_path):
    tracks = trackline_summary(archive)
    catalog = catalog_review(json.loads(block_path.read_text()))
    return {"schema_version": 1,
            "scope": "point-buchon-block-a3-trackline-acquisition-lineage",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source_archive_url": "https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/Point_Buchon_Control/multibeam/data/version2/products/Pt_Buchon_control_additional_products.tar.gz",
            "source_archive_sha256": ARCHIVE_SHA256,
            "trackline_member": TRACKLINES_MEMBER, "trackline_member_sha256": TRACKLINES_SHA256,
            "tracklines": tracks,
            "noaa_multibeam_footprint_catalog": CATALOG.rsplit("/query", 1)[0],
            "catalog_surveys_intersecting_private_block_envelope": catalog,
            "catalog_2009_survey_intersects_envelope": any(row["survey_year"] == 2009 for row in catalog),
            "delivery_metadata_2009_not_cell_acquisition_proof": True,
            "cell_acquisition_year_verified": False,
            "source_line_to_grid_cell_crosswalk_verified": False,
            "qualified_waypoints": 0, "fishing_target": False, "exportable": False,
            "limitations": [
                "The Block A3 bathymetry-trackline file in the same delivered package lists only 24-26 October 2007 lines. This contradicts treating the 2009 package metadata as the acquisition date of every grid cell.",
                "The current bounded NOAA multibeam-footprint catalog query intersects the private block envelope but is not an exhaustive line-cell source inventory. No 2009 survey appears in that bounded response.",
                "Trackline bounding boxes and dates do not identify which soundings contributed to each finished grid cell. Obtain the CARIS/BASE line-cell crosswalk and uncertainty surface before assigning acquisition dates or depth confidence.",
            ]}


def stable(report):
    return {key: value for key, value in report.items() if key != "checked_at"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "var/review/point-buchon-additional-products/Pt_Buchon_control_additional_products.tar.gz")
    parser.add_argument("--blocks", type=Path, default=ROOT / "var/review/point-buchon-2009-csumb-100m-blocks.geojson")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/point-buchon-block-a3-trackline-lineage.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = audit(args.archive, args.blocks)
    if args.verify and stable(result) != stable(json.loads(args.verify.read_text())):
        raise ValueError("Point Buchon Block A3 acquisition lineage changed; review before publication")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print({"bathy_trackline_dates": result["tracklines"]["bathy"]["date_counts"],
           "catalog_2009": result["catalog_2009_survey_intersects_envelope"],
           "qualified_waypoints": 0})


if __name__ == "__main__":
    main()
