"""The coast report's ocean packet assembled from SkipperCast's own feeds (FE-84).

    python -m skippercast.pipeline.coast_snapshots --root var/live-published

Writes `regions/morro-bay/coast-ocean.json`, the `packages/coast` `OceanData`
(`packages/coast/src/ocean-types.ts`) that `/api/coast/ocean` serves when the
Worker's `COAST_FEEDS` switch lists `ocean` (`server/coast-data.ts`). It reads
two files already in the published tree: the region's `intelligence.json`
(WCOFS and HF radar surface currents) and the root `goes-times.json` (FE-44).
The Fish Worker built the same packet from the same two inputs; the current
rules are ported from `fish` `src/providers/ocean.ts` (`normalizeSkipperOcean`):
reviewed NOAA products only, status `ok` only, native frame times, rounded
speeds and bearings kept, gaps left blank. Each field keeps its own fetch,
issue and sample clocks; a feed that fails a check is published as an `error`
source with no data, never as current. The report's nearshore and beach rows
and the History view's bundle need no assembly: the Worker reads FE-40's
`nearshore.json`, FE-41's `beach-health.json` and FE-42's `history.json` as
published.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys

from ..platform.contracts import atomic_json
from .goes_frames import CAPABILITIES_URL, epoch, iso

COUNTY, REGION = "slo", "morro-bay"
OCEAN_FEED_URL = f"https://raw.githubusercontent.com/Grahammmm/skippercast/conditions/regions/{REGION}/intelligence.json"
HOUR, SKEW = 3_600_000, 300_000
FIELDS_FORECAST = ["latitude", "longitude", "speed_knots", "toward_degrees"]
FIELDS_RADAR = FIELDS_FORECAST + ["hdop", "radar_count"]
DEFINITIONS = {
    "wcofs": ("forecast", 4, "https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html", FIELDS_FORECAST),
    "hfr-1": ("observation", 1, "https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_1km.html", FIELDS_RADAR),
    "hfr-6": ("observation", 6, "https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_6km.html", FIELDS_RADAR),
}
BOUNDS = (34.92, 35.85, -121.96, -120.5)  # SLO marine bounds: south, north, west, east
SOURCE_FILE = re.compile(r"^wcofs\.t\d{2}z\.\d{8}\.regulargrid\.f\d{3}\.nc$")
FORECAST_TEXT = ("NOAA WCOFS surface-current forecast", "NOAA National Ocean Service · WCOFS",
                 "Approximately 4 km surface model at native three-hour times. Assimilates HF radar; agreement is "
                 "not independent validation. Wet-cell gaps retained. Does not resolve reef, bottom drift, surf zone, "
                 "or harbor-bar currents.")
RADAR_TEXT = ("NOAA / IOOS Surface Currents Program · HFRNet",
              "Near-surface radar observation; missing cells remain blank. HDOP ≤2 and at least two contributing "
              "radars. Not future, bottom, or harbor-bar current.")


def _ms(value):
    return epoch(value) if isinstance(value, str) else None


def _fresh(at, now, hours):
    return at is not None and at <= now + SKEW and now - at <= hours * HOUR


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _frames(data, kind, fields, issued, now):
    """Native frames as `CurrentFrame`s, or None when any frame or cell is malformed."""
    forecast, frames, prior = kind == "forecast", [], -math.inf
    for frame in data["frames"]:
        at = frame.get("time") * 1000 if isinstance(frame, dict) and _number(frame.get("time")) else None
        cells = frame.get("cells") if isinstance(frame, dict) else None
        if at is None or at <= prior or not isinstance(cells, list) or len(cells) > 1500:
            return None
        prior = at
        if forecast:
            hours = (at - issued) / HOUR
            if hours < 0 or hours > 72 or abs(hours / 3 - round(hours / 3)) > 1 / 3600:
                return None
        elif at > now + SKEW:
            return None
        out = []
        for row in cells:
            if not isinstance(row, list) or len(row) != len(fields) or not all(map(_number, row)):
                return None
            lat, lon, speed, bearing = row[:4]
            if not (BOUNDS[0] <= lat <= BOUNDS[1] and BOUNDS[2] <= lon <= BOUNDS[3] and 0 <= speed <= 9.72 and 0 <= bearing <= 360):
                return None
            toward = bearing % 360  # rounded upstream bearings can be 360.0
            if not forecast and (row[4] < 0 or row[4] > 2 or not float(row[5]).is_integer() or not 2 <= row[5] <= 20):
                continue  # radar cells outside the HDOP and site-count gate are left out, as fish does
            # u/v are reconstructed for display from the rounded speed and bearing, not model precision.
            ms, rad = speed / 1.94384449, math.radians(toward)
            cell = {"lat": lat, "lon": lon, "speedKnots": speed, "towardDeg": toward,
                    "uMs": round(ms * math.sin(rad), 5), "vMs": round(ms * math.cos(rad), 5)}
            if not forecast:
                cell.update(hdop=row[4], radarCount=int(row[5]))
            out.append(cell)
        source_file = frame.get("source_file")
        frames.append({"validAt": iso(int(at)), "cells": out,
                       **({"sourceFile": source_file} if isinstance(source_file, str) and SOURCE_FILE.match(source_file) else {})})
    return frames


def currents(doc, now):
    """`CurrentField`s from the region's intelligence feed; ValueError when the feed is invalid or over 6 h old."""
    if (not isinstance(doc, dict) or doc.get("schema_version") != 1 or doc.get("region_id") != REGION
            or not _fresh(_ms(doc.get("generated_at")), now, 6)):
        raise ValueError("Invalid or stale regional ocean feed")
    fields = []
    for ident, (kind, resolution, url, names) in DEFINITIONS.items():
        source = (doc.get("sources") or {}).get(ident)
        source = source if isinstance(source, dict) else {}
        data, fetched = source.get("data"), _ms(source.get("data_retrieved_at") or source.get("last_success_at"))
        if source.get("status") != "ok" or not isinstance(data, dict) \
                or data.get("kind") != kind or data.get("surface_only") is not True or data.get("resolution_km") != resolution \
                or data.get("fields") != names or not _fresh(fetched, now, 6):
            continue
        forecast = kind == "forecast"
        issued, sample = _ms(data.get("issued_at")), _ms(data.get("sample_at"))
        if not _fresh(issued, now, 36) if forecast else not _fresh(sample, now, 6):
            continue
        stride = data.get("grid_stride", 1)
        if (not isinstance(stride, int) or isinstance(stride, bool) or not 1 <= stride <= 20
                or not isinstance(data.get("frames"), list) or not data["frames"] or len(data["frames"]) > (25 if forecast else 6)):
            continue
        frames = _frames(data, kind, names, issued, now)
        if not frames or not any(f["cells"] for f in frames):
            continue
        if forecast and (data.get("horizontal_datum") != "NAD83" or data.get("vertical_layer") != "surface (0 m)"):
            continue
        if not forecast and not any(f["cells"] and _fresh(epoch(f["validAt"]), now, 6) for f in frames):
            continue
        attribution, limitations = (FORECAST_TEXT[1:] if forecast else RADAR_TEXT)
        fields.append({"id": ident, "kind": kind, "label": FORECAST_TEXT[0] if forecast else f"NOAA / IOOS {resolution} km surface radar",
                       "url": url, "fetchedAt": iso(fetched), "issuedAt": iso(issued) if issued is not None else None,
                       "sampleAt": iso(sample) if sample is not None else None, "nativeResolutionKm": resolution,
                       "sampleStride": stride, "horizontalDatum": "NAD83" if forecast else "WGS84", "surfaceOnly": True,
                       "frames": frames, "license": "public-domain-us-gov", "attribution": attribution, "limitations": limitations})
    return fields


def cloud(record, now):
    """The FE-44 `CloudImage` while its newest frame is within the client's 90-minute gate; ValueError otherwise."""
    if not isinstance(record, dict) or record.get("id") != "goes-longwave" or record.get("kind") != "observation":
        raise ValueError("GOES frame index unavailable")
    observed, times = _ms(record.get("observedAt")), record.get("availableTimes")
    if not _fresh(observed, now, 1.5) or not _fresh(_ms(record.get("fetchedAt")), now, 6) \
            or not isinstance(times, list) or record["observedAt"] not in times:
        raise ValueError("GOES imagery is stale or unavailable")
    return record


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def assemble(intelligence, goes, now=None):
    """`OceanData` for the SLO county; every source's outcome and clock is its own."""
    now_dt = now or datetime.now(timezone.utc)
    clock = int(now_dt.timestamp() * 1000)
    packet = {"schemaVersion": 1, "countyId": COUNTY, "generatedAt": iso(clock), "currents": [], "cloud": None, "sources": []}
    generated = _ms(intelligence.get("generated_at")) if isinstance(intelligence, dict) else None
    try:
        packet["currents"] = currents(intelligence, clock)
        error = None if packet["currents"] else "No fresh reviewed current fields"
    except ValueError as failure:
        error = str(failure)
    packet["sources"].append({"id": "skippercast-noaa-ocean", "url": OCEAN_FEED_URL, "fetchedAt": iso(generated if generated is not None else clock),
                              "status": "error" if error else "ok", **({"error": error} if error else {})})
    fetched = _ms(goes.get("fetchedAt")) if isinstance(goes, dict) else None
    try:
        packet["cloud"], error = cloud(goes, clock), None
    except ValueError as failure:
        error = str(failure)
    packet["sources"].append({"id": "noaa-goes", "url": CAPABILITIES_URL, "fetchedAt": iso(fetched if fetched is not None else clock),
                              "status": "error" if error else "ok", **({"error": error} if error else {})})
    return packet


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True, help="the published tree: reads regions/morro-bay/intelligence.json "
                        "and goes-times.json, writes regions/morro-bay/coast-ocean.json")
    args = parser.parse_args(argv)
    packet = assemble(_read(args.root / "regions" / REGION / "intelligence.json"), _read(args.root / "goes-times.json"), now)
    atomic_json(args.root / "regions" / REGION / "coast-ocean.json", packet)
    print(json.dumps({"generatedAt": packet["generatedAt"], "currents": [f["id"] for f in packet["currents"]],
                      "cloud": bool(packet["cloud"]), "sources": {s["id"]: s["status"] for s in packet["sources"]}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
