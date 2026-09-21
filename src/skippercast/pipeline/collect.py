"""Bounded daily collection. No credentials, private logs, or delivery adapters."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from . import parsers
from .regulations import regulatory_snapshot

UA = "SkipperCast/0.2 (https://github.com/Grahammmm/skippercast)"
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap"
BOUNDS = {"latitude": [34.95, 35.7], "longitude": [-121.95, -120.7]}
DATASETS = {
    "sst": ("jplMURSST41", ["analysed_sst", "analysis_error", "mask"], 5, 72),
    "chlorophyll": ("erdMH1chla1day_R2022NRT", ["chlorophyll"], 1, 96),
    "currents": ("ucsdHfrW6", ["water_u", "water_v", "number_of_sites", "hdop"], 1, 12),
}
WATCHES = {
    "rules-central": ("CDFW Central Region rules", "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central", ["Dungeness", "halibut", "Conception"]),
    "rules-gear": ("CDFW finfish gear and general rules", "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Sport-Fishing/General-Ocean-Fishing-Regs", ["28.65", "27.60"]),
    "rules-invertebrates": ("CDFW invertebrate gear rules", "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Sport-Fishing/Invertebrate-Fishing-Regs", ["29.80", "trap"]),
    "rules-whales": ("CDFW whale-safe crab restrictions", "https://wildlife.ca.gov/Conservation/Marine/Whale-Safe-Fisheries", ["recreational", "crab"]),
    "rules-health": ("CDFW fishery health closures", "https://wildlife.ca.gov/Fishing/Ocean/Health-Advisories", ["Dungeness", "health"]),
    "rules-ocean": ("CDFW official regulation index", "https://wildlife.ca.gov/Fishing/Ocean", ["2026", "Tunas"]),
    "rules-groundfish": ("CDFW groundfish", "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary", ["groundfish", "regulations"]),
    "rules-inseason": ("CDFW in-season changes", "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Inseason", ["in-season", "ocean"]),
    "rules-salmon": ("CDFW salmon", "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Salmon", ["salmon", "season"]),
    "rules-crab": ("CDFW crab", "https://wildlife.ca.gov/Crab", ["Dungeness", "recreational"]),
    "mpa-buchon": ("CDFW Point Buchon MPAs", "https://wildlife.ca.gov/Conservation/Marine/MPAs/Point-Buchon", ["Buchon", "conservation"]),
    "mpa-cambria": ("CDFW Cambria MPAs", "https://wildlife.ca.gov/Conservation/Marine/MPAs/Cambria-White-Rock", ["Cambria", "conservation"]),
    "harbor": ("Morro Bay harbor information", "https://www.morrobayca.gov/144/Harbor", ["harbor", "Morro"]),
}
MODEL_META = {
    "gfs_global": "https://api.open-meteo.com/data/ncep_gfs013/static/meta.json",
    "ecmwf_ifs025": "https://api.open-meteo.com/data/ecmwf_ifs025/static/meta.json",
    "ncep_gfswave025": "https://marine-api.open-meteo.com/data/ncep_gfswave025/static/meta.json",
    "ecmwf_wam025": "https://marine-api.open-meteo.com/data/ecmwf_wam025/static/meta.json",
}
POINTS = [("Point Estero", 35.45, -121.02), ("Estero Bay", 35.36, -120.94),
          ("Point Buchon", 35.24, -120.94), ("Off Avila", 35.1, -120.82),
          ("Offshore central", 35.3, -121.5)]


def stamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def age_hours(value, now):
    try:
        return (now - datetime.fromisoformat(value.replace("Z", "+00:00"))).total_seconds() / 3600
    except (AttributeError, ValueError, TypeError):
        return None


class Client:
    def __init__(self, now):
        self.now = now
        self.requests = []

    def get(self, url, as_json=False, as_pdf=False):
        for attempt in range(2):
            record = {"url": url, "attempt": attempt + 1, "retrieved_at": stamp()}
            try:
                with urlopen(Request(url, headers={"User-Agent": UA, "Accept": "application/json" if as_json else "*/*"}), timeout=25) as response:
                    limit = 35_000_000 if as_pdf else 5_000_000
                    body = response.read(limit + 1)
                    record.update(http_status=response.status, http_date=response.headers.get("Date"),
                                  last_modified=response.headers.get("Last-Modified"), bytes=len(body),
                                  sha256=hashlib.sha256(body).hexdigest())
                if len(body) > limit:
                    raise ValueError("Response exceeds bounded collection size")
                if not body.strip():
                    raise ValueError("Empty response")
                if as_pdf:
                    if not body.startswith(b"%PDF-"):
                        raise ValueError("Expected an official PDF; received another content type")
                    result = {"content_sha256": hashlib.sha256(body).hexdigest(),
                              "interpretation": "manual review required", "permission_to_fish": None}
                else:
                    text = body.decode("utf-8")
                    result = json.loads(text) if as_json else text
                if isinstance(result, dict) and result.get("error"):
                    raise ValueError("Provider returned an error response")
                self.requests.append(record)
                return result
            except Exception as error:
                record["error"] = f"{type(error).__name__}: {str(error)[:220]}"
                if isinstance(error, HTTPError):
                    record["http_status"] = error.code
                self.requests.append(record)
                if attempt == 1 or isinstance(error, (ValueError, HTTPError)) and getattr(error, "code", 0) < 500:
                    raise
                time.sleep(1)


def source(ident, name, kind, url, max_age, loader, now, previous=None):
    client = Client(now)
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
        if kind == "page-watch":
            old_hash = (previous or {}).get("data", {}).get("content_sha256") if (previous or {}).get("data") else None
            result["changed_since_previous"] = old_hash != data["content_sha256"] if old_hash else None
    except Exception as error:
        result["issue"] = f"{type(error).__name__}: {str(error)[:220]}"
        if previous and previous.get("data"):
            result.update(status="retained", data=previous["data"], last_success_at=previous.get("last_success_at"),
                          data_retrieved_at=previous.get("data_retrieved_at"))
    result["requests"] = client.requests
    return result


def grid_loader(kind):
    dataset, variables, stride, _ = DATASETS[kind]
    def load(client):
        metadata_url = f"{ERDDAP}/info/{dataset}/index.json"
        meta = parsers.erddap_metadata(client.get(metadata_url, True))
        query = parsers.erddap_query(meta, variables, BOUNDS, stride)
        url = f"{ERDDAP}/griddap/{dataset}.json?" + quote(query, safe=",:()")
        grid = parsers.erddap_grid(client.get(url, True), meta, variables, kind)
        grid.update(dataset=dataset, metadata_url=metadata_url, query_url=url, requested_bounds=BOUNDS, stride=stride)
        return grid
    return load


def model_loader(model):
    wave = model in ("ecmwf_wam025", "ncep_gfswave025")
    variables = ([f"{p}_{q}" for p in ("wave", "wind_wave", "swell_wave", "secondary_swell_wave")
                  for q in ("height", "period", "direction")] if wave else
                 ["wind_speed_10m", "wind_gusts_10m", "wind_direction_10m", "visibility", "precipitation", "temperature_2m", "weather_code"])
    params = {"latitude": ",".join(str(p[1]) for p in POINTS), "longitude": ",".join(str(p[2]) for p in POINTS),
              "hourly": ",".join(variables), "models": model, "forecast_days": 8, "timezone": "UTC",
              "timeformat": "unixtime", "cell_selection": "sea"}
    if wave:
        params["length_unit"] = "imperial"
    else:
        params.update(wind_speed_unit="kn", temperature_unit="fahrenheit")
    url = ("https://marine-api.open-meteo.com/v1/marine?" if wave else "https://api.open-meteo.com/v1/forecast?") + urlencode(params)
    def load(client):
        meta = client.get(MODEL_META[model], True)
        initialized = meta.get("last_run_initialisation_time")
        if not isinstance(initialized, (float, int)):
            raise ValueError("Model initialization timestamp absent")
        data = client.get(url, True)
        if not isinstance(data, list) or len(data) != len(POINTS):
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
                "meta": meta, "requested_points": [{"name": p[0], "latitude": p[1], "longitude": p[2]} for p in POINTS],
                "points": data, "note": "Daily model archive for evidence research; browser weather refreshes independently."}
    return url, load


def collect(now, previous=None, days=30):
    previous = previous if previous and previous.get("schema_version") == 1 else {}
    old_sources = previous.get("sources", {})
    sources = {}
    local_day = now.astimezone(ZoneInfo("America/Los_Angeles")).date()
    jobs = []
    for kind, (dataset, _, _, max_age) in DATASETS.items():
        jobs.append((kind, {"sst": "NASA JPL MUR sea temperature", "chlorophyll": "NASA Aqua MODIS chlorophyll", "currents": "NOAA IOOS HF radar currents"}[kind],
                     "grid", f"{ERDDAP}/info/{dataset}/index.html", max_age, grid_loader(kind)))
    for ident, station, spectral in [("buoy-46215", "46215", False), ("buoy-46215-swell", "46215", True), ("buoy-46028", "46028", False)]:
        url = f"https://www.ndbc.noaa.gov/data/realtime2/{station}.{'spec' if spectral else 'txt'}"
        jobs.append((ident, f"NOAA NDBC {station}" + (" swell components" if spectral else " observations"), "observation", url, 6,
                     lambda c, u=url, s=station, sp=spectral: parsers.ndbc(c.get(u), s, sp)))
    tide_params = {"product": "predictions", "application": "SkipperCast", "station": "9412110", "datum": "MLLW",
                   "begin_date": now.strftime("%Y%m%d"), "end_date": (now + timedelta(days=8)).strftime("%Y%m%d"),
                   "time_zone": "gmt", "units": "english", "interval": "hilo", "format": "json"}
    url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?" + urlencode(tide_params)
    jobs.append(("tides", "NOAA Port San Luis tide predictions", "prediction", url, 36, lambda c, u=url: parsers.tides(c.get(u, True))))
    for zone in ("PZZ645", "PZZ670"):
        url = f"https://api.weather.gov/alerts/active/zone/{zone}"
        jobs.append(("alerts-" + zone, "NWS " + zone + " advisories", "advisory", url, 36, lambda c, u=url: parsers.alerts(c.get(u, True))))
    for ident, (name, url, keywords) in WATCHES.items():
        jobs.append((ident, name, "page-watch", url, 36, lambda c, u=url, k=keywords: parsers.page_watch(c.get(u), k)))
    url = "https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=239985"
    jobs.append(("rules-book", "CDFW 2026 ocean regulations booklet", "page-watch", url, 36,
                 lambda c, u=url: c.get(u, as_pdf=True)))
    for model in MODEL_META:
        url, loader = model_loader(model)
        jobs.append(("model-" + model, model + " via Open-Meteo", "forecast", url, 36, loader))
    def run(job):
        return source(*job, now=now, previous=old_sources.get(job[0]))
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(run, jobs):
            sources[result["id"]] = result
            print(f"{result['id']}: {result['status']}", flush=True)
    # Refetch the latest seven completed local dates for late corrections. Older
    # successful day facts are reused with their original retrieval timestamps.
    report_jobs = []
    for offset in range(1, days + 1):
        day = (local_day - timedelta(days=offset)).isoformat()
        ident = "catches-" + day
        old = old_sources.get(ident)
        if offset > 7 and old and old.get("status") == "ok" and old.get("data"):
            sources[ident] = {**old, "reused": True}
            continue
        url = "https://www.socalfishreports.com/dock_totals/boats.php?date=" + day
        report_jobs.append((ident, "Landing reports " + day, "charter-reports", url, 36,
                            lambda c, u=url, d=day: parsers.charter_reports(c.get(u), d, u)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(run, report_jobs):
            sources[result["id"]] = result
    reports = [r for s in sources.values() if s["kind"] == "charter-reports" and s.get("data")
               for r in s["data"]["reports"]]
    snapshot = {"schema_version": 1, "generated_at": stamp(now), "completed_at": stamp(),
                "schedule": {"cron": "17 4 * * *", "timezone": "America/Los_Angeles", "max_delay_hours": 36},
                "scope": "Morro Bay and Avila landing reports; Avila–Point Estero ocean samples plus offshore search water",
                "report_window": {"start": (local_day - timedelta(days=days)).isoformat(),
                                  "end": (local_day - timedelta(days=1)).isoformat(), "days": days},
                "sources": sources, "reports": sorted(reports, key=lambda r: (r["date"], r["id"]), reverse=True),
                "catch_probability": None, "bite_score": None,
                "regulations": regulatory_snapshot(sources, now),
                "limitations": ["Landing port is not a catch position; named grounds are broad reports, not GPS fixes.",
                                "Reports are a selected sample, with unknown effort and missing unsuccessful trips.",
                                "Satellite temperature and HF radar measure surface context, not bottom conditions.",
                                "Daily observations are not a seven-day bite forecast or live entrance clearance."]}
    last_seven = [sources.get("catches-" + (local_day - timedelta(days=i)).isoformat(), {}) for i in range(1, 8)]
    coverage = sum(s.get("status") == "ok" for s in last_seven)
    critical = coverage >= 5 and any(sources[k]["status"] == "ok" for k in ("buoy-46215", "buoy-46028"))
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
