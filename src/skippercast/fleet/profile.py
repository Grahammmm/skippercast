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

Exit status: 0 when every file is valid, 1 when any is not, 2 when the optional
`jsonschema` package is missing (a profile is never passed unvalidated).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from .. import validate
from ..platform.contracts import REPO

__all__ = ["KIND", "MAX_NOTES", "OFF_LIMITS_FILE", "WEBMAIL_DOMAINS", "load_off_limits", "policy_errors",
           "provenance", "review_flags", "validate_profile"]

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
