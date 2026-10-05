"""The adapter contract (design section 6).

An adapter turns one source binding into ``Candidate``s (discover) or ``Fact``s
(enrich). It fetches only through ``ctx.net`` (``fleet.net.FleetSession``) and
never writes to a sink; ingest turns its output into sink operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, Mapping, Protocol

from ..ops import departure_id, fact_id, offering_id, value_key

if TYPE_CHECKING:  # config imports this package for the registry; keep the runtime import one-way
    from ..config import Binding, FleetRegion
    from ..net import FleetSession


@dataclass(frozen=True)
class Fact:
    """One observed value with the profile schema's provenance fields."""
    field: str
    value: Any
    source_id: str
    source_url: str
    method: str
    confidence: float
    rights: str
    retrieved_at: str
    flags: tuple[str, ...] = ()  # needs a person before it may win (e.g. a webmail address); ingest opens a review

    def as_dict(self) -> dict:
        row = {"field": self.field, "value": self.value, "source_id": self.source_id, "source_url": self.source_url,
               "method": self.method, "confidence": self.confidence, "rights": self.rights,
               "retrieved_at": self.retrieved_at}
        if self.flags:
            row["flags"] = list(self.flags)
        return row


def offering_name_norm(name: str) -> str:
    """The offering id's name part: upper case, A-Z and 0-9 only (the fleet_name_screen rule)."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


@dataclass(frozen=True)
class Offering:
    """A trip type as one source lists it; ``op`` makes its ``offering.upsert`` once the vessel id is known."""
    name: str
    trip_type: str
    facts: tuple[Fact, ...]                # the facts it was read from (source_fact_ids_json)
    price_cents: int | None = None
    price_basis: str | None = None         # per-person or private
    currency: str = "USD"
    duration_h: float | None = None
    capacity: int | None = None
    departs_local: str | None = None       # HH:MM
    days: tuple[str, ...] | None = None
    season_from: str | None = None         # MM-DD
    season_to: str | None = None

    def id(self, vessel_id: str) -> str:
        season = f"{self.season_from}/{self.season_to}" if self.season_from and self.season_to else ""
        return offering_id(vessel_id, offering_name_norm(self.name), season)

    def op(self, vessel_id: str, seen_at: str) -> dict:
        facts = sorted({fact_id(vessel_id, f.field, f.source_id, f.source_url, value_key(f.value)) for f in self.facts})
        return {"op": "offering.upsert", "id": self.id(vessel_id), "seen_at": seen_at, "vessel_id": vessel_id,
                "name": self.name, "trip_type": self.trip_type, "duration_h": self.duration_h,
                "price_cents": self.price_cents, "price_basis": self.price_basis, "capacity": self.capacity,
                "currency": self.currency, "departs_local": self.departs_local,
                "days_json": list(self.days) if self.days else None, "season_from": self.season_from,
                "season_to": self.season_to, "status": "active", "source_fact_ids_json": facts}

    def as_dict(self) -> dict:
        return {"name": self.name, "trip_type": self.trip_type, "facts": [f.as_dict() for f in self.facts],
                "price_cents": self.price_cents, "price_basis": self.price_basis, "currency": self.currency,
                "duration_h": self.duration_h, "capacity": self.capacity, "departs_local": self.departs_local,
                "days": list(self.days) if self.days is not None else None, "season_from": self.season_from,
                "season_to": self.season_to}


@dataclass(frozen=True)
class Departure:
    """One dated trip of an offering where a schedule is published (``fleet_departures``)."""
    offering: Offering
    date: str                              # YYYY-MM-DD
    departs_local: str | None
    price_cents: int | None
    load_text: str | None                  # as published
    source_url: str
    retrieved_at: str

    def op(self, vessel_id: str) -> dict:
        offering = self.offering.id(vessel_id)
        return {"op": "departure.upsert", "id": departure_id(offering, self.date, self.departs_local or ""),
                "offering_id": offering, "vessel_id": vessel_id, "date": self.date,
                "departs_local": self.departs_local, "price_cents": self.price_cents, "load_text": self.load_text,
                "source_url": self.source_url, "retrieved_at": self.retrieved_at}

    def as_dict(self) -> dict:
        return {"offering": self.offering.as_dict(), "date": self.date, "departs_local": self.departs_local,
                "price_cents": self.price_cents, "load_text": self.load_text, "source_url": self.source_url,
                "retrieved_at": self.retrieved_at}


@dataclass(frozen=True)
class Candidate:
    """A vessel as one source lists it: names, port and landing hints, stable keys and facts.

    ``offerings`` and ``departures`` become operations once resolve has assigned the vessel.
    """
    source_id: str
    name: str
    port_hint: str | None = None
    landing_hint: str | None = None
    keys: Mapping[str, str] = field(default_factory=dict)  # uscg_doc, call_sign, mmsi, state_reg, hull_id
    facts: tuple[Fact, ...] = ()
    # The fingerprint field: a stable per-record id within the source (usually the record's own URL). The resolver's
    # review fingerprint is source_id|record_id, so a decided merge review follows the record across runs. Unset, the
    # resolver falls back to source_id|name_norm|port_hint|first cleaned source URL.
    record_id: str | None = None
    offerings: tuple[Offering, ...] = ()
    departures: tuple[Departure, ...] = ()

    def as_dict(self) -> dict:
        return {"source_id": self.source_id, "name": self.name, "port_hint": self.port_hint,
                "landing_hint": self.landing_hint, "keys": dict(self.keys), "facts": [f.as_dict() for f in self.facts],
                "record_id": self.record_id, "offerings": [o.as_dict() for o in self.offerings],
                "departures": [d.as_dict() for d in self.departures]}


@dataclass
class RunContext:
    region: "FleetRegion"
    net: "FleetSession"
    run_dir: Path
    clock: Callable[[], str]  # ISO-8601 UTC timestamp


class Adapter(Protocol):
    id: str
    kind: Literal["discover", "enrich", "both"]

    def discover(self, binding: "Binding", ctx: RunContext) -> Iterable[Candidate]: ...

    def enrich(self, vessel: Mapping[str, Any], binding: "Binding", ctx: RunContext) -> Iterable[Fact]: ...
