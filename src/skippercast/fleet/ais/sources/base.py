"""The AIS source interface and the normalised records every source yields (design.md section 10).

A source turns a provider's messages into ``AisPosition`` and ``AisStatic``
records, both tagged with the source id, so the store, listener and processor
never see a provider format. ``stream`` is the live feed (aisstream, a paid
Datalastic plan); ``history`` replays one UTC day (MarineCadastre). A source
that cannot do one of them raises ``Unsupported``; one that needs an owner
decision or a key before it can run raises ``NotConfigured``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import AsyncIterator, Iterator, Protocol, Union, runtime_checkable

__all__ = ["Bbox", "AisPosition", "AisStatic", "AisMessage", "AisSource", "NotConfigured", "Unsupported",
           "MMSI_MIN", "MMSI_MAX", "valid_mmsi", "bbox_of", "bbox_contains"]

# [[lat_south, lon_west], [lat_north, lon_east]], the region file's ``ais.bbox`` order.
Bbox = tuple[tuple[float, float], tuple[float, float]]

MMSI_MIN = 1
MMSI_MAX = 999_999_999


class NotConfigured(RuntimeError):
    """The source is not set up (no paid plan, no key); the owner must decide before it can run."""


class Unsupported(NotImplementedError):
    """The source cannot do this at all (aisstream has no replay, MarineCadastre is not live)."""


@dataclass(frozen=True)
class AisPosition:
    """One position report. ``ts`` and ``received_at`` are epoch milliseconds (UTC).

    ``sog`` (knots), ``cog`` (degrees true), ``heading`` (degrees true) and
    ``nav_status`` are ``None`` when the transponder reported "not available".
    """
    mmsi: int
    ts: int
    lat: float
    lon: float
    sog: float | None
    cog: float | None
    heading: int | None
    nav_status: int | None
    msg_type: str
    source: str
    received_at: int


@dataclass(frozen=True)
class AisStatic:
    """One static or voyage record; fields the message does not carry are ``None``.

    ``dim_*`` are metres from the GPS antenna (AIS dimension A, B, C, D).
    ``ais_class`` is ``"A"`` or ``"B"``.
    """
    mmsi: int
    ts: int
    name: str | None
    call_sign: str | None
    imo: int | None
    ship_type: int | None
    dim_bow: int | None
    dim_stern: int | None
    dim_port: int | None
    dim_starboard: int | None
    ais_class: str
    source: str


AisMessage = Union[AisPosition, AisStatic]


def valid_mmsi(value) -> bool:
    """True for an integer MMSI in 1..999,999,999 (booleans are not MMSIs)."""
    return isinstance(value, int) and not isinstance(value, bool) and MMSI_MIN <= value <= MMSI_MAX


def bbox_of(ais) -> Bbox:
    """The ``Bbox`` of a ``config.Ais`` (or anything with south, west, north and east)."""
    return ((ais.south, ais.west), (ais.north, ais.east))


def bbox_contains(bbox: Bbox, lat: float, lon: float) -> bool:
    (south, west), (north, east) = bbox
    return south <= lat <= north and west <= lon <= east


@runtime_checkable
class AisSource(Protocol):
    """A provider of normalised AIS records (design.md section 10)."""

    id: str          # "aisstream", "datalastic", "marinecadastre"
    realtime: bool   # True when ``stream`` is the source's purpose

    def stream(self, bbox: Bbox, mmsis: set[int] | None) -> AsyncIterator[AisMessage]:
        """Live records inside ``bbox`` (only ``mmsis`` when given), until cancelled."""
        ...

    def history(self, day: date, bbox: Bbox, mmsis: set[int] | None) -> Iterator[AisMessage]:
        """Every record for one UTC ``day`` inside ``bbox`` (only ``mmsis`` when given)."""
        ...
