"""Small, strict parsers for published facts. Missing is never calm or zero."""

from datetime import date, datetime, timezone
import hashlib
import html
import math
import re
from urllib.parse import urljoin

SPECIES = ("lingcod", "rockfish", "halibut", "salmon", "albacore", "bluefin", "dungeness")
GROUND_IDS = {"pecho rock": "CHARTER-PECHO", "diablo": "CHARTER-DIABLO", "morro bay": "CHARTER-MORRO"}


def plain(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def numeric(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def iso_time(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Source timestamp lacks timezone")
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def species_id(label):
    patterns = [("lingcod", r"lingcod"), ("rockfish", r"rockfish|rockcod|bocaccio|bolina"),
                ("halibut", r"halibut"), ("salmon", r"salmon|chinook"),
                ("bluefin", r"bluefin"), ("albacore", r"albacore"), ("dungeness", r"dungeness")]
    return next((key for key, pattern in patterns if re.search(pattern, label, re.I)), None)


def charter_reports(body, day, url):
    """Parse the publisher's sometimes unclosed <tr>s, not arbitrary page prose."""
    d = date.fromisoformat(day)
    if f"{d:%B} {d.day}, {d.year}" not in body or "Fish Counts" not in body:
        raise ValueError("Report page/date not recognized; cannot infer zero trips")
    reports, identities, duplicates = [], {}, set()
    for tr in re.split(r"<tr\b[^>]*>", body, flags=re.I):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr.split("</tr>")[0], flags=re.S | re.I)
        if len(cells) < 3 or not any(p in cells[0] for p in ("Morro Bay, CA", "Avila Beach, CA")):
            continue
        boat = re.search(r"<b>(.*?)</b>", cells[0], re.S | re.I)
        link = re.search(r'href=["\']([^"\']+)["\']', cells[0])
        if not boat or not link:
            raise ValueError("Local trip missing boat identity")
        details, catch = plain(cells[1]), plain(cells[2])
        ground_match = re.search(r"<i>(.*?)</i>", cells[1], re.S | re.I)
        ground = plain(ground_match[1]) if ground_match else None
        anglers_match = re.search(r"\b(\d+) Anglers?\b", details, re.I)
        trip_type = plain(re.sub(r"<i>.*?</i>", "", cells[1], flags=re.S | re.I))
        trip_type = re.sub(r"^\d+ Anglers?\s*", "", trip_type, flags=re.I)
        catches = []
        for part in re.split(r",\s+(?=\d)", catch):
            count_match = re.match(r"([\d,]+)\s+(.+)", part)
            if not count_match:
                continue
            label = re.sub(r"\([^)]*\)", "", count_match[2]).strip()
            key = species_id(label)
            if not key:
                continue
            disposition = "released" if re.search(r"release", label, re.I) else "reported"
            label = re.sub(r"\s+Released?\b", "", label, flags=re.I).strip()
            catches.append({"species": key, "label": label, "count": int(count_match[1].replace(",", "")),
                            "disposition": disposition})
        # A blank or changed count cell must not silently become a zero catch.
        if catch and not re.search(r"\d|no fish|no catch", catch, re.I):
            raise ValueError("Unrecognized local catch cell")
        name = plain(boat[1])
        identity = f"{day}|{name}|{trip_type}|{ground}"
        duplicate = identity + "|" + catch
        if duplicate in duplicates:
            continue
        duplicates.add(duplicate)
        identities[identity] = identities.get(identity, 0) + 1
        ident = hashlib.sha256(f"{identity}|{identities[identity]}".encode()).hexdigest()[:16]
        reports.append({"id": ident, "date": day, "boat": name,
                        "port": "Morro Bay" if "Morro Bay, CA" in cells[0] else "Avila Beach",
                        "trip_type": trip_type, "anglers": int(anglers_match[1]) if anglers_match else None,
                        "ground": ground, "ground_id": GROUND_IDS.get((ground or "").lower()),
                        "catches": catches, "species": sorted({c["species"] for c in catches if c["count"] > 0}),
                        "source_url": url, "boat_source_url": urljoin(url, link[1]),
                        "fishing_hours": None, "coordinates": None, "depth_ft": None})
    return {"date": day, "reports": reports, "sample_date": day,
            "sample_time_precision": "calendar date only; trip times not published"}


def ndbc(body, station, spectral=False):
    lines = body.strip().splitlines()
    if len(lines) < 3 or not lines[0].startswith("#YY"):
        raise ValueError("NDBC table header missing")
    keys, units = lines[0].lstrip("#").split(), lines[1].lstrip("#").split()
    required = {"WVHT", "SwH", "SwP", "WWH", "WWP"} if spectral else {"WVHT", "DPD", "WTMP", "WSPD"}
    if not required.issubset(keys):
        raise ValueError("NDBC columns changed")
    unit_map = dict(zip(keys, units))
    if unit_map["WVHT"] != "m" or (not spectral and unit_map["WSPD"] != "m/s"):
        raise ValueError("Unexpected NDBC units")
    rows = []
    missing = {"MM", "999", "999.0", "9999", "9999.0"}
    for line in lines[2:]:
        values = line.split()
        if len(values) != len(keys):
            raise ValueError("Malformed NDBC row")
        t = datetime(*map(int, values[:5]), tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        row = {"time": t}
        for k, v in zip(keys[5:], values[5:]):
            row[k] = None if v in missing else v if k in ("SwD", "WWD", "STEEPNESS") else numeric(v)
            if k in ("WVHT", "DPD", "APD", "SwH", "SwP", "WWH", "WWP", "WTMP", "ATMP", "DEWP") and row[k] == 99:
                row[k] = None
        rows.append(row)
        if len(rows) == 144:
            break
    if not rows:
        raise ValueError("NDBC returned no observations")
    return {"station": station, "sample_at": max(r["time"] for r in rows), "units": unit_map, "observations": rows}


def tides(data):
    if data.get("error") or not isinstance(data.get("predictions"), list) or not data["predictions"]:
        raise ValueError("NOAA tide predictions unavailable")
    rows = [{"time": iso_time(p["t"].replace(" ", "T") + "Z"), "height_ft": numeric(p["v"]),
             "type": p.get("type")} for p in data["predictions"]]
    if any(r["height_ft"] is None for r in rows):
        raise ValueError("Invalid tide height")
    return {"station": "9412110", "datum": "MLLW", "units": "ft", "timezone": "UTC",
            "coverage_start": rows[0]["time"], "coverage_end": rows[-1]["time"], "predictions": rows,
            "note": "Port San Luis reference. Not Morro Bay bar current or slack-water predictions."}


def alerts(data):
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ValueError("NWS alert response not recognized")
    rows = []
    for f in data["features"]:
        p = f["properties"]
        rows.append({k: p.get(k) for k in ("id", "event", "headline", "severity", "sent", "effective", "onset", "expires", "ends")})
    return {"issued_at": data.get("updated"), "alerts": rows,
            "note": "Daily audit only. The app checks active advisories again with live weather."}


def erddap_metadata(data):
    rows = data["table"]["rows"]
    attrs, dimensions, variables = {}, {}, {}
    for kind, variable, attribute, dtype, value in rows:
        if kind == "attribute":
            attrs.setdefault(variable, {})[attribute] = value
        elif kind == "dimension":
            dimensions[variable] = value
        elif kind == "variable":
            variables[variable] = [d.strip() for d in value.split(",")]
    if not {"time", "latitude", "longitude"}.issubset(dimensions):
        raise ValueError("ERDDAP dimensions changed")
    return {"attrs": attrs, "dimensions": dimensions, "variables": variables}


def erddap_query(meta, variables, bounds, stride):
    """Coordinate requests follow the source axis orientation, including descending latitude."""
    g = meta["attrs"]["NC_GLOBAL"]
    when = iso_time(g["time_coverage_end"])
    parts = []
    for variable in variables:
        dims = meta["variables"][variable]
        slices = []
        for dim in dims:
            if dim == "time":
                slices.append(f"[({when})]")
            elif dim in ("latitude", "longitude"):
                lo, hi = bounds[dim]
                if "averageSpacing=-" in meta["dimensions"][dim]:
                    lo, hi = hi, lo
                slices.append(f"[({lo}):{stride}:({hi})]")
            elif dim == "altitude":
                slices.append("[0]")
            else:
                raise ValueError("Unsupported ERDDAP dimension")
        parts.append(variable + "".join(slices))
    return ",".join(parts)


def erddap_grid(data, meta, variables, kind):
    table = data["table"]
    keys, units = table["columnNames"], table["columnUnits"]
    unit_map = dict(zip(keys, units))
    required = {"time", "latitude", "longitude", *variables}
    if not required.issubset(keys) or unit_map.get("time") != "UTC":
        raise ValueError("ERDDAP grid columns/time units changed")
    expected = {"analysed_sst": "degree_C", "analysis_error": "degree_C", "chlorophyll": "mg m-3",
                "water_u": "m s-1", "water_v": "m s-1"}
    for v in variables:
        if v in expected and unit_map[v] != expected[v]:
            raise ValueError(f"Unexpected {v} units")
    samples, valid = [], 0
    for raw in table["rows"]:
        row = dict(zip(keys, raw))
        for v in variables:
            value = numeric(row[v])
            attrs = meta["attrs"].get(v, {})
            fill = numeric(attrs.get("_FillValue"))
            low, high = numeric(attrs.get("valid_min")), numeric(attrs.get("valid_max"))
            if value is not None and (value == fill or (low is not None and value < low) or (high is not None and value > high)):
                value = None
            row[v] = round(value, 5) if value is not None else None
        if kind == "sst" and (row.get("mask") is None or int(row["mask"]) & 1 == 0 or int(row["mask"]) & 2):
            row["analysed_sst"] = None
        if kind == "currents" and (row.get("number_of_sites") is None or row["number_of_sites"] < 2):
            row["water_u"] = row["water_v"] = None
        row["time"] = iso_time(row["time"])
        row["latitude"], row["longitude"] = round(float(row["latitude"]), 5), round(float(row["longitude"]), 5)
        primary = ["water_u", "water_v"] if kind == "currents" else [variables[0]]
        valid += all(row[v] is not None for v in primary)
        samples.append(row)
    if not samples:
        raise ValueError("Empty ERDDAP grid")
    times = {s["time"] for s in samples}
    if len(times) != 1:
        raise ValueError("Expected one dated grid; no composite invented")
    g = meta["attrs"]["NC_GLOBAL"]
    return {"sample_at": times.pop(), "metadata_created_at": g.get("date_created"),
            "units": unit_map, "valid_cells": valid, "total_cells": len(samples), "samples": samples,
            "title": g.get("title"), "license": g.get("license"), "kind": kind,
            "native_resolution_degrees": [g.get("geospatial_lat_resolution"), g.get("geospatial_lon_resolution")]}


def page_watch(body, keywords):
    """Detect a reviewed page changing, without pretending to interpret law."""
    text = watch_content(body)
    if not all(re.search(word, text, re.I) for word in keywords):
        raise ValueError("Expected source content absent; possible error/challenge page")
    return {"content_sha256": hashlib.sha256(text.encode()).hexdigest(), "interpretation": "manual review required",
            "normalization": "text-and-links-v3", "permission_to_fish": None}


def watch_content(body):
    """Track document links too: a replacement PDF can keep the same link label."""
    body = re.sub(r"<!--.*?(?:-->|$)", "", body, flags=re.S)
    cleaned = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", body, flags=re.S | re.I)
    links = sorted({html.unescape(value) for _, value in re.findall(r'''\bhref\s*=\s*(["'])(.*?)\1''', cleaned, re.I | re.S)
                    if value and not value.startswith(('#', 'javascript:', 'mailto:', 'tel:'))})
    return plain(cleaned) + '\nDOCUMENT LINKS\n' + '\n'.join(links)
