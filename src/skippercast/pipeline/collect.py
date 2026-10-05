"""Bounded daily collection. No credentials, private logs, or delivery adapters."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from urllib.parse import quote, urlencode, urlsplit
from zoneinfo import ZoneInfo

from .. import http

from . import parsers
from ..forecast import local as forecast_local
from .regulations import regulatory_snapshot, watch_jobs
from .settings import settings, previous_for_region
from ..platform.contracts import public_url
from ..util.time import stamp

UA = http.USER_AGENT
# 5xx and 429 are retried (with backoff and Retry-After); other 4xx fail at once.
RETRY_STATUSES = frozenset(range(500, 600)) | {429}
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap"
# TECK.net daily dock totals; the fleet teck-reports adapter reads the same sites' boat pages.
TECK_DOCK_TOTALS = "https://www.socalfishreports.com/dock_totals/boats.php?date="
BOUNDS = {"latitude": [34.95, 35.7], "longitude": [-121.95, -120.7]}
DATASETS = {
    "sst": ("jplMURSST41", ["analysed_sst", "analysis_error", "mask"], 5, 72),
    "chlorophyll": ("erdMH1chla1day_R2022NRT", ["chlorophyll"], 1, 96),
    "currents": ("ucsdHfrW6", ["water_u", "water_v", "number_of_sites", "hdop"], 1, 12),
}
# SkipperCast's own NOAA/ECMWF forecast tiles (skippercast.forecast) replace the
# Open-Meteo API; responses keep Open-Meteo's shape so every consumer is unchanged.
MODEL_META = {model: forecast_local.meta_url(model)
              for model in ("gfs_global", "ecmwf_ifs025", "ncep_gfswave016", "ecmwf_wam")}
POINTS = [("Point Estero", 35.45, -121.02), ("Estero Bay", 35.36, -120.94),
          ("Point Buchon", 35.24, -120.94), ("Off Avila", 35.1, -120.82),
          ("Offshore central", 35.3, -121.5)]


def age_hours(value, now):
    try:
        return (now - datetime.fromisoformat(value.replace("Z", "+00:00"))).total_seconds() / 3600
    except (AttributeError, ValueError, TypeError):
        return None


def run_id(environ=None):
    """The GitHub Actions run that produced a feed, or "local" outside Actions."""
    return ((os.environ if environ is None else environ).get("GITHUB_RUN_ID") or "").strip() or "local"


def publication(environ=None):
    """Fields every published latest.json carries so the public copy can be traced
    to the run that wrote it (scripts/verify_published_feed.py checks them)."""
    return {"published_at": stamp(), "run_id": run_id(environ)}


class Client:
    """Bounded source reads for one collected source; `requests` holds one receipt per attempt.

    Transport, redirects, address checks, retries and size limits come from the
    shared `skippercast.http.Session`; this class keeps the collector's contract
    (what is retried, byte limits, content checks) and its receipt shape.
    """

    def __init__(self, now, session=None, cache=...):
        self.now = now
        self.requests = []
        self.session = session if session is not None else http.default_session()
        self.cache = cache  # ... keeps the session's own conditional-GET cache

    def _record(self, url, receipt, error=None):
        """Append one receipt row per attempt; returns the last row."""
        rows = []
        for entry in receipt.history:
            row = {"url": url, "attempt": entry["attempt"], "retrieved_at": entry["started_at"]}
            if entry.get("status") is not None:
                row["http_status"] = entry["status"]
            if entry.get("elapsed_ms") is not None:
                row["elapsed_ms"] = entry["elapsed_ms"]
            if entry.get("error_class"):
                row["error_class"] = entry["error_class"]
                detail = entry.get("error") or (f"HTTP {entry['status']}" if entry.get("status") else "")
                row["error"] = f"{entry['error_class']}: {detail[:220]}"
            rows.append(row)
        if not rows:  # refused before any attempt
            rows.append({"url": url, "attempt": 1, "retrieved_at": stamp()})
        last = rows[-1]
        if error is not None:
            last.update(error=f"{type(error).__name__}: {str(error)[:220]}",
                        error_class=getattr(error, "error_class", type(error).__name__))
        else:
            last.update(http_status=receipt.status, http_date=receipt.http_date, final_url=receipt.final_url,
                        content_type=receipt.content_type, last_modified=receipt.last_modified,
                        bytes=receipt.bytes, sha256=receipt.sha256, elapsed_ms=receipt.elapsed_ms)
            last.pop("error_class", None)
            last.pop("error", None)
            if receipt.compressed_bytes is not None:
                last["compressed_bytes"] = receipt.compressed_bytes
            if receipt.from_cache:
                last["from_cache"] = True
        self.requests.extend(rows)
        return last

    def get(self, url, as_json=False, as_pdf=False, as_binary=False):
        public_url(url)
        coastwatch = urlsplit(url).hostname == 'coastwatch.pfeg.noaa.gov'
        limit = 35_000_000 if as_pdf else 5_000_000
        # Server errors and throttling are retried; CoastWatch also answers bursts with 403.
        retry = RETRY_STATUSES | ({403} if coastwatch else set())
        options = {} if self.cache is ... else {"cache": self.cache}
        try:
            response = self.session.get(
                url, headers={"Accept": "application/json" if as_json else "*/*", "Accept-Encoding": "gzip"},
                timeout=25, max_bytes=limit, attempts=3 if coastwatch else 2, retry_statuses=retry, **options)
        except http.SourceError as error:
            self._record(url, error.receipt or http.Receipt(url=url), error)
            raise
        record = self._record(url, response.receipt)
        try:
            body = response.body
            if not body.strip():
                raise ValueError("Empty response")
            if as_binary:
                result = body
            elif as_pdf:
                if not body.startswith(b"%PDF-"):
                    raise ValueError("Expected an official PDF; received another content type")
                result = {"content_sha256": hashlib.sha256(body).hexdigest(),
                          "normalization": "pdf-bytes-v1",
                          "interpretation": "manual review required", "permission_to_fish": None}
            else:
                text = body.decode("utf-8")
                result = json.loads(text) if as_json else text
            if isinstance(result, dict) and result.get("error"):
                raise ValueError("Provider returned an error response")
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {str(error)[:220]}"
            raise
        return result


def http_cache():
    """The conditional-GET cache the collector reads through: the process-wide session's
    (``SKIPPERCAST_HTTP_CACHE``; None when caching is off).

    TECK.net pages are fetched by the daily dock-totals jobs below and by the fleet
    ``teck-reports`` adapter; both go through this one cache, so there is one TECK.net
    cache directory (design section 6, "Relationship to the existing reports pipeline").
    """
    return http.default_session().cache


def client_factory(session=None, cache=...):
    """Build ``Client``s the way ``source`` does, optionally over another session.

    ``session`` is anything with ``skippercast.http.Session.get``'s signature (the fleet
    passes its ``FleetSession``, which adds the allowlist, robots.txt and off-limits
    rules on top of a ``Session``); ``cache`` replaces that session's cache for each
    request (pass ``http_cache()`` to share the collector's). With no arguments this
    is ``Client`` over the default session.
    """
    return lambda now: Client(now, session=session, cache=cache)


def source(ident, name, kind, url, max_age, loader, now, previous=None, client_factory=Client):
    client = client_factory(now)
    result = {"id": ident, "name": name, "kind": kind, "url": url, "checked_at": stamp(now),
              "max_age_hours": max_age, "status": "failed", "data": None}
    try:
        data = loader(client)
        result.update(data=data, status="ok", last_success_at=stamp(), data_retrieved_at=stamp())
        sample = data.get("sample_at") or data.get("issued_at")
        if sample:
            age = age_hours(sample, now)
            if age is None or age < -1 or age > max_age:
                result.update(status="stale", issue="Source time is outside this product's freshness window")
        if data.get("total_cells") and data.get("valid_cells") == 0:
            result.update(status="missing", issue="No usable cells in this regional grid; no gap filling applied")
        if kind in ("page-watch", "pdf-watch"):
            old_hash = (previous or {}).get("data", {}).get("content_sha256") if (previous or {}).get("data") else None
            result["changed_since_previous"] = old_hash != data["content_sha256"] if old_hash else None
    except Exception as error:
        result["issue"] = f"{type(error).__name__}: {str(error)[:220]}"
        if previous and previous.get("data"):
            result.update(status="retained", data=previous["data"], last_success_at=previous.get("last_success_at"),
                          data_retrieved_at=previous.get("data_retrieved_at"))
    result["requests"] = client.requests
    return result


def grid_loader(kind, bounds=None, config=None):
    bounds = BOUNDS if bounds is None else bounds
    if config and config.get("adapter") == "noaa-ncss-sst":
        if kind != "sst": raise ValueError("NOAA NCSS adapter only supports SST")
        from .noaa_sst import fetch
        return lambda client: fetch(client, bounds)
    if config and config.get("adapter") == "noaa-ncss-chlorophyll":
        if kind != "chlorophyll": raise ValueError("NOAA NCSS chlorophyll adapter only supports chlorophyll")
        from .noaa_chlorophyll import fetch
        return lambda client: fetch(client, bounds)
    if config and config.get("adapter") == "noaa-ncss-hfr":
        if kind != "currents": raise ValueError("NOAA NCSS HFR adapter only supports currents")
        from .noaa_hfr import fetch
        return lambda client: fetch(client, bounds)
    dataset, variables, stride, _ = DATASETS[kind]
    base_url = ERDDAP
    if config:
        dataset, variables, stride = config["dataset"], config["variables"], config["stride"]
        base_url = config["base_url"]
    def load(client):
        metadata_url = f"{base_url}/info/{dataset}/index.json"
        meta = parsers.erddap_metadata(client.get(metadata_url, True))
        query = parsers.erddap_query(meta, variables, bounds, stride)
        url = f"{base_url}/griddap/{dataset}.json?" + quote(query, safe=",:()")
        grid = parsers.erddap_grid(client.get(url, True), meta, variables, kind)
        grid.update(dataset=dataset, metadata_url=metadata_url, query_url=url, requested_bounds=bounds, stride=stride)
        return grid
    return load


def model_loader(model, points=None):
    points = POINTS if points is None else points
    wave = model in ("ecmwf_wam", "ncep_gfswave016")
    variables = ([f"{p}_{q}" for p in ("wave", "wind_wave", "swell_wave", "secondary_swell_wave")
                  for q in ("height", "period", "direction")] if wave else
                 ["wind_speed_10m", "wind_gusts_10m", "wind_direction_10m", "visibility", "precipitation", "temperature_2m", "cloud_cover", "weather_code"])
    params = {"latitude": ",".join(str(p[1]) for p in points), "longitude": ",".join(str(p[2]) for p in points),
              "hourly": ",".join(variables), "models": model, "forecast_days": 8, "timezone": "UTC",
              "timeformat": "unixtime", "cell_selection": "sea"}
    if wave:
        params["length_unit"] = "imperial"
    else:
        params.update(wind_speed_unit="kn", temperature_unit="fahrenheit")
    url = forecast_local.public_url(model, params)
    def load(client):
        meta = forecast_local.meta(model, client)
        initialized = meta.get("last_run_initialisation_time")
        if not isinstance(initialized, (float, int)):
            raise ValueError("Model initialization timestamp absent")
        data = forecast_local.sample(model, params, client)
        data = data if isinstance(data, list) else [data]
        if len(data) != len(points):
            raise ValueError("Forecast point count changed")
        for p in data:
            units, hourly = p.get("hourly_units", {}), p.get("hourly", {})
            times = hourly.get("time", [])
            if units.get("time") != "unixtime" or p.get("utc_offset_seconds") != 0 or not times or len(set(times)) != len(times):
                raise ValueError("Forecast time axis invalid")
            if any(len(hourly.get(v, [])) != len(times) for v in variables):
                raise ValueError("Forecast variable coverage mismatch")
            expected = {"wave_height": "ft", "wave_period": "s"} if wave else {"wind_speed_10m": "kn", "wind_gusts_10m": "kn"}
            if any(units.get(k) != v for k, v in expected.items()):
                raise ValueError("Forecast units changed")
        return {"model": model, "sample_at": stamp(datetime.fromtimestamp(initialized, timezone.utc)),
                "meta": meta, "requested_points": [{"name": p[0], "latitude": p[1], "longitude": p[2]} for p in points],
                "points": data, "note": "SkipperCast forecast tiles built from NOAA and ECMWF open data; the app samples the same tiles."}
    return url, load


def collect(now, previous=None, days=30, region_id="morro-bay"):
    config = settings(region_id)
    region = config["region"]
    previous = previous_for_region(previous, region_id)
    stations = region["stations"]
    west, south, east, north = region["bounds"]
    bounds = {"latitude": [south, north], "longitude": [west, east]}
    points = [(p["name"], p["latitude"], p["longitude"]) for p in region["forecast_points"]]
    old_sources = previous.get("sources", {})
    sources = {}
    local_day = now.astimezone(ZoneInfo(region["timezone"])).date()
    jobs = []
    for kind, request in config["grids"].items():
        jobs.append((kind, request["name"], "grid", request["documentation_url"],
                     request["max_age_hours"], grid_loader(kind, bounds, request)))
    for ident, station, spectral in [("buoy-"+stations["nearshore_buoy"], stations["nearshore_buoy"], False), ("buoy-"+stations["nearshore_buoy"]+"-swell", stations["nearshore_buoy"], True), ("buoy-"+stations["offshore_buoy"], stations["offshore_buoy"], False)]:
        url = f"https://www.ndbc.noaa.gov/data/realtime2/{station}.{'spec' if spectral else 'txt'}"
        jobs.append((ident, f"NOAA NDBC {station}" + (" swell components" if spectral else " observations"), "observation", url, 6,
                     lambda c, u=url, s=station, sp=spectral: parsers.ndbc(c.get(u), s, sp)))
    tide_params = {"product": "predictions", "application": "SkipperCast", "station": stations["tide"], "datum": "MLLW",
                   "begin_date": now.strftime("%Y%m%d"), "end_date": (now + timedelta(days=8)).strftime("%Y%m%d"),
                   "time_zone": "gmt", "units": "english", "interval": "hilo", "format": "json"}
    url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?" + urlencode(tide_params)
    jobs.append(("tides", "NOAA " + stations["tide_name"] + " reference tide predictions", "prediction", url, 36, lambda c, u=url, s=stations["tide"], n=stations["tide_note"]: parsers.tides(c.get(u, True), s, n)))
    for zone in dict.fromkeys(region["marine_zones"].values()):
        url = f"https://api.weather.gov/alerts/active/zone/{zone}"
        jobs.append(("alerts-" + zone, "NWS " + zone + " advisories", "advisory", url, 36, lambda c, u=url: parsers.alerts(c.get(u, True))))
    mpa_url = "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?" + urlencode({
        "where":"1=1", "geometry":",".join(str(v) for v in region["mpa"]["bounds"]),
        "geometryType":"esriGeometryEnvelope", "inSR":"4326", "spatialRel":"esriSpatialRelIntersects",
        "outFields":"NAME,FULLNAME,Type,CCR", "returnGeometry":"true", "outSR":"4326", "f":"geojson"})
    def mpa_read(client):
        data = client.get(mpa_url, True)
        if data.get("type") != "FeatureCollection" or data.get("exceededTransferLimit") or len(data.get("features", [])) < region["mpa"]["minimum_features"]:
            raise ValueError("Incomplete protected-area boundary response")
        if any(f.get("geometry", {}).get("type") not in ("Polygon", "MultiPolygon") or not isinstance(f.get("properties", {}).get("NAME"), str) for f in data["features"]):
            raise ValueError("Malformed protected-area geometry")
        return {"geojson": data, "checked_at": stamp(), "boundary_issue_time": None}
    jobs.append(("mpa-boundaries", "CDFW DS582 protected-area geometry", "boundaries", mpa_url, 36, mpa_read))
    if region.get('closure_check'):
        from hashlib import sha256
        closure_url=region['closure_check']['url']
        def closure_check(client):
            text=client.get(closure_url)
            if 'id_point' not in text or 'lat_dd' not in text: raise ValueError('Unexpected closure coordinate format')
            return {'sha256':sha256(text.encode('utf-8')).hexdigest(),'issue_time':None}
        jobs.append(('additional-closures','Reviewed NOAA closure coordinate file','boundaries',closure_url,36,closure_check))
    jobs.extend(watch_jobs(config['watches']))
    for model in config["model_ids"]:
        url, loader = model_loader(model, points)
        jobs.append(("model-" + model, model + " (SkipperCast NOAA/ECMWF tiles)", "forecast", url, 36, loader))
    def run(job):
        return source(*job, now=now, previous=old_sources.get(job[0]))
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(run, jobs):
            sources[result["id"]] = result
            print(f"{result['id']}: {result['status']}", flush=True)
    # Refetch the latest seven completed local dates for late corrections. Older
    # successful day facts are reused with their original retrieval timestamps.
    report_jobs = []
    for offset in range(1, days + 1) if region["landing_names"] else []:
        day = (local_day - timedelta(days=offset)).isoformat()
        ident = "catches-" + day
        old = old_sources.get(ident)
        if offset > 7 and old and old.get("status") == "ok" and old.get("data"):
            sources[ident] = {**old, "reused": True}
            continue
        url = TECK_DOCK_TOTALS + day
        report_jobs.append((ident, "Landing reports " + day, "charter-reports", url, 36,
                            lambda c, u=url, d=day: parsers.charter_reports(c.get(u), d, u, ports=config["report_ports"])))
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(run, report_jobs):
            sources[result["id"]] = result
    reports = [r for s in sources.values() if s["kind"] == "charter-reports" and s.get("data")
               for r in s["data"]["reports"]]
    snapshot = {"schema_version": 1, "generated_at": stamp(now), "completed_at": stamp(),
                **publication(),
                "schedule": {"cron": "17 4 * * *", "timezone": "America/Los_Angeles", "max_delay_hours": 36},
                "region_id": region_id, "scope": region["name"], "bounds": region["bounds"],
                "landing_names": region["landing_names"],
                "report_window": {"start": (local_day - timedelta(days=days)).isoformat(),
                                  "end": (local_day - timedelta(days=1)).isoformat(), "days": days},
                "sources": sources, "reports": sorted(reports, key=lambda r: (r["date"], r["id"]), reverse=True),
                "catch_probability": None, "bite_score": None,
                "regulations": regulatory_snapshot(sources, now, config["regulations"],
                                                   config["legal_source_ids"]),
                "limitations": ["Landing port is not a catch position; named grounds are broad reports, not GPS fixes.",
                                "Reports are a selected sample, with unknown effort and missing unsuccessful trips.",
                                "Satellite temperature and HF radar measure surface context, not bottom conditions.",
                                "Daily observations are not a seven-day bite forecast or live entrance clearance."]}
    last_seven = [sources.get("catches-" + (local_day - timedelta(days=i)).isoformat(), {}) for i in range(1, 8)]
    coverage = sum(s.get("status") == "ok" for s in last_seven)
    critical = (coverage >= 5 if region["landing_names"] else True) and any(sources[k]["status"] == "ok" for k in ("buoy-" + stations["nearshore_buoy"], "buoy-" + stations["offshore_buoy"]))
    issues = [s["id"] for s in sources.values() if s["status"] != "ok"]
    snapshot["health"] = {"status": "ok" if not issues else "degraded" if critical else "failed",
                          "critical_available": critical, "recent_report_days_ok": coverage,
                          "sources_ok": sum(s["status"] == "ok" for s in sources.values()),
                          "sources_total": len(sources), "issues": issues}
    validate(snapshot)
    return snapshot


def validate(snapshot):
    if snapshot.get("schema_version") != 1 or not isinstance(snapshot.get("sources"), dict):
        raise ValueError("Invalid feed schema")
    parsers.iso_time(snapshot["generated_at"])
    if "published_at" in snapshot or "run_id" in snapshot:
        if not isinstance(snapshot.get("published_at"), str) or not isinstance(snapshot.get("run_id"), str) \
                or not snapshot["run_id"]:
            raise ValueError("Published feed needs both published_at and run_id")
        parsers.iso_time(snapshot["published_at"])
    if snapshot.get("catch_probability") is not None or snapshot.get("bite_score") is not None:
        raise ValueError("Uncalibrated catch probability must remain absent")
    ids = [r["id"] for r in snapshot["reports"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate trip records")
    for ident, source_data in snapshot["sources"].items():
        if source_data["id"] != ident or source_data["status"] not in ("ok", "stale", "missing", "failed", "retained"):
            raise ValueError("Invalid source status")
        if source_data["status"] == "ok" and source_data.get("data") is None:
            raise ValueError("Successful source has no parsed data")
    json.dumps(snapshot, allow_nan=False)
