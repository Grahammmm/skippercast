"""aisstream.io: the subscription message and the message normaliser (design.md section 10).

aisstream is a free WebSocket feed (``wss://stream.aisstream.io/v0/stream``).
After connecting, the client sends one subscription message within three
seconds; the server then streams JSON envelopes::

    {"MessageType": "PositionReport",
     "MetaData": {"MMSI": ..., "ShipName": ..., "latitude": ..., "longitude": ..., "time_utc": ...},
     "Message": {"PositionReport": {...}}}

Field names follow aisstream's published models
(https://aisstream.io/documentation, github.com/aisstream/ais-message-models).
``normalise`` turns one envelope into zero or more ``AisPosition`` and
``AisStatic`` records. ``AisstreamSource.stream`` opens the WebSocket
(``fleet/ais/ws.py``, standard library), sends the subscription and yields
normalised records until the connection drops; reconnecting is the listener's
job (``fleet/ais/listener.py``). aisstream keeps no history, so ``history`` is
``Unsupported``.

Times. ``MetaData.time_utc`` is when aisstream received the message. A position
report also carries ``Timestamp``, the UTC second the transponder took its fix
(60 to 63 mean "not available"). When present, ``ts`` is that second within the
minute of receipt, moved back a minute when it would lie more than
``FUTURE_SLACK_MS`` after receipt; so the same report heard by two stations gets
the same ``(mmsi, ts, source)`` key and the store keeps it once. Otherwise, and
for static records, ``ts`` is the receipt time. A report that reaches aisstream
more than about 55 s after its fix lands in the wrong minute; such a position has
``received_at - ts > LATE_MS`` and the processor (CF-43) must treat its time as
suspect. The store keeps the earliest receipt of a key (``store.py``).

"Not available" values (SOG 102.3, COG 360, heading 511, latitude 91,
longitude 181, navigational status 15, zero dimensions, ship type 0, IMO 0)
become ``None``; a position without a usable latitude and longitude is dropped. Names and call signs lose
AIS ``@`` padding and surrounding spaces.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Iterator

from .base import AisMessage, AisPosition, AisStatic, Bbox, NotConfigured, Unsupported, valid_mmsi

__all__ = ["SOURCE_ID", "URL", "MESSAGE_TYPES", "POSITION_TYPES", "STATIC_TYPES", "MAX_MMSI_FILTER",
           "FUTURE_SLACK_MS", "LATE_MS", "SUBSCRIBE_MMSI_MIN", "AisstreamError", "MalformedMessage",
           "AisstreamSource", "subscription_message", "normalise", "parse_time_utc"]

SOURCE_ID = "aisstream"
URL = "wss://stream.aisstream.io/v0/stream"
POSITION_TYPES = ("PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport")
STATIC_TYPES = ("ShipStaticData", "StaticDataReport")
# Every type this module normalises; the region's ais.message_types must be a subset.
MESSAGE_TYPES = POSITION_TYPES + STATIC_TYPES
MAX_MMSI_FILTER = 200          # aisstream's limit on FiltersShipMMSI
SUBSCRIBE_MMSI_MIN = 100_000_000   # a filter names ship stations: 9 digits, no leading zero
FUTURE_SLACK_MS = 5_000        # receipt-clock skew tolerated before a fix second is read as last minute
# A position with received_at - ts above this may sit in the wrong minute (module docstring);
# CF-43 treats its time as suspect.
LATE_MS = 55_000

_CLASS = {"PositionReport": "A", "ShipStaticData": "A",
          "StandardClassBPositionReport": "B", "ExtendedClassBPositionReport": "B", "StaticDataReport": "B"}
_TIME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
                   r"\s*(?:([+-])(\d{2}):?(\d{2})|Z)?(?:\s+UTC)?$")


class AisstreamError(RuntimeError):
    """aisstream sent an error object (for example a rejected API key) instead of a message."""


class MalformedMessage(ValueError):
    """The text is not an aisstream envelope, or its body is missing required fields."""


def parse_time_utc(text: str) -> int:
    """``MetaData.time_utc`` (``2026-07-04 18:22:32.318353912 +0000 UTC``) as epoch milliseconds."""
    match = _TIME.match(text.strip()) if isinstance(text, str) else None
    if not match:
        raise MalformedMessage("MetaData.time_utc is not a timestamp")
    year, month, day, hour, minute, second, fraction, sign, off_h, off_m = match.groups()
    micro = int((fraction or "0").ljust(6, "0")[:6])
    moment = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), micro, timezone.utc)
    millis = int(moment.timestamp()) * 1000 + micro // 1000
    if sign:
        offset = (int(off_h) * 60 + int(off_m)) * 60_000
        millis -= offset if sign == "+" else -offset
    return millis


def subscription_message(api_key: str, bbox: Bbox, mmsis: Iterable[int] | None = None,
                         message_types: Iterable[str] | None = None) -> dict[str, Any]:
    """The first frame a client sends: one bounding box, optional MMSI and message-type filters.

    ``mmsis`` of ``None`` subscribes to every vessel in the box (discovery needs
    all statics); an empty collection is refused rather than read as "all".
    """
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("aisstream needs an API key")
    try:
        (south, west), (north, east) = bbox
        south, west, north, east = (float(v) for v in (south, west, north, east))
    except (TypeError, ValueError):
        raise ValueError("bbox must be [[lat_south, lon_west], [lat_north, lon_east]]") from None
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("bbox must be [[lat_south, lon_west], [lat_north, lon_east]] with south < north, west < east")
    message = {"APIKey": api_key, "BoundingBoxes": [[[south, west], [north, east]]]}
    if mmsis is not None:
        wanted = sorted(set(mmsis))
        if not wanted:
            raise ValueError("an MMSI filter must name at least one MMSI (pass None for every vessel)")
        if any(not valid_mmsi(m) or m < SUBSCRIBE_MMSI_MIN for m in wanted):
            raise ValueError("filter MMSIs must be 9-digit integers (100000000..999999999)")
        if len(wanted) > MAX_MMSI_FILTER:
            raise ValueError(f"aisstream accepts at most {MAX_MMSI_FILTER} MMSIs per subscription")
        message["FiltersShipMMSI"] = [f"{m:09d}" for m in wanted]
    if message_types is not None:
        types = list(dict.fromkeys(message_types))
        unknown = [t for t in types if t not in MESSAGE_TYPES]
        if unknown or not types:
            raise ValueError(f"message types must be a non-empty subset of {', '.join(MESSAGE_TYPES)}")
        message["FilterMessageTypes"] = types
    return message


def _text(value) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.replace("@", " ").split())
    return cleaned or None


def _number(value, unavailable: float | None = None, low: float | None = None, high: float | None = None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if unavailable is not None and value >= unavailable:
        return None
    if (low is not None and value < low) or (high is not None and value > high):
        return None
    return value


def _positive_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _dimensions(node) -> tuple[int | None, int | None, int | None, int | None]:
    node = node if isinstance(node, dict) else {}
    return tuple(_positive_int(node.get(key)) for key in ("A", "B", "C", "D"))


def _fix_time(received: int, second) -> int:
    """The fix time from the report's UTC second, within the minute of receipt (module docstring)."""
    if isinstance(second, bool) or not isinstance(second, int) or not 0 <= second <= 59:
        return received
    candidate = received - received % 60_000 + second * 1000
    if candidate > received + FUTURE_SLACK_MS:
        candidate -= 60_000
    return candidate


def _meta(meta: dict, key: str):
    """MetaData fields appear as ``latitude`` on the wire and ``Latitude`` in some docs; accept both."""
    if key in meta:
        return meta[key]
    return meta.get(key[:1].upper() + key[1:])


def _envelope(raw) -> dict:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="strict")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise MalformedMessage("not JSON") from None
    if not isinstance(raw, dict):
        raise MalformedMessage("not a JSON object")
    if "error" in raw and "MessageType" not in raw:
        raise AisstreamError(str(raw["error"])[:200])
    return raw


def normalise(raw, received_at: int | None = None, clock: Callable[[], datetime] | None = None,
              source: str = SOURCE_ID) -> list[AisMessage]:
    """Normalise one aisstream envelope (text, bytes or parsed dict) to records.

    Returns ``[]`` for message types this module does not handle (including the
    ``SubscriptionConfirmation`` frame) and for invalid reports. Raises
    ``AisstreamError`` on an error frame and ``MalformedMessage`` on text that
    is not an envelope. ``received_at`` (epoch ms) is used when ``time_utc`` is
    missing, else ``clock()``.
    """
    envelope = _envelope(raw)
    kind = envelope.get("MessageType")
    if kind not in MESSAGE_TYPES:
        return []
    body = (envelope.get("Message") or {}).get(kind)
    meta = envelope.get("MetaData") or {}
    if not isinstance(body, dict) or not isinstance(meta, dict):
        raise MalformedMessage(f"{kind}: missing Message.{kind} or MetaData")
    if body.get("Valid") is False:
        return []
    mmsi = body.get("UserID", _meta(meta, "MMSI"))
    if not valid_mmsi(mmsi):
        return []
    if isinstance(_meta(meta, "time_utc"), str):
        received = parse_time_utc(_meta(meta, "time_utc"))
    elif received_at is not None:
        received = int(received_at)
    else:
        received = int((clock or (lambda: datetime.now(timezone.utc)))().timestamp() * 1000)
    ais_class = _CLASS[kind]
    records: list[AisMessage] = []
    if kind in POSITION_TYPES:
        lat = _number(body.get("Latitude"), low=-90, high=90)
        lon = _number(body.get("Longitude"), low=-180, high=180)
        if lat is not None and lon is not None:
            nav = body.get("NavigationalStatus") if kind == "PositionReport" else None
            records.append(AisPosition(
                mmsi=mmsi, ts=_fix_time(received, body.get("Timestamp")), lat=float(lat), lon=float(lon),
                sog=_number(body.get("Sog"), unavailable=102.3, low=0),
                cog=_number(body.get("Cog"), unavailable=360, low=0),
                heading=_number(body.get("TrueHeading"), unavailable=360, low=0),
                nav_status=nav if isinstance(nav, int) and not isinstance(nav, bool) and 0 <= nav <= 14 else None,
                msg_type=kind, source=source, received_at=received))
    if kind in ("ShipStaticData", "ExtendedClassBPositionReport"):
        bow, stern, port, starboard = _dimensions(body.get("Dimension"))
        records.append(AisStatic(
            mmsi=mmsi, ts=received, name=_text(body.get("Name")),
            call_sign=_text(body.get("CallSign")) if kind == "ShipStaticData" else None,
            imo=_positive_int(body.get("ImoNumber")) if kind == "ShipStaticData" else None,
            ship_type=_positive_int(body.get("Type")), dim_bow=bow, dim_stern=stern, dim_port=port,
            dim_starboard=starboard, ais_class=ais_class, source=source))
    elif kind == "StaticDataReport":
        static = _static_report(body, mmsi, received, source)
        if static is not None:
            records.append(static)
    return records


def _static_report(body: dict, mmsi: int, received: int, source: str) -> AisStatic | None:
    """Message 24: part A (``PartNumber`` false) carries the name, part B type, call sign and size."""
    if body.get("PartNumber") is True:
        part = body.get("ReportB") or {}
        if not isinstance(part, dict) or part.get("Valid") is False:
            return None
        bow, stern, port, starboard = _dimensions(part.get("Dimension"))
        return AisStatic(mmsi=mmsi, ts=received, name=None, call_sign=_text(part.get("CallSign")), imo=None,
                         ship_type=_positive_int(part.get("ShipType")), dim_bow=bow, dim_stern=stern,
                         dim_port=port, dim_starboard=starboard, ais_class="B", source=source)
    part = body.get("ReportA") or {}
    if not isinstance(part, dict) or part.get("Valid") is False:
        return None
    return AisStatic(mmsi=mmsi, ts=received, name=_text(part.get("Name")), call_sign=None, imo=None, ship_type=None,
                     dim_bow=None, dim_stern=None, dim_port=None, dim_starboard=None, ais_class="B", source=source)


class AisstreamSource:
    """The aisstream ``AisSource``.

    ``connect`` (``async (url) -> socket`` with ``send``, ``recv`` and ``close``)
    defaults to ``ws.connect``; tests pass a fake. ``on_malformed`` is called
    with the exception for each frame that is not an envelope (it is skipped).
    """

    id = SOURCE_ID
    realtime = True
    url = URL

    def __init__(self, api_key: str | None = None, message_types: Iterable[str] = MESSAGE_TYPES,
                 connect: Callable[[str], Awaitable[Any]] | None = None,
                 on_malformed: Callable[[Exception], None] | None = None):
        self._api_key = api_key
        self.message_types = tuple(message_types)
        self._connect = connect
        self.on_malformed = on_malformed
        subscription_message("placeholder", ((0, 0), (1, 1)), None, self.message_types)   # validate the types now

    def __repr__(self):   # never shows the key
        return f"AisstreamSource(message_types={list(self.message_types)!r}, key={'set' if self._api_key else 'unset'})"

    def subscription(self, bbox: Bbox, mmsis: set[int] | None = None) -> dict[str, Any]:
        if not self._api_key:
            raise NotConfigured("AISSTREAM_API_KEY is not set")
        return subscription_message(self._api_key, bbox, mmsis, self.message_types)

    def normalise(self, raw, received_at: int | None = None, clock=None) -> list[AisMessage]:
        return normalise(raw, received_at=received_at, clock=clock, source=self.id)

    async def stream(self, bbox: Bbox, mmsis: set[int] | None = None) -> AsyncIterator[AisMessage]:
        """Connect, subscribe and yield records until the connection ends.

        Ends by raising: ``ws.ConnectionClosed`` (or another ``OSError``) when the
        connection drops, ``AisstreamError`` on an error frame (a rejected key).
        A malformed frame is reported to ``on_malformed`` and skipped.
        """
        subscription = json.dumps(self.subscription(bbox, mmsis))
        if self._connect is None:
            from .. import ws
            connect = ws.connect
        else:
            connect = self._connect
        socket = await connect(self.url)
        try:
            await socket.send(subscription)
            while True:
                raw = await socket.recv()
                try:
                    records = self.normalise(raw)
                except MalformedMessage as error:
                    if self.on_malformed is not None:
                        self.on_malformed(error)
                    continue
                for record in records:
                    yield record
        finally:
            await socket.close()

    def history(self, day, bbox: Bbox, mmsis: set[int] | None = None) -> Iterator[AisMessage]:
        raise Unsupported("aisstream has no replay; use the marinecadastre source for history")
