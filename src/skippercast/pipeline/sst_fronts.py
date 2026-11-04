"""Offshore SST fronts (BF-sst-fronts): edges found in the published SST analysis tiles.

A front is an edge, never a point. The publisher pools every tile of one region's
`sst-analysis` layer into one grid (so an edge crossing a tile boundary is one front), keeps
the cells where the temperature change across the two neighbours exceeds their summed
analysis error (the same rule as habitat_dynamics.py `gradients`), thins those to the ridge
of strongest change and links the ridge into lines. Each front carries its observation time,
its gradient strength and an uncertainty band taken from the analysis's own stated error:
the position is uncertain by (analysis error / gradient) either side of the line.

A tile frame whose observation time is missing, unparseable, in the future or older than the
feed's `max_age_hours` in catalog/feed-health.json yields no front; that limit has no default.
Temperatures or errors that are not finite numbers, or outside the sea's range, are refused
with an `SstFrontError`. This module reads tiles and writes one JSON document; it never
touches the network.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

LAYER_ID = "sst-fronts"
FEED = "sst-fronts"
KM_PER_DEGREE = 111.195
TEMP_RANGE_C = (-2.0, 40.0)
MAX_ERROR_C = 5.0
MIN_FRONT_CELLS = 5  # an edge, not a dot: shorter chains are noise
STEPS = [(di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1) if (di, dj) != (0, 0)]
NEEDED = ("latitude", "longitude", "temperature_c", "analysis_error_c")


class SstFrontError(ValueError):
    """A tile or the feed-health file cannot be used; the publisher refuses rather than guess."""


def max_age_hours(health):
    """The fronts feed's age limit; absent or not a positive finite number fails loudly."""
    try:
        value = health["feeds"][FEED]["max_age_hours"]
    except (KeyError, TypeError):
        value = None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise SstFrontError(f"catalog/feed-health.json has no usable feeds.{FEED}.max_age_hours")
    return float(value)


def observation_time(value):
    """An aware UTC datetime from epoch seconds or an ISO stamp with a zone, else None."""
    try:
        if isinstance(value, str):
            when = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return when if when.tzinfo else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _number(value, low, high, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise SstFrontError(f"{what} {value!r} is not a finite number in {low}..{high}")
    return float(value)


def _frames(tile, name):
    fields = tile.get("fields") if isinstance(tile, dict) else None
    frames = tile.get("frames") if isinstance(tile, dict) else None
    res = tile.get("resolution_degrees") if isinstance(tile, dict) else None
    if not isinstance(fields, list) or any(n not in fields for n in NEEDED) or not isinstance(frames, list):
        raise SstFrontError(f"{name}: not an sst-analysis tile")
    if not isinstance(res, list) or len(res) != 2 or res[0] != res[1] or not isinstance(res[0], (int, float)) or not 0 < res[0] <= 0.25:
        raise SstFrontError(f"{name}: unusable grid resolution")
    return [fields.index(n) for n in NEEDED], frames, float(res[0])


def usable_frames(tiles, now, limit_hours):
    """(observation time, rows, resolution) for each frame that may yield fronts, and a count of the refused ones."""
    out, refused = [], {"missing_time": 0, "unparseable_time": 0, "future": 0, "stale": 0}
    for name, tile in tiles:
        index, frames, res = _frames(tile, name)
        for frame in frames:
            raw = frame.get("time") if isinstance(frame, dict) else None
            when = observation_time(raw)
            if raw is None:
                refused["missing_time"] += 1
            elif when is None:
                refused["unparseable_time"] += 1
            elif when > now:
                refused["future"] += 1
            elif (now - when).total_seconds() > limit_hours * 3600:  # exactly at the limit still counts
                refused["stale"] += 1
            elif isinstance(frame.get("cells"), list):
                out.append((when, [[r[i] for i in index] for r in frame["cells"]], res))
    return out, refused


def _grid(rows, res):
    grid = {}
    for lat, lon, temp, err in rows:
        if temp is None or err is None:
            continue  # land, cloud or no error figure: not judged
        t = _number(temp, *TEMP_RANGE_C, "temperature_c")
        e = _number(err, 0, MAX_ERROR_C, "analysis_error_c")
        y, x = _number(lat, -90, 90, "latitude"), _number(lon, -180, 180, "longitude")
        grid[(round(y / res), round(x / res))] = (t, e, y)
    return grid


def _change(grid, a, b, km):
    """Temperature change per km across neighbours a and b, 0 unless it exceeds their summed error."""
    if a not in grid or b not in grid:
        return None
    (ta, ea, _), (tb, eb, _) = grid[a], grid[b]
    return (tb - ta) / km if abs(tb - ta) > ea + eb else 0.0


def ridge(grid, res):
    """Cells holding the local maximum of supported temperature change, with that change in °C per km."""
    strength = {}
    for (i, j), (_, _, lat) in grid.items():
        gy = _change(grid, (i - 1, j), (i + 1, j), 2 * res * KM_PER_DEGREE) or 0.0
        gx = _change(grid, (i, j - 1), (i, j + 1), 2 * res * KM_PER_DEGREE * max(math.cos(math.radians(lat)), 1e-6)) or 0.0
        if gx or gy:
            strength[(i, j)] = (math.hypot(gx, gy), abs(gx) >= abs(gy))
    kept = {}
    for (i, j), (g, along_lon) in strength.items():
        a, b = ((i, j - 1), (i, j + 1)) if along_lon else ((i - 1, j), (i + 1, j))
        if g > strength.get(a, (0,))[0] and g >= strength.get(b, (0,))[0]:
            kept[(i, j)] = g
    return kept


def _components(cells):
    left, parts = set(cells), []
    while left:
        stack, part = [left.pop()], []
        while stack:
            i, j = cell = stack.pop()
            part.append(cell)
            for di, dj in STEPS:
                if (i + di, j + dj) in left:
                    left.remove((i + di, j + dj))
                    stack.append((i + di, j + dj))
        parts.append(sorted(part))
    return parts


def _lines(part):
    """Walk the linked cells into ordered lines, starting at an end and stepping to the nearest unvisited neighbour."""
    left, lines = set(part), []
    while left:
        line = [min(sorted(left), key=lambda c: sum((c[0] + di, c[1] + dj) in left for di, dj in STEPS))]
        left.remove(line[0])
        while True:
            nxt = sorted((line[-1][0] + di, line[-1][1] + dj) for di, dj in STEPS if (line[-1][0] + di, line[-1][1] + dj) in left)
            if not nxt:
                break
            line.append(min(nxt, key=lambda c: (abs(c[0] - line[-1][0]) + abs(c[1] - line[-1][1]), c)))
            left.remove(line[-1])
        lines.append(line)
    return [line for line in lines if len(line) > 1] or lines


def fronts_for(rows, res, when):
    """The fronts of one pooled observation: line geometry, strength and the band from the analysis error."""
    grid = _grid(rows, res)
    kept = ridge(grid, res)
    out = []
    for part in _components(kept):
        if len(part) < MIN_FRONT_CELLS:
            continue
        strength = sum(kept[c] for c in part) / len(part)
        error = sum(grid[c][1] for c in part) / len(part)
        coords = [[[round(c[1] * res, 5), round(c[0] * res, 5)] for c in line] for line in _lines(part)]
        out.append({"observed_at": when.isoformat(timespec="seconds").replace("+00:00", "Z"), "cells": len(part),
                    "strength_c_per_km": round(strength, 4), "uncertainty_c": round(error, 3),
                    "band_half_width_km": round(error / strength, 3),
                    "geometry": {"type": "LineString", "coordinates": coords[0]} if len(coords) == 1
                    else {"type": "MultiLineString", "coordinates": coords}})
    out.sort(key=lambda f: (-f["cells"], repr(f["geometry"]["coordinates"])))
    for n, front in enumerate(out, 1):
        front["id"] = f"front-{n}"
    return out


def publish(region_id, tiles, health, now, product="NOAA Geo-Polar Blended night SST", credit="NOAA CoastWatch"):
    """The region's fronts document from its tiles (an iterable of (name, parsed tile)), at `now`."""
    limit = max_age_hours(health)
    usable, refused = usable_frames(list(tiles), now, limit)
    newest = max((u[0] for u in usable), default=None)
    pooled = [r for when, rows, _ in usable if when == newest for r in rows]
    resolutions = {res for when, _, res in usable if when == newest}
    if len(resolutions) > 1:
        raise SstFrontError("tiles of one observation disagree on grid resolution")
    fronts = fronts_for(pooled, resolutions.pop(), newest) if newest else []
    return {"schema_version": 1, "region_id": region_id, "layer_id": LAYER_ID, "product": product, "credit": credit,
            "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"), "max_age_hours": limit,
            "observed_at": newest.isoformat(timespec="seconds").replace("+00:00", "Z") if newest else None,
            "refused_frames": refused, "fronts": fronts}


def publish_region(region_dir, health_path, now):
    """Write `sst-fronts.json` beside the region's habitat-dynamics.json from its habitat-tiles; returns the document.

    This is what the regional habitat refresh (scripts/refresh_regions.py habitat) calls, so the file
    the client requests is part of the same release as the tiles it was found in."""
    from skippercast.platform.contracts import atomic_json
    region_dir = Path(region_dir)
    tiles = [(p.name, json.loads(p.read_text())) for p in sorted((region_dir / "habitat-tiles").glob("sst-analysis-*.json"))]
    document = publish(region_dir.name, tiles, json.loads(Path(health_path).read_text()), now)
    atomic_json(region_dir / "sst-fronts.json", document)
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description="Publish a region's offshore SST fronts")
    parser.add_argument("--region", required=True)
    parser.add_argument("--tiles", type=Path, required=True, help="folder holding the region's sst-analysis-*.json tiles")
    parser.add_argument("--health", type=Path, default=Path("catalog/feed-health.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    tiles = [(p.name, json.loads(p.read_text())) for p in sorted(args.tiles.glob("sst-analysis-*.json"))]
    document = publish(args.region, tiles, json.loads(args.health.read_text()), datetime.now(timezone.utc))
    args.out.write_text(json.dumps(document, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
