"""local-nmea: AIVDM from our own receiver, normalised to the AIS source interface.

Our own receive-only VHF station (a dongle with a decoder, or a hardware AIS
receiver) sends NMEA 0183 sentences, one per line, over the LAN: ``udp://HOST:PORT``
makes this source listen on that address, ``tcp://HOST:PORT`` makes it connect to
the receiver. This is a socket to our own equipment, not a web fetch, so the host
is not restricted and ``fleet/net.py`` does not apply; any other scheme raises
``NotConfigured``. The URL comes from the ``url`` argument or the
``SKIPPERCAST_AIS_NMEA_URL`` environment variable; with neither, ``stream`` raises
``NotConfigured``.

Decoded: ``!AIVDM`` sentences with a valid checksum (at most 82 characters),
multi-fragment messages assembled by sequence id and channel, and message types
1, 2, 3 (Class A position), 5 (Class A static and voyage), 18 (Class B position),
19 (Class B extended: position and static) and 24 (Class B static; parts A and B
are not joined, each yields the fields it carries). Everything else is skipped.
``!AIVDO`` is our own ship and is always dropped and counted (``counts``).

The records are tagged ``source="local-nmea"`` and use the same names, "not
available" rules and time rules as ``aisstream.py`` (``msg_type`` is aisstream's
name for the type, so ``message_types`` filters the same way; a fix second of 60 to
63 means "not available", and a second that would lie past ``FUTURE_SLACK_MS``
after receipt is moved back a minute). Rights are ``internal-only`` until the owner
decides display (``process.SOURCE_RIGHTS``). Reconnecting is the listener's job; a
TCP peer that closes ends the stream. ``history`` is ``Unsupported``. Standard
library only.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
import os
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Iterator
from urllib.parse import urlsplit

from .aisstream import MESSAGE_TYPES, _fix_time
from .base import AisMessage, AisPosition, AisStatic, Bbox, NotConfigured, Unsupported, bbox_contains, valid_mmsi

__all__ = ["SOURCE_ID", "ENV_URL", "MAX_SENTENCE", "GROUP_TIMEOUT_MS", "MalformedSentence", "MalformedMessage",
           "Fragment", "Assembler", "LocalNmeaSource", "parse_sentence", "decode", "normalise"]

SOURCE_ID = "local-nmea"
ENV_URL = "SKIPPERCAST_AIS_NMEA_URL"
MAX_SENTENCE = 82              # NMEA 0183: including the leading "!" and the line end
GROUP_TIMEOUT_MS = 10_000      # an incomplete multi-fragment group is dropped after this

_KIND = {1: "PositionReport", 2: "PositionReport", 3: "PositionReport", 5: "ShipStaticData",
         18: "StandardClassBPositionReport", 19: "ExtendedClassBPositionReport", 24: "StaticDataReport"}
_MIN_BITS = {1: 143, 2: 143, 3: 143, 5: 270, 18: 139, 19: 301, 24: 40}


class MalformedSentence(ValueError):
    """The line is an AIVDM/AIVDO sentence that is too long, has a bad checksum or bad fields."""


class MalformedMessage(ValueError):
    """The payload is not a decodable message, or carries an unusable MMSI or position."""


@dataclass(frozen=True)
class Fragment:
    own: bool        # True for !AIVDO (own ship)
    count: int       # fragments in the message
    index: int       # 1-based
    seq: str         # sequential message id ("" for a single fragment)
    channel: str
    payload: str
    fill: int


def parse_sentence(line: str) -> Fragment | None:
    """One NMEA line as a ``Fragment``; ``None`` for a blank line or another sentence type.

    Raises ``MalformedSentence`` for an AIVDM/AIVDO line that is longer than 82
    characters, has no or a wrong checksum, or has unusable fields.
    """
    text = line.strip()
    if not text.startswith(("!AIVDM", "!AIVDO")):
        return None
    if len(text) > MAX_SENTENCE:
        raise MalformedSentence("sentence longer than 82 characters")
    body, star, given = text[1:].partition("*")
    if not star or len(given) != 2:
        raise MalformedSentence("missing checksum")
    try:
        want = int(given, 16)
    except ValueError:
        raise MalformedSentence("checksum is not hexadecimal") from None
    check = 0
    for char in body:
        check ^= ord(char)
    if check != want:
        raise MalformedSentence("bad checksum")
    fields = body.split(",")
    if len(fields) != 7:
        raise MalformedSentence("expected 7 fields")
    _, count, index, seq, channel, payload, fill = fields
    try:
        count_n, index_n, fill_n = int(count), int(index), int(fill)
    except ValueError:
        raise MalformedSentence("fragment numbers are not whole numbers") from None
    if not (1 <= index_n <= count_n <= 9) or not 0 <= fill_n <= 5 or not payload:
        raise MalformedSentence("fragment numbers out of range")
    return Fragment(own=body.startswith("AIVDO"), count=count_n, index=index_n, seq=seq, channel=channel,
                    payload=payload, fill=fill_n)


class Assembler:
    """Joins multi-fragment messages keyed by (sequence id, channel).

    ``add`` returns ``(payload, fill)`` once a message is complete, else ``None``.
    A group is dropped, silently, when it is older than ``GROUP_TIMEOUT_MS``, when a
    fragment arrives out of order or with another count, or when a later fragment
    has no group (a mixed sequence id or a lost first fragment).
    """

    def __init__(self):
        self._groups: dict[tuple[str, str], dict[str, Any]] = {}
        self.dropped = 0

    def add(self, fragment: Fragment, now_ms: int) -> tuple[str, int] | None:
        for key in [k for k, g in self._groups.items() if now_ms - g["started"] > GROUP_TIMEOUT_MS]:
            del self._groups[key]
            self.dropped += 1
        if fragment.count == 1:
            return fragment.payload, fragment.fill
        key = (fragment.seq, fragment.channel)
        group = self._groups.get(key)
        if fragment.index == 1:
            if group is not None:
                self.dropped += 1
            self._groups[key] = {"started": now_ms, "count": fragment.count, "parts": [fragment.payload]}
            return None
        if group is None:
            self.dropped += 1
            return None
        if fragment.index != len(group["parts"]) + 1 or fragment.count != group["count"]:
            del self._groups[key]
            self.dropped += 1
            return None
        group["parts"].append(fragment.payload)
        if fragment.index == fragment.count:
            del self._groups[key]
            return "".join(group["parts"]), fragment.fill
        return None


def _bits(payload: str, fill: int) -> str:
    out = []
    for char in payload:
        code = ord(char)
        if not (48 <= code <= 87 or 96 <= code <= 119):
            raise MalformedMessage("payload character outside the 6-bit armour")
        value = code - 48
        out.append(format(value - 8 if value > 40 else value, "06b"))
    bits = "".join(out)
    return bits[:-fill] if fill else bits


def _uint(bits: str, start: int, length: int) -> int:
    return int(bits[start:start + length], 2)


def _int(bits: str, start: int, length: int) -> int:
    value = _uint(bits, start, length)
    return value - (1 << length) if value >= 1 << (length - 1) else value


def _chars(bits: str, start: int, length: int) -> str | None:
    """6-bit text: values 0..31 are ``@``..``_``, 32..63 are space..``?``; ``@`` padding is removed."""
    text = []
    for at in range(start, min(start + length, len(bits) - 5), 6):
        value = _uint(bits, at, 6)
        text.append(chr(value + 64) if value < 32 else chr(value))
    cleaned = " ".join("".join(text).replace("@", " ").split())
    return cleaned or None


def decode(payload: str, fill_bits: int = 0) -> dict[str, Any]:
    """The fields of one message, raw (scaled, but "not available" values kept).

    Raises ``MalformedMessage`` for a payload that is too short for its type or has
    characters outside the 6-bit armour. Types this module does not handle give
    ``{"type": n}`` only.
    """
    bits = _bits(payload, fill_bits)
    if len(bits) < 38:
        raise MalformedMessage("payload too short")
    kind = _uint(bits, 0, 6)
    out: dict[str, Any] = {"type": kind}
    if kind not in _KIND:
        return out
    if len(bits) < _MIN_BITS[kind]:
        raise MalformedMessage(f"type {kind}: payload too short")
    out["mmsi"] = _uint(bits, 8, 30)
    if kind in (1, 2, 3):
        out.update(nav_status=_uint(bits, 38, 4), sog=_uint(bits, 50, 10), lon=_int(bits, 61, 28),
                   lat=_int(bits, 89, 27), cog=_uint(bits, 116, 12), heading=_uint(bits, 128, 9),
                   second=_uint(bits, 137, 6))
    elif kind == 5:
        out.update(imo=_uint(bits, 40, 30), call_sign=_chars(bits, 70, 42), name=_chars(bits, 112, 120),
                   ship_type=_uint(bits, 232, 8), dims=(_uint(bits, 240, 9), _uint(bits, 249, 9),
                                                         _uint(bits, 258, 6), _uint(bits, 264, 6)))
    elif kind in (18, 19):
        out.update(sog=_uint(bits, 46, 10), lon=_int(bits, 57, 28), lat=_int(bits, 85, 27), cog=_uint(bits, 112, 12),
                   heading=_uint(bits, 124, 9), second=_uint(bits, 133, 6))
        if kind == 19:
            out.update(name=_chars(bits, 143, 120), ship_type=_uint(bits, 263, 8),
                       dims=(_uint(bits, 271, 9), _uint(bits, 280, 9), _uint(bits, 289, 6), _uint(bits, 295, 6)))
    else:   # 24
        part = _uint(bits, 38, 2)
        out["part"] = part
        if part == 0:
            if len(bits) < 160:
                raise MalformedMessage("type 24 part A: payload too short")
            out["name"] = _chars(bits, 40, 120)
        elif part == 1:
            if len(bits) < 162:
                raise MalformedMessage("type 24 part B: payload too short")
            out.update(ship_type=_uint(bits, 40, 8), call_sign=_chars(bits, 90, 42),
                       dims=(_uint(bits, 132, 9), _uint(bits, 141, 9), _uint(bits, 150, 6), _uint(bits, 156, 6)))
            if out["mmsi"] // 10_000_000 == 98:    # an auxiliary craft: these bits hold the mother ship's MMSI
                out["dims"] = (0, 0, 0, 0)
        else:
            raise MalformedMessage("type 24: part number is neither A nor B")
    return out


def _positive(value) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


def normalise(decoded: dict[str, Any], received_ms: int,
              on_malformed: Callable[[Exception], None] | None = None) -> list[AisMessage]:
    """Records for one decoded message (``[]`` for an unhandled type).

    An invalid MMSI, or a position whose latitude (91) or longitude (181) is "not
    available", is reported to ``on_malformed`` and gives no position record. A
    type 19 with no position still yields its static record.
    """
    kind = decoded.get("type")
    if kind not in _KIND:
        return []

    def bad(why: str) -> None:
        if on_malformed is not None:
            on_malformed(MalformedMessage(why))

    mmsi = decoded["mmsi"]
    if not valid_mmsi(mmsi):
        bad(f"type {kind}: invalid MMSI")
        return []
    name, ais_class = _KIND[kind], ("A" if kind in (1, 2, 3, 5) else "B")
    records: list[AisMessage] = []
    if kind in (1, 2, 3, 18, 19):
        lat, lon = decoded["lat"] / 600_000, decoded["lon"] / 600_000
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            bad(f"type {kind}: position not available")
        else:
            sog, cog, heading = decoded["sog"], decoded["cog"], decoded["heading"]
            nav = decoded.get("nav_status")
            records.append(AisPosition(
                mmsi=mmsi, ts=_fix_time(received_ms, decoded["second"]), lat=lat, lon=lon,
                sog=None if sog >= 1023 else sog / 10, cog=None if cog >= 3600 else cog / 10,
                heading=None if heading >= 360 else heading,
                nav_status=nav if isinstance(nav, int) and 0 <= nav <= 14 else None,
                msg_type=name, source=SOURCE_ID, received_at=received_ms))
    if kind in (5, 19) or (kind == 24):
        bow, stern, port, starboard = (_positive(v) for v in decoded.get("dims", (0, 0, 0, 0)))
        if kind == 24 and decoded["part"] == 0:
            static = AisStatic(mmsi=mmsi, ts=received_ms, name=decoded["name"], call_sign=None, imo=None,
                               ship_type=None, dim_bow=None, dim_stern=None, dim_port=None, dim_starboard=None,
                               ais_class="B", source=SOURCE_ID)
        else:
            static = AisStatic(mmsi=mmsi, ts=received_ms, name=decoded.get("name") if kind != 24 else None,
                               call_sign=decoded.get("call_sign"), imo=_positive(decoded.get("imo")),
                               ship_type=_positive(decoded.get("ship_type")), dim_bow=bow, dim_stern=stern,
                               dim_port=port, dim_starboard=starboard, ais_class=ais_class, source=SOURCE_ID)
        records.append(static)
    return records


class LocalNmeaSource:
    """The local-nmea ``AisSource`` (module docstring).

    ``connect`` (``async (host, port) -> (reader, writer)``) replaces
    ``asyncio.open_connection`` for TCP. ``clock`` returns epoch seconds.
    ``on_malformed`` is called with the exception for each bad sentence or message
    (it is skipped). ``counts`` tallies ``own_ship_dropped``, ``malformed``,
    ``outside_bbox``, ``filtered`` and ``dropped_groups``. For UDP, ``ready`` is set
    once the socket is bound and ``local_address`` is its (host, port).
    """

    id = SOURCE_ID
    realtime = True

    def __init__(self, *, url: str | None = None, message_types: Iterable[str] | None = None,
                 connect: Callable[[str, int], Awaitable[Any]] | None = None,
                 clock: Callable[[], float] = time.time,
                 on_malformed: Callable[[Exception], None] | None = None):
        self._url = url
        types = tuple(MESSAGE_TYPES if message_types is None else message_types)
        unknown = [t for t in types if t not in MESSAGE_TYPES]
        if unknown or not types:
            raise ValueError(f"message types must be a non-empty subset of {', '.join(MESSAGE_TYPES)}")
        self.message_types = types
        self._connect = connect
        self._clock = clock
        self.on_malformed = on_malformed
        self.counts: Counter = Counter()
        self.ready = asyncio.Event()
        self.local_address: tuple[str, int] | None = None

    def __repr__(self):
        return f"LocalNmeaSource(message_types={list(self.message_types)!r})"

    def endpoint(self) -> tuple[str, str, int]:
        """``(scheme, host, port)`` from the url or the environment; ``NotConfigured`` when unusable."""
        url = self._url or os.environ.get(ENV_URL)
        if not url:
            raise NotConfigured(f"{ENV_URL} is not set (udp://HOST:PORT to listen, tcp://HOST:PORT to connect)")
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise NotConfigured("the local-nmea url is not udp://HOST:PORT or tcp://HOST:PORT") from None
        if parts.scheme not in ("udp", "tcp") or not parts.hostname or port is None:
            raise NotConfigured("the local-nmea url must be udp://HOST:PORT or tcp://HOST:PORT")
        return parts.scheme, parts.hostname, port

    def _malformed(self, error: Exception) -> None:
        self.counts["malformed"] += 1
        if self.on_malformed is not None:
            self.on_malformed(error)

    def _line(self, line: str, assembler: Assembler, bbox: Bbox, mmsis: set[int] | None) -> list[AisMessage]:
        now_ms = int(self._clock() * 1000)
        try:
            fragment = parse_sentence(line)
        except MalformedSentence as error:
            self._malformed(error)
            return []
        if fragment is None:
            return []
        if fragment.own:
            self.counts["own_ship_dropped"] += 1
            return []
        before = assembler.dropped
        whole = assembler.add(fragment, now_ms)
        self.counts["dropped_groups"] += assembler.dropped - before
        if whole is None:
            return []
        try:
            decoded = decode(*whole)
        except MalformedMessage as error:
            self._malformed(error)
            return []
        kind = _KIND.get(decoded["type"])
        if kind is None:
            return []
        if kind not in self.message_types:
            self.counts["filtered"] += 1
            return []
        records = normalise(decoded, now_ms, self._malformed)
        if mmsis is not None and decoded.get("mmsi") not in mmsis:
            return []
        if any(isinstance(r, AisPosition) and not bbox_contains(bbox, r.lat, r.lon) for r in records):
            self.counts["outside_bbox"] += 1
            return []
        return records

    async def stream(self, bbox: Bbox, mmsis: set[int] | None = None) -> AsyncIterator[AisMessage]:
        """Read sentences and yield records until cancelled or the TCP peer closes."""
        scheme, host, port = self.endpoint()
        assembler = Assembler()
        if scheme == "tcp":
            connect = self._connect or asyncio.open_connection
            reader, writer = await connect(host, port)
            self.ready.set()
            try:
                while True:
                    try:
                        raw = await reader.readline()
                    except ValueError as error:      # a line longer than the reader's limit
                        self._malformed(MalformedSentence(str(error)))
                        continue
                    if not raw:
                        return
                    for record in self._line(raw.decode("ascii", errors="replace"), assembler, bbox, mmsis):
                        yield record
            finally:
                writer.close()
        else:
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=10_000)

            class _Protocol(asyncio.DatagramProtocol):
                def datagram_received(self, data, addr):
                    try:
                        queue.put_nowait(data)
                    except asyncio.QueueFull:
                        pass

            transport, _ = await loop.create_datagram_endpoint(_Protocol, local_addr=(host, port))
            self.local_address = transport.get_extra_info("sockname")[:2]
            self.ready.set()
            try:
                while True:
                    data = await queue.get()
                    for line in data.decode("ascii", errors="replace").splitlines():
                        for record in self._line(line, assembler, bbox, mmsis):
                            yield record
            finally:
                transport.close()

    def history(self, day, bbox: Bbox, mmsis: set[int] | None = None) -> Iterator[AisMessage]:
        raise Unsupported("local-nmea has no replay; it only streams from our own receiver")
