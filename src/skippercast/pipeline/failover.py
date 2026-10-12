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


def data_age(data, now):
    """Hours since the data's own clock (observation, issue, or a prediction's coverage end); never a retrieval time."""
    for key in ("sample_at", "issued_at", "coverage_end"):
        age = age_hours((data or {}).get(key), now)
        if age is not None:
            return age
    return None


def newer(a, b, now):
    """Whether data a is provably newer than data b; unknown clocks never win."""
    age_a, age_b = data_age(a, now), data_age(b, now)
    return age_a is not None and (age_b is None or age_a < age_b)


def ordered_source(chain, read, now, previous=None):
    """read(station, previous) returns an ordinary source row; retain only its own data.

    An errored primary can continue serving its retained data inside max_age. Once
    outside that window, try backups. If none is fresh, serve the newest data:
    a stale reading newer than the last served data stays stale under its own
    station; otherwise the last served data (and its station) is retained rather
    than relabelled as the primary.
    """
    previous = previous or {}
    previous_station = previous.get("station") or (previous.get("data") or {}).get("station") or chain[0]
    attempts, rows, first = [], {}, None
    for station in chain:
        row = read(station, previous if previous_station == station else None)
        attempts.extend(row.get("requests", []))
        usable = fresh(row, now)
        if row.get("status") == "ok" and not usable:
            row.update(status="stale", issue="Source data is outside this product's freshness or prediction coverage window")
        rows[station] = row
        first = first or row
        if usable:
            row["station"] = station
            if station != chain[0]:
                row["fallback_for"] = chain[0]
            row["requests"] = attempts
            return row
    # Nothing is fresh: serve the newest data on hand. A reading just returned
    # stale beats an older retained one (#565); retained data keeps its station
    # and original clocks, and only a station still in the chain can retain.
    newest, station = None, chain[0]
    for candidate in chain:
        row = rows[candidate]
        if row.get("status") == "stale" and row.get("data") and (newest is None or newer(row["data"], newest["data"], now)):
            newest, station = row, candidate
    if previous.get("data") and previous_station in rows and (newest is None or newer(previous["data"], newest["data"], now)):
        row = rows[previous_station]
        row.update(status="retained", data=previous["data"],
                   last_success_at=previous.get("last_success_at"),
                   data_retrieved_at=previous.get("data_retrieved_at"))
        station = previous_station
    else:
        row = newest or first
    row["station"] = station
    if station != chain[0]:
        row["fallback_for"] = chain[0]
    row["requests"] = attempts
    return row
