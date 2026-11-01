"""Bulk join of the charter registry to MMSIs through FCC ULS ship licences and USCG PSIX (AISBULK-1).

Private research tool. It reads, and never writes, a fleet run's ``resolved.jsonl``, the AIS processor's
``state.sqlite`` (opened read-only: ``match_statics`` and ``match_presence``), the FCC weekly ship file
``l_ship.zip`` and PSIX export workbooks (the ``uscg-psix`` adapter's sector export). It writes one private
JSON and one private Markdown table to an ``--out`` directory that must lie outside the repository, and
prints counts only (no boat names, MMSIs or call signs), so its standard output can go in a PR.

Registry data never enters the repository (CONTRIBUTING.md, design section 17): the join table stays in
``--out``. Licensee names are kept only for organisations (``fcc_uls.is_entity``); an individual licensee is
written as ``individual (withheld)``. Licensee addresses are used only to test the port region and are never
written.

**Candidates.** For each registry vessel, every MMSI that (a) an AIS static broadcasts under the vessel's
normalised name, (b) an FCC licence of the same name carries (licensee in California, or the MMSI heard on
AIS), or (c) a licence reached through a same-name PSIX vessel's official number or call sign carries.

**Resolution needs corroboration beyond the name.** A candidate resolves with at least one method and no
contradiction:

- ``licence-call-sign``: an active FCC licence of the same name holds this MMSI *and* the call sign the AIS
  static broadcasts, the AIS static carries the name, and the home port is plausible;
- ``licence-mmsi``: an active FCC licence of the same name holds this MMSI, the AIS static under this MMSI
  carries the name (and no call sign that differs from the licence's), and the home port is plausible;
- ``official-number``: an active FCC licence of the same name holds this MMSI and an official number that a
  same-name PSIX vessel, inspected by a unit serving the port, also holds.

The home port is plausible when the MMSI was inside the port's geofence on at least one day of the AIS
state's window, or the licensee's ZIP code lies in the port's region (``GROUP_ZIP3``, coarse and tolerant).
Contradictions: an AIS call sign absent from the licence, an MMSI licensed to another name, a call sign
licensed to another MMSI or to no one, a non-US MMSI or call sign, an AIS ship type that is neither fishing,
pleasure nor passenger, a length more than 20% off the licence's, or an MMSI seen only in other ports while
its licensee lives elsewhere. A vessel with one resolving MMSI is ``resolved``; two resolving MMSIs, or one
MMSI resolving for two registry vessels, leave it ``unresolved``.

Run (from the repository root, with ``src`` and the root on ``sys.path``)::

    python research/scripts/join_fleet_registries.py --resolved RUN/resolved.jsonl \\
        --state FLEET/ais/state.sqlite --fcc DL/l_ship.zip --psix DL/*.xlsx --out PRIVATE_DIR
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Iterable, Iterator, Mapping
import zipfile

from skippercast.fleet.adapters.fcc_uls import STATUSES, WIDTH, is_entity
from skippercast.fleet.adapters.uscg_psix import Vessel, parse_inspections
from skippercast.fleet.normalize import name_norm

from research.lib.paths import ROOT

__all__ = ["norm", "legacy_norm", "same_name", "Licence", "Static", "PsixVessel", "load_fcc", "load_ais",
           "load_psix", "join", "summary", "main"]

# ---- normalisation ---------------------------------------------------------------------------------

LEADING = frozenset({"THE", "FV", "F/V", "F.V.", "MV", "M/V", "M.V."})
LEGACY_DROP = frozenset({"THE", "F/V", "FV", "M/V", "MV", "II", "III", "IV"})
AIS_NAME_MAX = 20     # an AIS static name is at most 20 characters; a full-length one may be cut short
FCC_NAME_MAX = 35     # the ULS ship name field
MIN_PREFIX = 8        # a cut-short name matches a longer registry name only on at least 8 characters


def norm(name: str | None) -> str:
    """The registry's ``name_norm`` (THE, F/V, M/V dropped; a trailing roman numeral becomes digits; NEW kept),
    after dropping a parenthetical note ("Test Wave (as named on harbor page)") and the leading FV and MV that
    AIS and licence names carry without the slash."""
    tokens = re.sub(r"\([^)]*\)?", " ", name or "").upper().split()
    while len(tokens) > 1 and tokens[0] in LEADING:
        tokens = tokens[1:]
    return name_norm(" ".join(tokens))


PLACEHOLDER = re.compile(r"\b(?:NOT STATED|UNNAMED|FLEET|VESSEL NAMES?)\b", re.I)
OPERATOR = re.compile(r"\b(?:SPORTS?\s?FISHING|SPORT FISHING|CHARTERS?|CHARTER BOATS|BOATS|ADVENTURES|GUIDE SERVICE|"
                      r"COMMUNITY FISHING|BAY CRUISES?)\s*$", re.I)


def name_kind(name: str) -> str:
    """``placeholder`` (the source named no boat), ``operator`` (a business name, not a boat name) or ``vessel``."""
    if PLACEHOLDER.search(name or ""):
        return "placeholder"
    if OPERATOR.search(re.sub(r"\([^)]*\)?", " ", name or "").strip()):
        return "operator"
    return "vessel"


def legacy_norm(name: str | None) -> str:
    """The first-pass rule this tool replaces: drop THE, F/V, FV, M/V, MV, II, III, IV anywhere, keep A-Z0-9."""
    return re.sub(r"[^A-Z0-9]", "", "".join(t for t in (name or "").upper().split() if t not in LEGACY_DROP))


def same_name(registry: str, other: str, truncated: bool = False) -> bool:
    if not registry or not other:
        return False
    return registry == other or (truncated and len(other) >= MIN_PREFIX and registry.startswith(other))


def near_name(registry: str, other: str) -> bool:
    """A one-letter spelling variant (same length, at least 6 characters, exactly one letter differs): used only
    for a licence that was found by its MMSI or call sign, never to discover a candidate."""
    return bool(registry and other and len(registry) == len(other) >= 6
                and sum(a != b for a, b in zip(registry, other)) == 1)


# ---- regions (coarse, tolerant: a plausibility test, never a resolution on its own) ----------------

PORT_GROUP = {
    **dict.fromkeys(("crescent-city", "trinidad", "eureka", "shelter-cove", "noyo-harbor"), "north"),
    **dict.fromkeys(("bodega-bay", "sausalito", "san-francisco", "richmond", "berkeley", "emeryville", "alameda",
                     "benicia", "pittsburg", "antioch", "rio-vista", "bethel-island", "stockton", "pillar-point"),
                    "bay"),
    **dict.fromkeys(("santa-cruz", "moss-landing", "monterey"), "monterey-bay"),
    **dict.fromkeys(("morro-bay", "port-san-luis"), "slo"),
    **dict.fromkeys(("santa-barbara", "ventura", "oxnard"), "channel"),
    **dict.fromkeys(("marina-del-rey", "redondo-beach", "san-pedro", "long-beach"), "la"),
    **dict.fromkeys(("newport-beach", "dana-point"), "oc"),
    **dict.fromkeys(("oceanside", "mission-bay", "san-diego"), "sd"),
}
_LA = {str(z) for z in range(900, 919)}
GROUP_ZIP3 = {
    "north": {"954", "955", "960"},
    "bay": {"940", "941", "943", "944", "945", "946", "947", "948", "949", "950", "951", "952", "953", "954",
            "956", "957", "958"},
    "monterey-bay": {"936", "937", "939", "940", "945", "946", "947", "948", "949", "950", "951", "952", "953"},
    "slo": {"932", "933", "934", "936", "937", "939"},
    "channel": {"912", "913", "930", "931", "934", "935"},
    "la": _LA | {"926", "927", "928", "935"},
    "oc": {"900", "902", "903", "906", "907", "908", "917", "922", "923", "924", "925", "926", "927", "928"},
    "sd": {"919", "920", "921", "922", "925", "926"},
}
# PSIX originating unit (normalised) -> port groups it plausibly inspects for.
UNIT_GROUPS = {
    "SECTORSANDIEGO": {"sd", "oc"},
    "SECTORLOSANGELESLONGBEACH": {"la", "oc", "channel", "slo"},
    "MARINESAFETYDETACHMENTSANTABARBARA": {"channel", "slo"},
    "SECTORSANFRANCISCO": {"bay", "monterey-bay", "north"},
    "SECTORHUMBOLDTBAY": {"north"},
    "MARINESAFETYDETACHMENTHUMBOLDTBAY": {"north"},
}
US_MIDS = frozenset({"303", "338", "366", "367", "368", "369"})
US_CALL = re.compile(r"(?:[KNW]|A[A-L])[A-Z0-9]{2,6}")
# AIS ship types a charter boat may broadcast: fishing, pleasure, passenger (60-69), and none/unknown.
CHARTER_TYPES = frozenset({0, 30, 37} | set(range(60, 70)))
UNSPECIFIC_TYPES = frozenset({90, 99})   # "other type": no contradiction, but no support either
LENGTH_TOLERANCE = 0.2
FT = 0.3048


def _alnum(text: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def official_key(text: str | None) -> str:
    """A USCG official number as digits (a leading D or ON dropped), else a state registration as A-Z0-9."""
    raw = _alnum(text)
    match = re.fullmatch(r"(?:D|ON)?(\d{5,8})", raw)
    return match.group(1) if match else raw


# ---- records -----------------------------------------------------------------------------------------

@dataclass
class Licence:
    usi: str
    call_sign: str
    name: str
    official: str
    mmsi: str
    length: int | None = None
    general: str = ""
    specific: str = ""
    status: str = "unknown"
    licensee: str | None = None        # an organisation's name only
    individual: bool = False
    state: str = ""
    groups: frozenset = frozenset()     # port groups whose ZIP3 holds the licensee (private; never written)

    @property
    def norm(self) -> str:
        return norm(self.name)

    @property
    def truncated(self) -> bool:
        return len(self.name) >= FCC_NAME_MAX

    def public(self) -> dict:
        return {"usi": self.usi, "call_sign": self.call_sign or None, "name": self.name, "mmsi": self.mmsi or None,
                "official": self.official or None, "status": self.status, "class": f"{self.general}/{self.specific}",
                "length": self.length, "licensee": self.licensee or ("individual (withheld)" if self.individual
                                                                      else None),
                "licensee_state": self.state or None}


@dataclass
class Static:
    mmsi: str
    name: str | None
    call_sign: str | None
    ship_type: int | None
    length_m: float | None

    @property
    def norm(self) -> str:
        return norm(self.name)

    @property
    def truncated(self) -> bool:
        return len(" ".join((self.name or "").split())) >= AIS_NAME_MAX


@dataclass
class PsixVessel:
    vessel_id: str
    name: str
    official: str
    call_sign: str
    flag: str
    units: set = field(default_factory=set)
    types: set = field(default_factory=set)

    @property
    def norm(self) -> str:
        return norm(self.name)

    def groups(self) -> set:
        return set().union(*(UNIT_GROUPS.get(_alnum(u), set()) for u in self.units)) if self.units else set()


# ---- loaders -----------------------------------------------------------------------------------------

def _dat(archive: zipfile.ZipFile, kind: str) -> Iterator[list[str]]:
    member = next((n for n in archive.namelist() if n.upper() == f"{kind}.DAT"), None)
    if member is None:
        raise ValueError(f"{kind}.dat is missing from the ship file")
    with archive.open(member) as raw:
        for line in io.TextIOWrapper(raw, encoding="latin-1", newline=""):
            fields = line.rstrip("\r\n").split("|")
            if fields[0] != kind:
                continue
            if len(fields) < WIDTH[kind]:
                raise ValueError(f"{kind} record has {len(fields)} fields, expected at least {WIDTH[kind]}")
            yield fields


def load_fcc(path: Path, *, names: set[str], mmsis: set[str], calls: set[str], officials: set[str]) -> list[Licence]:
    """Licences whose ship name, MMSI, call sign or official number touches the join (all states, all statuses).

    SH (0-based): 4 call sign, 7 general class, 8 specific class, 9 name, 10 official number, 16 length,
    21 MMSI. HD: 5 status. EN (licensee rows, type L): 7 entity name, 8/10 personal names, 17 state, 18 ZIP,
    23 applicant type.
    """
    archive = zipfile.ZipFile(path)
    prefixes = {n for n in names if len(n) >= MIN_PREFIX}
    kept: dict[str, Licence] = {}
    for f in _dat(archive, "SH"):
        name = " ".join(f[9].split())
        key, mmsi, call, official = norm(name), f[21].strip(), _alnum(f[4]), official_key(f[10])
        long_name = len(name) >= FCC_NAME_MAX and any(n.startswith(key) for n in prefixes)
        if not (key in names or long_name or (mmsi and mmsi in mmsis) or (call and call in calls)
                or (official and official in officials)):
            continue
        length = int(f[16]) if f[16].strip().isdigit() and int(f[16]) > 0 else None
        kept[f[1]] = Licence(usi=f[1], call_sign=call, name=name, official=official,
                             mmsi=mmsi if re.fullmatch(r"\d{9}", mmsi) and mmsi != "000000000" else "",
                             length=length, general=f[7].strip(), specific=f[8].strip())
    for f in _dat(archive, "HD"):
        if (lic := kept.get(f[1])) is not None:
            lic.status = STATUSES.get(f[5].strip().upper(), "unknown")
            lic.call_sign = lic.call_sign or _alnum(f[4])
    for f in _dat(archive, "EN"):
        lic = kept.get(f[1])
        if lic is None or f[5].strip() != "L":
            continue
        entity = is_entity(f[23], f[7], f[8], f[10])
        lic.licensee = f[7].strip() if entity else None
        lic.individual = not entity
        lic.state = f[17].strip().upper()
        zip3 = f[18].strip()[:3]
        lic.groups = frozenset(g for g, zips in GROUP_ZIP3.items() if lic.state == "CA" and zip3 in zips)
    return list(kept.values())


def load_ais(path: Path) -> tuple[dict[str, Static], dict[str, Counter], dict]:
    """Statics by MMSI, port-geofence presence days by MMSI and port, and the presence window (read-only)."""
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        statics = {str(m): Static(str(m), name, call or None, ship_type, length) for m, name, call, ship_type, length
                   in db.execute("SELECT mmsi, name, call_sign, ship_type, length_m FROM match_statics")}
        presence: dict[str, Counter] = defaultdict(Counter)
        for mmsi, port, days in db.execute("SELECT mmsi, port_id, COUNT(DISTINCT day) FROM match_presence "
                                           "GROUP BY mmsi, port_id"):
            presence[str(mmsi)][port] = days
        first, last = db.execute("SELECT MIN(day), MAX(day) FROM match_presence").fetchone()
    finally:
        db.close()
    return statics, presence, {"first_day": first, "last_day": last}


def fold_psix(rows: Iterable[Mapping[str, str]]) -> list[PsixVessel]:
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        key = row.get("vessel_id") or (row.get("official") and f"on-{row['official']}")
        if key:
            grouped[key].append(dict(row))
    out = []
    for key, group in sorted(grouped.items()):
        latest = Vessel(key, group).latest
        out.append(PsixVessel(vessel_id=key, name=" ".join(latest["name"].split()), official=official_key(
            latest["official"]), call_sign=_alnum(latest["call_sign"]), flag=latest["flag"],
            units={r["unit"] for r in group if r.get("unit")}, types={r["vessel_type"] for r in group}))
    return out


def load_psix(paths: Iterable[Path]) -> tuple[list[PsixVessel], int]:
    rows: list[dict] = []
    for path in paths:
        rows.extend(parse_inspections(Path(path).read_bytes()))
    return fold_psix(rows), len(rows)


# ---- the join ----------------------------------------------------------------------------------------

def _length_check(static: Static | None, licences: list[Licence]) -> str:
    lengths = [l.length for l in licences if l.length]
    if not static or not static.length_m or not lengths:
        return "unknown"
    for value in lengths:   # ULS help says metres; filers often give feet: either unit may agree
        for metres, unit in ((value * FT, "ft"), (float(value), "m")):
            if abs(static.length_m - metres) <= LENGTH_TOLERANCE * metres:
                return f"agrees ({value} {unit})"
    return "contradicts"


class _Index:
    def __init__(self, statics, licences, psix):
        self.statics = statics
        self.static_by_norm: dict[str, list[Static]] = defaultdict(list)
        self.long_statics = []
        self.static_by_call: dict[str, list[Static]] = defaultdict(list)
        for s in statics.values():
            self.static_by_norm[s.norm].append(s)
            if s.truncated:
                self.long_statics.append(s)
            if s.call_sign:
                self.static_by_call[_alnum(s.call_sign)].append(s)
        self.lic_by_mmsi, self.lic_by_call = defaultdict(list), defaultdict(list)
        self.lic_by_official, self.lic_by_norm = defaultdict(list), defaultdict(list)
        for lic in licences:
            if lic.mmsi:
                self.lic_by_mmsi[lic.mmsi].append(lic)
            if lic.call_sign:
                self.lic_by_call[lic.call_sign].append(lic)
            if lic.official:
                self.lic_by_official[lic.official].append(lic)
            self.lic_by_norm[lic.norm].append(lic)
        self.long_licences = [l for l in licences if l.truncated]
        self.psix_by_norm, self.psix_by_official = defaultdict(list), defaultdict(list)
        for p in psix:
            self.psix_by_norm[p.norm].append(p)
            if p.official:
                self.psix_by_official[p.official].append(p)

    def statics_named(self, key: str) -> list[Static]:
        out = list(self.static_by_norm.get(key, ()))
        out += [s for s in self.long_statics if s not in out and same_name(key, s.norm, True)]
        return out

    def licences_named(self, key: str) -> list[Licence]:
        out = list(self.lic_by_norm.get(key, ()))
        out += [l for l in self.long_licences if l not in out and same_name(key, l.norm, True)]
        return out


def _candidate(v: dict, mmsi: str, via: set, ix: _Index, presence: Mapping[str, Counter]) -> dict:
    key, port = v["norm"], v["port_id"]
    group = PORT_GROUP.get(port)
    static = ix.statics.get(mmsi)
    static_named = bool(static and same_name(key, static.norm, static.truncated))
    licensed = ix.lic_by_mmsi.get(mmsi, [])
    # A licence found by this MMSI may carry a one-letter spelling variant of the name (a filing typo).
    named = [l for l in licensed if same_name(key, l.norm, l.truncated) or near_name(key, l.norm)]
    variant = [l for l in named if not same_name(key, l.norm, l.truncated)]
    active = [l for l in named if l.status == "active"]
    ais_call = _alnum(static.call_sign) if static and static.call_sign else ""
    call_lics = ix.lic_by_call.get(ais_call, []) if ais_call else []
    call_this = [l for l in call_lics if l.mmsi == mmsi]
    call_named = [l for l in call_this if l in named]
    # The call sign is confirmed when a same-name licence for this MMSI carries it; a transponder often keeps the
    # call sign of the vessel's earlier (now expired) licence after relicensing, which still confirms it.
    call_ok = bool(call_named) and bool(active)
    call_stale = call_ok and not any(l.status == "active" for l in call_named)
    days = presence.get(mmsi, Counter())
    home_days, other_ports = days.get(port, 0), {p: d for p, d in days.items() if p != port}
    region_ok = any(group in l.groups for l in active)
    psix = sorted({p.vessel_id: p for l in active if l.official for p in ix.psix_by_official.get(l.official, ())
                   if same_name(key, p.norm) and group in p.groups()}.values(), key=lambda p: p.vessel_id)
    # The official number must point at this MMSI alone: no other active licence of that number, and PSIX's
    # current call sign not licensed to a different MMSI.
    other_mmsi = sorted({o.mmsi for l in active if l.official for o in ix.lic_by_official.get(l.official, ())
                         if o.status == "active" and o.mmsi and o.mmsi != mmsi} |
                        {o.mmsi for p in psix if p.call_sign for o in ix.lic_by_call.get(p.call_sign, ())
                         if o.status == "active" and o.mmsi and o.mmsi != mmsi})
    port_ok = home_days > 0 or region_ok
    length = _length_check(static, active or named)

    methods, keys, conflicts, notes = [], [], [], []
    if static_named:
        keys.append("name(ais-static)")
    if named:
        keys.append("name(fcc-licence" + (", spelling variant)" if variant and len(variant) == len(named) else ")"))
    if active and static:
        keys.append("mmsi(fcc-licence=ais-static)")
    if call_ok:
        keys.append("call_sign(fcc-licence=ais-static" + (", earlier licence)" if call_stale else ")"))
    if psix:
        keys.append("official_number(fcc-licence=psix)")
    if home_days:
        keys.append(f"home_port(ais-presence {home_days}d)")
    if region_ok:
        keys.append("home_port(licensee-region)")
    if psix:
        keys.append("home_port(psix-unit)")
    if length.startswith("agrees"):
        keys.append(f"length(ais vs licence {length[8:-1]})")

    if static_named and call_ok and port_ok:
        methods.append("licence-call-sign")
    if static_named and active and (not ais_call or call_ok) and port_ok:
        methods.append("licence-mmsi")
    if active and psix and port_ok and not other_mmsi:
        methods.append("official-number")
    elif active and psix and other_mmsi:
        notes.append("official-number-also-points-at(" + ",".join(other_mmsi) + ")")
    elif active and psix:
        notes.append("official-number-matches-but-home-port-only-from-psix-unit")

    if licensed and not named:
        conflicts.append("mmsi-licensed-to-another-name")
    if static and static.norm and not static_named and not near_name(key, static.norm):
        conflicts.append("ais-broadcasts-another-name")
    if mmsi[:3] not in US_MIDS:
        conflicts.append(f"non-us-mmsi(mid {mmsi[:3]})")
    if ais_call:
        if not call_lics:
            conflicts.append("call-sign-not-us-format" if not US_CALL.fullmatch(ais_call) else
                             "call-sign-not-licensed")
        elif not call_this:
            conflicts.append("call-sign-licensed-to-another-mmsi")
        elif not call_named:
            conflicts.append("call-sign-licensed-under-another-name")
    if static and static.ship_type not in (None, *CHARTER_TYPES, *UNSPECIFIC_TYPES):
        conflicts.append(f"ais-ship-type-{static.ship_type}")
    if length == "contradicts":
        if len(methods) >= 2:   # AIS dimensions are self-entered; two registry agreements outweigh them
            notes.append("ais-length-differs-from-licence")
        else:
            conflicts.append("length-contradicts-licence")
    if active and not port_ok and not psix and other_ports:
        conflicts.append("seen-only-in-other-ports-and-licensee-elsewhere")
    if named and not active:
        notes.append("licence-not-active(" + ",".join(sorted({l.status for l in named})) + ")")
    if active and not port_ok and not psix and not other_ports:
        notes.append("home-port-unconfirmed(licensee-elsewhere, no ais presence)")
    if not named and not licensed and static:
        notes.append("mmsi-not-in-fcc-licences")
    if other_ports:
        notes.append("ais-presence-elsewhere(" + ",".join(f"{p} {d}d" for p, d in sorted(other_ports.items())) + ")")
    if static and static.ship_type in UNSPECIFIC_TYPES:
        notes.append(f"ais-ship-type-{static.ship_type}(unspecific)")

    lic = next((l for l in active if l.call_sign == ais_call), None) or (active or named or [None])[0]
    return {"mmsi": mmsi, "via": sorted(via), "methods": methods, "conflicts": conflicts, "notes": notes,
            "keys": keys, "call_sign": (lic.call_sign if lic else "") or ais_call or None,
            "call_sign_source": "fcc-licence" if lic and lic.call_sign else ("ais-static" if ais_call else None),
            "official": lic.official if lic and lic.official else None,
            "official_source": "fcc-licence" if lic and lic.official else None,
            "licence": lic.public() if lic else None, "length_check": length,
            "ais": {"name": static.name, "call_sign": static.call_sign, "ship_type": static.ship_type,
                    "length_m": static.length_m} if static else None,
            "psix": [{"vessel_id": p.vessel_id, "name": p.name, "official": p.official, "call_sign": p.call_sign,
                      "units": sorted(p.units)} for p in psix],
            "home_port_days": home_days,
            "lead": bool(static_named and home_days >= 3 and static.ship_type in CHARTER_TYPES and not conflicts)}


AIS_METHODS = ("licence-call-sign", "licence-mmsi")


def _heard_at_home(c: dict) -> bool:
    """The MMSI broadcasts the vessel's name and was in its home-port geofence, with nothing against it."""
    return "name(ais-static)" in c["keys"] and c["home_port_days"] > 0 and not c["conflicts"]


def _resolving(candidates: list[dict]) -> list[dict]:
    """Candidates with a method and no contradiction. When several MMSIs resolve and exactly one of them is
    confirmed on AIS (licence-call-sign or licence-mmsi), it wins over licence-only ones (a superseded licence
    still on file); the losers are recorded on the winner."""
    good = [c for c in candidates if c["methods"] and not c["conflicts"]]
    on_air = [c for c in good if any(m in AIS_METHODS for m in c["methods"])]
    if len(good) > 1 and len(on_air) == 1:
        on_air[0]["notes"].append("preferred-over-licence-only(" + ",".join(c["mmsi"] for c in good
                                                                           if c is not on_air[0]) + ")")
        return on_air
    return good


def join(registry: list[dict], statics: dict[str, Static], presence: Mapping[str, Counter],
         licences: list[Licence], psix: list[PsixVessel]) -> list[dict]:
    """One row per registry vessel: verdict, chosen MMSI and its evidence, and every candidate checked."""
    ix = _Index(statics, licences, psix)
    rows = []
    for v in registry:
        v = {**v, "norm": norm(v["name"])}
        key = v["norm"]
        found: dict[str, set] = defaultdict(set)
        ais_named = ix.statics_named(key)
        for s in ais_named:
            found[s.mmsi].add("ais-static-name")
        fcc_named = ix.licences_named(key)
        for lic in fcc_named:
            if lic.mmsi and (lic.state == "CA" or lic.mmsi in statics):
                found[lic.mmsi].add("fcc-licence-name")
        psix_named = ix.psix_by_norm.get(key, [])
        for p in psix_named:
            for lic in ix.lic_by_official.get(p.official, []) if p.official else ():
                if lic.mmsi:
                    found[lic.mmsi].add("psix-official-number")
            if p.call_sign:
                for lic in ix.lic_by_call.get(p.call_sign, []):
                    if lic.mmsi:
                        found[lic.mmsi].add("psix-call-sign")
                for s in ix.static_by_call.get(p.call_sign, []):
                    found[s.mmsi].add("psix-call-sign")
        candidates = [_candidate(v, m, via, ix, presence) for m, via in sorted(found.items())]
        rows.append({"vessel_id": v["vessel_id"], "name": v["name"], "port_id": v["port_id"],
                     "website": v.get("website"), "norm": key, "name_kind": name_kind(v["name"]),
                     "candidates": candidates,
                     "checked": {"ais_static_name": len(ais_named), "fcc_licence_name": len(fcc_named),
                                 "fcc_licence_name_ca": sum(1 for l in fcc_named if l.state == "CA"),
                                 "psix_name": len(psix_named)}})
    # Verdicts: one MMSI resolving with no contradiction; an MMSI may resolve for one registry vessel only.
    resolving = {id(r): _resolving(r["candidates"]) for r in rows}
    claims = Counter(c["mmsi"] for r in rows for c in resolving[id(r)])
    for r in rows:
        good = resolving[id(r)]
        shared = [c for c in good if claims[c["mmsi"]] > 1]
        rival = [c for c in r["candidates"] if good and c is not good[0] and _heard_at_home(c)]
        if len(good) == 1 and not shared and not (rival and not _heard_at_home(good[0])):
            chosen = good[0]
            r.update(verdict="resolved", reason=None, mmsi=chosen["mmsi"], method=chosen["methods"][0])
        else:
            if len({c["mmsi"] for c in good}) > 1:
                reason = "ambiguous: several MMSIs resolve"
            elif shared:
                reason = "mmsi-shared: the MMSI resolves for another registry vessel too"
            elif good:
                reason = ("ambiguous: the licence-only MMSI is not heard on AIS, another MMSI broadcasts the name at "
                          "the home port")
            elif not r["candidates"]:
                reason = ("no vessel name: the registry row names an operator or says the boat is unnamed"
                          if r["name_kind"] != "vessel" else "no candidate in AIS statics, FCC licences or PSIX")
            elif any(not c["conflicts"] for c in r["candidates"]):
                against = sum(1 for c in r["candidates"] if c["conflicts"])
                reason = "uncorroborated: name match only" + (f" ({against} other candidate(s) contradicted)"
                                                               if against else "")
            else:
                reason = "contradicted: " + "; ".join(sorted({x for c in r["candidates"] for x in c["conflicts"]}))
            chosen = None
            r.update(verdict="unresolved", reason=reason, mmsi=None, method=None)
        best = chosen or next((c for c in r["candidates"] if c["lead"]), None)
        r["best"] = best
        r["lead"] = bool(best and best["lead"] and chosen is None)
    shared_names = Counter(c["mmsi"] for r in rows for c in r["candidates"] if "ais-static-name" in c["via"])
    for r in rows:
        for c in r["candidates"]:
            c["registry_vessels_sharing"] = shared_names[c["mmsi"]] if "ais-static-name" in c["via"] else None
    return rows


def call_sign_report(rows: list[dict], licences: list[Licence]) -> list[dict]:
    """Every call sign an AIS static name candidate broadcasts, checked against the licences by call sign."""
    by_call: dict[str, list[Licence]] = defaultdict(list)
    for lic in licences:
        if lic.call_sign:
            by_call[lic.call_sign].append(lic)
    out = []
    for r in rows:
        for c in r["candidates"]:
            if "ais-static-name" not in c["via"] or not c["ais"] or not c["ais"]["call_sign"]:
                continue
            call = _alnum(c["ais"]["call_sign"])
            group = PORT_GROUP.get(r["port_id"])
            found = by_call.get(call, [])
            if not found:
                verdict = "not licensed (non-US call sign format)" if not US_CALL.fullmatch(call) else "not licensed"
            else:
                same = [l for l in found if l.mmsi == c["mmsi"] and (same_name(r["norm"], l.norm, l.truncated)
                                                                      or near_name(r["norm"], l.norm))]
                if not same:
                    verdict = "licensed to another vessel or MMSI: candidate wrong"
                elif not any(l.status == "active" for l in same):
                    verdict = "licence not active"
                elif "licence-call-sign" in c["methods"] and not c["conflicts"]:
                    verdict = "confirmed"
                elif any(group in l.groups for l in same) or c["home_port_days"]:
                    verdict = "licence matches; other contradiction: " + ", ".join(c["conflicts"])
                else:
                    verdict = "licensee elsewhere and no AIS presence at the port: candidate not corroborated"
            out.append({"name": r["name"], "port_id": r["port_id"], "mmsi": c["mmsi"], "call_sign": call,
                        "verdict": verdict, "licences": [l.public() for l in found]})
    return out


def summary(rows: list[dict], legacy: Mapping[str, int] | None = None) -> dict:
    """Counts only: safe for a PR body."""
    resolved = [r for r in rows if r["verdict"] == "resolved"]
    remaining = [r for r in rows if r["verdict"] != "resolved"]
    reasons = Counter(r["reason"].split(":")[0] for r in remaining)
    ports = Counter(r["port_id"] for r in rows)
    left = Counter(r["port_id"] for r in remaining)
    return {"vessels": len(rows), "resolved": len(resolved), "remaining": len(remaining),
            "resolved_by_method": dict(sorted(Counter(r["method"] for r in resolved).items())),
            "remaining_by_reason": dict(sorted(reasons.items())),
            "remaining_leads": sum(1 for r in remaining if r["lead"]),
            "remaining_by_name_kind": dict(sorted(Counter(r["name_kind"] for r in remaining).items())),
            "remaining_by_port": {p: {"vessels": ports[p], "remaining": left[p]} for p in sorted(ports)},
            "with_ais_name_match": sum(1 for r in rows if r["checked"]["ais_static_name"]),
            **({"normalisation": dict(legacy)} if legacy else {})}


def compare_normalisation(registry: list[dict], statics: Mapping[str, Static]) -> tuple[dict, list[dict]]:
    """Registry vessels with at least one AIS static name match under the first-pass rule and under ``norm``,
    and (private) which vessels differ, with the MMSIs only the legacy rule matched."""
    old_index, new_index = defaultdict(set), defaultdict(set)
    longs = [s for s in statics.values() if s.truncated]
    for s in statics.values():
        old_index[legacy_norm(s.name)].add(s.mmsi)
        new_index[s.norm].add(s.mmsi)
    old = new = 0
    changed = []
    for v in registry:
        a = old_index.get(legacy_norm(v["name"]), set())
        key = norm(v["name"])
        b = set(new_index.get(key, set())) | {s.mmsi for s in longs if same_name(key, s.norm, True)}
        old, new = old + bool(a), new + bool(b)
        if a != b:
            changed.append({"name": v["name"], "port_id": v["port_id"], "legacy_only": sorted(a - b),
                            "new_only": sorted(b - a)})
    return ({"legacy_matched": old, "matched": new, "vessels_changed": len(changed),
             "legacy_only_mmsis": sum(len(c["legacy_only"]) for c in changed),
             "new_only_mmsis": sum(len(c["new_only"]) for c in changed)}, changed)


# ---- output ------------------------------------------------------------------------------------------

def _cell(value) -> str:
    return str(value if value not in (None, "", []) else "-").replace("|", "/").replace("\n", " ")


def markdown(rows: list[dict], calls: list[dict], counts: dict, meta: dict, norm_changes: Iterable[dict] = ()) -> str:
    lines = [f"# Charter registry MMSI bulk join (private) - {meta['generated_at']}", "",
             f"Resolved with corroboration: **{counts['resolved']} of {counts['vessels']}**; remaining "
             f"**{counts['remaining']}** ({counts['remaining_leads']} of them AIS leads: name, charter type and "
             "3+ days in the home-port geofence, but no licence or registry record).", "",
             "## Join table", "",
             "| Vessel | Port | Verdict | MMSI | Call sign | Official no. | Field sources | Keys matched | Licensee "
             "| Reason / notes |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in sorted(rows, key=lambda r: (r["verdict"] != "resolved", r["port_id"], r["name"])):
        b = r["best"]
        sources = (f"mmsi: {'fcc-licence ' + b['licence']['usi'] if b.get('licence') else 'ais-static'}; "
                   f"call sign: {b['call_sign_source'] or '-'}; official: {b['official_source'] or '-'}") if b else "-"
        lic = (b["licence"] or {}).get("licensee") if b else None
        verdict = r["verdict"] + (" (lead)" if r["lead"] else "")
        notes = r["reason"] or ""
        if b:
            notes = "; ".join(x for x in [notes, *b["notes"]] if x)
        elif r["candidates"]:
            notes += " | candidates: " + ", ".join(
                f"{c['mmsi']} [{'+'.join(c['via'])}] {'/'.join(c['conflicts']) or 'no method'}" for c in r["candidates"][:6])
        else:
            notes += " | checked: " + ", ".join(f"{k} {v}" for k, v in r["checked"].items())
        lines.append("| " + " | ".join(_cell(x) for x in (
            r["name"], r["port_id"], verdict, b and (b["mmsi"] if r["verdict"] == "resolved" or r["lead"] else
                                                       f"({b['mmsi']})"),
            b and b["call_sign"], b and b["official"], sources, b and ", ".join(b["keys"]), lic, notes)) + " |")
    lines += ["", "## Call signs broadcast by AIS name candidates, checked against FCC ULS", "",
              "| Vessel | Port | MMSI | Call sign | Verdict | Licences for the call sign (name, MMSI, status, licensee, "
              "state) |", "| --- | --- | --- | --- | --- | --- |"]
    for c in sorted(calls, key=lambda c: (c["verdict"] != "confirmed", c["port_id"], c["name"])):
        lic = "; ".join(f"{l['name']}, {l['mmsi'] or 'no MMSI'}, {l['status']}, {l['licensee'] or '-'}, "
                        f"{l['licensee_state'] or '-'}" for l in c["licences"]) or "none"
        lines.append("| " + " | ".join(_cell(x) for x in (c["name"], c["port_id"], c["mmsi"], c["call_sign"],
                                                             c["verdict"], lic)) + " |")
    lines += ["", "## Remaining by port", "", "| Port | Vessels | Remaining |", "| --- | --- | --- |"]
    lines += [f"| {p} | {v['vessels']} | {v['remaining']} |" for p, v in counts["remaining_by_port"].items()]
    lines += ["", "## Normalisation: vessels whose AIS static name matches changed", "",
              "| Vessel | Port | MMSIs only the first-pass rule matched | MMSIs only the new rule matches |",
              "| --- | --- | --- | --- |"]
    lines += [f"| {_cell(c['name'])} | {c['port_id']} | {_cell(', '.join(c['legacy_only']))} | "
              f"{_cell(', '.join(c['new_only']))} |" for c in norm_changes]
    lines += ["", "## Inputs", "", "```json", json.dumps(meta, indent=2, sort_keys=True), "```", ""]
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--fcc", type=Path, required=True)
    parser.add_argument("--psix", type=Path, nargs="*", default=[])
    parser.add_argument("--out", type=Path, required=True, help="private directory outside the repository")
    args = parser.parse_args(argv)
    if _inside_repository(args.out):
        parser.error("--out must be outside the repository: the join table is private registry data")
    registry = [json.loads(line) for line in args.resolved.read_text().splitlines() if line.strip()]
    statics, presence, window = load_ais(args.state)
    psix, psix_rows = load_psix(args.psix)
    names = {norm(v["name"]) for v in registry}
    licences = load_fcc(args.fcc, names=names, mmsis=set(statics),
                        calls={_alnum(s.call_sign) for s in statics.values() if s.call_sign} |
                        {p.call_sign for p in psix if p.call_sign},
                        officials={p.official for p in psix if p.official})
    rows = join(registry, statics, presence, licences, psix)
    calls = call_sign_report(rows, licences)
    normalisation, norm_changes = compare_normalisation(registry, statics)
    counts = summary(rows, normalisation)
    counts["call_signs"] = dict(sorted(Counter(c["verdict"].split(":")[0] for c in calls).items()))
    counts["inputs"] = {"registry": len(registry), "ais_statics": len(statics), "fcc_licences_kept": len(licences),
                        "psix_inspection_rows": psix_rows, "psix_vessels": len(psix),
                        "ais_presence_days": window}
    meta = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "inputs": {str(p): _sha256(p) for p in [args.resolved, args.fcc, *args.psix]},
            "ais_state": str(args.state), "ais_presence_window": window}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "join.json").write_text(json.dumps({"meta": meta, "counts": counts, "rows": rows,
                                                    "call_signs": calls, "normalisation_changes": norm_changes},
                                                   indent=1))
    (args.out / "join.md").write_text(markdown(rows, calls, counts, meta, norm_changes))
    print(json.dumps(counts, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
