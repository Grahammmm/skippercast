"""Fishing events and segment geometry from a classified trip (design.md sections 5 and 11).

One event per fishing segment: ``fishing-drift`` becomes a ``drift-anchor``
event, ``fishing-troll`` a ``troll`` event. Its point is the component-wise
median of the segment's fixes and its ``radius_m`` the 90th-percentile
(nearest-rank) distance from that point. Fixes inside any harbor geofence are
left out of both: ``classify`` merges a short dip into a geofence into the
surrounding fishing run, and that dip must not drag the point into the harbor.
A fishing segment with no fix outside every geofence yields no event.

Every event carries ``basis = inferred-from-movement`` (D10): it marks where a
boat stopped or trolled, never a catch location. ``species_json`` stays null
until catch-log pairing.

Segment geometry is the segment's fixes simplified with Douglas-Peucker at
``thresholds.activity.simplify_tolerance_m`` and encoded as a Google polyline
(``simplify``); every segment kind keeps its geometry except ``gap``, which has
no fixes.

Ids follow design.md section 5: trips ``sha256(mmsi|departed_at|source)``,
segments ``sha256(trip_id|seq)``, events ``sha256(trip_id|started_at|kind)``,
each cut to 32 hex characters, with times as ISO-8601 UTC milliseconds. Pure
functions, standard library only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import math
from statistics import median
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..ops import id32
from .classify import Classification, Segment
from .segment import BASIS, ActivityThresholds, Geofence, distance_nm, port_at
from .simplify import simplify_encode

__all__ = ["BASIS", "EVENT_KINDS", "Event", "TripContext", "build_events", "event_id", "from_iso", "iso_utc",
           "median_point", "p90_radius_m", "season_of", "segment_geometry", "segment_id", "simplify_tolerance_m",
           "trip_id"]

EVENT_KINDS = {"fishing-drift": "drift-anchor", "fishing-troll": "troll"}
METRES_PER_NM = 1852.0


# ---------------------------------------------------------------- ids and times

def iso_utc(ms: int) -> str:
    """Epoch milliseconds as ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (the registry's ``iso_ms`` form)."""
    moment = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ms) % 1000:03d}Z"


def from_iso(text: str) -> int:
    """Epoch milliseconds of an ISO-8601 time (``Z`` or an offset)."""
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError(f"{text!r}: time without a zone")
    return round(moment.timestamp() * 1000)


def trip_id(mmsi: int | str, departed_at_ms: int, source: str) -> str:
    return id32(str(mmsi), iso_utc(departed_at_ms), source)


def segment_id(trip: str, seq: int) -> str:
    return id32(trip, str(seq))


def event_id(trip: str, started_at_ms: int, kind: str) -> str:
    return id32(trip, iso_utc(started_at_ms), kind)


def season_of(ms: int, tz: str, parts: Mapping[str, Sequence[int]]) -> tuple[str, str | None]:
    """(season year, season part id) of a moment in the region's timezone; the part is None when no part holds the month."""
    local = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(tz))
    part = next((pid for pid, months in parts.items() if local.month in months), None)
    return str(local.year), part


def simplify_tolerance_m(thresholds: ActivityThresholds) -> float:
    """``thresholds.activity.simplify_tolerance_m`` from the region config."""
    value = thresholds.raw.get("simplify_tolerance_m")
    if value is None:
        raise ValueError("thresholds.activity.simplify_tolerance_m is missing from the region config")
    return float(value)


# ---------------------------------------------------------------- geometry

def segment_geometry(segment: Segment, tolerance_m: float) -> str | None:
    """Encoded polyline (precision 5) of the segment's fixes after Douglas-Peucker; None for a ``gap``."""
    return simplify_encode([(p.lat, p.lon) for p in segment.positions], tolerance_m)


def median_point(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Component-wise median (lat, lon)."""
    if not points:
        raise ValueError("median of no points")
    return median(p[0] for p in points), median(p[1] for p in points)


def p90_radius_m(points: Sequence[tuple[float, float]], centre: tuple[float, float]) -> float:
    """90th-percentile (nearest-rank) great-circle distance in metres from ``centre``."""
    if not points:
        raise ValueError("radius of no points")
    distances = sorted(distance_nm(centre[0], centre[1], lat, lon) * METRES_PER_NM for lat, lon in points)
    return distances[max(0, math.ceil(0.9 * len(distances)) - 1)]


# ---------------------------------------------------------------- events

@dataclass(frozen=True)
class TripContext:
    """What an event inherits from its trip and vessel (the processor knows these; classify does not)."""
    trip_id: str
    vessel_id: str
    region: str
    source: str
    rights: str
    season: str
    season_part: str | None = None
    port_id: str | None = None
    vessel_class: str | None = None
    trip_type: str | None = None


@dataclass(frozen=True)
class Event:
    """One ``fleet_events`` row. Times are epoch milliseconds here and ISO strings in ``as_row``."""
    id: str
    trip_id: str
    segment_id: str
    vessel_id: str
    region: str
    kind: str
    lat: float
    lon: float
    radius_m: float
    started_at: int
    ended_at: int
    dwell_min: int
    port_id: str | None
    vessel_class: str | None
    trip_type: str | None
    season: str
    season_part: str | None
    source: str
    rights: str
    classifier_version: str
    species_json: str | None = None
    basis: str = BASIS

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["started_at"], row["ended_at"] = iso_utc(self.started_at), iso_utc(self.ended_at)
        return row

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Event":
        """From a ``fleet_events`` row (ISO times), e.g. a season's events read back for aggregation."""
        values = {f.name: row.get(f.name) for f in fields(cls) if f.name in row}
        for name in ("started_at", "ended_at"):
            if isinstance(values.get(name), str):
                values[name] = from_iso(values[name])
        values.setdefault("basis", BASIS)
        return cls(**values)


def build_events(classification: Classification, ports: Sequence[Geofence], context: TripContext) -> list[Event]:
    """One event per fishing segment of the classified trip (module docstring)."""
    events = []
    for segment in classification.segments:
        kind = EVENT_KINDS.get(segment.kind)
        if kind is None:
            continue
        points = [(p.lat, p.lon) for p in segment.positions if port_at(ports, p.lat, p.lon) is None]
        if not points:
            continue
        lat, lon = median_point(points)
        events.append(Event(
            id=event_id(context.trip_id, segment.started_at, kind),
            trip_id=context.trip_id,
            segment_id=segment_id(context.trip_id, segment.seq),
            vessel_id=context.vessel_id,
            region=context.region,
            kind=kind,
            lat=round(lat, 6),
            lon=round(lon, 6),
            radius_m=round(p90_radius_m(points, (lat, lon)), 1),
            started_at=segment.started_at,
            ended_at=segment.ended_at,
            dwell_min=round(segment.minutes),
            port_id=context.port_id,
            vessel_class=context.vessel_class,
            trip_type=context.trip_type,
            season=context.season,
            season_part=context.season_part,
            source=context.source,
            rights=context.rights,
            classifier_version=classification.classifier_version,
        ))
    return events
