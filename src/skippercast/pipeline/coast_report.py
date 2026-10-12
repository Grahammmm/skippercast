"""The coast report's base assembled from SkipperCast collectors (FE-87).

    python -m skippercast.pipeline.coast_report --root var/live-published

Writes `regions/morro-bay/coast-report.json`, the SLO county `packages/coast`
`Report` that `/api/coast/report` serves when `COAST_FEEDS` lists `report`
(`server/coast-data.ts` merges FE-84's nearshore and beach feeds into it).
NWS area forecasts and alerts and the CO-OPS tides have no SkipperCast
collector, so they are fetched here with `fish` `src/providers/index.ts` rules
(`expandGrid`, `filterAlerts`, `parseTides`). Buoys come from this cycle's
`latest.json` (`live.py`); catches, sea-surface temperature and protected areas
from the daily feed (`collect.py`), with `fish` `catches.ts` rules. Each source
keeps its own status, outcome and clocks; a failed one has no rows. As in
`fish`, a run with no populated forecast and no buoy reading under 3 h old
writes nothing, so the Worker falls back to Fish once the last report is 2 h old.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .. import http
from ..platform.contracts import atomic_json
from .coast_snapshots import COUNTY, REGION, _ms, _number, _read
from .goes_frames import iso

# packages/coast/src/counties.ts `slo` (a test keeps them equal): id, name, lat, lon, landLat, landLon, forecastZone.
AREAS = (("north", "Cambria & San Simeon", 35.63, -121.2, 35.57, -121.1, "PZZ645"),
         ("central", "Morro Bay & Point Estero", 35.35, -120.95, 35.365, -120.85, "PZZ645"),
         ("south", "Avila Beach & Pismo", 35.16, -120.78, 35.17, -120.74, "PZZ645"))
BUOYS = (("46215", "Diablo Canyon"), ("46028", "Cape San Martin"))
TIDE_STATION, TIDE_NAME, TIMEZONE = "9412110", "Port San Luis", "America/Los_Angeles"
NWS, COOPS = "https://api.weather.gov/", "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?"
ALERTS_URL = NWS + "alerts/active?area=CA,PZ"  # CA alone omits marine-zone alerts
DAILY_URL = f"https://raw.githubusercontent.com/Grahammmm/skippercast/data/regions/{REGION}/latest.json"
CATALOG_URL = "https://github.com/Grahammmm/skippercast/blob/a481da68923649db6fda277af4bd6f40813f6436/catalog/sources.json"
HOSTS = ("api.weather.gov", "api.tidesandcurrents.noaa.gov", "raw.githubusercontent.com")
FT, KT, HOUR, DAY = 3.280839895, 1.943844492, 3_600_000, 86_400_000
FIELDS = (("windKnots", "windSpeed", "knots"), ("gustKnots", "windGust", "knots"), ("waveFt", "waveHeight", "feet"),
          ("wavePeriodS", "wavePeriod", "seconds"), ("swellFt", "primarySwellHeight", "feet"),
          ("swellPeriodS", "primarySwellPeriod", "seconds"), ("windWaveFt", "windWaveHeight", "feet"),
          ("windDirectionDeg", "windDirection", "degrees"), ("airTempF", "temperature", "fahrenheit"),
          ("precipPct", "probabilityOfPrecipitation", "percent"), ("cloudCoverPct", "skyCover", "percent"),
          ("relativeHumidityPct", "relativeHumidity", "percent"))
UNITS = {"knots": {"m_s-1": KT, "kn": 1, "kt": 1, "knot": 1}, "feet": {"m": FT, "ft": 1}, "seconds": {"s": 1},
         "degrees": {"degree_(angle)": 1, "degree": 1}, "percent": {"percent": 1}}
NDBC_UNITS = {"WVHT": "m", "DPD": "sec", "WTMP": "degC", "WSPD": "m/s", "GST": "m/s"}
DURATION = re.compile(r"P(?:([\d.]+)W)?(?:([\d.]+)D)?(?:T(?:([\d.]+)H)?(?:([\d.]+)M)?(?:([\d.]+)S)?)?")
TIDE_TIME, DATE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d"), re.compile(r"\d{4}-\d{2}-\d{2}")
INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)")
TRIP_ID, LABEL = re.compile(r"[a-f0-9]{16}"), re.compile(r"[<>\x00-\x1f]")
HABITAT = "Reviewed SkipperCast habitat is served separately through the current release gate; partial coverage, physical fit only."
FAILURES = (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError)


def _obj(value): return value if isinstance(value, dict) else {}
def _list(value): return value if isinstance(value, list) else []
def _iso(value): return iso(_ms(value)) if _ms(value) is not None else None
def _error(status, error, **extra): return {**status, "outcome": "error", **extra, "error": str(error)[:300]}


def _get(session, url, limit=2_000_000):
    return json.loads(session.get(url, timeout=12, max_bytes=limit, attempts=2, allowed_hosts=HOSTS,
                                  headers={"Accept": "application/geo+json,application/json"}).body)


def interval(text):
    """An NWS `validTime` (`start/duration` or `start/end`) as (start, end) epoch ms; ValueError otherwise."""
    start, _, end = text.partition("/") if isinstance(text, str) else ("", "", "")
    a, match = _ms(start), DURATION.fullmatch(end)
    if match and any(match.groups()) and a is not None:
        w, d, h, m, s = (float(v or 0) for v in match.groups())
        b = a + ((w * 7 + d) * 86400 + h * 3600 + m * 60 + s) * 1000
    else:
        b = _ms(end)
    if a is None or b is None or b <= a:
        raise ValueError("Invalid forecast interval")
    return a, b


def convert(value, uom, target):
    """An NWS value in its WMO unit as knots, feet, seconds, degrees, °F or percent; None for anything else."""
    unit = uom.split(":")[-1] if isinstance(uom, str) else None
    if not _number(value) or not unit:
        return None
    if target == "fahrenheit":
        return value * 1.8 + 32 if unit == "degC" else value if unit == "degF" else None
    if target == "knots" and unit == "km_h-1":
        return value / 1.852
    scale = UNITS[target].get(unit)
    return None if scale is None or (target == "percent" and not 0 <= value <= 100) else value * scale


def expand(grid, now):
    """`expandGrid`: 168 hourly rows from this hour; an hour is kept only with a wind, wave or air value."""
    series = {}
    for out, key, target in FIELDS:
        field, rows = _obj(grid.get(key)), []
        for row in _list(field.get("values")):
            try:
                rows.append((*interval(row["validTime"]), convert(row.get("value"), field.get("uom"), target)))
            except FAILURES:
                continue  # a malformed interval stays unavailable
        series[out] = rows
    start, hours = now // HOUR * HOUR, []
    for at in range(start, start + 168 * HOUR, HOUR):
        row = {"at": iso(at), **{out: next((v for a, b, v in rows if a <= at < b), None) for out, rows in series.items()}}
        if any(row[k] is not None for k in ("windKnots", "gustKnots", "waveFt", "wavePeriodS", "airTempF")):
            hours.append(row)
    return hours


def forecast(session, area, now, fetched):
    """One area's `AreaForecast`, its status and the alert zones of its marine and shore points."""
    ident, name, lat, lon, land_lat, land_lon, zone = area
    status = {"id": f"nws-{ident}", "label": f"NWS · {name}", "url": f"{NWS}points/{lat},{lon}", "kind": "forecast", "fetchedAt": fetched}
    row = {"id": ident, "hours": [], "sourceId": status["id"], "point": [lon, lat]}
    try:
        point = _obj(_get(session, status["url"]).get("properties"))
        if not str(point.get("forecastGridData")).startswith(NWS + "gridpoints/"):
            raise ValueError("Missing NWS grid endpoint")
        status["url"] = point["forecastGridData"]
        grid = _get(session, status["url"]).get("properties")
        land = _obj(_get(session, f"{NWS}points/{land_lat},{land_lon}").get("properties"))
        if not isinstance(grid, dict) or not isinstance(_obj(grid.get("windSpeed")).get("values"), list):
            raise ValueError("Incomplete NWS grid")
        hours = expand(grid, now)
        if not hours:
            raise ValueError("No populated forecast hours")
        try:
            through = iso(int(interval(grid.get("validTimes"))[1]))
        except ValueError:
            through = None
        issued = _iso(grid.get("updateTime"))
        zones = [zone, *(z.split("/")[-1] for z in (point.get("forecastZone"), point.get("county"),
                                                    land.get("forecastZone"), land.get("county")) if isinstance(z, str))]
        clocks = {k: v for k, v in (("issuedAt", issued), ("validThrough", through)) if v}
        return {**row, "hours": hours, **({"issuedAt": issued} if issued else {})}, {**status, "outcome": "ok", **clocks}, zones
    except FAILURES as error:
        return row, _error(status, error), [zone]


def _ring(x, y, ring):
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        (a, b), (c, d) = ring[i][:2], ring[j][:2]
        inside ^= (b > y) != (d > y) and x < (c - a) * (y - b) / (d - b) + a
        j = i
    return inside


def _inside(area, geometry):
    kind = _obj(geometry).get("type")
    polygons = [geometry["coordinates"]] if kind == "Polygon" else geometry["coordinates"] if kind == "MultiPolygon" else []
    return any(rings and _ring(x, y, rings[0]) and not any(_ring(x, y, r) for r in rings[1:])
               for rings in polygons for x, y in ((area[3], area[2]), (area[5], area[4])))


def alerts(payload, zones):
    """`filterAlerts`: active alerts whose zones or polygon reach a county area, tagged with those areas."""
    if not isinstance(_obj(payload).get("features"), list):
        raise ValueError("Missing alert feature collection")
    if _obj(payload.get("pagination")).get("next"):
        raise ValueError("Incomplete alerts: unexpected pagination")
    unique = {}
    for feature in payload["features"]:
        p = _obj(_obj(feature).get("properties"))
        if not isinstance(p.get("event"), str):
            continue
        affected = {z.split("/")[-1] for z in _list(p.get("affectedZones")) if isinstance(z, str)}
        affected |= {z for z in _list(_obj(p.get("geocode")).get("UGC")) if isinstance(z, str)}
        areas = [a[0] for a in AREAS if affected.intersection(zones.get(a[0], ())) or _inside(a, feature.get("geometry"))]
        ident = next((str(v) for v in (feature.get("id"), p.get("id"), p.get("@id")) if v is not None), "")
        if areas and ident:
            unique[ident] = {"id": ident, "event": p["event"], "headline": str(p["event"] if p.get("headline") is None else p["headline"]),
                             "description": str(p.get("description") or ""), "effective": _iso(p.get("effective")),
                             "expires": _iso(p.get("expires")), "url": p["@id"] if isinstance(p.get("@id"), str) else ident,
                             "areaIds": areas}
    return list(unique.values())


def tide_url(now, product):
    """CO-OPS predictions from the previous UTC day (the start of a Pacific day) to three days ahead."""
    day = lambda moment: moment.strftime("%Y%m%d")
    return COOPS + urlencode({"product": "predictions", "application": "SkipperCast", "begin_date": day(now - timedelta(days=1)),
                              "end_date": day(now + timedelta(days=3)), "datum": "MLLW", "station": TIDE_STATION,
                              "time_zone": "gmt", "units": "metric", "interval": product, "format": "json"})


def tides(payload, events):
    """`parseTides`: MLLW predictions in metres as feet at their own times; any bad row fails the product."""
    if _obj(payload).get("error"):
        raise ValueError(str(_obj(payload["error"]).get("message") or "CO-OPS error"))
    out = []
    for p in _list(_obj(payload).get("predictions")) or [None]:
        t, v = _obj(p).get("t"), _obj(p).get("v")
        if not isinstance(t, str) or not TIDE_TIME.fullmatch(t) or not isinstance(v, str) or not v.strip():
            raise ValueError("Invalid tide record" if p else "Missing tide predictions")
        at, value = _ms(t.replace(" ", "T") + ":00Z"), float(v)
        if at is None or not math.isfinite(value) or (events and p.get("type") not in ("H", "L")):
            raise ValueError("Invalid tide value/time")
        out.append({"at": iso(at), "heightFt": value * FT, **({"type": p["type"]} if events else {})})
    return out


def observation(data, station, url):
    """`parseNdbc` over the live feed's rows: the newest with a wave height, else with wind; one time for every field."""
    if data.get("station") != station or any(_obj(data.get("units")).get(k) != u for k, u in NDBC_UNITS.items()):
        raise ValueError("NDBC columns unavailable")
    rows = sorted((r for r in _list(data.get("observations")) if isinstance(r, dict) and _ms(r.get("time")) is not None
                   and (_number(r.get("WVHT")) or _number(r.get("WSPD")))), key=lambda r: _ms(r["time"]), reverse=True)
    row = next((r for r in rows if _number(r.get("WVHT"))), rows[0] if rows else None)
    if row is None:
        raise ValueError("No valid NDBC observations")
    value = lambda k, scale=1, offset=0: row[k] * scale + offset if _number(row.get(k)) else None
    return {"stationId": station, "observedAt": iso(_ms(row["time"])), "url": url, "waveFt": value("WVHT", FT),
            "wavePeriodS": value("DPD"), "waterTempF": value("WTMP", 1.8, 32), "windKnots": value("WSPD", KT),
            "gustKnots": value("GST", KT), "directionDeg": value("MWD")}


def buoys(live, fallback):
    """Each buoy's `Observation` and status from the live feed, with the live collector's fetch clock and outcome."""
    feed = _obj(live.get("sources")) if _obj(live).get("schema_version") == 1 and live.get("region_id") == REGION else {}
    rows, statuses = [], []
    for station, name in BUOYS:
        url = f"https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"
        record = next((s for s in feed.values() if isinstance(s, dict) and s.get("url") == url), {})
        status = {"id": f"ndbc-{station}", "label": f"NDBC · {name}", "url": url, "kind": "observation"}
        try:
            fetched = _iso(record.get("data_retrieved_at"))
            if record.get("status") not in ("ok", "stale") or not isinstance(record.get("data"), dict) or not fetched:
                raise ValueError(record.get("issue") or "No current record in the live buoy feed")
            rows.append(observation(record["data"], station, url))
            statuses.append({**status, "outcome": "ok", "fetchedAt": fetched})
        except FAILURES as error:
            statuses.append(_error(status, error, fetchedAt=_iso(record.get("checked_at")) or fallback))
    return rows, statuses


def _instant(value):
    ms = _ms(value) if isinstance(value, str) and INSTANT.fullmatch(value) else None
    if ms is None or iso(ms)[:19] != value[:19]:
        raise ValueError("Invalid catch source clock")
    return ms


def _fresh(value, now):
    if not -300_000 <= now - _instant(value) <= 72 * HOUR:
        raise ValueError("Catch source clock is future dated or older than 72 hours")
    return value


def _date(value):
    if isinstance(value, str) and DATE.fullmatch(value):
        try:
            return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) * 1000
        except ValueError:
            pass
    raise ValueError("Invalid catch trip date")


def _local_day(ms): return _date(datetime.fromtimestamp(ms / 1000, ZoneInfo(TIMEZONE)).date().isoformat())
def _integer(value, high): return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= high


def _short(value, limit):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > limit or LABEL.search(value):
        raise ValueError("Invalid catch factual label")
    return value


def _publisher(value, date):
    if value != f"https://www.socalfishreports.com/dock_totals/boats.php?date={date}":
        raise ValueError("Catch publisher URL/date mismatch")
    return value


def _normalized(r, retrieved):
    """A trip's linked factual counts only, never publisher prose or a catch position."""
    if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not TRIP_ID.fullmatch(r["id"]) or r.get("port") not in ("Morro Bay", "Avila Beach"):
        raise ValueError("Invalid catch trip identity or port")
    if r.get("anglers", "") is not None and not _integer(r.get("anglers"), 1000):
        raise ValueError("Invalid or missing angler count")
    if not 0 < len(_list(r.get("catches"))) <= 100:
        raise ValueError("Missing catch categories; cannot infer zero catch")
    species = []
    for c in r["catches"]:
        if not _integer(_obj(c).get("count"), 1_000_000) or c.get("disposition") not in ("reported", "retained", "released"):
            raise ValueError("Invalid or missing catch count/disposition")
        _short(c.get("species"), 60)
        species.append({"name": _short(c.get("label"), 80), "count": c["count"], "disposition": c["disposition"],
                        **({"released": True} if c["disposition"] == "released" else {})})
    return {"id": r["id"], "tripDate": r.get("date"), "boat": _short(r.get("boat"), 80), "landing": r["port"], "anglers": r["anglers"],
            "tripType": _short(r.get("trip_type"), 80), "species": species, "sourceUrl": _publisher(r.get("source_url"), r.get("date")),
            "retrievedAt": retrieved, **({"reportedGround": _short(r["ground"], 120)} if r.get("ground") is not None else {})}


def _trip(raw, receipts, window, today, generated, now):
    """One trip checked against its original day receipt; None when older than the 29-day view."""
    trip = _date(_obj(raw).get("date"))
    if not window[0] <= trip <= min(window[1], today):
        raise ValueError("Trip outside reviewed window")
    if trip < today - 29 * DAY:
        return None
    receipt = _obj(receipts.get("catches-" + raw["date"]))
    day = _obj(receipt.get("data"))
    if receipt.get("status") != "ok" or receipt.get("kind") != "charter-reports" or day.get("date") != raw["date"] \
            or not isinstance(day.get("reports"), list) or len(day["reports"]) > 5000:
        raise ValueError("Catch day is failed or missing")
    _publisher(receipt.get("url"), raw["date"])
    retrieved = _fresh(receipt.get("checked_at"), now)
    if _instant(retrieved) > _instant(generated) + 300_000 or _local_day(_instant(retrieved)) < trip:
        raise ValueError("Catch receipt clock inconsistent with feed/trip")
    matching = [r for r in day["reports"] if isinstance(r, dict) and r.get("id") == raw.get("id")]
    record = _normalized(raw, retrieved)
    if len(matching) != 1 or record != _normalized(matching[0], retrieved):
        raise ValueError("Trip missing from, ambiguous in or different from its original day receipt")
    return record


def catches(doc, now, received):
    """`collectCatches` over the daily feed: (trips, status, catchStatus, catchContext or None)."""
    status = {"id": "landing-reports", "label": "Local charter trip facts · SkipperCast / SoCalFishReports", "url": DAILY_URL,
              "kind": "report", "outcome": "error", "fetchedAt": received}
    try:
        d, today = _obj(doc), _local_day(now)
        if isinstance(doc, Exception) or d.get("schema_version") != 1 or d.get("region_id") != REGION or not isinstance(d.get("sources"), dict) \
                or not isinstance(d.get("reports"), list) or len(d["reports"]) > 5000 or not isinstance(d.get("report_window"), dict):
            raise ValueError(doc if isinstance(doc, Exception) else "Unreviewed catch feed schema or region")
        generated, span = _fresh(d.get("generated_at"), now), d["report_window"]
        start, end = _date(span.get("start")), _date(span.get("end"))
        if not start <= end <= min(today, start + 29 * DAY) or span.get("days") != (end - start) // DAY + 1 \
                or end >= _local_day(_instant(generated)):
            raise ValueError("Invalid catch report window")
        kept, conflicted, omitted, duplicates = {}, set(), 0, 0
        for raw in d["reports"]:
            try:
                record = _trip(raw, d["sources"], (start, end), today, generated, now)
            except FAILURES:
                omitted += 1
                continue
            if record is None:
                continue
            ident = record["id"]
            if ident in conflicted or (ident in kept and kept[ident] != record):
                omitted += 1 if ident in conflicted else 2
                kept.pop(ident, None)
                conflicted.add(ident)
            elif ident in kept:
                duplicates += 1
            else:
                kept[ident] = record
        trips = sorted(sorted(kept.values(), key=lambda r: r["id"]), key=lambda r: r["tripDate"], reverse=True)
        latest = trips[0]["tripDate"] if trips else None
        context = {"feedUrl": DAILY_URL, "feedGeneratedAt": generated, "receivedAt": received, "windowStart": span["start"],
                   "windowEnd": span["end"], "latestTripDate": latest,
                   "rights": {"scope": "linked-factual-counts", "reviewedAt": "2026-09-21", "sourceCatalogUrl": CATALOG_URL}}
        unavailable = f"{omitted} records unavailable" if omitted else ""
        text = (f"{len(trips)} linked dated boat-trip reports; latest {latest}. Reported counts are not proven retained catches. "
                f"{unavailable + '. ' if omitted else ''}{f'{duplicates} exact duplicates ignored. ' if duplicates else ''}"
                "Landing port is not a catch location.") if trips else (
            f"No verified dated local trip facts in this feed edition{'; ' + unavailable if omitted else ''}. "
            "Missing reports do not establish zero fishing or catches.")
        found = {"error": f"{omitted} stale, failed, conflicting or invalid trip records excluded; independently valid records preserved."}
        return trips, {**status, **(found if omitted else {"outcome": "ok"})}, text, context
    except FAILURES as error:
        return [], _error(status, error), "Dated local catch facts unavailable for this edition. Published reports remain linked.", None


def _temperature(data, fetched, url):
    """The daily SST grid as a `SurfaceTemperature`: open-water cells of one analysis, with their error."""
    units, samples, resolution = _obj(data.get("units")), _list(data.get("samples")), _list(data.get("native_resolution_degrees"))
    points = [{"lon": s["longitude"], "lat": s["latitude"], "tempF": s["analysed_sst"] * 1.8 + 32, "errorF": s["analysis_error"] * 1.8}
              for s in samples if isinstance(s, dict) and s.get("mask") == 1
              and all(_number(s.get(k)) for k in ("longitude", "latitude", "analysed_sst", "analysis_error")) and s["analysis_error"] >= 0]
    if data.get("kind") != "sst" or units.get("analysed_sst") != "degree_C" or units.get("analysis_error") != "degree_C" \
            or {_obj(s).get("time") for s in samples} != {data.get("sample_at")} or not _iso(data.get("sample_at")) \
            or not points or not resolution or not _number(resolution[0]):
        raise ValueError("Incomplete or changed surface temperature analysis")
    return {"sourceId": "noaa-blended-sst", "analysedAt": _iso(data["sample_at"]), "fetchedAt": fetched, "nativeResolutionDeg": resolution[0],
            "sampleSpacingDeg": resolution[0] * (data.get("stride") or 1), "points": points, "url": url, "kind": "analysis"}


def _protected(data, fetched, url):
    geo = _obj(data.get("geojson"))
    if geo.get("type") != "FeatureCollection" or not _list(geo.get("features")) or geo.get("exceededTransferLimit"):
        raise ValueError("Incomplete protected-area geometry")
    return {"sourceId": "cdfw-protected-areas", "fetchedAt": fetched, "url": url, "license": "CC BY 4.0",
            "attribution": "CDFW Marine Region GIS Lab · DS582", "featureCollection": {"type": "FeatureCollection", "features": geo["features"]}}


def spatial(doc, fallback):
    """`SpatialData` from the daily feed's SST and DS582 sources, each with its own status and clocks."""
    found, layers, statuses = _obj(_obj(doc).get("sources")), {}, []
    for key, layer, ident, label, kind, build in (
            ("sst", "surfaceTemperature", "noaa-blended-sst", "NOAA Geo-Polar Blended · surface temperature analysis", "analysis", _temperature),
            ("mpa-boundaries", "protectedAreas", "cdfw-protected-areas", "CDFW · marine protected area boundaries", "rule", _protected)):
        record = _obj(found.get(key))
        data = _obj(record.get("data"))
        status = {"id": ident, "label": label, "url": str(data.get("query_url") or record.get("url") or DAILY_URL), "kind": kind}
        try:
            fetched = _iso(record.get("data_retrieved_at"))
            if isinstance(doc, Exception) or record.get("status") != "ok" or not fetched:
                raise ValueError(doc if isinstance(doc, Exception) else record.get("issue") or "Unavailable in the daily feed")
            layers[layer] = build(data, fetched, status["url"])
            statuses.append({**status, "outcome": "ok", "fetchedAt": fetched})
        except FAILURES as error:
            statuses.append(_error(status, error, fetchedAt=_iso(record.get("checked_at")) or fallback))
    return layers, statuses


def assemble(session, live, now=None):
    """The county `Report`. With `now` every clock is that instant (tests); otherwise each source's own fetch time."""
    moment = now or datetime.now(timezone.utc)
    start = int(moment.timestamp() * 1000)
    clock = (lambda: iso(start)) if now else (lambda: iso(int(time.time() * 1000)))
    forecasts, sources, zones = [], [], {}
    for area in AREAS:
        row, status, zones[area[0]] = forecast(session, area, start, clock())
        forecasts.append(row)
        sources.append(status)
    observations, statuses = buoys(live, clock())
    predicted = {}
    for product, ident in (("6", "coops-tides"), ("hilo", "coops-tide-events")):
        status = {"id": ident, "label": f"NOAA tides · {TIDE_NAME}", "url": tide_url(moment, product), "kind": "prediction", "fetchedAt": clock()}
        try:
            predicted[ident] = tides(_get(session, status["url"]), product == "hilo")
            statuses.append({**status, "outcome": "ok", "validThrough": predicted[ident][-1]["at"]})
        except FAILURES as error:
            predicted[ident] = []
            statuses.append(_error(status, error))
    status = {"id": "nws-alerts", "label": "NWS active coastal alerts", "url": ALERTS_URL, "kind": "forecast", "fetchedAt": clock()}
    try:
        active = alerts(_get(session, ALERTS_URL), zones)
        statuses.append({**status, "outcome": "ok"})
    except FAILURES as error:
        active = []
        statuses.append(_error(status, error))
    received = clock()
    try:
        daily = _get(session, DAILY_URL, 5_000_000)
    except FAILURES as error:
        daily = error
    trips, status, catch_status, context = catches(daily, _ms(clock()), received)
    layers, spatial_statuses = spatial(daily, received)
    return {"schemaVersion": 1, "countyId": COUNTY, "generatedAt": clock(), "forecasts": forecasts, "observations": observations,
            "tides": predicted["coops-tides"], "tideEvents": predicted["coops-tide-events"], "alerts": active,
            "sources": sources + statuses + spatial_statuses + [status], "catches": trips, "catchStatus": catch_status,
            **({"catchContext": context} if context else {}),
            "visibility": {"status": "unknown", "feet": None, "observedAt": None, "sourceUrl": None}, "habitatStatus": HABITAT,
            "spatial": layers}


def publishable(report):
    """`publicationDecision`, reduced: a populated forecast area or a buoy observation under three hours old."""
    now = _ms(report["generatedAt"])
    return any(f["hours"] for f in report["forecasts"]) or any(now - _ms(o["observedAt"]) <= 3 * HOUR for o in report["observations"])


def main(argv=None, session=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True, help="the published tree: reads regions/morro-bay/latest.json "
                        "(this cycle's buoys), writes regions/morro-bay/coast-report.json")
    args = parser.parse_args(argv)
    report = assemble(session or http.Session(allowed_hosts=HOSTS), _read(args.root / "regions" / REGION / "latest.json"), now)
    print(json.dumps({"generatedAt": report["generatedAt"], "sources": {s["id"]: s["outcome"] for s in report["sources"]}}))
    if not publishable(report):
        print("No populated forecast area or recent buoy observation; the last coast report is kept.", file=sys.stderr)
        return 1
    atomic_json(args.root / "regions" / REGION / "coast-report.json", report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
