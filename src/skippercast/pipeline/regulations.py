"""Publish reviewed rules and compare sources with a fixed, reviewed baseline.

A successful HTTP request is not a legal review. Changed content stays flagged
until the registry is reviewed and its approved fingerprint is updated.
"""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[3] / "dist/data/regulations.json"


def valid_window(window):
    try:
        start, end = (datetime.strptime(window[key], '%Y-%m-%d').date() for key in ('start', 'end'))
        if start > end or start.isoformat() != window['start'] or end.isoformat() != window['end']:
            return False
        if 'start_at' in window:
            opening = datetime.fromisoformat(window['start_at'].replace('Z', '+00:00'))
            if opening.tzinfo is None or opening.date() != start:
                return False
        return True
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def regulatory_snapshot(sources, now, registry=None):
    data = deepcopy(registry if registry is not None else json.loads(REGISTRY.read_text()))
    species = data.get('species', {})
    if data.get("schema_version") != 1 or not species or not all(
        isinstance(p, dict) and all(isinstance(p.get(key), str) for key in ('name', 'season', 'bag', 'size'))
        and isinstance(p.get('windows'), list) and all(valid_window(w) for w in p['windows']) and p.get('source_ids')
        and all(ident in data.get('sources', {}) for ident in p['source_ids'])
        for p in species.values()
    ):
        raise ValueError("Regulations registry is incomplete")
    checks = {}
    for ident, expected in data["sources"].items():
        source = sources.get(ident, {})
        checked = source.get("data_retrieved_at")
        try:
            age = (now - datetime.fromisoformat(checked.replace("Z", "+00:00"))).total_seconds() / 3600
        except (ValueError, AttributeError, TypeError):
            age = float("inf")
        fingerprint = (source.get("data") or {}).get("content_sha256")
        approved = expected.get("approved_content_sha256")
        if source.get("status") != "ok" or not -1 <= age <= 36:
            status = "unavailable"
        elif not approved or not fingerprint:
            status = "unreviewed"
        elif fingerprint != approved:
            status = "changed"
        else:
            status = "unchanged"
        checks[ident] = {"status": status, "checked_at": source.get("checked_at"),
                         "data_retrieved_at": checked, "content_sha256": fingerprint,
                         "source_status": source.get("status", "missing")}
    data["checks"] = checks
    data["checked_at"] = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    data["review_required"] = [ident for ident, check in checks.items() if check["status"] != "unchanged"]
    return data
