"""Review recent NOAA DisMAP trawl catches by broad California coast sector.

This is research evidence, not a fishing-target or waypoint generator.  NOAA's
trawl design samples trawlable shelf/slope and cannot characterize small reefs.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
LAYER = "https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/WC_ANN_Sample_Locations_CURRENT/FeatureServer/0"
FIELDS = "OBJECTID,SampleID,Year,Species,SpeciesCommonName,WTCPUE,Depth,Latitude,Longitude"
TARGET = "(Species = 'Ophiodon elongatus' OR Species = 'Hippoglossus stenolepis' OR SpeciesCommonName LIKE '%rockfish%')"


def fetch(url):
    with urlopen(url, timeout=90) as response:
        body = response.read()
    data = json.loads(body)
    if "error" in data:
        raise ValueError(f"DisMAP query failed: {data['error']}")
    return data, hashlib.sha256(body).hexdigest()


def query(**params):
    return fetch(LAYER + "/query?" + urlencode({**params, "f": "json"}))


def label(row):
    if row["Species"] == "Ophiodon elongatus":
        return "lingcod"
    if row["Species"] == "Hippoglossus stenolepis":
        return "pacific-halibut"
    if "rockfish" in (row["SpeciesCommonName"] or "").lower():
        return "rockfish-trawl-group"
    raise ValueError("Unrequested taxon in DisMAP response")


def sector_for(lat, sectors):
    matches = [s["id"] for s in sectors if s["latitude"][0] <= lat < s["latitude"][1]]
    if lat == 42.0:
        matches = [s["id"] for s in sectors if s["latitude"][1] == 42.0]
    if len(matches) > 1:
        raise ValueError("Overlapping sector latitude bands")
    return matches[0] if matches else None


def summarize(records, sectors, years):
    groups = defaultdict(lambda: {"sample_positive": {}, "sample_depth_m": {}, "taxa": set(), "depths_m": []})
    ids = set()
    outside = 0
    for row in records:
        oid = row["OBJECTID"]
        if oid in ids:
            raise ValueError("Duplicate DisMAP OBJECTID across pages")
        ids.add(oid)
        year, lat, lon = row["Year"], row["Latitude"], row["Longitude"]
        cpue, depth, sample = row["WTCPUE"], row["Depth"], row["SampleID"]
        if (year not in years or not all(isinstance(v, (int, float)) and math.isfinite(v)
                                         for v in (lat, lon, cpue, depth))
                or not 32 <= lat <= 42 or not -126 <= lon <= -117
                or cpue < 0 or not 0 <= depth <= 2000 or not sample):
            raise ValueError("Invalid or out-of-scope DisMAP catch record")
        sector = sector_for(lat, sectors)
        if sector is None:
            outside += 1
            continue
        key = (sector, year, label(row))
        group = groups[key]
        if sample in group["sample_depth_m"] and abs(group["sample_depth_m"][sample] - depth) > 0.1:
            raise ValueError("Conflicting depths for one DisMAP sample")
        group["sample_positive"][sample] = group["sample_positive"].get(sample, False) or cpue > 0
        group["sample_depth_m"][sample] = depth
        group["taxa"].add(row["Species"])
        group["depths_m"].append(depth)
    result = []
    for (sector, year, target), group in sorted(groups.items()):
        positives = sum(group["sample_positive"].values())
        shallow = {sample for sample, depth in group["sample_depth_m"].items() if depth <= 60.96}
        result.append({"sector_id": sector, "year": year, "target": target,
                       "samples_with_taxon_record": len(group["sample_positive"]),
                       "samples_with_positive_cpue": positives,
                       "samples_with_zero_cpue": len(group["sample_positive"]) - positives,
                       "samples_at_or_under_200ft": len(shallow),
                       "positive_samples_at_or_under_200ft": sum(group["sample_positive"][sample] for sample in shallow),
                       "depth_range_m": [round(min(group["depths_m"]), 1), round(max(group["depths_m"]), 1)],
                       "source_taxa": sorted(group["taxa"])})
    return result, outside


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--years", type=int, nargs="+", default=[2023, 2024, 2025])
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((ROOT / "dist").resolve()):
        raise ValueError("DisMAP observations require review before public release")
    years = sorted(set(args.years))
    if not years or min(years) < 2003 or max(years) > datetime.now(timezone.utc).year:
        raise ValueError("Invalid survey years")
    metadata, metadata_sha = fetch(LAYER + "?f=json")
    expected_fields = set(FIELDS.split(","))
    if not expected_fields <= {field["name"] for field in metadata.get("fields", [])}:
        raise ValueError("DisMAP field schema changed")
    latest, _ = query(where="1=1", outStatistics=json.dumps([
        {"statisticType": "max", "onStatisticField": "Year", "outStatisticFieldName": "latest_year"}]))
    latest_year = latest["features"][0]["attributes"]["latest_year"]
    if latest_year > max(years):
        raise ValueError(f"DisMAP now includes {latest_year}; review and extend the selected-year window")
    sectors = json.loads((ROOT / "catalog/coastal-sectors.json").read_text())["sectors"]
    all_rows, pages = [], []
    for year in years:
        where = f"Year = {year} AND Latitude >= 32 AND Latitude <= 42 AND Longitude >= -126 AND Longitude <= -117 AND {TARGET}"
        count_data, _ = query(where=where, returnCountOnly="true")
        count = count_data["count"]
        if count <= 0:
            raise ValueError(f"DisMAP returned no selected records for {year}")
        offset = 0
        while offset < count:
            data, digest = query(where=where, outFields=FIELDS, returnGeometry="false",
                                 orderByFields="OBJECTID ASC", resultOffset=offset,
                                 resultRecordCount=min(5000, count - offset))
            features = data.get("features", [])
            if not features or len(features) > 5000:
                raise ValueError("Incomplete DisMAP page")
            all_rows.extend(feature["attributes"] for feature in features)
            pages.append({"year": year, "offset": offset, "rows": len(features), "response_sha256": digest})
            offset += len(features)
        if sum(page["rows"] for page in pages if page["year"] == year) != count:
            raise ValueError("DisMAP count and pages differ")
    groups, outside = summarize(all_rows, sectors, years)
    receipt = {"schema_version": 1, "source": LAYER, "source_metadata_sha256": metadata_sha,
               "service_layer_name": metadata["name"], "service_last_edit_ms": metadata.get("editingInfo", {}).get("lastEditDate"),
               "retrieved_at": datetime.now(timezone.utc).isoformat(), "years": years,
               "latest_source_year": latest_year,
               "records_reviewed": len(all_rows), "outside_browse_sectors": outside,
               "pages": pages, "sector_year_target": groups,
               "fishing_target": False, "current_fish_presence": False, "exportable": False,
               "limitations": ["NOAA DisMAP standardizes survey trawl catch per unit effort (kg/ha); it is not angler catch probability.",
                               "Trawls sample trawlable shelf/slope and systematically miss many rocky reefs and shallower inshore grounds.",
                               "Each sector reports the number of sampled depths at or under 200 ft; deeper catches must not validate a 200 ft bottom-fishing candidate.",
                               "Broad latitude browse sectors include offshore and island waters and are not management or legal boundaries.",
                               "A zero is a surveyed taxon noncatch in a trawl sample, not proof of local species absence.",
                               "No source sample coordinates, target score, waypoint or route is published by this review."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"records": len(all_rows), "groups": len(groups), "outside": outside}))


if __name__ == "__main__":
    main()
