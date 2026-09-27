#!/usr/bin/env python3
"""Screen USGS CMECS bedrock interpretation against private Point Buchon blocks.

This polygon layer uses sonar/backscatter and video from the same map family as
the existing character raster. It is a lithology refinement, not independent
groundtruth or a fishing target. Output contains aggregates only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile

import shapefile
from shapely.geometry import box, shape
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9KBGELE/58f7e9655c85408db68ce2ca1d8cd560/CMECS_OffshorePointBuchon.zip"
STEM = "CMECS_OffshorePointBuchon"
EXPECTED_RECORDS = 193015
EXPECTED_CLASSES = {"S1.1.1", "S1.2.1.2.1", "S1.2.1.3.1", "S1.2.2.2", "S1.2.2.4.2"}
BLOCK_FILES = {
    "original_csumb_depth": "point-buchon-2009-csumb-100m-blocks.geojson",
    "historical_rov": "point-buchon-rov-100m-blocks.geojson",
}
EXPECTED_BLOCK_COUNTS = {"original_csumb_depth": 181, "historical_rov": 26}


def digest(path):
    h = sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def blocks(path, expected_count):
    data = json.loads(path.read_text())
    features = data.get("features", [])
    if len(features) != expected_count:
        raise ValueError("Private research block count changed")
    polygons = [shape(feature["geometry"]) for feature in features]
    if any(not polygon.is_valid or polygon.area != 10000 for polygon in polygons):
        raise ValueError("Research blocks are not valid 100 m squares")
    return features, polygons


def group(source, features, polygons):
    bbox = box(min(p.bounds[0] for p in polygons), min(p.bounds[1] for p in polygons),
               max(p.bounds[2] for p in polygons), max(p.bounds[3] for p in polygons))
    local_shapes, codes = [], []
    invalid_in_envelope = invalid_potentially_intersecting_blocks = 0
    for row in source.iterShapeRecords(bbox=bbox.bounds):
        geom = shape(row.shape.__geo_interface__)
        if not geom.is_valid:
            invalid_in_envelope += 1
            # A bounding-box hit is intentionally conservative. Do not repair
            # geometry and silently count a manufactured boundary as surveyed.
            if any(box(*geom.bounds).intersects(block) for block in polygons):
                invalid_potentially_intersecting_blocks += 1
            continue
        if not geom.intersects(bbox):
            continue
        code = row.record["Substrate"]
        if code not in EXPECTED_CLASSES:
            raise ValueError("Unknown CMECS substrate code")
        if (code == "S1.1.1") != (row.record["SubInd"] == "Hard"):
            raise ValueError("CMECS bedrock/induration attribution changed")
        local_shapes.append(geom)
        codes.append(code)
    if not local_shapes:
        raise ValueError("No CMECS source polygons inside research extent")
    tree = STRtree(local_shapes)
    counts = Counter()
    class_area = Counter()
    for feature, block in zip(features, polygons):
        area = Counter()
        for index in tree.query(block):
            overlap = local_shapes[index].intersection(block)
            if not overlap.is_empty:
                area[codes[index]] += overlap.area
        total = sum(area.values())
        if total > block.area + 1:
            raise ValueError("Overlapping CMECS classes exceed research block area")
        if total > 0:
            counts["blocks_with_source_coverage"] += 1
        if area["S1.1.1"] > 0:
            counts["blocks_with_any_mapped_bedrock"] += 1
        if area["S1.1.1"] >= 1000:
            counts["blocks_with_at_least_1000m2_mapped_bedrock"] += 1
            if feature["properties"].get("lingcod_seen", 0) > 0:
                counts["historical_lingcod_positive_blocks_with_at_least_1000m2_mapped_bedrock"] += 1
        for code, value in area.items():
            class_area[code] += value
    return {
        "private_research_blocks": len(features),
        "valid_source_polygons_in_review_envelope": len(local_shapes),
        "invalid_source_polygons_in_review_envelope": invalid_in_envelope,
        "invalid_polygons_with_possible_block_bbox_hit": invalid_potentially_intersecting_blocks,
        "blocks_with_source_coverage": counts["blocks_with_source_coverage"],
        "blocks_with_any_mapped_bedrock": counts["blocks_with_any_mapped_bedrock"],
        "blocks_with_at_least_1000m2_mapped_bedrock": counts["blocks_with_at_least_1000m2_mapped_bedrock"],
        "historical_lingcod_positive_blocks_with_at_least_1000m2_mapped_bedrock": counts["historical_lingcod_positive_blocks_with_at_least_1000m2_mapped_bedrock"],
        "valid_polygon_intersected_area_m2_by_cmecs_substrate": {key: round(class_area[key], 1) for key in sorted(EXPECTED_CLASSES)},
    }


def audit(archive, block_dir):
    source_hash = digest(archive)
    block_paths = {name: block_dir / file for name, file in BLOCK_FILES.items()}
    block_hashes = {name: digest(path) for name, path in block_paths.items()}
    with tempfile.TemporaryDirectory(prefix="skippercast-cmecs-") as work:
        with ZipFile(archive) as z:
            names = {STEM + ext for ext in (".shp", ".shx", ".dbf", ".prj", ".shp.xml")}
            if not names <= set(z.namelist()):
                raise ValueError("Incomplete USGS CMECS shapefile archive")
            for name in names:
                z.extract(name, work)
        source = shapefile.Reader(str(Path(work) / (STEM + ".shp")))
        if len(source) != EXPECTED_RECORDS:
            raise ValueError("USGS CMECS feature count changed")
        expected_fields = {"SubInd", "Substrate", "Geoform", "Geology"}
        if not expected_fields <= {field[0] for field in source.fields[1:]}:
            raise ValueError("USGS CMECS schema changed")
        prj = (Path(work) / (STEM + ".prj")).read_text()
        if "WGS_1984_UTM_Zone_10N" not in prj:
            raise ValueError("USGS CMECS CRS changed")
        metadata = (Path(work) / (STEM + ".shp.xml")).read_text()
        if not all(text in metadata for text in ("position accuracies are highly variable", "polygon boundaries cannot be quantified", "video-supervised", "66,987 polygons")):
            raise ValueError("USGS CMECS accuracy or lineage metadata changed")
        results = {}
        for name, path in block_paths.items():
            features, polygons = blocks(path, EXPECTED_BLOCK_COUNTS[name])
            results[name] = group(source, features, polygons)
        return {
            "schema_version": 1,
            "scope": "point-buchon-cmecs-geologic-interpretation-private-block-review",
            "source_url": SOURCE_URL,
            "source_archive_sha256": source_hash,
            "source_metadata_sha256": digest(Path(work) / (STEM + ".shp.xml")),
            "source_total_polygons": len(source),
            "source_metadata_overview_polygons": 66987,
            "metadata_overview_count_matches_archive": 66987 == len(source),
            "private_block_sha256": block_hashes,
            "groups": results,
            "fishing_target": False, "exportable": False, "fishing_rank": None,
            "limitations": [
                "CMECS bedrock is an interpreted polygon from 2 m backscatter, bathymetry derivatives and reused video; it is not an independent survey or measured rock-size layer.",
                "The publisher cannot quantify polygon boundary accuracy; video positions are highly variable, about 10 m. Intersection with a private 100 m research square does not locate an individual boulder.",
                "Invalid source polygons possibly intersect private blocks. They are excluded from area counts rather than silently repaired; valid-only area is incomplete and absence cannot be inferred.",
                "The research squares are not fishing areas or chart-depth-qualified footprints. Source coverage is sparse within many squares, and portions outside polygons are unknown rather than soft bottom.",
                "Historical ROV detections share program lineage with other ROV summaries and do not establish present fish presence, effort-normalized catch odds, or legal access.",
                "MLLW depth/upper uncertainty, independent bottom confirmation and full route/legal/chart review remain required before any rank, public spot or export.",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--block-dir", type=Path, default=ROOT / "var/review")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.archive, args.block_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({name: {key: value for key, value in row.items() if key.startswith("blocks_")}
                      for name, row in result["groups"].items()}))


if __name__ == "__main__":
    main()
