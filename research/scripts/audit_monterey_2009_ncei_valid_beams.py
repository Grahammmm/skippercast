#!/usr/bin/env python3
"""Read 2009 CentralMontereyBay GSF valid beams in two research outlines.

The source is processed original cruise data, but its GSF processing record
does not identify a vertical tidal datum. Nominal band and per-beam reported
errors cannot qualify MLLW depth or a fishing mark.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import struct
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from pyproj import Geod
from shapely import contains_xy
from shapely.geometry import shape

from research.scripts.audit_point_buchon_ncei_beam_overlap import beam_positions
from research.scripts.audit_point_buchon_ncei_beam_overlap import check_generated_companions


ROOT = Path(__file__).resolve().parents[2]
FILE_LAYER = "https://gis.ngdc.noaa.gov/arcgis/rest/services/multibeam_files/MapServer/0/query"
BASE = "https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/CentralMontereyBay/multibeam/data/version2/MB/reson7125_400/"
PROCESSED = {
    "20091103_191445": (4181191, "6c2cbc1bf2b9557f44abd3dd15f6048ff300c124ef4681e06fb17c103f36dbbe", "c17f55c67e558747329fb98f6a6c29e12917bb00646cc8aaa3a732a4d496903c", "a17e71038a83be9178329df5a16e80264e7ec99836e9d6aaad9111704a8a0fef"),
    "20091103_193335": (4181192, "7ed3ed3ea6816d2fdaeeda8f673c95bcce2d266e710df92c0e45d9c76fcdf45b", "9e5a10e04caf74b77ef82880818182a0a69fccab3f47b3cc36b78ad5eaf76042", "b66957419f7f207a7cbffc8808b88e96490baaadd2557a0d4e82d2ba43baaae3"),
    "20091103_210239": (4181196, "e25a78a99b1ecdccbdcb8a1ed2e04a3cfcdcf362ac327b3e617b6579233deebc", "ee5da57ab136f64d974caade1db0ebc2aab46f9add388d62ace8a71c86d24a82", "fbda5bd5876d3811b7cae44be3cd1cfe68bf0637a1c954a1255bbf310c05e0be"),
    "20091105_200442": (4181220, "7c17a5ab71d941afd8f7ee639bde09aab02bc62695dc7a27bb8c63d1be30ea05", "9137c4ff0757e61fcba2666f7a64c24ebfcd280809562c3a0eb2a1208cc368f5", "fb34e3ed94b1842106d50ecca6441ed1f311d97ecbb22cf961f1cfa7cd91ac85"),
    "20091105_211608": (4181221, "5ce8d4324968728754bbd53f3e1095084b20edf6de1fb8114401de2f802afefe", "6f325832b628d38624b2abe52afefaed2ac9bba9e4c3f23fecd52fdc6496acb9", "4b659ef0e7706fa50528bf24d7a4bd379eacf285614f49ac4f1ab0798f34100a"),
}


def file_name(stem):
    return f"{stem}_ventresca7125.gsf.mb121.gz"


def read_pinned(path, url, expected, fetch, limit):
    if fetch and not path.exists():
        request = Request(url, headers={"User-Agent": "SkipperCast-original-survey-audit/1.0"})
        with urlopen(request, timeout=120) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"NCEI source changed or oversized: {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"Pinned NCEI source missing or changed: {path.name}")
    return path.read_bytes()


def query_file_layer(root, ident, geometry, fetch):
    path = root / "var/review/ncei-centralmontereybay-priority" / f"{ident}-file-layer.json"
    if fetch:
        polygon = {"rings": geometry["coordinates"], "spatialReference": {"wkid": 4326}}
        data = urlencode({
            "where": "NGDC_ID='NEW2895'", "geometry": json.dumps(polygon, separators=(",", ":")),
            "geometryType": "esriGeometryPolygon", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "OBJECTID,DATASET_ID,DATASET_NAME,DATA_TYPE,FILE_ID,DATA_FILE,COLLECTION_DATE,SURVEY_NAME,NGDC_ID,MBIO_FORMAT_ID",
            "returnGeometry": "false", "f": "json",
        }).encode()
        request = Request(FILE_LAYER, data=data, headers={
            "User-Agent": "SkipperCast-original-survey-audit/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urlopen(request, timeout=60) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("NCEI file-layer response exceeds bound")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("error") or payload.get("exceededTransferLimit") or not isinstance(payload.get("features"), list):
        raise ValueError("Incomplete NCEI file-layer response")
    rows = [feature.get("attributes") or {} for feature in payload["features"]]
    processed = {row["FILE_ID"]: row for row in rows if row.get("DATA_TYPE") == "MB PROCESSED"}
    raw_lines = [row for row in rows if row.get("DATA_TYPE") == "MB RAW"]
    expected = {spec[0] for stem, spec in PROCESSED.items() if stem in ({
        "023": ("20091103_191445", "20091103_193335", "20091105_211608"),
        "046": ("20091103_210239", "20091105_200442"),
    }[ident])}
    if (set(processed) != expected or len(raw_lines) != len(expected)
            or len(rows) != 2 * len(expected)):
        raise ValueError(f"NCEI per-file research intersection changed at {ident}")
    for file_id, row in processed.items():
        stem = next(stem for stem, spec in PROCESSED.items() if spec[0] == file_id)
        if (row.get("DATA_FILE") != ("ocean/ships/ventresca/CentralMontereyBay/multibeam/data/version2/MB/reson7125_400/" + file_name(stem))
                or row.get("SURVEY_NAME") != "CentralMontereyBay"
                or row.get("NGDC_ID") != "NEW2895"
                or row.get("MBIO_FORMAT_ID") != "121"):
            raise ValueError(f"NCEI processed line metadata changed: {file_id}")
    return sorted(processed), hashlib.sha256(raw).hexdigest()


def decode_line(path, inf, fnv, spec, outlines, collect=None):
    geod = Geod(ellps="WGS84")
    counts = Counter()
    navigation = []
    scales = {}
    parameters = []
    values = {ident: {"beams": 0, "band_beams": 0, "depth": [], "v_error": [], "h_error": []}
              for ident in outlines}
    version = None
    with gzip.open(path, "rb") as source:
        while header := source.read(8):
            if len(header) != 8:
                raise ValueError("Truncated GSF record header")
            size, record_id = struct.unpack(">II", header)
            if record_id & 0x80000000 or size > 10_000_000:
                raise ValueError("Unexpected GSF record structure")
            body = source.read(size)
            if len(body) != size:
                raise ValueError("Truncated GSF record body")
            kind = record_id & 0xFFF
            if kind == 1:
                version = body.rstrip(b"\0").decode("ascii")
                if version != "GSF-v03.06":
                    raise ValueError("Unexpected GSF version")
            elif kind == 4:
                if len(body) < 10:
                    raise ValueError("Truncated GSF processing record")
                count = struct.unpack_from(">H", body, 8)[0]
                pos = 10
                for _ in range(count):
                    length = struct.unpack_from(">H", body, pos)[0]
                    pos += 2
                    parameters.append(body[pos:pos + length].rstrip(b"\0").decode("ascii"))
                    pos += length
                if any(body[pos:]) or len(body) - pos > 3:
                    raise ValueError("GSF processing record length changed")
            elif kind == 2:
                counts["ping_records"] += 1
                if len(body) < 56:
                    raise ValueError("Truncated GSF ping")
                lon_i, lat_i = struct.unpack_from(">ii", body, 8)
                n_beams, _, ping_flags = struct.unpack_from(">HHH", body, 16)
                heading = struct.unpack_from(">H", body, 30)[0] / 100
                lon, lat = lon_i / 1e7, lat_i / 1e7
                if not (-122.1 < lon < -121.7 and 36.5 < lat < 36.9 and 100 <= n_beams <= 1024):
                    raise ValueError("Unexpected Monterey GSF ping geometry")
                navigation.append((lon, lat, heading))
                pos, arrays = 56, {}
                while pos + 4 <= len(body):
                    packed = struct.unpack_from(">I", body, pos)[0]
                    subkind, length = packed >> 24, packed & 0xFFFFFF
                    pos += 4
                    if pos + length > len(body):
                        raise ValueError("Truncated GSF ping subrecord")
                    raw = body[pos:pos + length]
                    pos += length
                    if subkind == 100:
                        count = struct.unpack_from(">I", raw)[0]
                        if len(raw) != 4 + 12 * count:
                            raise ValueError("Unexpected GSF scale factor size")
                        for j in range(count):
                            sid, compression, reserved, multiplier, origin = struct.unpack_from(">BBHii", raw, 4 + 12*j)
                            if compression or reserved or multiplier <= 0:
                                raise ValueError("Unsupported GSF scale compression")
                            scales[sid] = (multiplier, origin)
                    elif subkind in (1, 2, 3, 16, 19, 20):
                        arrays[subkind] = raw
                if (pos != len(body) or set(arrays) != {1, 2, 3, 16, 19, 20}
                        or any(len(arrays[k]) != n_beams * (1 if k == 16 else 2) for k in arrays)
                        or any(k not in scales for k in (1, 2, 3, 19, 20))):
                    raise ValueError("GSF beam arrays or active scales changed")
                counts["beam_records"] += n_beams
                flags = np.frombuffer(arrays[16], dtype="u1")
                valid = (flags & 1) == 0
                # NCEI's generated .inf counts beam flags even in ignored pings.
                counts["beam_flags_good_including_ignored_pings"] += int(valid.sum())
                if ping_flags & 1:
                    counts["ignored_ping_records"] += 1
                    continue
                counts["valid_unflagged_beams"] += int(valid.sum())
                if not np.any(valid):
                    continue

                def number(subkind, dtype):
                    mult, origin = scales[subkind]
                    return np.frombuffer(arrays[subkind], dtype=dtype)[valid].astype("f8") / mult - origin

                depth = number(1, ">u2")
                across, along = number(2, ">i2"), number(3, ">i2")
                v_error, h_error = number(19, ">u2"), number(20, ">u2")
                if (not np.all(np.isfinite(depth)) or np.any((depth <= 0) | (depth > 200))
                        or np.any(np.abs(across) > 1000) or np.any(np.abs(along) > 1000)):
                    raise ValueError("Unexpected processed GSF depth or offsets")
                beam_lon, beam_lat = beam_positions(geod, lon, lat, heading, across, along)
                for ident, polygon in outlines.items():
                    inside = contains_xy(polygon, beam_lon, beam_lat)
                    if not np.any(inside):
                        continue
                    selected = depth[inside]
                    values[ident]["beams"] += len(selected)
                    values[ident]["band_beams"] += int(((selected >= 60.96) & (selected <= 91.44)).sum())
                    values[ident]["depth"].append(selected)
                    values[ident]["v_error"].append(v_error[inside])
                    values[ident]["h_error"].append(h_error[inside])
                    if collect is not None:
                        collect(ident, beam_lon[inside], beam_lat[inside], selected)
    if version != "GSF-v03.06" or counts["ping_records"] < 100:
        raise ValueError("GSF file lacks full ping or version records")
    required = {"TIDE_COMPENSATED=YES", "TIDAL_DATUM=UNKNOWN", "GEOID=WGS-84"}
    if not required.issubset(parameters):
        raise ValueError("GSF vertical processing parameters changed")
    companion_counts = {**counts, "valid_unflagged_beams": counts["beam_flags_good_including_ignored_pings"]}
    companion = check_generated_companions(inf, fnv, {
        "inf_sha256": spec[2], "fnv_sha256": spec[3],
    }, navigation, companion_counts)
    companion["generated_inf_includes_ignored_ping_beams"] = True
    summary = {}
    for ident, entry in values.items():
        selected = np.concatenate(entry["depth"]) if entry["depth"] else np.array([])
        vert = np.concatenate(entry["v_error"]) if entry["v_error"] else np.array([])
        horiz = np.concatenate(entry["h_error"]) if entry["h_error"] else np.array([])
        summary[ident] = {
            "valid_beams_inside_outline": entry["beams"],
            "valid_beams_nominal_200_300ft_unknown_datum": entry["band_beams"],
            "source_depth_m_range_unknown_datum": [round(float(selected.min()), 3), round(float(selected.max()), 3)] if len(selected) else None,
            "reported_beam_vertical_error_95pct_m_range": [round(float(vert.min()), 3), round(float(vert.max()), 3)] if len(vert) else None,
            "reported_beam_horizontal_error_95pct_m_range": [round(float(horiz.min()), 3), round(float(horiz.max()), 3)] if len(horiz) else None,
        }
    return dict(counts), summary, companion, sorted(required)


def build(root, fetch=False):
    context_path = root / "dist/data/usgs-offshore-monterey-hard-context.geojson"
    matrix_path = root / "research/receipts/monterey-300-source-evidence-matrix.json"
    features = {f["properties"]["id"]: f for f in json.loads(context_path.read_text())["features"]}
    matrix = json.loads(matrix_path.read_text())
    if matrix.get("outline_count") != 17:
        raise ValueError("Monterey research outline set changed")
    identifiers = {suffix: next(row["context_id"] for row in matrix["review_order"] if row["context_id"].endswith("-" + suffix))
                   for suffix in ("023", "046")}
    outlines = {suffix: shape(features[identifiers[suffix]]["geometry"]) for suffix in identifiers}
    file_index = {}
    for suffix, ident in identifiers.items():
        files, sha = query_file_layer(root, suffix, features[ident]["geometry"], fetch)
        file_index[suffix] = {"processed_file_ids": files, "response_sha256": sha}
    cache = root / "var/review/ncei-centralmontereybay-priority"
    lines = []
    totals = {suffix: Counter() for suffix in identifiers}
    for stem, spec in sorted(PROCESSED.items()):
        name = file_name(stem)
        path = cache / name
        read_pinned(path, BASE + name, spec[1], fetch, 30_000_000)
        companion_base = BASE + "generated/" + name.removesuffix(".gz")
        inf = read_pinned(cache / (name.removesuffix(".gz") + ".inf"), companion_base + ".inf", spec[2], fetch, 1_000_000)
        fnv = read_pinned(cache / (name.removesuffix(".gz") + ".fnv"), companion_base + ".fnv", spec[3], fetch, 2_000_000)
        counts, outline_rows, checks, processing = decode_line(path, inf, fnv, spec, outlines)
        for suffix, row in outline_rows.items():
            totals[suffix]["valid_beams_inside_outline"] += row["valid_beams_inside_outline"]
            totals[suffix]["valid_beams_nominal_200_300ft_unknown_datum"] += row["valid_beams_nominal_200_300ft_unknown_datum"]
        lines.append({"ncei_file_id": spec[0], "gsf_url": BASE + name,
                      "gsf_sha256": spec[1], "inf_sha256": spec[2], "fnv_sha256": spec[3],
                      "counts": counts, "generated_companion_checks": checks,
                      "outlines": outline_rows})
    return {
        "schema_version": 1, "scope": "monterey-2009-centralmontereybay-original-valid-beam-research",
        "source_cruise_url": "https://www.ngdc.noaa.gov/ships/ventresca/CentralMontereyBay_mb.html",
        "ncei_file_layer_url": FILE_LAYER,
        "research_context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        "research_matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "ncei_file_layer": file_index, "processed_files_audited": len(lines),
        "processing_parameters_common": processing,
        "outlines": {suffix: {"context_id": identifiers[suffix], **totals[suffix],
                              "mllw_depth_qualified": False, "upper_vertical_error_qualified": False,
                              "independent_of_2013_merge_established": False,
                              "fishing_target": False, "exportable": False}
                     for suffix in identifiers},
        "lines": lines, "fishing_target": False, "exportable": False,
        "next_acquisition": "Get the 2009 Ventresca/CSUMB processing report and tide-zone/vertical-datum record, horizontal registration, uncertainty budget and source-to-2013-merge point_source_id crosswalk. Compare actual original beam positions to paired USGS 2 m depth/character cells before any patch review.",
        "limitations": [
            "GSF valid-beam flags and positions are original processed-line evidence, but tide compensation is labeled YES while TIDAL_DATUM is UNKNOWN; nominal GSF depths cannot establish MLLW 300 ft compliance.",
            "The 95% per-beam error arrays are source-reported values, not a demonstrated conservative upper product-depth error; datum transformation, tides, horizontal registration, gridding and seabed change are unbounded here.",
            "Survey line overlaps are correlated and not separate species observations or proof of a contiguous rock patch. The 2013 merge may reuse this cruise, so independence from that resample is unresolved.",
            "No source-based fish presence, complete MPA/legal/access/ENC/route review or current catch validation is supplied. The receipt omits original beam and fishing coordinates.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, default=Path("research/receipts/monterey-2009-centralmontereybay-valid-beam-review.json"))
    args = parser.parse_args()
    report = build(args.root.resolve(), args.fetch)
    if args.verify:
        old = json.loads(args.verify.read_text())
        if report != {key: value for key, value in old.items() if key != "checked_at"}:
            raise ValueError("2009 original NCEI beam result changed; hold for review")
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("2009 NCEI original processed beams reviewed in two research outlines; zero fishing targets")


if __name__ == "__main__":
    main()
