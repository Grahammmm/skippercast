"""Trip segmentation over one vessel's AIS positions (design.md section 11, D10).

Pure functions, standard library only. The input is one MMSI's ``AisPosition``
records from the raw store; the output is a list of ``Trip`` records that
``classify`` then cuts into segments. Nothing here reads files, the network or
the clock, so the same positions and thresholds always give the same trips.

Rules (thresholds come from ``regions/<id>/fleet.json`` ``thresholds.activity``,
loaded with ``skippercast.fleet.config``):

- **In port** means inside any harbor geofence of the region (even-odd ray
  casting from ``config.point_in_polygon``; no GIS dependency).
- A trip **departs** at the first position outside every geofence after the
  vessel has been in port, and **returns** at the first position of a stay
  inside any geofence that is held for ``in_port_debounce_min`` (the next
  position outside comes at least that long after the first one inside, or
  the data ends inside after that long). A shorter dip into a geofence does
  not end the trip; ``classify`` labels it ``in-port``.
- If the positions start at sea the trip has no departure port and is emitted
  ``truncated`` (its start is unknown).
- A silence at sea longer than ``gap_split_hours`` after which the vessel is next
  seen in port closes the trip at its last position before the silence, as
  ``truncated``. Shorter silences stay inside the trip; ``classify`` turns any
  over ``gap_unknown_min`` into a ``gap`` segment.
- A trip still at sea when the positions end is ``open``, or ``truncated`` (ended
  at its last position) when it began more than ``max_open_trip_hours[class]``
  before ``now_ms``.
- Closed and truncated trips shorter than ``min_trip_minutes`` or never more than
  ``min_trip_offshore_nm`` from every geofence are dropped (a harbor shuffle).
  Open trips are kept: they may still grow.

Positions whose ``received_at - ts`` exceeds ``LATE_MS`` (design section 10) may
sit in the wrong minute. Their place is still used for geofence containment and
offshore distance, but ``classify`` keeps them out of derived speed, heading and
straightness. ``is_suspect`` is the single test.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .sources.aisstream import LATE_MS
from .sources.base import AisPosition

__all__ = ["BASIS", "LATE_MS", "TRIP_STATUSES", "ActivityThresholds", "Geofence", "Trip", "distance_nm",
           "is_suspect", "offshore_nm", "port_at", "prepare", "split_trips"]

# Every trip, segment and event derived here describes movement, never a confirmed catch (D10).
BASIS = "inferred-from-movement"
TRIP_STATUSES = ("open", "closed", "truncated")
EARTH_RADIUS_NM = 3440.065
MINUTE_MS = 60_000


class Geofence(Protocol):
    """What segmentation needs of a port: ``config.Port`` satisfies it."""
    id: str
    geofence: Sequence[tuple[float, float]]

    def contains(self, lat: float, lon: float) -> bool: ...


@dataclass(frozen=True)
class ActivityThresholds:
    """``thresholds.activity`` of a fleet region, typed. ``raw`` keeps the full mapping for hashing."""
    in_port_debounce_min: float
    min_trip_minutes: float
    min_trip_offshore_nm: float
    gap_unknown_min: float
    gap_split_hours: float
    max_open_trip_hours: Mapping[str, float]
    window_min: float
    min_segment_minutes: float
    drift_max_sog_kn: float
    drift_min_minutes: float
    troll_min_sog_kn: float
    troll_max_sog_kn: float
    troll_max_straightness: float
    troll_min_heading_variance: float
    troll_min_minutes: float
    raw: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, thresholds: Mapping[str, Any]) -> "ActivityThresholds":
        """From a region's ``thresholds`` (or just its ``activity`` member)."""
        activity = thresholds["activity"] if "activity" in thresholds else thresholds
        drift, troll = activity["drift"], activity["troll"]
        return cls(
            in_port_debounce_min=float(activity["in_port_debounce_min"]),
            min_trip_minutes=float(activity["min_trip_minutes"]),
            min_trip_offshore_nm=float(activity["min_trip_offshore_nm"]),
            gap_unknown_min=float(activity["gap_unknown_min"]),
            gap_split_hours=float(activity["gap_split_hours"]),
            max_open_trip_hours={str(k): float(v) for k, v in activity["max_open_trip_hours"].items()},
            window_min=float(activity["window_min"]),
            min_segment_minutes=float(activity["min_segment_minutes"]),
            drift_max_sog_kn=float(drift["max_sog_kn"]),
            drift_min_minutes=float(drift["min_minutes"]),
            troll_min_sog_kn=float(troll["min_sog_kn"]),
            troll_max_sog_kn=float(troll["max_sog_kn"]),
            troll_max_straightness=float(troll["max_straightness"]),
            troll_min_heading_variance=float(troll["min_heading_variance"]),
            troll_min_minutes=float(troll["min_minutes"]),
            raw=_plain(activity),
        )

    @classmethod
    def from_region(cls, region) -> "ActivityThresholds":
        """From a ``config.FleetRegion``."""
        return cls.from_mapping(region.thresholds)

    def max_open_ms(self, vessel_class: str | None) -> float:
        """Age after which an open trip is truncated; the longest class limit when the class is unknown."""
        hours = self.max_open_trip_hours.get(vessel_class) if vessel_class else None
        if hours is None:
            hours = max(self.max_open_trip_hours.values())
        return hours * 3_600_000


def _plain(node):
    """A JSON-ready copy of a (possibly frozen) mapping."""
    if isinstance(node, Mapping):
        return {str(k): _plain(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_plain(v) for v in node]
    return node


@dataclass(frozen=True)
class Trip:
    """One departure from port to return (or truncation). Times are epoch milliseconds (UTC).

    ``positions`` run from the departure fix up to, not including, the return
    fix; ``returned_at`` is the return fix's time (or the last position for an
    open or truncated trip), so a trip covers ``[departed_at, returned_at]``.
    """
    mmsi: int
    depart_port_id: str | None
    return_port_id: str | None
    departed_at: int
    returned_at: int
    status: str
    positions: tuple[AisPosition, ...]
    distance_nm: float
    max_offshore_nm: float
    basis: str = BASIS

    @property
    def duration_min(self) -> float:
        return (self.returned_at - self.departed_at) / MINUTE_MS


# ---------------------------------------------------------------- geometry

def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def port_at(ports: Iterable[Geofence], lat: float, lon: float) -> str | None:
    """Id of the first port (in region order) whose geofence holds the point, else None."""
    for port in ports:
        if port.contains(lat, lon):
            return port.id
    return None


def _segment_distance_nm(lat: float, lon: float, ring) -> float:
    """Distance from a point to a ring's boundary on a local equirectangular projection."""
    kx = math.cos(math.radians(lat)) * 60.0  # nm per degree of longitude here
    best = math.inf
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        ax, ay = (x1 - lon) * kx, (y1 - lat) * 60.0
        bx, by = (x2 - lon) * kx, (y2 - lat) * 60.0
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
        px, py = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(px, py))
    return best


def offshore_nm(ports: Sequence[Geofence], lat: float, lon: float) -> float:
    """Distance from the point to the nearest geofence in nautical miles; 0 inside one."""
    if not ports:
        return 0.0
    if port_at(ports, lat, lon) is not None:
        return 0.0
    return min(_segment_distance_nm(lat, lon, port.geofence) for port in ports)


# ---------------------------------------------------------------- positions

def is_suspect(position: AisPosition) -> bool:
    """True when the report reached the source more than ``LATE_MS`` after its fix, so its minute is uncertain."""
    return position.received_at - position.ts > LATE_MS


def _opt(value) -> tuple[int, float]:
    """Sort key for an optional number: None first, then by value."""
    return (0, 0.0) if value is None else (1, float(value))


def _order(p: AisPosition):
    """A total order over fixes, so duplicates of one ``ts`` resolve the same way in any input order."""
    return (p.ts, p.received_at, p.source, p.lat, p.lon, _opt(p.sog), _opt(p.cog), _opt(p.heading),
            _opt(p.nav_status), p.msg_type)


def prepare(positions: Iterable[AisPosition]) -> list[AisPosition]:
    """One MMSI's positions sorted by time, one per ``ts`` (earliest receipt wins; ties break on every field).

    Raises ValueError when the positions belong to more than one MMSI.
    """
    rows = sorted(positions, key=_order)
    if len({p.mmsi for p in rows}) > 1:
        raise ValueError("split_trips takes one MMSI's positions at a time")
    out: list[AisPosition] = []
    for row in rows:
        if out and out[-1].ts == row.ts:
            continue
        out.append(row)
    return out


# ---------------------------------------------------------------- trips

def _make_trip(positions, ports, depart_port, return_port, departed_at, returned_at, status) -> Trip:
    distance = sum(distance_nm(a.lat, a.lon, b.lat, b.lon) for a, b in zip(positions, positions[1:]))
    offshore = max((offshore_nm(ports, p.lat, p.lon) for p in positions), default=0.0)
    return Trip(mmsi=positions[0].mmsi, depart_port_id=depart_port, return_port_id=return_port,
                departed_at=departed_at, returned_at=returned_at, status=status, positions=tuple(positions),
                distance_nm=round(distance, 6), max_offshore_nm=round(offshore, 6))


def _keep(trip: Trip, th: ActivityThresholds) -> bool:
    if trip.status == "open":
        return True
    return trip.duration_min >= th.min_trip_minutes and trip.max_offshore_nm > th.min_trip_offshore_nm


def split_trips(positions: Iterable[AisPosition], ports: Sequence[Geofence], thresholds: ActivityThresholds, *,
                vessel_class: str | None = None, now_ms: int | None = None) -> list[Trip]:
    """Cut one MMSI's positions into trips (module docstring). ``now_ms`` defaults to the last position's time."""
    rows = prepare(positions)
    if not rows:
        return []
    ports = tuple(ports)
    th = thresholds
    debounce_ms = th.in_port_debounce_min * MINUTE_MS
    split_ms = th.gap_split_hours * 3_600_000
    now = rows[-1].ts if now_ms is None else now_ms
    where = [port_at(ports, p.lat, p.lon) for p in rows]

    trips: list[Trip] = []
    n = len(rows)
    i = 0
    # Positions before the first one in port belong to a trip whose start is unknown.
    in_port = where[0] is not None
    depart_port: str | None = None
    current: list[AisPosition] = []
    started_unknown = not in_port
    last_port = where[0]
    while i < n:
        p, port = rows[i], where[i]
        if in_port:
            if port is None:
                in_port, current, depart_port, started_unknown = False, [p], last_port, False
            else:
                last_port = port
            i += 1
            continue
        # At sea (in a trip).
        prev = current[-1] if current else None
        if port is not None:
            if prev is not None and p.ts - prev.ts > split_ms:
                # Long silence, next seen in port: close at the last position, truncated.
                trips.append(_make_trip(current, ports, depart_port, None, current[0].ts, prev.ts, "truncated"))
                in_port, current, last_port = True, [], port
                i += 1
                continue
            # A stay inside: held for the debounce?
            j = i
            while j + 1 < n and where[j + 1] is not None:
                j += 1
            held_until = rows[j + 1].ts if j + 1 < n else rows[j].ts
            if held_until - p.ts >= debounce_ms:
                status = "truncated" if started_unknown else "closed"
                start = current[0].ts if current else p.ts
                if current:
                    trips.append(_make_trip(current, ports, depart_port, port, start, p.ts, status))
                in_port, current, last_port = True, [], where[j]
                i = j + 1
                continue
            if j + 1 >= n:
                # The data ends inside before the debounce: the trip is still open.
                current.extend(rows[i:j + 1])
                i = j + 1
                continue
            current.extend(rows[i:j + 1])
            i = j + 1
            continue
        current.append(p)
        i += 1

    if not in_port and current:
        status = "truncated" if started_unknown or now - current[0].ts > th.max_open_ms(vessel_class) else "open"
        trips.append(_make_trip(current, ports, depart_port, None, current[0].ts, current[-1].ts, status))
    return [trip for trip in trips if _keep(trip, th)]
