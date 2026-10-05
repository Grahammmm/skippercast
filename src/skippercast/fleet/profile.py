"""Validate charter fleet boat profiles: the OSINT agent's output contract.

    python -m skippercast.fleet.profile <profile.json> [<profile.json> ...]

docs/plans/charter-fleet/design.md section 8. A profile must match
schemas/fleet-profile.schema.json and pass the policy checks below, which the
schema cannot express:

- no `source_url` (in a provenance object or a conflict) on an off-limits host (D7);
- a value on an off-limits host (a booking link, an Instagram or Facebook handle
  or URL) only when it was read off a page (`method` `page`): the operator's
  site, a landing page or a report site, never a search result or a guess;
- `boat.mmsi` and `boat.ais.mmsi` agree, or a `conflicts[]` entry names the MMSI;
- `boat.reputation.other` holds numbers only, never review text;
- `notes` and `boat.ais.notes` are at most 2,000 characters.

A business email on a webmail domain is not an error: `review_flags()` lists it
so ingest can open a review. Ingest refuses any file with errors.

`profile_facts()` maps a valid profile to what ingest stores (CF-20): each
provenance object becomes one fact (`source_id` `osint`, rights `facts-only`,
confidence capped at 0.8 for `search` and `inference`); `trip_types[]` become
offerings; `conflicts[]` are returned for `fact-conflict` reviews. A null leaf
gives no fact (absence is not evidence). The Google rating and review count are
dropped: the Places terms allow storing `place_id` only (CF-16).

Exit status: 0 when every file is valid, 1 when any is not, 2 when the optional
`jsonschema` package is missing (a profile is never passed unvalidated).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit

from .. import validate
from ..platform.contracts import REPO
from .adapters.base import Fact, Offering, offering_name_norm
from .normalize import slugify

__all__ = ["CONFIDENCE_CAP", "DROPPED", "KIND", "MAX_NOTES", "OFF_LIMITS_FILE", "RIGHTS", "SOURCE_ID", "WEBMAIL_DOMAINS",
           "ProfileFacts", "load_off_limits", "offering_names", "policy_errors", "profile_facts", "profiled_at", "provenance",
           "review_flags", "validate_profile"]

KIND = "fleet-profile"
MAX_NOTES = 2000
# D7 and design.md section 6: the single list of off-limits hosts, shared with the region loader.
OFF_LIMITS_FILE = REPO / "catalog/fleet/off-limits.json"
# Social accounts whose handle and URL are values on an off-limits host.
OFF_LIMITS_SOCIAL = ("instagram", "facebook")
WEBMAIL_DOMAINS = frozenset({"aol.com", "att.net", "comcast.net", "gmail.com", "googlemail.com", "hotmail.com",
                             "icloud.com", "live.com", "mac.com", "me.com", "msn.com", "outlook.com", "proton.me",
                             "protonmail.com", "sbcglobal.net", "yahoo.com", "ymail.com"})
PROVENANCE_KEYS = frozenset({"value", "source_url", "retrieved_at", "method", "confidence"})
MMSI_CONFLICT_FIELDS = frozenset({"mmsi", "boat.mmsi", "ais.mmsi", "boat.ais.mmsi"})


def load_off_limits(path=None):
    """Off-limits hosts (lower case) from catalog/fleet/off-limits.json (`{"hosts": [{"host": ...}]}`).

    There is no built-in fallback: a missing or malformed catalog raises, so a
    profile is never validated against a stale or empty list.
    """
    path = OFF_LIMITS_FILE if path is None else Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"{path}: the off-limits catalog is missing; profiles cannot be validated "
                                "without it (catalog/fleet/off-limits.json, design.md section 6)") from None
    entries = data.get("hosts") if isinstance(data, dict) else None
    hosts = [entry.get("host") if isinstance(entry, dict) else None for entry in entries or ()]
    if not hosts or not all(isinstance(host, str) and host for host in hosts):
        raise ValueError(f"{path}: expected {{\"hosts\": [{{\"host\": ...}}, ...]}} with at least one host")
    return tuple(host.lower() for host in hosts)


def _host(url):
    if not isinstance(url, str):
        return ""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _on_host(host, hosts):
    return any(host == h or host.endswith("." + h) for h in hosts)


def _mentions_host(text, hosts):
    """True when a string names an off-limits host as a host (a URL, or a bare `host/path`)."""
    lowered = text.lower()
    return any(re.search(r"(?:^|[^a-z0-9-])" + re.escape(h) + r"(?![a-z0-9-])", lowered) for h in hosts)


def provenance(node, path="boat"):
    """Every provenance object under a node as (path, object), in document order."""
    if isinstance(node, dict):
        if PROVENANCE_KEYS <= set(node):
            yield path, node
            return
        for key, value in node.items():
            yield from provenance(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from provenance(value, f"{path}[{index}]")


def _value(node):
    return node.get("value") if isinstance(node, dict) else None


def policy_errors(doc, off_limits=None):
    """Policy violations as 'path: rule' strings; tolerant of a document that fails the schema."""
    hosts = load_off_limits() if off_limits is None else tuple(off_limits)
    doc = doc if isinstance(doc, dict) else {}
    boat = doc.get("boat") if isinstance(doc.get("boat"), dict) else {}
    errors = []
    social_paths = tuple(f"boat.social.{name}." for name in OFF_LIMITS_SOCIAL)
    for path, prov in provenance(boat):
        source_host = _host(prov.get("source_url"))
        if _on_host(source_host, hosts):
            errors.append(f"{path}: source_url on an off-limits host ({source_host})")
            continue
        value = prov.get("value")
        off_limits_value = (isinstance(value, str) and _mentions_host(value, hosts)) or path.startswith(social_paths)
        if off_limits_value and prov.get("method") != "page":
            errors.append(f"{path}: a value on an off-limits host must be read off the operator's site, a landing "
                          f"page or a report site (method 'page'), not {prov.get('method')!r}")
    conflicts = doc.get("conflicts") if isinstance(doc.get("conflicts"), list) else []
    for index, conflict in enumerate(conflicts):
        values = conflict.get("values") if isinstance(conflict, dict) else None
        for j, entry in enumerate(values if isinstance(values, list) else ()):
            source_host = _host(entry.get("source_url") if isinstance(entry, dict) else None)
            if _on_host(source_host, hosts):
                errors.append(f"conflicts[{index}].values[{j}]: source_url on an off-limits host ({source_host})")
    ais = boat.get("ais") if isinstance(boat.get("ais"), dict) else {}
    boat_mmsi, ais_mmsi = _value(boat.get("mmsi")), _value(ais.get("mmsi"))
    if boat_mmsi is not None and ais_mmsi is not None and str(boat_mmsi) != str(ais_mmsi):
        listed = any(isinstance(c, dict) and c.get("field") in MMSI_CONFLICT_FIELDS for c in conflicts)
        if not listed:
            errors.append("boat.mmsi: disagrees with boat.ais.mmsi and no conflicts[] entry names the MMSI")
    reputation = boat.get("reputation") if isinstance(boat.get("reputation"), dict) else {}
    others = reputation.get("other")
    for index, item in enumerate(others if isinstance(others, list) else ()):
        value = _value(item)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"boat.reputation.other[{index}]: numbers only (a rating or a count), never review text")
    for path, text in (("notes", doc.get("notes")), ("boat.ais.notes", _value(ais.get("notes")))):
        if isinstance(text, str) and len(text) > MAX_NOTES:
            errors.append(f"{path}: {len(text)} characters; at most {MAX_NOTES}")
    return errors


def review_flags(doc):
    """Valid but needs a person: a business email on a webmail domain (design.md section 6, operator-site)."""
    boat = doc.get("boat") if isinstance(doc, dict) and isinstance(doc.get("boat"), dict) else {}
    email = _value(boat.get("email_business"))
    if isinstance(email, str) and email.rpartition("@")[2].lower() in WEBMAIL_DOMAINS:
        return ["boat.email_business: webmail address; confirm it is published as the business contact"]
    return []


# ---- profile -> facts, offerings and conflicts (CF-20) -------------------------------------

SOURCE_ID = "osint"
RIGHTS = "facts-only"
CONFIDENCE_CAP = 0.8                       # design section 8: search and inference never claim more
CAPPED_METHODS = frozenset({"search", "inference"})
METHOD_STRENGTH = ("page", "api", "search", "inference")  # a combined fact takes its weakest part's method
# boat key -> fact field (the resolver's field names where a column exists, resolve.COLUMNS).
SCALARS = {
    "name": "name", "vessel_class": "vessel_class", "operator_business": "operator", "landing": "landing",
    "port": "port", "home_marina": "home_marina", "uscg_doc_number": "uscg_doc", "state_registration": "state_reg",
    "hull_id": "hull_id", "call_sign": "call_sign", "mmsi": "mmsi", "year_built": "year_built", "builder": "builder",
    "length_ft": "length_ft", "beam_ft": "beam_ft", "passengers_max": "passengers_max", "bunks": "bunks",
    "cruising_speed_kn": "cruise_kn", "website": "website", "booking_url": "booking_url",
    "booking_platform": "booking_platform", "phone_business": "phone_business", "email_business": "email_business",
    "contact_form_url": "contact_form_url", "fuel_surcharge": "fuel_surcharge",
    "cancellation_policy": "cancellation_policy",
}
LISTS = {"former_names": "former_names[]", "amenities": "amenities[]"}
SOCIAL_NETWORKS = ("instagram", "facebook", "youtube", "tiktok")
SOCIAL_PARTS = ("handle", "url", "followers", "posting_frequency")
AIS_PARTS = ("mmsi", "match_method", "confidence", "last_seen_source", "notes")
# Profile values never stored, with the reason (design section 17).
DROPPED = {
    "boat.reputation.google_rating": "Google Places terms: only place_id may be stored (CF-16)",
    "boat.reputation.google_reviews": "Google Places terms: only place_id may be stored (CF-16)",
}
HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
SPECIES = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_RUN_TIME = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})T(\d{2}):?(\d{2}):?(\d{2})Z")


@dataclass
class ProfileFacts:
    """What one valid profile stores: facts (``flagged`` ones need a review first), offerings and conflicts."""
    vessel_id: str
    region: str
    profiled_at: str | None                  # when the agent profiled the boat (profiled_at())
    facts: list = field(default_factory=list)          # Fact, source osint
    flagged: list = field(default_factory=list)        # Fact with flags (a webmail address)
    offerings: list = field(default_factory=list)      # (Offering, target species slugs)
    conflicts: list = field(default_factory=list)      # the profile's conflicts[] entries


def _confidence(prov: dict) -> float:
    value = float(prov["confidence"])
    return min(value, CONFIDENCE_CAP) if prov.get("method") in CAPPED_METHODS else value


def _fact(field_: str, prov: dict, flags: tuple[str, ...] = ()) -> Fact:
    return Fact(field_, prov["value"], SOURCE_ID, prov["source_url"], prov["method"], _confidence(prov), RIGHTS,
                prov["retrieved_at"], flags)


def _combined(field_: str, value: Any, parts: list[dict]) -> Fact:
    """One fact built from several provenance objects: the first part's source, the latest retrieval,
    the weakest method and the lowest (capped) confidence."""
    method = max((p["method"] for p in parts), key=METHOD_STRENGTH.index)
    return Fact(field_, value, SOURCE_ID, parts[0]["source_url"], method, min(_confidence(p) for p in parts), RIGHTS,
                max(p["retrieved_at"] for p in parts))


def _prov(node: Any) -> dict | None:
    return node if isinstance(node, dict) and PROVENANCE_KEYS <= set(node) and node.get("value") is not None else None


def profiled_at(doc: dict) -> str | None:
    """When the boat was profiled: the run id's timestamp (``20261011T101700Z-...`` or ``2026-10-11T101700Z-...``),
    else the latest ``retrieved_at`` in the profile, else None."""
    match = _RUN_TIME.match(str(doc.get("run_id") or ""))
    if match:
        y, mo, d, h, mi, s = match.groups()
        return f"{y}-{mo}-{d}T{h}:{mi}:{s}Z"
    times = [prov["retrieved_at"] for _path, prov in provenance(doc.get("boat") or {})]
    return max(times) if times else None


def _species(values: list[dict]) -> list[str]:
    out: list[str] = []
    for prov in values:
        slug = slugify(str(prov["value"])) if _prov(prov) else ""
        if slug and SPECIES.match(slug) and slug not in out:
            out.append(slug)
    return out


def _trip(trip: dict) -> tuple[Fact, Offering, list[str]] | None:
    """A trip_types[] entry as its fact and offering; None without a name."""
    from .adapters.landing_pages import season_range, trip_type  # noqa: PLC0415  (adapters import this module)
    name = _prov(trip.get("name"))
    if name is None or not isinstance(name["value"], str) or not name["value"].strip():
        return None
    parts = {key: _prov(trip.get(key)) for key in ("name", "duration_h", "price_usd", "departs", "season")}
    species = [p for p in trip.get("target_species") or () if _prov(p)]
    value = {key: prov["value"] for key, prov in parts.items() if prov is not None}
    if species:
        value["target_species"] = [p["value"] for p in species]
    fact = _combined("trip_types[]", value, [p for p in parts.values() if p is not None] + species)
    label = name["value"].strip()[:120].strip()
    price, duration, departs = value.get("price_usd"), value.get("duration_h"), value.get("departs")
    season = season_range(value["season"]) if isinstance(value.get("season"), str) else None
    offering = Offering(
        label, trip_type(label), (fact,),
        price_cents=round(price * 100) if isinstance(price, (int, float)) and price >= 0 else None,
        duration_h=duration if isinstance(duration, (int, float)) and duration > 0 else None,
        departs_local=departs if isinstance(departs, str) and HHMM.match(departs) else None,
        season_from=season[0] if season else None, season_to=season[1] if season else None)
    return fact, offering, _species(species)


def profile_facts(doc: dict) -> ProfileFacts:
    """Map a profile that passed ``validate_profile`` to its facts, offerings and conflicts."""
    boat = doc["boat"]
    out = ProfileFacts(doc["vessel_id"], doc["region"], profiled_at(doc))
    flags = review_flags(doc)
    for key, field_ in SCALARS.items():
        prov = _prov(boat.get(key))
        if prov is not None:
            flagged = ("webmail",) if key == "email_business" and flags else ()
            (out.flagged if flagged else out.facts).append(_fact(field_, prov, flagged))
    for key, field_ in LISTS.items():
        out.facts += [_fact(field_, prov) for item in boat.get(key) or () if (prov := _prov(item))]
    by_source: dict[str, list[dict]] = {}
    for item in boat.get("waters") or ():
        if (prov := _prov(item)) is not None:
            by_source.setdefault(prov["source_url"], []).append(prov)
    for parts in by_source.values():  # one waters fact per page: the list that page supports
        values = sorted({p["value"] for p in parts}, key=lambda v: ("ocean", "bay", "delta", "inland").index(v))
        out.facts.append(_combined("waters", values, parts))
    for network in SOCIAL_NETWORKS:
        account = (boat.get("social") or {}).get(network) or {}
        for part in SOCIAL_PARTS:
            if (prov := _prov(account.get(part))) is not None:
                out.facts.append(_fact(f"social.{network}.{part}", prov))
    for trip in boat.get("trip_types") or ():
        mapped = _trip(trip)
        if mapped is not None:
            fact, offering, species = mapped
            out.facts.append(fact)
            out.offerings.append((offering, species))
    for captain in boat.get("captains") or ():
        name, role = _prov(captain.get("name")), _prov(captain.get("role"))
        if name is not None:
            value = {"name": name["value"], **({"role": role["value"]} if role else {})}
            out.facts.append(_combined("captains[]", value, [name] + ([role] if role else [])))
    reporting = boat.get("catch_reporting") or {}
    out.facts += [_fact("catch_reporting.sources[]", prov) for item in reporting.get("sources") or ()
                  if (prov := _prov(item))]
    if (prov := _prov(reporting.get("frequency"))) is not None:
        out.facts.append(_fact("catch_reporting.frequency", prov))
    out.facts += [_fact("reputation.other[]", prov) for item in (boat.get("reputation") or {}).get("other") or ()
                  if (prov := _prov(item))]
    for photo in boat.get("photos") or ():
        url, credit = _prov(photo.get("url")), _prov(photo.get("attribution"))
        if url is not None and credit is not None:
            out.facts.append(_combined("photos[]", {"url": url["value"], "attribution": credit["value"]}, [url, credit]))
    ais = boat.get("ais") or {}
    for part in AIS_PARTS:
        if (prov := _prov(ais.get(part))) is not None:
            out.facts.append(_fact(f"ais.{part}", prov))
    out.conflicts = [c for c in doc.get("conflicts") or () if isinstance(c, dict)]
    return out


def offering_names(offerings) -> set[str]:
    """The name keys (``offering_name_norm``) of stored offerings: an osint trip never duplicates one."""
    return {offering_name_norm(o["name"]) for o in offerings or () if isinstance(o.get("name"), str)}


def validate_profile(doc, off_limits=None):
    """Schema errors plus every policy error; empty when the profile may be ingested.

    Raises validate.MissingDependency when jsonschema is not installed: a
    profile is never accepted on the policy checks alone.
    """
    policy = policy_errors(doc, off_limits)   # first, so a missing off-limits catalog fails even without jsonschema
    return validate.errors(KIND, doc) + policy


def main(argv=None):
    parser = argparse.ArgumentParser(prog="skippercast.fleet.profile", description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    status = 0
    for path in args.paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            problems = validate_profile(document)
        except validate.MissingDependency as error:
            print(error, file=sys.stderr)
            return 2
        except (OSError, ValueError) as error:
            print(f"{path}: {type(error).__name__}: {error}", file=sys.stderr)
            status = 1
            continue
        if problems:
            status = 1
            print(f"{path}: {len(problems)} error(s)", file=sys.stderr)
            for problem in problems[:50]:
                print(f"  {problem}", file=sys.stderr)
        else:
            print(f"{path}: valid {KIND}")
            for flag in review_flags(document):
                print(f"  review: {flag}")
    return status


if __name__ == "__main__":
    sys.exit(main())
