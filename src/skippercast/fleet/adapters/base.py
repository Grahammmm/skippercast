"""The adapter contract (design section 6).

An adapter turns one source binding into ``Candidate``s (discover) or ``Fact``s
(enrich). It fetches only through ``ctx.net`` (``fleet.net.FleetSession``) and
never writes to a sink; ingest turns its output into sink operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, Mapping, Protocol

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


@dataclass(frozen=True)
class Candidate:
    """A vessel as one source lists it: names, port and landing hints, stable keys and facts."""
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

    def as_dict(self) -> dict:
        return {"source_id": self.source_id, "name": self.name, "port_hint": self.port_hint,
                "landing_hint": self.landing_hint, "keys": dict(self.keys), "facts": [f.as_dict() for f in self.facts]}


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
