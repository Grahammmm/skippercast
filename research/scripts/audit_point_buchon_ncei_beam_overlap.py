#!/usr/bin/env python3
"""Screen valid original GSF beam positions against original USGS Point Buchon cells.

This is a source-datum cross-survey research receipt, not a fishing-point release.
The 2007 GSF and 2008 USGS raster have unconfirmed vertical datums and registration.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import struct

import numpy as np
from pyproj import Geod, Transformer
import rasterio

from research.scripts.audit_point_buchon_ncei_multibeam_lead import LOWER_M, UPPER_M, PROBES, companion_urls, fetch
from research.scripts.audit_point_buchon_original_pair import original_tiff


ROOT = Path(__file__).resolve().parents[2]
SPEC_URL = "https://github.com/schwehr/generic-sensor-format/blob/master/doc/GSF_spec.md"


def decode_beams(compressed, expected_sha):
    if hashlib.sha256(compressed).hexdigest() != expected_sha or len(compressed) > 20_000_000:
        raise ValueError("Original NCEI GSF bytes changed or exceed reviewed size")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        data = source.read(80_000_001)
    if len(data) > 80_000_000:
        raise ValueError("Original NCEI GSF expansion exceeds reviewed size")
    offset, scales, pings, navigation, excluded_pings = 0, {}, [], [], 0
    counts = Counter()
    while offset + 8 <= len(data):
        length, record_id = struct.unpack_from(">II", data, offset)
        if (record_id & 0x80000000 or length > 10_000_000 or offset + 8 + length > len(data)):
            raise ValueError("Original NCEI GSF record structure changed")
        body = data[offset + 8:offset + 8 + length]
        offset += 8 + length
        if record_id & 0xFFF != 2:
            continue
        counts["ping_records"] += 1
        if len(body) < 56:
            raise ValueError("Original NCEI GSF ping header truncated")
        lon_i, lat_i = struct.unpack_from(">ii", body, 8)
        beam_count, _center, ping_flags = struct.unpack_from(">HHH", body, 16)
        heading = struct.unpack_from(">H", body, 30)[0] / 100
        if (beam_count != 101 or not (-121.2 < lon_i / 1e7 < -120.7)
                or not (35.1 < lat_i / 1e7 < 35.4) or not 0 <= heading <= 360):
            raise ValueError("Original NCEI GSF ping geometry changed")
        navigation.append((lon_i / 1e7, lat_i / 1e7, heading))
        cursor, arrays = 56, {}
        while cursor + 4 <= len(body):
            packed = struct.unpack_from(">I", body, cursor)[0]
            kind, size = packed >> 24, packed & 0xFFFFFF
            cursor += 4
            if cursor + size > len(body):
                raise ValueError("Original NCEI GSF ping subrecord truncated")
            raw = body[cursor:cursor + size]
            cursor += size
            if kind == 100:
                if len(raw) < 4:
                    raise ValueError("Original NCEI GSF scale factor truncated")
                factor_count = struct.unpack_from(">I", raw)[0]
                if len(raw) != 4 + factor_count * 12:
                    raise ValueError("Original NCEI GSF scale factor count changed")
                for i in range(factor_count):
                    sid, compression, reserved, multiplier, origin = struct.unpack_from(">BBHii", raw, 4 + 12*i)
                    if compression or reserved or multiplier <= 0:
                        raise ValueError("Original NCEI GSF beam compression or scale changed")
                    scales[sid] = (multiplier, origin)
            elif kind in (1, 2, 3, 16, 19, 20):
                if kind in arrays:
                    raise ValueError("Original NCEI GSF duplicate beam array")
                arrays[kind] = raw
        if cursor != len(body) or set(arrays) != {1, 2, 3, 16, 19, 20}:
            raise ValueError("Original NCEI GSF beam arrays incomplete")
        if any(kind not in scales for kind in (1, 2, 3, 19, 20)):
            raise ValueError("Original NCEI GSF active scale factors missing")
        if any(len(arrays[kind]) != beam_count * 2 for kind in (1, 2, 3, 19, 20)) or len(arrays[16]) != beam_count:
            raise ValueError("Original NCEI GSF beam array widths changed")
        flags = np.frombuffer(arrays[16], dtype="u1")
        counts["beam_records"] += beam_count
        counts["flagged_or_zero_beams"] += int(np.count_nonzero(flags & 1))
        if ping_flags & 1:
            excluded_pings += 1
            continue
        valid = (flags & 1) == 0
        counts["valid_unflagged_beams"] += int(np.count_nonzero(valid))
        def numbers(kind, dtype):
            mult, origin = scales[kind]
            return np.frombuffer(arrays[kind], dtype=dtype).astype("f8")[valid] / mult - origin
        depth = numbers(1, ">u2")
        across = numbers(2, ">i2")
        along = numbers(3, ">i2")
        vertical_error = numbers(19, ">u2")
        horizontal_error = numbers(20, ">u2")
        if (not np.all(np.isfinite(depth)) or np.any(depth <= 0) or np.any(depth > 1000)
                or np.any(np.abs(across) > 1000) or np.any(np.abs(along) > 1000)):
            raise ValueError("Original NCEI GSF valid-beam values out of reviewed bounds")
        pings.append((lon_i / 1e7, lat_i / 1e7, heading, depth, across, along,
                      vertical_error, horizontal_error))
    if offset != len(data) or counts["ping_records"] < 100 or counts["valid_unflagged_beams"] < 1000:
        raise ValueError("Original NCEI GSF beam file incomplete")
    counts["excluded_ping_records"] = excluded_pings
    return pings, navigation, dict(counts)


def check_generated_companions(inf, fnv, spec, navigation, counts):
    if hashlib.sha256(inf).hexdigest() != spec["inf_sha256"]:
        raise ValueError("NCEI generated line summary bytes changed")
    if hashlib.sha256(fnv).hexdigest() != spec["fnv_sha256"]:
        raise ValueError("NCEI generated navigation bytes changed")
    good = re.search(rb"Number of Good Beams:\s*(\d+)", inf)
    if not good or int(good.group(1)) != counts["valid_unflagged_beams"]:
        raise ValueError("Decoded valid GSF beam count differs from NCEI generated summary")
    rows = fnv.decode("ascii").splitlines()
    if len(rows) != counts["ping_records"]:
        raise ValueError("Decoded GSF ping count differs from NCEI navigation")
    for row, (lon, lat, heading) in zip(rows, navigation):
        fields = row.split()
        if (len(fields) != 19 or abs(float(fields[7]) - lon) > .000005
                or abs(float(fields[8]) - lat) > .000005
                or abs(float(fields[9]) - heading) > .02):
            raise ValueError("Decoded GSF ping position differs from NCEI navigation")
    return {"generated_inf_good_beams_match": True, "generated_fnv_navigation_rows_match": True,
            "generated_inf_sha256": spec["inf_sha256"],
            "generated_fnv_sha256": spec["fnv_sha256"]}


def beam_positions(geod, lon, lat, heading, across, along):
    # GSF x is forward and y is starboard. Geod.fwd uses clockwise azimuth.
    azimuth = heading + np.degrees(np.arctan2(across, along))
    distance = np.hypot(across, along)
    beam_lon, beam_lat, _ = geod.fwd(np.full(len(across), lon), np.full(len(across), lat),
                                    azimuth, distance)
    return beam_lon, beam_lat


def beam_cell_screen(pings, bathy, character):
    geod = Geod(ellps="WGS84")
    projector = Transformer.from_crs("EPSG:4326", bathy.crs, always_xy=True)
    rows, cols, source_depths, vertical_errors, horizontal_errors = [], [], [], [], []
    for lon, lat, heading, depth, across, along, v_error, h_error in pings:
        beam_lon, beam_lat = beam_positions(geod, lon, lat, heading, across, along)
        x, y = projector.transform(beam_lon, beam_lat)
        row = np.floor((y - bathy.transform.f) / bathy.transform.e).astype("i4")
        col = np.floor((x - bathy.transform.c) / bathy.transform.a).astype("i4")
        inside = ((row >= 0) & (row < bathy.height) & (col >= 0) & (col < bathy.width))
        rows.append(row[inside]); cols.append(col[inside]); source_depths.append(depth[inside])
        vertical_errors.append(v_error[inside]); horizontal_errors.append(h_error[inside])
    row, col = np.concatenate(rows), np.concatenate(cols)
    source_depth = np.concatenate(source_depths)
    v_error, h_error = np.concatenate(vertical_errors), np.concatenate(horizontal_errors)
    index = row.astype("i8") * bathy.width + col
    unique, inverse = np.unique(index, return_inverse=True)
    locations = [bathy.xy(int(i // bathy.width), int(i % bathy.width)) for i in unique]
    depths = np.ma.array(list(bathy.sample(locations, masked=True)))[:, 0]
    classes = np.ma.array(list(character.sample(locations, masked=True)))[:, 0]
    paired = (~np.ma.getmaskarray(depths) & ~np.ma.getmaskarray(classes)
              & np.isfinite(np.ma.getdata(depths)))
    usgs_depth = -np.ma.getdata(depths)
    class_values = np.ma.getdata(classes)
    both_band = (paired & (usgs_depth >= LOWER_M) & (usgs_depth <= UPPER_M))
    per_beam_band = (source_depth >= LOWER_M) & (source_depth <= UPPER_M)
    summary = {"outside_original_usgs_raster": int(sum(len(p[3]) for p in pings) - len(index)),
               "valid_beams_inside_raster": int(len(index)),
               "unique_usgs_pixels_under_valid_beams": int(len(unique)),
               "valid_beams_inside_raster_nominal_gsf_200_300ft_unknown_datum": int(np.count_nonzero(per_beam_band)),
               "valid_beams_on_paired_usgs_hard_rugose_200_300ft_source_datum": 0,
               "valid_beams_both_nominal_depth_bands_and_usgs_hard_rugose": 0,
               "unique_usgs_hard_rugose_200_300ft_pixels_under_valid_beams": int(np.count_nonzero(both_band & (class_values == 3))),
               "beam_vertical_error_95pct_m_range": [round(float(np.min(v_error)), 4), round(float(np.max(v_error)), 4)],
               "beam_horizontal_error_95pct_m_range": [round(float(np.min(h_error)), 4), round(float(np.max(h_error)), 4)]}
    hard_rugose_beam = both_band[inverse] & (class_values[inverse] == 3)
    summary["valid_beams_on_paired_usgs_hard_rugose_200_300ft_source_datum"] = int(np.count_nonzero(hard_rugose_beam))
    summary["valid_beams_both_nominal_depth_bands_and_usgs_hard_rugose"] = int(np.count_nonzero(hard_rugose_beam & per_beam_band))
    both = hard_rugose_beam & per_beam_band
    if np.any(both):
        differences = source_depth[both] - usgs_depth[inverse[both]]
        summary["same_pixel_gsf_minus_usgs_source_depth_m_median"] = round(float(np.median(differences)), 3)
        summary["same_pixel_gsf_minus_usgs_source_depth_m_p95_absolute"] = round(float(np.quantile(np.abs(differences), .95)), 3)
    return summary


def audit(bathy_zip, class_zip, fetcher=fetch):
    results = []
    with rasterio.open(original_tiff(bathy_zip)) as bathy, rasterio.open(original_tiff(class_zip)) as character:
        if (bathy.shape != character.shape or bathy.transform != character.transform
                or str(bathy.crs) != "EPSG:32610" or bathy.transform.b or bathy.transform.d):
            raise ValueError("USGS Point Buchon original pair alignment changed")
        for name, spec in PROBES.items():
            pings, navigation, counts = decode_beams(fetcher(spec["url"]), spec["sha256"])
            inf_url, fnv_url = companion_urls(spec["url"])
            companions = check_generated_companions(fetcher(inf_url), fetcher(fnv_url), spec,
                                                    navigation, counts)
            results.append({"survey_id": name, "gsf_url": spec["url"],
                            "gsf_compressed_sha256": spec["sha256"],
                            **companions, **counts, **beam_cell_screen(pings, bathy, character)})
    return {"schema_version": 1, "scope": "point-buchon-2007-ncei-original-valid-beam-overlap",
            "gsf_specification_url": SPEC_URL,
            "usgs_original_bathymetry_sha256": "c825293fc999ad757b32ee2acefcae590690d451d12fd367b2f8b3e9e6d731d4",
            "usgs_original_character_sha256": "0a9579783e5318bfee0ebef8ede112f32c5a2202272338ae9eb1fd9e96df8bc1",
            "source_vertical_datum": "Unknown for both processed GSF lines and published USGS raster",
            "surveys": results, "qualified_waypoints": 0, "fishing_target": False,
            "exportable": False,
            "limitation": "Valid original GSF beam positions are computed from ping position, heading and per-beam across/along offsets, with decoded counts and navigation checked against NCEI generated summaries. Nominal 200–300 ft overlap and same-pixel depth differences use two unresolved source datums and unverified horizontal registration. GSF error arrays are not verified total product uncertainty, and no current legal/safe-route/fish evidence is established. No spot rank or coordinate is authorized."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bathy", type=Path, default=ROOT / "var/review/usgs-point-buchon/Bathymetry_OffshorePointBuchon.zip")
    parser.add_argument("--character", type=Path, default=ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(audit(args.bathy, args.character), indent=2) + "\n"
    if args.verify and args.verify.read_text() != encoded:
        raise SystemExit("Point Buchon original valid-beam overlap changed; review before using")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded)


if __name__ == "__main__":
    main()
