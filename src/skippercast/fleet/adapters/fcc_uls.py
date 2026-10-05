"""FCC ULS ship station licences (design section 6, adapter ``fcc-uls``).

Downloads the weekly complete ship file (``l_ship.zip``) with a conditional
GET, reads its pipe-delimited ``EN`` (entity), ``HD`` (licence header) and
``SH`` (ship) records, and emits one ``Candidate`` per licence whose licensee
address is in the bound state, whatever its status (active, expired,
cancelled, terminated). Each candidate carries the vessel name, call sign,
MMSI and the documentation or state registration number as stable keys and
facts, and a ``fcc_licence`` fact with the status and dates.

Privacy (design section 6 and 17): the licensee is kept only when it is an
entity (an LLC, corporation, company), never when it is an individual, and no
address field is ever emitted. The licensee's city is used only to choose a
port hint when it names one of the region's ports; the city itself is not
emitted. A licence is its own candidate, so two same-name licences stay two
candidates (resolution, section 7, decides whether they are one vessel).

Record layout (FCC ULS public access files; 0-based field positions):

- ``HD``: 1 unique system identifier, 4 call sign, 5 licence status,
  6 radio service, 7 grant date, 8 expired date, 9 cancellation date.
- ``EN``: 1 identifier, 5 entity type (``L`` licensee), 7 entity name,
  8 first name, 10 last name, 16 city, 17 state, 23 applicant type code.
- ``SH``: 1 identifier, 4 call sign, 8 ship category, 9 vessel name,
  10 vessel identification (USCG official number or state registration),
  21 MMSI.
"""
from __future__ import annotations

import io
import re
from typing import IO, Iterable, Iterator, Mapping
import zipfile

from .base import Candidate, Fact, RunContext

__all__ = ["FccUls", "FccFormatError", "is_entity", "parse_ship_zip", "licence_url"]

ID = "fcc-uls"
DEFAULT_URL = "https://data.fcc.gov/download/pub/uls/complete/l_ship.zip"
MAX_BYTES = 200_000_000
LICENCE_URL = "https://wireless2.fcc.gov/UlsApp/UlsSearch/license.jsp?licKey={usi}"

STATUSES = {"A": "active", "E": "expired", "C": "cancelled", "T": "terminated", "L": "pending-legal",
            "P": "parent-cancelled", "X": "termination-pending"}
# Applicant type codes that are never an entity: I individual, A amateur club, R RACES.
PERSON_TYPES = frozenset({"I", "A", "R", ""})
ENTITY_SUFFIX = re.compile(
    r"(?:^|[\s,])(?:L\.?\s?L\.?\s?C|INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|L\.?\s?P|"
    r"L\.?\s?L\.?\s?P|P\.?\s?L\.?\s?L\.?\s?C)\.?$")

# Words that put a person in an otherwise entity-looking name.
PERSON_MARKERS = re.compile(
    r"(?:^|[\s,(])(?:D[\s./]*B[\s./]*A\.?|DOING BUSINESS AS|C\s?/\s?O|C\.\s?O\.|IN CARE OF|ATTN|TRUSTEES?|TTEES?"
    r"|ESTATE OF|ET\.? AL\.?)(?:$|[\s.,:)])")

# Minimum field counts each record type must have; a file with lines shorter than this changed layout.
WIDTH = {"HD": 10, "EN": 24, "SH": 22}
DOC = re.compile(r"^(?:D|ON)?\s*(\d{5,8})$")
STATE_REG = re.compile(r"^([A-Z]{2})\s*(\d{1,5})\s*([A-Z]{1,3})$")
CALL_SIGN = re.compile(r"^[A-Z0-9]{3,10}$")
MMSI = re.compile(r"^\d{9}$")


class FccFormatError(ValueError):
    """The ship file's layout is not the one this adapter reads (a member is missing or too narrow)."""


def licence_url(usi: str) -> str:
    return LICENCE_URL.format(usi=usi)


def is_entity(applicant_type: str, entity_name: str, first: str, last: str) -> bool:
    """True only for an organisation licensee.

    All must hold: the applicant type is not an individual's, the personal-name
    fields are empty, the name ends in an entity suffix, it carries no marker of
    a person (DBA, D/B/A, C/O, ATTN, TRUSTEE, ESTATE OF, ET AL), and what comes
    before the suffix has no comma (``SURNAME, GIVEN LLC``).
    """
    name = re.sub(r"\s+", " ", entity_name.strip().upper())
    suffix = ENTITY_SUFFIX.search(name)
    if (applicant_type.strip().upper() in PERSON_TYPES or first.strip() or last.strip() or not suffix
            or PERSON_MARKERS.search(name)):
        return False
    return "," not in name[:suffix.start()].rstrip(", ")


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _date(text: str) -> str | None:
    match = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", text.strip())
    return f"{match.group(3)}-{match.group(1)}-{match.group(2)}" if match else None


def _records(archive: zipfile.ZipFile, kind: str, stats: dict) -> Iterator[list[str]]:
    name = next((n for n in archive.namelist() if n.upper() == f"{kind}.DAT"), None)
    if name is None:
        raise FccFormatError(f"{kind}.dat is missing from the ship file")
    seen = 0
    with archive.open(name) as raw:
        for line in io.TextIOWrapper(raw, encoding="latin-1", newline=""):
            fields = line.rstrip("\r\n").split("|")
            if fields[0] != kind:
                stats["skipped_lines"] = stats.get("skipped_lines", 0) + 1
                continue
            if len(fields) < WIDTH[kind]:
                raise FccFormatError(f"{kind} record has {len(fields)} fields, expected at least {WIDTH[kind]}")
            seen += 1
            yield fields
    stats[f"{kind.lower()}_records"] = seen


def _keys(call_sign: str, mmsi: str, vessel_id: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    call_sign = call_sign.strip().upper()
    if CALL_SIGN.match(call_sign):
        keys["call_sign"] = call_sign
    mmsi = mmsi.strip()
    if MMSI.match(mmsi) and mmsi != "000000000":
        keys["mmsi"] = mmsi
    vessel_id = vessel_id.strip().upper()
    if doc := DOC.match(vessel_id):
        keys["uscg_doc"] = doc.group(1)
    elif reg := STATE_REG.match(vessel_id):
        keys["state_reg"] = "".join(reg.groups())
    return keys


def parse_ship_zip(data: bytes | IO[bytes], state: str, *, source_id: str, rights: str, retrieved_at: str,
                   ports: Mapping[str, str] | None = None, stats: dict | None = None,
                   all_statuses: bool = True, categories: Iterable[str] | None = None) -> Iterator[Candidate]:
    """Candidates from an ``l_ship.zip`` for licensees in ``state``, all statuses.

    ``ports`` maps a normalised port name to its port id, for the port hint.
    ``stats`` (optional) receives record and skip counts. ``all_statuses=False``
    keeps active licences only; ``categories`` keeps only those ship category codes.
    """
    stats = {} if stats is None else stats
    ports = ports or {}
    state = state.strip().upper()
    wanted = {c.strip().upper() for c in categories} if categories else None
    archive = zipfile.ZipFile(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data)
    licensees: dict[str, tuple[str | None, str | None]] = {}  # usi -> (entity name or None, port id)
    for f in _records(archive, "EN", stats):
        if f[5].strip() != "L" or f[17].strip().upper() != state:
            continue
        entity = f[7].strip() if is_entity(f[23], f[7], f[8], f[10]) else None
        licensees[f[1]] = (entity, ports.get(_norm(f[16])))
    headers: dict[str, list[str]] = {}
    for f in _records(archive, "HD", stats):
        if f[1] in licensees:
            headers[f[1]] = f
    emitted = unnamed = 0
    for f in _records(archive, "SH", stats):
        usi = f[1]
        if usi not in licensees or (wanted is not None and f[8].strip().upper() not in wanted):
            continue
        name = re.sub(r"\s+", " ", f[9]).strip()
        if not name:
            unnamed += 1
            continue
        entity, port = licensees[usi]
        hd = headers.get(usi)
        code = hd[5].strip().upper() if hd else ""
        status = STATUSES.get(code, "unknown")
        active = status == "active"
        if not active and not all_statuses:
            continue
        call_sign = (f[4] or (hd[4] if hd else "")).strip().upper()
        keys = _keys(call_sign, f[21], f[10])
        url = licence_url(usi)

        def fact(field: str, value, confidence: float) -> Fact:
            return Fact(field=field, value=value, source_id=source_id, source_url=url, method="registry",
                        confidence=confidence, rights=rights, retrieved_at=retrieved_at)

        facts = [fact("name", name, 0.8 if active else 0.6)]
        for key in ("call_sign", "mmsi"):
            if key in keys:
                facts.append(fact(key, keys[key], 0.95 if active else 0.7))
        for key in ("uscg_doc", "state_reg"):
            if key in keys:
                facts.append(fact(key, keys[key], 0.9 if active else 0.8))
        if entity:
            facts.append(fact("operator", entity, 0.8 if active else 0.6))
        licence = {"call_sign": call_sign or None, "status": status, "status_code": code or None,
                   "radio_service": (hd[6].strip() or None) if hd else None,
                   "grant_date": _date(hd[7]) if hd else None, "expired_date": _date(hd[8]) if hd else None,
                   "cancellation_date": _date(hd[9]) if hd else None, "category": f[8].strip() or None}
        facts.append(fact("fcc_licence", {k: v for k, v in licence.items() if v is not None}, 1.0))
        emitted += 1
        yield Candidate(source_id=source_id, name=name, port_hint=port, keys=keys, facts=tuple(facts))
    stats.update(licences=len(licensees), candidates=emitted, unnamed=unnamed)


class FccUls:
    """The ``fcc-uls`` adapter: discover only."""

    id = ID
    kind = "discover"

    def __init__(self) -> None:
        self.stats: dict = {}

    def discover(self, binding, ctx: RunContext) -> Iterable[Candidate]:
        from ..net import Skipped  # fleet.net imports config, which imports this package

        params = binding.params
        state = str(params.get("state") or ctx.region.id)
        url = str(params.get("url") or DEFAULT_URL)
        try:
            response = ctx.net.get(url, max_bytes=int(params.get("max_bytes") or MAX_BYTES), timeout=300)
        except Skipped as skip:
            self.stats = {"skipped": skip.as_dict()}
            return []
        self.stats = {"from_cache": bool(response.receipt.from_cache), "bytes": response.receipt.bytes}
        ports = {_norm(port.name): port.id for port in ctx.region.ports}
        return list(parse_ship_zip(response.body or b"", state, source_id=binding.id, rights=binding.rights,
                                   retrieved_at=ctx.clock(), ports=ports, stats=self.stats,
                                   all_statuses=bool(params.get("all_statuses", True)),
                                   categories=params.get("categories")))

    def enrich(self, vessel, binding, ctx: RunContext) -> Iterable[Fact]:
        return ()
