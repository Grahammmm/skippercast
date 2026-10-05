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


@dataclass(frozen=True)
class Candidate:
    """A vessel as one source lists it: names, port and landing hints, stable keys and facts."""
    source_id: str
    name: str
    port_hint: str | None = None
    landing_hint: str | None = None
    keys: Mapping[str, str] = field(default_factory=dict)  # uscg_doc, call_sign, mmsi, state_reg, hull_id
    facts: tuple[Fact, ...] = ()


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
