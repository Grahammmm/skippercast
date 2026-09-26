"""Read public marine forecast sources and preserve evidence for human review.

The current source profile is specific to Morro Bay, California. The numerical
screen is not a trip recommendation, automatic score, or entrance clearance.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UA = "SkipperCast/0.1 (personal marine forecast research)"
WIND_MODELS = ("ecmwf_ifs025", "gfs_global")
WAVE_MODELS = ("ecmwf_wam025", "ncep_gfswave016")
WIND_VARIABLES = (
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "precipitation", "visibility", "weather_code",
)
WAVE_VARIABLES = tuple(
    f"{kind}_{measure}"
    for kind in ("wave", "wind_wave", "swell_wave", "secondary_swell_wave")
    for measure in ("height", "period", "direction")
)
META_NAMES = ("meta-ecmwf-wind", "meta-gfs-wind", "meta-ecmwf-wave", "meta-gfs-wave")
SCREEN_HOURS = tuple(range(6, 14))


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_config(config):
    """Reject unsupported profiles, locations and accidental private settings."""
    allowed = {"source_profile", "timezone", "weather_sampling_points", "planning"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("config must contain only source_profile, timezone, weather_sampling_points and optional planning")
    if config.get("source_profile") != "morro-bay":
        raise ValueError("only the morro-bay source profile is implemented")
    if config.get("timezone") != "America/Los_Angeles":
        raise ValueError("the morro-bay profile requires America/Los_Angeles")
    try:
        ZoneInfo(config["timezone"])
    except ZoneInfoNotFoundError as error:
        raise ValueError("IANA timezone data is required; install OS timezone data or the tzdata package") from error
    points = config.get("weather_sampling_points")
    if not isinstance(points, list) or not 1 <= len(points) <= 16:
        raise ValueError("weather_sampling_points must contain 1–16 locations")
    names = set()
    for point in points:
        if not isinstance(point, dict) or set(point) != {"name", "latitude", "longitude"}:
            raise ValueError("each sampling point requires only name, latitude and longitude")
        name = point["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or name in names:
            raise ValueError("sampling point names must be unique lowercase identifiers")
        names.add(name)
        if not _number(point["latitude"]) or not 35.0 <= point["latitude"] <= 35.9:
            raise ValueError("sampling latitude must be within the supported Morro Bay region (35.0–35.9)")
        if not _number(point["longitude"]) or not -121.5 <= point["longitude"] <= -120.5:
            raise ValueError("sampling longitude must be within the supported Morro Bay region (-121.5–-120.5)")
    planning = config.get("planning", {})
    numeric_limits = {
        "cruise_knots": (0, 100), "maximum_fishing_depth_ft": (0, 200),
        "minimum_fishing_hours": (0, 24), "harbor_minutes_each_way": (0, 180),
    }
    time_fields = {"planned_return_local", "latest_return_local"}
    if not isinstance(planning, dict) or set(planning) - set(numeric_limits) - time_fields:
        raise ValueError("planning contains unsupported fields")
    for key, (lower, upper) in numeric_limits.items():
        if key in planning and (not _number(planning[key]) or not lower < planning[key] <= upper):
            raise ValueError(f"planning.{key} must be greater than {lower} and at most {upper}")
    for key in time_fields:
        if key in planning and (not isinstance(planning[key], str)
                                or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", planning[key])):
            raise ValueError(f"planning.{key} must use 24-hour HH:MM")
    if ("planned_return_local" in planning and "latest_return_local" in planning
            and planning["planned_return_local"] > planning["latest_return_local"]):
        raise ValueError("planned return cannot be later than latest return")
    return config


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fetch(name, url, out):
    """Save one response and its transport metadata, including failed reads."""
    record = {"name": name, "url": url, "retrieved_at": datetime.now(timezone.utc).isoformat()}
    try:
        curl = shutil.which("curl") if url.startswith("https://wildlife.ca.gov/") else None
        if curl:
            # Some systems expose the CDFW trust chain through curl's TLS store.
            # If curl is absent, urllib uses its default verified TLS context.
            with tempfile.TemporaryDirectory() as temp:
                headers, content = Path(temp) / "headers", Path(temp) / "content"
                result = subprocess.run(
                    [curl, "--silent", "--show-error", "--location", "--max-time", "25",
                     "--user-agent", UA, "--dump-header", str(headers), "--output", str(content),
                     "--write-out", "%{http_code}", url],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode:
                    raise RuntimeError(f"TLS-verified curl failed with exit {result.returncode}")
                parsed_headers = {}
                for line in headers.read_text(encoding="utf-8", errors="replace").splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        parsed_headers[key.lower()] = value.strip()
                data = content.read_bytes()
                record.update(status=int(result.stdout), http_date=parsed_headers.get("date"),
                              content_type=parsed_headers.get("content-type"),
                              last_modified=parsed_headers.get("last-modified"),
                              transport="curl, TLS verified")
        else:
            try:
                response = urlopen(Request(url, headers={"User-Agent": UA}), timeout=25)
            except HTTPError as error:
                response = error
            with response:
                data = response.read()
                record.update(status=response.status, http_date=response.headers.get("Date"),
                              content_type=response.headers.get("Content-Type"),
                              last_modified=response.headers.get("Last-Modified"),
                              transport="urllib, TLS verified")
        record.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        (out / f"{name}.raw.txt").write_bytes(data)
        body = data.decode("utf-8", errors="replace")
        if "html" in (record["content_type"] or ""):
            parser = PageText()
            parser.feed(body)
            (out / f"{name}.text.txt").write_text("\n".join(parser.parts) + "\n", encoding="utf-8")
        if record["status"] != 200:
            record["error"] = f"HTTP {record['status']}"
        elif not body.strip():
            record["error"] = "Empty response body"
        else:
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict) and parsed.get("error"):
                    record["error"] = str(parsed["error"])[:500]
            except ValueError:
                if "json" in (record["content_type"] or ""):
                    record["error"] = "Response advertised JSON but could not be parsed"
    except Exception as error:
        record["error"] = type(error).__name__ + ": " + str(error)[:250]
    record["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(out / f"{name}.meta.json", record)
    return record


def sources(config, now):
    """Build the Morro Bay URLs using the local date, not the UTC date."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(ZoneInfo(config["timezone"]))
    points = config["weather_sampling_points"]
    base = {"latitude": ",".join(str(p["latitude"]) for p in points),
            "longitude": ",".join(str(p["longitude"]) for p in points),
            "timezone": config["timezone"], "forecast_days": 8, "cell_selection": "sea"}
    wind = dict(base, models=",".join(WIND_MODELS), wind_speed_unit="kn", daily="sunrise,sunset",
                hourly=",".join(WIND_VARIABLES))
    wave = dict(base, models=",".join(WAVE_MODELS), hourly=",".join(WAVE_VARIABLES))
    tides = {"product": "predictions", "application": "SkipperCast",
             "begin_date": now.strftime("%Y%m%d"), "end_date": (now + timedelta(days=7)).strftime("%Y%m%d"),
             "datum": "MLLW", "station": "9412110", "time_zone": "lst_ldt",
             "units": "english", "interval": "hilo", "format": "json"}
    return {
        "wind-models": "https://api.open-meteo.com/v1/forecast?" + urlencode(wind),
        "wave-models": "https://marine-api.open-meteo.com/v1/marine?" + urlencode(wave),
        "meta-ecmwf-wind": "https://api.open-meteo.com/data/ecmwf_ifs025/static/meta.json",
        "meta-gfs-wind": "https://api.open-meteo.com/data/ncep_gfs013/static/meta.json",
        "meta-ecmwf-wave": "https://marine-api.open-meteo.com/data/ecmwf_wam025/static/meta.json",
        "meta-gfs-wave": "https://marine-api.open-meteo.com/data/ncep_gfswave016/static/meta.json",
        "nws-pzz645": "https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=PZZ645",
        "nws-lox-discussion": "https://forecast.weather.gov/product.php?issuedby=LOX&product=AFD&site=lox",
        "nws-active-alerts": "https://api.weather.gov/alerts/active/zone/PZZ645",
        "ndbc-46215": "https://www.ndbc.noaa.gov/data/realtime2/46215.txt",
        "ndbc-46215-swell": "https://www.ndbc.noaa.gov/data/realtime2/46215.spec",
        "ndbc-46028": "https://www.ndbc.noaa.gov/data/realtime2/46028.txt",
        "port-san-luis-tides-reference-only": "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?" + urlencode(tides),
        "harbor-information": "https://www.morrobayca.gov/156/Weather-Boating-Information",
        "harbor-department": "https://www.morrobayca.gov/144/Harbor",
        "cdfw-groundfish": "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary",
        "cdfw-inseason": "https://wildlife.ca.gov/Fishing/Ocean/Regulations/Inseason",
        "cdfw-buchon-mpas": "https://wildlife.ca.gov/Conservation/Marine/MPAs/Point-Buchon",
        "cdfw-cambria-mpas": "https://wildlife.ca.gov/Conservation/Marine/MPAs/Cambria-White-Rock",
        "virgs-catch-reports": "https://www.virgslanding.com/fish-counts.php",
    }


def _timestamps(raw, tz, gaps, label):
    if not isinstance(raw, list):
        gaps.append(f"{label}: missing or malformed hourly.time array")
        return []
    parsed, seen, duplicate = [], set(), set()
    for value in raw:
        try:
            stamp = datetime.fromisoformat(value)
            stamp = stamp.replace(tzinfo=tz) if stamp.tzinfo is None else stamp.astimezone(tz)
            if stamp.minute or stamp.second or stamp.microsecond:
                raise ValueError("not an hourly timestamp")
            if stamp in seen:
                duplicate.add(stamp)
            seen.add(stamp)
            parsed.append(stamp)
        except (ValueError, TypeError):
            parsed.append(None)
    if any(value is None for value in parsed):
        gaps.append(f"{label}: invalid hourly timestamps were excluded")
    if duplicate:
        gaps.append(f"{label}: duplicate hourly timestamps were excluded")
        parsed = [value if value not in duplicate else None for value in parsed]
    return parsed


def _location_screen(data, point, source, forecast_dates, tz, gaps):
    label = f"{source}/{point['name']}"
    entry = {"source": source, "requested_location": point, "returned_grid": {},
             "grid_warning": "Combined-model response grid is not proof of each model's native cell; inspect single-model requests when comparing locations.",
             "daily_06_to_13_screen": [], "unavailable_variables": [], "populated_coverage": {}}
    if not isinstance(data, dict):
        gaps.append(f"{label}: missing or malformed location object")
        data = {}
    entry["returned_grid"] = {key: data.get(key) if _number(data.get(key)) else None
                              for key in ("latitude", "longitude")}
    if any(not _number(value) for value in entry["returned_grid"].values()):
        gaps.append(f"{label}: returned grid coordinates unavailable")
    if data.get("timezone") != str(tz):
        gaps.append(f"{label}: returned timezone missing or does not match the request")
    hourly = data.get("hourly")
    if not isinstance(hourly, dict):
        gaps.append(f"{label}: missing or malformed hourly object")
        hourly = {}
    units = data.get("hourly_units")
    if not isinstance(units, dict):
        gaps.append(f"{label}: missing hourly units")
        units = {}
    stamps = _timestamps(hourly.get("time"), tz, gaps, label)
    models, variables = (WIND_MODELS, WIND_VARIABLES) if source == "wind-models" else (WAVE_MODELS, WAVE_VARIABLES)
    normalized = {}
    for model in models:
        for base in variables:
            variable = f"{base}_{model}"
            values = hourly.get(variable)
            if not isinstance(values, list):
                gaps.append(f"{label}: {variable} absent or not an array")
                values = []
            elif len(values) != len(stamps):
                gaps.append(f"{label}: {variable} length {len(values)} differs from time length {len(stamps)}")
            if any(value is not None and not _number(value) for value in values):
                gaps.append(f"{label}: {variable} contains invalid numeric values")
            cleaned = [values[i] if i < len(values) and _number(values[i]) else None for i in range(len(stamps))]
            normalized[variable] = cleaned
            if not any(value is not None for value in cleaned):
                entry["unavailable_variables"].append(variable)
            valid_times = [stamp for stamp, value in zip(stamps, cleaned) if stamp is not None and value is not None]
            entry["populated_coverage"][variable] = {
                "first": min(valid_times).isoformat() if valid_times else None,
                "last": max(valid_times).isoformat() if valid_times else None,
            }
            if not isinstance(units.get(variable), str) or not units[variable]:
                gaps.append(f"{label}: {variable} units unavailable")
            elif base in ("wind_speed_10m", "wind_gusts_10m") and units[variable] != "kn":
                gaps.append(f"{label}: {variable} unexpected wind unit {units[variable]!r}; expected kn")
            elif source == "wave-models" and base.endswith("_height") and units[variable] not in ("m", "ft"):
                gaps.append(f"{label}: {variable} unexpected wave-height unit {units[variable]!r}")
    missing_by_variable = {variable: [] for variable in normalized}
    for day in forecast_dates:
        indices = [i for i, stamp in enumerate(stamps)
                   if stamp is not None and stamp.date().isoformat() == day and stamp.hour in SCREEN_HOURS]
        row = {"date": day, "hour_count": len(indices), "expected_hour_count": len(SCREEN_HOURS), "ranges": {}}
        if len(indices) != len(SCREEN_HOURS):
            gaps.append(f"{label}: {day} has {len(indices)}/8 screening timestamps")
        for variable, values in normalized.items():
            usable = [values[i] for i in indices if values[i] is not None]
            unit = units.get(variable) if isinstance(units.get(variable), str) else None
            if source == "wave-models" and "_height_" in variable and unit == "m":
                usable = [value / 0.3048 for value in usable]
                unit = "ft"
            row["ranges"][variable] = {"min": round(min(usable), 2) if usable else None,
                                       "max": round(max(usable), 2) if usable else None,
                                       "available_hours": len(usable), "unit": unit}
            if len(usable) != len(SCREEN_HOURS):
                missing_by_variable[variable].append(day)
        entry["daily_06_to_13_screen"].append(row)
    for variable, days in missing_by_variable.items():
        if days:
            gaps.append(f"{label}: {variable} incomplete for {', '.join(days)}")
    if source == "wind-models":
        inconsistent = []
        for model in WIND_MODELS:
            speed = normalized[f"wind_speed_10m_{model}"]
            gust = normalized[f"wind_gusts_10m_{model}"]
            for stamp, sustained, gust_value in zip(stamps, speed, gust):
                if (stamp is not None and sustained is not None and gust_value is not None
                        and units.get(f"wind_speed_10m_{model}") == "kn"
                        and units.get(f"wind_gusts_10m_{model}") == "kn"
                        and gust_value < sustained):
                    inconsistent.append({"time": stamp.isoformat(), "model": model,
                                         "sustained": sustained, "gust": gust_value,
                                         "sustained_unit": units.get(f"wind_speed_10m_{model}"),
                                         "gust_unit": units.get(f"wind_gusts_10m_{model}")})
        entry["gust_below_sustained_flags"] = inconsistent
        if inconsistent:
            gaps.append(f"{label}: {len(inconsistent)} gust-below-sustained values require investigation")
    return entry


def summarize(out, config, today):
    """Produce ranges without interpolating or filling absent observations."""
    tz = ZoneInfo(config["timezone"])
    if isinstance(today, datetime):
        if today.tzinfo is None or today.utcoffset() is None:
            raise ValueError("datetime input must be timezone-aware")
        today = today.astimezone(tz).date()
    if not isinstance(today, date):
        raise ValueError("today must be a date or timezone-aware datetime")
    summary = {
        "source_profile": config["source_profile"], "timezone": config["timezone"],
        "local_date": today.isoformat(),
        "forecast_dates": [(today + timedelta(days=i)).isoformat() for i in range(1, 8)],
        "warning": "Numerical 06:00–13:00 screening only. This is not a complete trip window; no score, catch prediction, entrance clearance, or trip recommendation is generated.",
        "tide_reference_warning": "Port San Luis 9412110 is a nearby reference, not a Morro Bay entrance tide/current prediction. No harbor or bottom current is inferred from it.",
        "model_updates": {}, "locations": [], "data_gaps": [],
    }
    gaps = summary["data_gaps"]
    screen_end = datetime.combine(today + timedelta(days=7), datetime.min.time(), tz).replace(hour=13)
    for name in META_NAMES:
        try:
            metadata = json.loads((out / f"{name}.raw.txt").read_text(encoding="utf-8"))
            times = {}
            for key in ("last_run_initialisation_time", "last_run_availability_time", "data_end_time"):
                value = metadata[key]
                if not _number(value):
                    raise ValueError(f"invalid {key}")
                times[key] = datetime.fromtimestamp(value, timezone.utc)
            summary["model_updates"][name] = {key: value.isoformat() for key, value in times.items()}
            summary["model_updates"][name]["note"] = "Provider latest-run metadata, not per-value attribution to an immutable run. HTTP Date and generationtime_ms are not issue times."
            if times["data_end_time"] < screen_end:
                gaps.append(f"{name}: latest published coverage ends before the seven-date screen; later populated values need separate run attribution")
            if times["last_run_availability_time"] < times["last_run_initialisation_time"]:
                gaps.append(f"{name}: availability precedes initialization")
        except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
            gaps.append(f"Cannot establish {name} issue/coverage metadata: {type(error).__name__}")
    for name in ("wind-models", "wave-models"):
        try:
            datasets = json.loads((out / f"{name}.raw.txt").read_text(encoding="utf-8"))
            points = config["weather_sampling_points"]
            if isinstance(datasets, dict) and len(points) == 1 and "hourly" in datasets:
                datasets = [datasets]
            if not isinstance(datasets, list):
                raise ValueError("forecast response must be a location list (or one location object)")
            if len(datasets) != len(points):
                gaps.append(f"{name}: returned {len(datasets)} locations, expected {len(points)}")
            for i, point in enumerate(points):
                data = datasets[i] if i < len(datasets) else None
                summary["locations"].append(_location_screen(data, point, name, summary["forecast_dates"], tz, gaps))
        except (OSError, ValueError, TypeError) as error:
            gaps.append(f"{name}: {type(error).__name__}: {error}")
    _write_json(out / "screen.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="explicit public source profile JSON")
    parser.add_argument("--output", required=True, type=Path, help="new run directory; existing directories are never overwritten")
    args = parser.parse_args(argv)
    try:
        config = validate_config(json.loads(args.config.read_text(encoding="utf-8")))
        now = datetime.now(ZoneInfo(config["timezone"]))
        out = args.output
        out.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError) as error:
        print(f"collector: {error}", file=sys.stderr)
        return 2
    items = list(sources(config, now).items())
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(lambda item: fetch(item[0], item[1], out), items))
    _write_json(out / "manifest.json", records)
    screen = summarize(out, config, now)
    failures = [record for record in records if record.get("error")]
    incomplete = bool(failures or screen["data_gaps"])
    report = {"run_directory": str(out.resolve()), "status": "incomplete" if incomplete else "collected",
              "sources_attempted": len(records), "source_failures": failures, "data_gaps": screen["data_gaps"],
              "note": "Collection status is not a safety, regulatory, or trip assessment."}
    _write_json(out / "result.json", report)
    print(json.dumps(report, indent=2))
    return 1 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
