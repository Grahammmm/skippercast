#!/usr/bin/env python3
"""Audit original 2012 USGS outer Estero Bay depth and sounding-spread cells.

Source grid rows are paired by the report's documented WGS84-to-NAD83 frame
shift; this is a research precision check, not a total depth-uncertainty model.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = {
    "NAD83_utm10_EsteroBay.zip": "b44661031acac9e22e18fed8785e796690368cb8a2cdf7887903a1e732d6c08a",
    "WGS84_utm10_EsteroBay.zip": "0379883c10a67ecad2a65a38d6d948dc9441df06528bac08034d0dc85295e876",
    "StDev_utm10_EsteroBay.zip": "06a0c2e375617d7bb96cf739e1843045f50726925f2e834e1c81e742743d4f65",
}
METADATA = {
    "NAD83_metadata_EsteroBay.xml": "8764aed9a629890e3512c9451e215488b4bea78767718147e5c21c125b6cdf2c",
    "WGS84_metadata_EsteroBay.xml": "2bbf92a1c1163800e11e45c2f2bea98fd5ee95e0e44850762a4b27fbd24f2ea2",
    "StDev_metadata_EsteroBay.xml": "84d84abc196561626d99cef76984dc99597b04c6f7b7cf6e96bca4b994576d51",
}
BANDS = ((200, 250), (250, 300))


def checked(path, pin):
    if hashlib.sha256(path.read_bytes()).hexdigest() != pin[path.name]:
        raise ValueError(f"Original USGS object changed: {path.name}")


def fetch_sources(base):
    base.mkdir(parents=True, exist_ok=True)
    for name, expected in {**ARCHIVES, **METADATA}.items():
        path = base / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            continue
        part = path.with_suffix(path.suffix + ".download")
        kind = "metadata" if name.endswith(".xml") else "data"
        url = f"https://pubs.usgs.gov/of/2013/1225/{kind}/{name}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SkipperCast source audit; +https://skippercast.com)"})
        with urlopen(req, timeout=90) as response, part.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if hashlib.sha256(part.read_bytes()).hexdigest() != expected:
            part.unlink()
            raise ValueError(f"Original USGS object changed: {name}")
        part.replace(path)


def ascii_member(archive):
    checked(archive, ARCHIVES)
    package = zipfile.ZipFile(archive)
    members = [entry for entry in package.namelist() if entry.lower().endswith(".asc")]
    if len(members) != 1:
        package.close()
        raise ValueError("Expected exactly one original ASCII grid")
    return package, package.open(members[0])


def header(source):
    result = {}
    for _ in range(6):
        key, value = source.readline().decode("ascii").split()
        result[key.lower()] = float(value)
    if (result["ncols"] != 11456 or result["nrows"] != 16020
            or result["cellsize"] != 2 or result["nodata_value"] != -9999):
        raise ValueError("Source ASCII grid layout changed")
    return result


def audit(base):
    for name in METADATA:
        checked(base / name, METADATA)
    depth_package, depth_file = ascii_member(base / "NAD83_utm10_EsteroBay.zip")
    spread_package, spread_file = ascii_member(base / "StDev_utm10_EsteroBay.zip")
    wgs_package, wgs_file = ascii_member(base / "WGS84_utm10_EsteroBay.zip")
    try:
        depth_header, spread_header, wgs_header = header(depth_file), header(spread_file), header(wgs_file)
        if spread_header != wgs_header:
            raise ValueError("WGS84 and spread grids no longer align")
        dx = depth_header["xllcorner"] - spread_header["xllcorner"]
        dy = depth_header["yllcorner"] - spread_header["yllcorner"]
        if not 1.15 <= dx <= 1.2 or not -0.55 <= dy <= -0.45:
            raise ValueError("Documented frame/epoch grid shift changed")
        # The WGS grid is read to verify corresponding data masks and rows.
        counts = {f"{lo}-{hi}ft": {"depth_cells": 0, "paired_spread_cells": 0,
                                    "spread_sum_m": 0.0, "spread_max_m": 0.0,
                                    "spread_le_0_5m": 0, "spread_le_1m": 0}
                  for lo, hi in BANDS}
        valid_depth_total = 0
        mask_disagreement = 0
        for row in range(16020):
            d = np.fromstring(depth_file.readline().decode("ascii"), sep=" ")
            s = np.fromstring(spread_file.readline().decode("ascii"), sep=" ")
            w = np.fromstring(wgs_file.readline().decode("ascii"), sep=" ")
            if d.size != 11456 or s.size != 11456 or w.size != 11456:
                raise ValueError(f"Truncated original ASCII row {row}")
            depth_valid, spread_valid, wgs_valid = d != -9999, s != -9999, w != -9999
            valid_depth_total += int(np.count_nonzero(depth_valid))
            mask_disagreement += int(np.count_nonzero(depth_valid != wgs_valid))
            if np.any((s < 0) & spread_valid):
                raise ValueError("Negative sounding spread")
            for lo, hi in BANDS:
                item = counts[f"{lo}-{hi}ft"]
                band = depth_valid & (-d >= lo / 3.280839895) & (-d < hi / 3.280839895)
                item["depth_cells"] += int(np.count_nonzero(band))
                paired = band & spread_valid & wgs_valid
                values = s[paired]
                item["paired_spread_cells"] += int(values.size)
                if values.size:
                    item["spread_sum_m"] += float(np.sum(values))
                    item["spread_max_m"] = max(item["spread_max_m"], float(np.max(values)))
                    item["spread_le_0_5m"] += int(np.count_nonzero(values <= .5))
                    item["spread_le_1m"] += int(np.count_nonzero(values <= 1))
        if mask_disagreement > valid_depth_total * .001:
            raise ValueError("NAD83 and WGS84 valid-cell masks disagree materially")
        for item in counts.values():
            n = item.pop("paired_spread_cells")
            total = item.pop("spread_sum_m")
            item["paired_nominal_cells"] = n
            item["mean_within_cell_sounding_spread_m"] = round(total / n, 3) if n else None
            item["max_within_cell_sounding_spread_m"] = round(item.pop("spread_max_m"), 3) if n else None
            item["area_m2_at_2m_output_grid"] = 4 * item["depth_cells"]
        return {"schema_version": 1, "scope": "usgs-estero-bay-2012-original-200-300ft-research",
                "source_report": "https://doi.org/10.3133/ofr20131225",
                "source_archives_sha256": ARCHIVES, "source_metadata_sha256": METADATA,
                "survey_dates": ["2012-07-30", "2012-08-09"],
                "source_vertical_datum": "NAVD88 Geoid12 for NAD83 bathymetry",
                "native_depth_resolution_m_in_band": 2,
                "wgs_to_nad_grid_origin_shift_m": [round(dx, 3), round(dy, 3)],
                "valid_navd88_depth_cells": valid_depth_total,
                "nad_wgs_valid_mask_disagreements": mask_disagreement,
                "nominal_depth_bands": counts,
                "fishing_target": False, "exportable": False, "qualified_waypoints": 0,
                "limitations": [
                    "NAVD88 depths require spatial MLLW conversion and its propagated uncertainty before any 300 ft fishing-depth claim.",
                    "The spread grid is standard deviation of soundings in WGS84 cells, not an upper bound on total propagated product uncertainty; natural rugosity can inflate it.",
                    "Index pairing reflects documented coordinate-frame shift, but does not replace a surveyed registration-error analysis.",
                    "The output mosaic is 2 m; source cells beyond 100 m were 4 m and resampled. Only the 200–300 ft nominal band falls inside the native 2 m portion.",
                    "No independent substrate, MPA, chart, access, biological or drift/route screen has qualified these cells as fishing spots.",
                ]}
    finally:
        for stream in (depth_file, spread_file, wgs_file):
            stream.close()
        for archive in (depth_package, spread_package, wgs_package):
            archive.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--base", type=Path, default=ROOT / "var/review/estero-bay-2012")
    p.add_argument("--output", type=Path, default=ROOT / "dist/data/usgs-estero-bay-2012-original-200-300ft-review.json")
    args = p.parse_args()
    if args.fetch:
        fetch_sources(args.base)
    report = audit(args.base)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print({key: value["depth_cells"] for key, value in report["nominal_depth_bands"].items()})


if __name__ == "__main__":
    main()
