"""Bounded daily collection. No credentials, private logs, or delivery adapters."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import gzip
from io import BytesIO
import json
import re
import ssl
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from . import parsers
from .regulations import regulatory_snapshot, watch_jobs
from .settings import settings, previous_for_region
from ..platform.contracts import REPO, public_url
from ..platform.source_audit import PublicRedirect, check_public_address

UA = "SkipperCast/0.2 (https://github.com/Grahammmm/skippercast)"
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap"
BOUNDS = {"latitude": [34.95, 35.7], "longitude": [-121.95, -120.7]}
DATASETS = {
    "sst": ("jplMURSST41", ["analysed_sst", "analysis_error", "mask"], 5, 72),
    "chlorophyll": ("erdMH1chla1day_R2022NRT", ["chlorophyll"], 1, 96),
    "currents": ("ucsdHfrW6", ["water_u", "water_v", "number_of_sites", "hdop"], 1, 12),
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


def system_tls_official_watch(url, limit):
    """Recover a Mac Python trust-store failure using verified system TLS only.

    The fallback is restricted to exact California agency URLs in reviewed jurisdictions.
    It does not follow redirects or relax certificate validation.
    """
    state_hosts = {'wildlife.ca.gov', 'nrm.dfg.ca.gov', 'fgc.ca.gov'}
    if urlsplit(url).hostname not in state_hosts:
        raise ValueError('System TLS fallback is restricted to reviewed state agencies')
    allowed = set()
    for path in (REPO / 'jurisdictions').glob('california-*.json'):
        jurisdiction = json.loads(path.read_text())
        allowed.update(watch['url'] for watch in jurisdiction['watches'].values()
                       if urlsplit(watch['url']).hostname in state_hosts)
    if url not in allowed:
        raise ValueError('State agency URL is not an exact reviewed watch')
    with tempfile.TemporaryDirectory() as directory:
        body_path, header_path = (Path(directory) / name for name in ('body', 'headers'))
        subprocess.run(['/usr/bin/curl', '--fail', '--silent', '--show-error',
                        '--proto', '=https', '--max-time', '25', '--max-filesize', str(limit),
                        '--dump-header', str(header_path), '--output', str(body_path), url],
                       check=True, capture_output=True, timeout=30)
        body, headers = body_path.read_bytes(), header_path.read_text()
    statuses = re.findall(r'^HTTP/\S+\s+(\d{3})\b', headers, re.M)
    if not statuses or statuses[-1] != '200' or len(body) > limit or not body.strip():
        raise ValueError('State agency system TLS response was redirected, empty or oversized')
    final_headers = headers.split('\r\n\r\n')[-2] if '\r\n\r\n' in headers else headers
    fields = {name.lower(): value.strip() for name, value in
              re.findall(r'^([\w-]+):\s*(.*)$', final_headers, re.M)}
    return body, fields


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

    def get(self, url, as_json=False, as_pdf=False, as_binary=False):
        public_url(url)
        coastwatch = urlsplit(url).hostname == 'coastwatch.pfeg.noaa.gov'
        attempts = 3 if coastwatch else 2
        for attempt in range(attempts):
            record = {"url": url, "attempt": attempt + 1, "retrieved_at": stamp()}
            try:
                check_public_address(url)
                limit = 35_000_000 if as_pdf else 5_000_000
                try:
                    response = build_opener(PublicRedirect()).open(Request(url, headers={"User-Agent": UA, "Accept": "application/json" if as_json else "*/*", "Accept-Encoding": "gzip"}), timeout=25)
                except URLError as error:
                    if not isinstance(error.reason, ssl.SSLCertVerificationError):
                        raise
                    body, fields = system_tls_official_watch(url, limit)
                    record.update(http_status=200, http_date=fields.get('date'), final_url=url,
                                  content_type=fields.get('content-type'),
                                  last_modified=fields.get('last-modified'), bytes=len(body),
                                  sha256=hashlib.sha256(body).hexdigest(),
                                  transport='system curl; TLS verified; redirects disabled')
                else:
                    with response:
                        body = response.read(limit + 1)
                        if len(body) > limit:
                            raise ValueError("Response exceeds bounded collection size")
                        encoding = response.headers.get('Content-Encoding', 'identity').lower()
                        if encoding == 'gzip':
                            record['compressed_bytes'] = len(body)
                            with gzip.GzipFile(fileobj=BytesIO(body)) as compressed:
                                body = compressed.read(limit + 1)
                        elif encoding != 'identity':
                            raise ValueError('Unsupported response compression')
                        record.update(http_status=response.status, http_date=response.headers.get("Date"),
                                      final_url=response.url, content_type=response.headers.get('Content-Type'),
                                      last_modified=response.headers.get("Last-Modified"), bytes=len(body),
                                      sha256=hashlib.sha256(body).hexdigest())
                if len(body) > limit:
                    raise ValueError("Response exceeds bounded collection size")
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
                self.requests.append(record)
                return result
            except Exception as error:
                record["error"] = f"{type(error).__name__}: {str(error)[:220]}"
                if isinstance(error, HTTPError):
                    record["http_status"] = error.code
                self.requests.append(record)
                retry_coastwatch_forbidden = coastwatch and isinstance(error, HTTPError) and error.code == 403
                if (attempt == attempts - 1 or
                        isinstance(error, (ValueError, HTTPError)) and getattr(error, "code", 0) < 500
                        and not retry_coastwatch_forbidden):
                    raise
                time.sleep(1 + attempt)


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
    wave = model in ("ecmwf_wam025", "ncep_gfswave025")
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
    url = ("https://marine-api.open-meteo.com/v1/marine?" if wave else "https://api.open-meteo.com/v1/forecast?") + urlencode(params)
    def load(client):
        meta = client.get(MODEL_META[model], True)
        initialized = meta.get("last_run_initialisation_time")
        if not isinstance(initialized, (float, int)):
            raise ValueError("Model initialization timestamp absent")
        data = client.get(url, True)
        if not isinstance(data, list) or len(data) != len(points):
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
                "points": data, "note": "Regional model archive; shared with public weather views when fresh. Browser retains direct-provider recovery."}
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
    jobs.append(("tides", "NOAA " + stations["tide_name"] + " reference tide predictions", "prediction", url, 36, lambda c, u=url: parsers.tides(c.get(u, True))))
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
    for offset in range(1, days + 1) if region["landing_names"] else []:
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
                "region_id": region_id, "scope": region["name"], "bounds": region["bounds"],
                "landing_names": region["landing_names"],
                "report_window": {"start": (local_day - timedelta(days=days)).isoformat(),
                                  "end": (local_day - timedelta(days=1)).isoformat(), "days": days},
                "sources": sources, "reports": sorted(reports, key=lambda r: (r["date"], r["id"]), reverse=True),
                "catch_probability": None, "bite_score": None,
                "regulations": regulatory_snapshot(sources, now, config["regulations"]),
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
