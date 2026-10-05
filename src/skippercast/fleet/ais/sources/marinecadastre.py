"""NOAA MarineCadastre daily AIS files: history only, for the backfill (design.md sections 10 and 11, D9).

NOAA Office for Coastal Management publishes one Zstandard-compressed CSV per
UTC day (``csv2/csv<year>/ais-YYYY-MM-DD.csv.zst``, 240-320 MB compressed and
some 8 million rows nationwide), 80 to 150 days after the day. The header of
the 2026 files is::

    mmsi,base_date_time,longitude,latitude,sog,cog,heading,vessel_name,imo,call_sign,
    vessel_type,status,length,width,draft,cargo,transceiver

Columns are found by name, ignoring case and underscores, so the older
``MMSI,BaseDateTime,LAT,LON,...,TransceiverClass`` header reads the same way.
``base_date_time`` is UTC.

``history(day, bbox, mmsis)`` downloads the day's file through the policy HTTP
client (``skippercast.http``; retries rewind a temporary file next to the
backfill store), then decompresses and parses it as a stream, so memory holds
one row at a time plus one static record per vessel: never the file. A missing
file (HTTP 404: not published yet) raises ``DayNotPublished``.

Rows outside ``bbox``, of other MMSIs (when ``mmsis`` is given; with
``all_statics`` their statics are still kept, as the listener keeps statics of
every vessel in the box), with an invalid MMSI, time or position, or whose time
is not on ``day`` are dropped and counted.
Each kept row gives an ``AisPosition`` with ``source="marinecadastre"``,
``msg_type="csv"`` and ``received_at = ts`` (the file has no receipt time, so no
position is ever "late", section 10). The static fields repeat on every row; an
``AisStatic`` is emitted for the first row of a vessel and again only when they
change. MarineCadastre gives overall ``length`` and ``width``, not the antenna
offsets AIS reports, so a static carries ``dim_bow = length``, ``dim_stern = 0``,
``dim_port = width``, ``dim_starboard = 0``: the sums are the vessel's size, the
antenna position is unknown. ``transceiver`` gives ``ais_class``; a row without
it gives no static.

"Not available" values follow aisstream's (``sog`` 102.3, ``cog`` 360,
``heading`` 511, ``status`` 15, zero ship type, IMO, length or width) and become
``None``; ``imo`` may carry an ``IMO`` prefix.

Rights: NOAA's June 2026 FAQ limits use to "coastal and ocean planning
purposes" and forbids charging a fee for the data, so everything derived from
this source is tagged ``noaa-planning-only`` (``RIGHTS``; D9) and stays off any
paid surface.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import io
from pathlib import Path
import tempfile
from typing import IO, Iterable, Iterator, MutableMapping

from ....http import HTTPStatusError, Session
from .base import AisMessage, AisPosition, AisStatic, Bbox, Unsupported, valid_mmsi

__all__ = ["SOURCE_ID", "RIGHTS", "BASE_URL", "HOST", "MAX_BYTES", "COUNTERS", "DayNotPublished", "MalformedFile",
           "MarineCadastreSource", "day_url", "parse_rows", "read_zst"]

SOURCE_ID = "marinecadastre"
RIGHTS = "noaa-planning-only"
HOST = "noaaocm.blob.core.windows.net"
BASE_URL = f"https://{HOST}/ais/csv2/"
MAX_BYTES = 1_500_000_000            # a day file is 240-320 MB; this only stops a runaway response
DOWNLOAD_TIMEOUT = 120.0
READ_SIZE = 1 << 20
MSG_TYPE = "csv"
# Counted per call in the ``counts`` mapping ``history`` and ``parse_rows`` fill in.
COUNTERS = ("rows", "positions", "statics", "outside", "other_mmsi", "other_day", "malformed")

_REQUIRED = ("mmsi", "time", "lat", "lon")
_ALIASES = {
    "mmsi": "mmsi", "basedatetime": "time", "latitude": "lat", "lat": "lat", "longitude": "lon", "lon": "lon",
    "sog": "sog", "cog": "cog", "heading": "heading", "vesselname": "name", "imo": "imo", "callsign": "call_sign",
    "vesseltype": "ship_type", "status": "status", "length": "length", "width": "width",
    "transceiver": "transceiver", "transceiverclass": "transceiver",
}


class DayNotPublished(LookupError):
    """NOAA has not published this day's file (HTTP 404)."""


class MalformedFile(ValueError):
    """The file is not a MarineCadastre daily CSV (a required column is missing)."""


def day_url(day: date) -> str:
    return f"{BASE_URL}csv{day.year}/ais-{day.isoformat()}.csv.zst"


def read_zst(binary: IO[bytes]) -> IO[str]:
    """A text stream over a Zstandard-compressed binary stream, decompressed as it is read."""
    import zstandard   # the fleet extra; only the backfill needs it

    reader = zstandard.ZstdDecompressor().stream_reader(binary, read_size=READ_SIZE, read_across_frames=True)
    return io.TextIOWrapper(io.BufferedReader(reader, READ_SIZE), encoding="utf-8", newline="")


def _float(text: str, unavailable: float | None = None, low: float | None = None, high: float | None = None):
    text = text.strip()
    if not text:
        return None
    value = float(text)
    if value != value or (unavailable is not None and value == unavailable):
        return None
    if (low is not None and value < low) or (high is not None and value > high):
        return None
    return value


def _int(text: str, unavailable: int | None = None, high: int | None = None) -> int | None:
    value = _float(text)
    if value is None or value != int(value):
        return None
    value = int(value)
    return None if value == unavailable or value < 0 or (high is not None and value > high) else value


def _positive(text: str) -> int | None:
    value = _int(text)
    return value if value else None


def _imo(text: str) -> int | None:
    text = text.strip().upper()
    return _positive(text[3:] if text.startswith("IMO") else text)


def _clean(text: str) -> str | None:
    text = text.replace("@", " ").strip()
    return text or None


def _time_ms(text: str) -> int:
    """``2026-06-20 00:00:00`` (UTC) as epoch milliseconds."""
    moment = datetime.fromisoformat(text.strip())
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return round(moment.timestamp() * 1000)


def _columns(header: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, name in enumerate(header):
        key = _ALIASES.get(name.strip().lstrip("﻿").lower().replace("_", ""))
        if key and key not in found:
            found[key] = index
    missing = [k for k in _REQUIRED if k not in found]
    if missing:
        raise MalformedFile(f"not a MarineCadastre AIS CSV: no {', '.join(missing)} column")
    return found


def parse_rows(text: Iterable[str], day: date, bbox: Bbox, mmsis: set[int] | None = None,
               counts: MutableMapping[str, int] | None = None, all_statics: bool = False) -> Iterator[AisMessage]:
    """Normalised records from the lines of one day's CSV (module docstring), as they are read.

    ``mmsis`` limits positions, and statics too unless ``all_statics`` (statics of every vessel in ``bbox``, as
    the listener keeps them for MMSI matching).
    """
    counts = counts if counts is not None else {}
    for key in COUNTERS:
        counts.setdefault(key, 0)
    (south, west), (north, east) = bbox
    first = round(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
    last = first + 86_400_000
    wanted = None if mmsis is None else {str(m) for m in mmsis}
    rows = csv.reader(text)
    header = next(rows, None)
    if header is None:
        raise MalformedFile("empty file")
    col = _columns(header)
    i_mmsi, i_time, i_lat, i_lon = (col[k] for k in _REQUIRED)
    width = max(col.values()) + 1
    optional = {k: col.get(k) for k in ("sog", "cog", "heading", "status", "name", "call_sign", "imo", "ship_type",
                                        "length", "width", "transceiver")}

    def get(row, key):
        index = optional[key]
        return "" if index is None else row[index]

    def static_fields(row):
        ais_class = get(row, "transceiver").strip().upper()
        if ais_class not in ("A", "B"):
            return None
        try:
            length, beam = _positive(get(row, "length")), _positive(get(row, "width"))
            name, call_sign, imo, ship_type = (_clean(get(row, "name")), _clean(get(row, "call_sign")),
                                               _imo(get(row, "imo")), _positive(get(row, "ship_type")))
        except ValueError:
            return None
        if name is None and call_sign is None and imo is None and ship_type is None and not length and not beam:
            return None
        return (name, call_sign, imo, ship_type, length, 0 if length else None, beam, 0 if beam else None, ais_class)

    statics: dict[int, tuple] = {}
    for row in rows:
        counts["rows"] += 1
        if len(row) < width:
            counts["malformed"] += 1
            continue
        try:
            lat, lon = float(row[i_lat]), float(row[i_lon])
        except ValueError:
            counts["malformed"] += 1
            continue
        if not (south <= lat <= north and west <= lon <= east):
            counts["outside"] += 1
            continue
        text_mmsi = row[i_mmsi].strip()
        keep = wanted is None or text_mmsi in wanted
        if not keep:
            counts["other_mmsi"] += 1
            if not all_statics:
                continue
        try:
            mmsi = int(text_mmsi)
        except ValueError:
            counts["malformed"] += 1
            continue
        if not valid_mmsi(mmsi):
            counts["malformed"] += 1
            continue
        fields = static_fields(row)
        new_static = fields is not None and statics.get(mmsi) != fields
        if not keep and not new_static:
            continue
        try:
            ts = _time_ms(row[i_time])
            if keep:
                sog = _float(get(row, "sog"), 102.3, 0.0, 102.2)
                cog = _float(get(row, "cog"), 360.0, 0.0, 359.9)
                heading = _int(get(row, "heading"), 511, 359)
                nav_status = _int(get(row, "status"), 15, 15)
        except ValueError:
            counts["malformed"] += 1
            continue
        if not first <= ts < last:
            counts["other_day"] += 1
            continue
        if keep:
            counts["positions"] += 1
            yield AisPosition(mmsi, ts, lat, lon, sog, cog, heading, nav_status, MSG_TYPE, SOURCE_ID, ts)
        if new_static:
            statics[mmsi] = fields
            counts["statics"] += 1
            yield AisStatic(mmsi, ts, *fields, SOURCE_ID)


class MarineCadastreSource:
    """History from NOAA's daily files; ``stream`` is ``Unsupported`` (the files lag 80-150 days)."""

    id = SOURCE_ID
    realtime = False

    def __init__(self, session=None, workdir: Path | None = None, base_url: str = BASE_URL):
        self._session = session
        self.workdir = None if workdir is None else Path(workdir)
        self.base_url = base_url

    @property
    def session(self):
        if self._session is None:
            self._session = Session(extra_hosts=(HOST,), max_bytes=MAX_BYTES, timeout=DOWNLOAD_TIMEOUT)
        return self._session

    async def stream(self, bbox: Bbox, mmsis: set[int] | None = None):
        raise Unsupported("MarineCadastre publishes daily files 80-150 days late; it has no live feed")
        yield  # pragma: no cover  (makes this an async generator)

    def url(self, day: date) -> str:
        return day_url(day).replace(BASE_URL, self.base_url, 1)

    def history(self, day: date, bbox: Bbox, mmsis: set[int] | None = None,
                counts: MutableMapping[str, int] | None = None, all_statics: bool = False) -> Iterator[AisMessage]:
        """Every record of one UTC ``day`` inside ``bbox`` (only ``mmsis`` when given; ``parse_rows``), streamed."""
        if self.workdir is not None:
            self.workdir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=self.workdir, prefix=f"ais-{day.isoformat()}-") as download:
            try:
                self.session.download(self.url(day), download, max_bytes=MAX_BYTES,
                                      allowed_prefixes=(self.base_url,), timeout=DOWNLOAD_TIMEOUT)
            except HTTPStatusError as error:
                if error.status == 404:
                    raise DayNotPublished(f"{day.isoformat()}: no MarineCadastre file yet") from None
                raise
            download.seek(0)
            with read_zst(download) as text:
                yield from parse_rows(text, day, bbox, mmsis, counts, all_statics)

