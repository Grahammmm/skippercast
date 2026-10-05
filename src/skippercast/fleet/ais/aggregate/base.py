"""Pluggable aggregate modules over fishing events (design.md sections 5 and 11).

A module turns events into ``fleet_aggregates`` cells:
``compute(events, params) -> list[Cell]``. A module only says which cell an
event falls in (``Aggregator.bin``); ``build_cells`` does the rest the same way
for every module, so an ``h3`` module later needs no schema or rule change:

- **Whole-season cells always.** Every event counts once in its season's cell
  with ``season_part`` null, and, when the event has a part, once more in that
  part's cell. A reader wanting the season reads the null-part rows and never
  sums parts (the map API's heat default, section 14).
- **Privacy knobs** from ``thresholds.aggregate``, each a pass-through when
  null (the admin views): ``delay_hours`` leaves out events that ended less
  than that long before ``now_ms``; ``min_distinct_vessels`` drops any cell
  with fewer distinct vessels. ``resolution_m`` is the grid's cell edge.
- **Rights** of a cell are the most restrictive of its events' rights
  (``RIGHTS_ORDER``); an unknown tag is an error rather than a guess.
- **Ids** are ``sha256(region|module|params_hash|season|season_part|kind|cell)``
  cut to 32 hex characters (a null part hashes as the empty string), where ``params_hash`` covers the canonical
  ``params_json``, so different parameter sets never overwrite each other.

Pure and deterministic given ``now_ms`` and ``computed_at``; standard library only.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping, Protocol
from zoneinfo import ZoneInfo

from ...ops import id32
from ..events import Event, iso_utc

__all__ = ["RIGHTS_ORDER", "AggregateParams", "Aggregator", "Cell", "build_cells", "compute", "module",
           "most_restrictive", "register"]

# Least to most restrictive. internal-only never leaves the admin views; noaa-planning-only (MarineCadastre,
# D9) may not be sold; api-terms carries provider caching terms; facts-only and public-record allow facts.
RIGHTS_ORDER = ("public-domain", "public-record", "facts-only", "api-terms", "noaa-planning-only", "internal-only")
HOUR_MS = 3_600_000


def most_restrictive(tags: Iterable[str]) -> str:
    """The most restrictive rights tag of the inputs; ValueError on none or an unknown tag."""
    ranks = []
    for tag in tags:
        if tag not in RIGHTS_ORDER:
            raise ValueError(f"unknown rights tag {tag!r}")
        ranks.append(RIGHTS_ORDER.index(tag))
    if not ranks:
        raise ValueError("no rights to combine")
    return RIGHTS_ORDER[max(ranks)]


def _optional_number(raw: Mapping[str, Any], key: str, *, integer: bool = False, minimum: float = 0):
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (integer and value != int(value)):
        raise ValueError(f"thresholds.aggregate.{key} must be {'an integer' if integer else 'a number'} or null")
    if value < minimum:
        raise ValueError(f"thresholds.aggregate.{key} must be at least {minimum}")
    return int(value) if integer else float(value)


@dataclass(frozen=True)
class AggregateParams:
    """``thresholds.aggregate`` of a region. ``raw`` is the full mapping, stored as ``params_json``."""
    module: str
    resolution_m: float | None
    min_distinct_vessels: int | None
    delay_hours: float | None
    raw: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, thresholds: Mapping[str, Any]) -> "AggregateParams":
        """From a region's ``thresholds`` (or just its ``aggregate`` member)."""
        raw = thresholds["aggregate"] if "aggregate" in thresholds else thresholds
        plain = json.loads(json.dumps(raw, default=dict))
        return cls(module=str(plain["module"]),
                   resolution_m=_optional_number(plain, "resolution_m", minimum=1),
                   min_distinct_vessels=_optional_number(plain, "min_distinct_vessels", integer=True, minimum=1),
                   delay_hours=_optional_number(plain, "delay_hours"),
                   raw=plain)

    @classmethod
    def from_region(cls, region) -> "AggregateParams":
        """From a ``config.FleetRegion``."""
        return cls.from_mapping(region.thresholds)

    @property
    def params_json(self) -> str:
        return json.dumps(self.raw, sort_keys=True, separators=(",", ":"))

    @property
    def params_hash(self) -> str:
        return hashlib.sha256(self.params_json.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Cell:
    """One ``fleet_aggregates`` row."""
    id: str
    region: str
    module: str
    params_json: str
    cell_id: str
    lat: float
    lon: float
    season: str
    season_part: str | None
    kind: str
    vessels_n: int
    events_n: int
    dwell_min: int
    first_date: str | None
    last_date: str | None
    rights: str
    computed_at: str

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class Aggregator(Protocol):
    name: str

    def bin(self, event: Event, params: AggregateParams) -> tuple[str, float, float]:
        """(cell_id, centre lat, centre lon) of the cell holding the event's point."""
        ...

    def compute(self, events: Iterable[Event], params: AggregateParams, **options) -> list[Cell]: ...


_MODULES: dict[str, Aggregator] = {}


def register(aggregator: Aggregator) -> Aggregator:
    _MODULES[aggregator.name] = aggregator
    return aggregator


def module(name: str) -> Aggregator:
    """The registered aggregate module called ``name`` (importing the built-in ones on first use)."""
    if name not in _MODULES:
        from . import grid  # noqa: F401  (registers itself)
    try:
        return _MODULES[name]
    except KeyError:
        raise ValueError(f"unknown aggregate module {name!r}") from None


def compute(events: Iterable[Event], params: AggregateParams, **options) -> list[Cell]:
    """Run the module ``params.module`` names (see ``build_cells`` for ``options``)."""
    return module(params.module).compute(events, params, **options)


def _local_date(ms: int, zone: ZoneInfo) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=zone).date().isoformat()


def build_cells(aggregator: Aggregator, events: Iterable[Event], params: AggregateParams, *,
                now_ms: int | None = None, tz: str = "UTC", computed_at: str | None = None) -> list[Cell]:
    """Bin events with ``aggregator`` and build cells under the shared rules (module docstring).

    ``now_ms`` is required when ``delay_hours`` is set (the delay fails closed
    rather than publishing fresh events). ``tz`` is the region's timezone for
    ``first_date`` and ``last_date``. ``computed_at`` defaults to ``now_ms``,
    else the clock.
    """
    if params.module != aggregator.name:
        raise ValueError(f"params are for module {params.module!r}, not {aggregator.name!r}")
    if params.delay_hours is not None and now_ms is None:
        raise ValueError("delay_hours is set: now_ms is required")
    zone = ZoneInfo(tz)
    if computed_at is None:
        computed_at = iso_utc(now_ms) if now_ms is not None else iso_utc(round(datetime.now(timezone.utc).timestamp() * 1000))
    cutoff = None if params.delay_hours is None else now_ms - params.delay_hours * HOUR_MS

    groups: dict[tuple, list[Event]] = defaultdict(list)
    centres: dict[str, tuple[float, float]] = {}
    for event in events:
        if cutoff is not None and event.ended_at > cutoff:
            continue
        cell_id, lat, lon = aggregator.bin(event, params)
        centres[cell_id] = (lat, lon)
        groups[(event.region, event.season, None, event.kind, cell_id)].append(event)
        if event.season_part is not None:
            groups[(event.region, event.season, event.season_part, event.kind, cell_id)].append(event)

    cells = []
    for (region, season, part, kind, cell_id), members in groups.items():
        vessels = {e.vessel_id for e in members}
        if params.min_distinct_vessels is not None and len(vessels) < params.min_distinct_vessels:
            continue
        lat, lon = centres[cell_id]
        cells.append(Cell(
            id=id32(region, params.module, params.params_hash, season, part or "", kind, cell_id),
            region=region, module=params.module, params_json=params.params_json, cell_id=cell_id,
            lat=round(lat, 6), lon=round(lon, 6), season=season, season_part=part, kind=kind,
            vessels_n=len(vessels), events_n=len(members), dwell_min=sum(e.dwell_min for e in members),
            first_date=_local_date(min(e.started_at for e in members), zone),
            last_date=_local_date(max(e.ended_at for e in members), zone),
            rights=most_restrictive(e.rights for e in members), computed_at=computed_at))
    cells.sort(key=lambda c: (c.region, c.season, c.season_part or "", c.kind, c.cell_id))
    return cells
