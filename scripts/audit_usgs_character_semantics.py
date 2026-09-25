"""Verify class meanings against original, SHA-pinned USGS FGDC XML.

Raster value tables sometimes contain only a value and pixel count. In that
case their class number alone cannot establish bottom type. This audit uses
the producer's enumerated FGDC definition, never a guessed universal code.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


HOSTS = {"pubs.usgs.gov", "cmgds.marine.usgs.gov"}
MAX_BYTES = 2_000_000


def fetch(url):
    parsed = urlsplit(url or "")
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username
            or parsed.password or parsed.query or not parsed.path.endswith(".xml")):
        raise ValueError("Metadata URL is outside the reviewed USGS XML hosts")
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast FGDC class review/1.0"}), timeout=45) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("Original metadata redirected or failed")
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Original metadata is empty or oversized")
    return raw


def definitions(raw):
    root = ET.fromstring(raw)
    values = {}
    for attribute in root.findall(".//eainfo/detailed/attr"):
        label = (attribute.findtext("attrlabl") or "").strip().lower()
        if label not in {"value", "gridcode", "class"}:
            continue
        for domain in attribute.findall("./attrdomv/edom"):
            value = (domain.findtext("edomv") or "").strip()
            meaning = " ".join((domain.findtext("edomvd") or "").split())
            if not value or not meaning or value in values and values[value] != meaning:
                raise ValueError("Missing or conflicting original enumerated class")
            values[value] = meaning
    return values


def metadata_formula_for_class3(raw):
    """Recognize only the original CSMP zone/slope encoding explicitly stated."""
    root = ET.fromstring(raw)
    attributes = {" ".join((attr.findtext("attrlabl") or "").lower().split()):
                  " ".join((attr.findtext("attrdef") or "").lower().split())
                  for attr in root.findall(".//eainfo/detailed/attr")}
    value = attributes.get("value", "")
    substrate = attributes.get("substrate", "")
    if ("depth zone 2, add 0 to grid value" in value
            and "slope class 1, add 0 to grid value" in value
            and "class 3, rock and boulder, rugose" in substrate):
        return substrate
    return None


def audit(native, metadata, getter=fetch):
    if (native.get("scope") != "usgs-ds781-statewide-original-character-raster-audit"
            or metadata.get("scope") != "usgs-ds781-original-fgdc-metadata-triage"):
        raise ValueError("Wrong USGS original-source inventories")
    by_url = {row.get("xml_url"): row for row in metadata["records"] if row.get("xml_url")}
    rows = [row for row in native["products"] if row["status"] == "ok"]
    if len(rows) != native["inspected_count"] or len(by_url) != len(set(by_url)):
        raise ValueError("USGS original-source inventory changed")

    def one(row):
        url = row["metadata_url"]
        source = by_url.get(url)
        if (source is None or source["status"] != "reviewed"
                or source.get("rights_evidence") != "explicit-public-domain-redistribution"
                or source.get("metadata_sha256") != row["metadata_sha256"]):
            raise ValueError("Character metadata or redistribution review is not pinned: " + url)
        raw = getter(url)
        actual = hashlib.sha256(raw).hexdigest()
        if actual != row["metadata_sha256"]:
            raise ValueError("Original FGDC metadata changed after review: " + url)
        values = definitions(raw)
        class3 = values.get("3")
        normalized = (class3 or "").lower()
        enumerated = ("hard" in normalized and "rugos" in normalized
                      and any(word in normalized for word in ("bedrock", "boulder", "rock")))
        formula = metadata_formula_for_class3(raw) if not enumerated else None
        source_table = row.get("original_class_table") if row["class_table_status"] == "verified" else None
        table_rock_values = sorted({entry["value"] for entry in source_table or []
                                    if entry.get("substrate_class") == 3
                                    and "rock" in entry.get("substrate_description", "").lower()
                                    and "rugos" in entry.get("substrate_description", "").lower()})
        available_class3 = int(row.get("class_counts", {}).get("3", 0)) > 0
        hard_rugose = available_class3 and (enumerated or bool(formula)
                                             or 3 in table_rock_values)
        source = ("fgdc-enumeration" if enumerated else
                  "fgdc-zone-slope-formula" if formula else
                  "original-raster-value-table" if table_rock_values else None)
        verified = bool(source)
        return {"map_area": row["map_area"], "archive_url": row["archive_url"],
                "archive_sha256": row["archive_sha256"], "metadata_url": url,
                "metadata_sha256": actual, "raster_class_table_status": row["class_table_status"],
                "original_fgdc_classes": values,
                "original_fgdc_class3_formula": formula,
                "original_table_rock_values": table_rock_values,
                "class_3_hard_rugose_verified": hard_rugose,
                "class_3_verification_source": source if hard_rugose else None,
                "status": "verified" if verified else "held-class-meaning"}

    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(one, rows))
    result.sort(key=lambda row: (row["map_area"], row["archive_url"]))
    return {"schema_version": 1, "scope": "usgs-ds781-original-fgdc-class-semantics",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "source_native_audit_sha256": None,
            "source_metadata_inventory_sha256": None,
            "opened_metadata_count": len(result),
            "verified_class_3_count": sum(row["class_3_hard_rugose_verified"] for row in result),
            "verified_product_count": sum(row["status"] == "verified" for row in result),
            "status": "reviewed" if all(row["status"] == "verified" for row in result) else "partial",
            "fishing_target": False, "exportable": False,
            "limitations": [
                "FGDC enumerations explain a historical classified raster, not the presence, dimensions or condition of an individual rock or fish.",
                "A class-3 label does not independently clear chart-datum depth, MPAs, federal and local closures, hazards, species rules or safe access.",
                "USGS states the source data are not intended for navigation."
            ], "products": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, default=Path("dist/data/usgs-ds781-native-character-review.json"))
    parser.add_argument("--metadata", type=Path, default=Path("catalog/usgs-ds781-metadata-review.json"))
    parser.add_argument("--output", type=Path, default=Path("dist/data/usgs-ds781-character-semantics.json"))
    parser.add_argument("--verify", type=Path, help="Hold changed original class meaning for review")
    args = parser.parse_args()
    result = audit(json.loads(args.native.read_text()), json.loads(args.metadata.read_text()))
    result["source_native_audit_sha256"] = hashlib.sha256(args.native.read_bytes()).hexdigest()
    result["source_metadata_inventory_sha256"] = hashlib.sha256(args.metadata.read_bytes()).hexdigest()
    if args.verify:
        baseline = json.loads(args.verify.read_text())
        if {k: v for k, v in baseline.items() if k != "reviewed_at"} != {
                k: v for k, v in result.items() if k != "reviewed_at"}:
            raise ValueError("Original USGS class semantics changed; review before publication")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    temporary.replace(args.output)
    print(result["verified_product_count"], "of", result["opened_metadata_count"],
          "product semantics verified;", result["verified_class_3_count"], "class-3 grids")


if __name__ == "__main__":
    main()
