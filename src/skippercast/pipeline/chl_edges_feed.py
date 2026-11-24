"""Build a regional chlorophyll-edge document from in-memory habitat tiles."""

from collections.abc import Iterable
from datetime import datetime, timezone
import math
from typing import Any

from skippercast.pipeline.chl_edges import edges_for
from skippercast.pipeline.sst_fronts import observation_time


# Provisional clear-water floor; tune on real regional fixtures before release.
MIN_OBSERVED_FRACTION = 0.2
_FIELDS = ("latitude", "longitude", "chlorophyll_mg_m3")


class ChlEdgeFeedError(ValueError):
    """The feed cannot be built from the supplied tiles or settings."""


def _tile_parts(name: str, tile: dict[str, Any]) -> tuple[list[int], list, float]:
    fields = tile.get("fields") if isinstance(tile, dict) else None
    frames = tile.get("frames") if isinstance(tile, dict) else None
    resolution = tile.get("resolution_degrees") if isinstance(tile, dict) else None
    if not isinstance(fields, list) or any(field not in fields for field in _FIELDS) or not isinstance(frames, list):
        raise ChlEdgeFeedError(f"{name}: not a chlorophyll-observation tile")
    if (not isinstance(resolution, list) or len(resolution) != 2
            or not all(isinstance(step, (int, float)) and not isinstance(step, bool)
                       and 0 < step <= 0.25 for step in resolution)
            or resolution[0] != resolution[1]):
        raise ChlEdgeFeedError(f"{name}: unusable grid resolution")
    return [fields.index(field) for field in _FIELDS], frames, float(resolution[0])


def _rows(cells: Any, indices: list[int], where: str) -> list[list[float]]:
    if not isinstance(cells, list):
        raise ChlEdgeFeedError(f"{where}: cells is not a list")
    width = max(indices) + 1
    rows = []
    for number, cell in enumerate(cells):
        if not isinstance(cell, list) or len(cell) < width:
            raise ChlEdgeFeedError(f"{where}: cell {number} is not a list with the required fields")
        row = [cell[index] for index in indices]
        if row[2] is not None:
            rows.append(row)
    return rows


def usable_chl_frames(
    tiles: Iterable[tuple[str, dict[str, Any]]], now: datetime, max_age_hours: float,
) -> tuple[list[tuple[datetime, list[list[float]], float]], dict[str, int]]:
    """Project fresh frames to observed rows; count the same time refusals as SST fronts."""
    if (isinstance(max_age_hours, bool) or not isinstance(max_age_hours, (int, float))
            or not 0 < max_age_hours < math.inf):
        raise ChlEdgeFeedError("max_age_hours must be a positive finite number")
    usable = []
    refused = {"missing_time": 0, "unparseable_time": 0, "future": 0, "stale": 0}
    for name, tile in tiles:
        indices, frames, resolution = _tile_parts(name, tile)
        for number, frame in enumerate(frames):
            raw = frame.get("time") if isinstance(frame, dict) else None
            when = observation_time(raw)
            if raw is None:
                refused["missing_time"] += 1
            elif when is None:
                refused["unparseable_time"] += 1
            elif when > now:
                refused["future"] += 1
            elif (now - when).total_seconds() > max_age_hours * 3600:
                refused["stale"] += 1
            else:
                rows = _rows(frame.get("cells"), indices, f"{name} frame {number}")
                usable.append((when, rows, resolution))
    return usable, refused


def _observed_fraction(frames_meta: list[dict[str, Any]], newest: datetime) -> float | None:
    # Coverage is regional: tile cells alone do not account for unobserved water.
    for frame in frames_meta:
        if isinstance(frame, dict) and observation_time(frame.get("time")) == newest:
            total = frame.get("total_cells")
            if isinstance(total, int) and not isinstance(total, bool) and total > 0:
                valid = frame["valid_cells"]
                # The Chart refuses a document whose fraction is outside [0, 1]; fail at build time instead.
                if isinstance(valid, int) and not isinstance(valid, bool) and not 0 <= valid <= total:
                    raise ChlEdgeFeedError(
                        f"newest frame coverage counts contradict each other: valid_cells {valid}, "
                        f"total_cells {total}")
                return round(valid / total, 3)
            break
    return None


def _stamp(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def publish(
    region_id: str, tiles: Iterable[tuple[str, dict[str, Any]]], frames_meta: list[dict[str, Any]],
    now: datetime, max_age_hours: float, product: str, credit: str,
) -> dict[str, Any]:
    """Return the newest observation's edges or its reason for withholding them."""
    if not isinstance(frames_meta, list):
        raise ChlEdgeFeedError("frames_meta must be a list")
    usable, refused = usable_chl_frames(tiles, now, max_age_hours)
    newest = max((when for when, _, _ in usable), default=None)
    fraction = None
    edges = []
    if newest is None:
        withheld = "no-usable-frame"
    else:
        resolutions = {res for when, _, res in usable if when == newest}
        if len(resolutions) > 1:
            raise ChlEdgeFeedError("tiles of one observation disagree on grid resolution")
        fraction = _observed_fraction(frames_meta, newest)
        if fraction is not None and fraction < MIN_OBSERVED_FRACTION:
            withheld = "too-little-clear-water"
        else:
            withheld = None
            pooled = [row for when, rows, _ in usable if when == newest for row in rows]
            edges = edges_for(pooled, resolutions.pop(), newest)
    return {
        "schema_version": 1,
        "region_id": region_id,
        "layer_id": "chl-edges",
        "product": product,
        "credit": credit,
        "generated_at": _stamp(now),
        "max_age_hours": max_age_hours,
        "observed_at": _stamp(newest) if newest is not None else None,
        "observed_fraction": fraction,
        "withheld": withheld,
        "refused_frames": refused,
        "edges": edges,
    }
