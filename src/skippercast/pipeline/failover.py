"""Ordered, opt-in station selection without changing legacy source entries."""
from datetime import datetime, timedelta
from .collect import age_hours


def station_chain(stations, role):
    """Primary IDs stay strings for current clients; roles opt into source metadata."""
    configured = stations.get("roles", {}).get(role)
    return configured["stations"] if configured else [stations[role]]


def fresh(row, now):
    data = row.get("data") or {}
    if row.get("status") not in ("ok", "retained") or not data:
        return False
    if row.get("kind") == "prediction":
        try:
            start = datetime.fromisoformat(data["coverage_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(data["coverage_end"].replace("Z", "+00:00"))
            if start > now + timedelta(days=1) or end < now:
                return False
        except (KeyError, TypeError, ValueError):
            return False
    sample = data.get("sample_at") or data.get("issued_at") or row.get("data_retrieved_at") or row.get("last_success_at")
    age = age_hours(sample, now)
    return age is not None and -1 <= age <= row["max_age_hours"]


def ordered_source(chain, read, now, previous=None):
    """read(station, previous) returns an ordinary source row; retain only its own data.

    An errored primary can continue serving its retained data inside max_age. Once
    outside that window, try backups. If none is fresh, preserve the last served
    data (and its station) rather than relabelling it as the primary.
    """
    previous = previous or {}
    previous_station = previous.get("station") or (previous.get("data") or {}).get("station") or chain[0]
    attempts, first = [], None
    for station in chain:
        row = read(station, previous if previous_station == station else None)
        attempts.extend(row.get("requests", []))
        usable = fresh(row, now)
        if row.get("status") == "ok" and not usable:
            row.update(status="stale", issue="Source data is outside this product's freshness or prediction coverage window")
        first = first or row
        if usable:
            row["station"] = station
            if station != chain[0]:
                row["fallback_for"] = chain[0]
            row["requests"] = attempts
            return row
    row = first
    if previous.get("data"):
        row.update(status="retained", data=previous["data"],
                   last_success_at=previous.get("last_success_at"),
                   data_retrieved_at=previous.get("data_retrieved_at"))
        station = previous_station
    else:
        station = chain[0]
    row["station"] = station
    if station != chain[0]:
        row["fallback_for"] = chain[0]
    row["requests"] = attempts
    return row
