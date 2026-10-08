"""NDBC standard-met history: SHA-checked annual checkpoints, monthly bands, recent hourly means.

    python -m skippercast.pipeline.ndbc_history --mode full|recent --region morro-bay \
        --cache var/ndbc-history --previous <published history.json> --output <history.json>

The output is the `packages/coast` `HistoryBundle` (schemaVersion 1) that the
History view reads. `full` reads each station's archive index and every listed
annual file, reusing checkpoints whose bytes still match their SHA-256; `recent`
fetches only the 45-day realtime files and keeps the published baseline. Hours
are means of valid samples only; a missing hour is counted, never filled. This
is descriptive recorded history, not a climatology. Ported from `fish`
`src/providers/history.ts` and `scripts/refresh-history.mjs`.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import zlib

from .. import http

HOST = "www.ndbc.noaa.gov"
BASE = f"https://{HOST}"
HOUR = 3_600_000
WINDOW_DAYS = 45
MAX_BODY, MAX_DECODED, MAX_FILES = 2_000_000, 16_000_000, 100
KEY = re.compile(r"^ndbc/stdmet/[a-z0-9]{5}/\d{4}/[a-f0-9]{64}\.bin$")
# region id -> (packages/coast county id, stations: id, name, reference lat, lon)
STATIONS = {"morro-bay": ("slo", (("46215", "Diablo Canyon", 35.204, -120.859),
                                  ("46028", "Cape San Martin", 35.77, -121.903)))}
# metric -> (NDBC column, unit, valid SI min, max, archive sentinel, conversion)
FIELDS = {
    "waterTempF": ("WTMP", "°F", -5, 50, 999, lambda n: n * 1.8 + 32),
    "airTempF": ("ATMP", "°F", -60, 60, 999, lambda n: n * 1.8 + 32),
    "windKnots": ("WSPD", "kt", 0, 90, 99, lambda n: n * 1.9438444924406),
    "gustKnots": ("GST", "kt", 0, 110, 99, lambda n: n * 1.9438444924406),
    "waveFt": ("WVHT", "ft", 0, 40, 99, lambda n: n * 3.2808398950131),
    "periodS": ("DPD", "s", 0, 40, 99, lambda n: n),
}
UNITS = {"WVHT": "m", "DPD": "sec", "WTMP": "degC", "ATMP": "degC", "WSPD": "m/s", "GST": "m/s"}
QC_KEYS = ("inputRows", "acceptedRows", "rejectedRows", "duplicateRows", "conflictingValues", "maskedValues", "trailingMissingRows")


def iso(ms):
    return datetime.fromtimestamp(ms // 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def epoch(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def index_url(ident): return f"{BASE}/station_history.php?station={ident}"
def recent_url(ident): return f"{BASE}/data/realtime2/{ident}.txt"
def annual_url(ident, year): return f"{BASE}/data/historical/stdmet/{ident}h{year}.txt.gz"


def discover_years(html, ident, now):
    """Complete years the station's own archive index links; none are invented."""
    years = sorted({int(y) for y in re.findall(rf"(?:filename=|/){ident}h(\d{{4}})\.txt\.gz", html)})
    if not years or any(y < 1900 or y >= now.year for y in years):
        raise ValueError("No valid complete-year NDBC archive index")
    return years


def parse(text, now, year=None):
    """Standard-met rows -> (observations keyed by UTC ms, QC counts). SI units are converted."""
    lines = text.strip().splitlines()
    header = lines.pop(0).lstrip("#").split() if lines else []
    if header[:1] not in (["YY"], ["YYYY"]) or header[1:4] != ["MM", "DD", "hh"] or not {"WVHT", "WTMP"} <= set(header) or len(set(header)) != len(header):
        raise ValueError("Unsupported NDBC history schema")
    if lines and lines[0].startswith("#"):
        units = lines.pop(0).lstrip("#").split()
        for column, unit in UNITS.items():
            if column in header and units[header.index(column)] != unit:
                raise ValueError(f"Unexpected NDBC {column} unit")
    minutes, limit = header[4] == "mm", now.timestamp() * 1000 + 300_000
    qc, records = dict.fromkeys(QC_KEYS, 0), {}
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        qc["inputRows"] += 1
        row = line.split()
        if len(row) == len(header) - 1 and header[-1] == "TIDE":  # documented missing trailing TIDE column
            row.append("MM")
            qc["trailingMissingRows"] += 1
        try:
            if len(row) != len(header):
                raise ValueError
            y = int(row[0]) + ((1900 if int(row[0]) >= 70 else 2000) if len(row[0]) == 2 else 0)
            at = int(datetime(y, int(row[1]), int(row[2]), int(row[3]), int(row[4]) if minutes else 0, tzinfo=timezone.utc).timestamp() * 1000)
            if at > limit or (year is not None and y != year):
                raise ValueError
        except ValueError:
            qc["rejectedRows"] += 1
            continue
        obs = {}
        for metric, (column, _, low, high, missing, convert) in FIELDS.items():
            raw = row[header.index(column)] if column in header else "MM"
            try:
                n = float(raw)
            except ValueError:
                n = math.nan
            if raw == "MM" or not math.isfinite(n) or n == missing or not low <= n <= high or (metric == "periodS" and n == 0):
                obs[metric] = None
                qc["maskedValues"] += raw != "MM" and column in header
            else:
                obs[metric] = convert(n)
        if at in records:  # a conflicting duplicate masks the value instead of choosing one
            qc["duplicateRows"] += 1
            for metric, value in obs.items():
                if records[at][metric] != value:
                    records[at][metric] = None
                    qc["conflictingValues"] += 1
            continue
        records[at] = obs
        qc["acceptedRows"] += 1
    if not records:
        raise ValueError("No valid NDBC observation rows")
    return dict(sorted(records.items())), qc


def hourly(observations):
    """UTC-hour means of valid samples, with raw and per-metric counts. Hours without rows are absent."""
    groups = {}
    for at, obs in observations.items():
        groups.setdefault(at // HOUR * HOUR, []).append(obs)
    hours = []
    for at, group in sorted(groups.items()):
        hour, counts = {"at": iso(at), "sampleCount": len(group)}, {}
        for metric in FIELDS:
            values = [o[metric] for o in group if o[metric] is not None]
            counts[metric] = len(values)
            hour[metric] = round(sum(values) / len(values), 3) if values else None
        hours.append({**hour, "counts": counts})
    return hours


def recent_summary(observations, qc, now, days=WINDOW_DAYS):
    end = int(now.timestamp() * 1000)
    start = end // HOUR * HOUR - days * 24 * HOUR
    selected = {at: o for at, o in observations.items() if start <= at <= end}
    hours = hourly(selected)
    slots = {epoch(h["at"]) for h in hours if any(h[m] is not None for m in FIELDS)}
    expected, gap, max_gap = math.ceil((end - start) / HOUR), 0, 0
    for at in range(start, end, HOUR):
        gap = 0 if at in slots else gap + 1
        max_gap = max(max_gap, gap)
    measured = [at for at, o in selected.items() if any(v is not None for v in o.values())]
    return {"from": iso(start), "through": iso(end), "firstObservedAt": iso(measured[0]) if measured else None,
            "lastObservedAt": iso(measured[-1]) if measured else None,
            "stale": not measured or end - measured[-1] > 3 * HOUR, "expectedHours": expected,
            "observedHours": len(slots), "hourCoverageFraction": len(slots) / expected, "maxGapHours": max_gap,
            "hours": hours, "qc": qc}


def quantile(values, p):
    """Linear interpolation between sorted values (the fish/packages/coast definition)."""
    if not values:
        return None
    i = (len(values) - 1) * p
    low = math.floor(i)
    return round(values[low] + (values[math.ceil(i)] - values[low]) * (i - low), 3)


def seasonal(annual):
    """Pool UTC-hour means by calendar month across archive years; every hour weighs the same."""
    years = sorted(annual)
    months = []
    for month in range(1, 13):
        for metric, (_, unit, *_rest) in FIELDS.items():
            values, contributors, raw = [], [], 0
            for year in years:
                found = [h for h in annual[year] if int(h["at"][5:7]) == month and h[metric] is not None]
                values += [h[metric] for h in found]
                raw += sum(h["counts"][metric] for h in found)
                contributors += [year] if found else []
            values.sort()
            expected = sum(round((datetime(y + month // 12, month % 12 + 1, 1) - datetime(y, month, 1)).total_seconds() / 3600) for y in years)
            months.append({"month": month, "metric": metric, "unit": unit, "count": len(values), "rawSampleCount": raw,
                           "expectedHours": expected, "coverageFraction": len(values) / expected if expected else 0,
                           "yearsWithData": contributors, "p10": quantile(values, .1), "median": quantile(values, .5),
                           "p90": quantile(values, .9), "min": values[0] if values else None, "max": values[-1] if values else None,
                           "mean": round(sum(values) / len(values), 3) if values else None})
    label = (f"Recorded seasonal history · {years[0]}–{years[-1]}" if len(years) > 1 else
             f"{years[0]} recorded year reference" if years else "Historical reference unavailable")
    return {"kind": "multi-year-reference" if len(years) > 1 else "year-reference" if years else "unavailable", "label": label,
            "years": years, "periodStart": f"{years[0]}-01-01T00:00:00.000Z" if years else None,
            "periodEnd": f"{years[-1]}-12-31T23:59:59.999Z" if years else None,
            "aggregation": "UTC-hour means, weighted equally", "months": months}


def decode(body):
    if body[:2] != b"\x1f\x8b":
        return body.decode("utf-8")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    text = decoder.decompress(body, MAX_DECODED + 1)
    if decoder.unconsumed_tail or len(text) > MAX_DECODED or not decoder.eof:
        raise ValueError("NOAA archive exceeds the decoded budget or is truncated")
    return text.decode("utf-8")


def fetch(session, url, role, year=None):
    if not re.fullmatch(rf"{re.escape(BASE)}/(station_history\.php\?station=[a-z0-9]{{5}}|data/(historical/stdmet|realtime2)/[a-z0-9.]+)", url):
        raise ValueError("Unapproved NOAA history URL")
    body = session.get(url, timeout=15, max_bytes=MAX_BODY, allowed_hosts=[HOST], allowed_prefixes=[BASE + "/"]).body or b""
    text = decode(body)
    return body, text, {"url": url, "role": role, **({"year": year} if year else {}), "outcome": "ok", "fetchedAt": iso(int(datetime.now(timezone.utc).timestamp() * 1000)),
                        "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "decodedBytes": len(text.encode())}


def atomic(path, value, compact=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, **({"separators": (",", ":")} if compact else {"indent": 1})) + "\n")
    tmp.replace(path)


def annual_receipt(session, cache, checkpoint, ident, year, revalidate=False):
    """Reuse a checkpointed archive whose bytes still match its SHA-256; otherwise fetch and record it."""
    key, saved = f"{ident}:annual:{year}", checkpoint["records"].get(f"{ident}:annual:{year}")
    if saved and saved.get("outcome") == "ok" and not revalidate and KEY.fullmatch(saved.get("objectKey", "")):
        try:
            body = (cache / saved["objectKey"]).read_bytes()
            if hashlib.sha256(body).hexdigest() == saved["sha256"]:
                return decode(body), saved
        except OSError:
            pass  # missing or corrupt receipt: refetch below
    url = annual_url(ident, year)
    try:
        body, text, source = fetch(session, url, "annual", year)
    except (OSError, ValueError) as error:
        checkpoint["records"][key] = {"url": url, "role": "annual", "year": year, "outcome": "error", "fetchedAt": iso(int(datetime.now(timezone.utc).timestamp() * 1000)), "error": str(error)}
        raise
    source["objectKey"] = f"ndbc/stdmet/{ident}/{year}/{source['sha256']}.bin"
    (cache / source["objectKey"]).parent.mkdir(parents=True, exist_ok=True)
    (cache / source["objectKey"]).write_bytes(body)
    checkpoint["records"][key] = source
    return text, source


def limitations(ident):
    return ["Station history describes recorded conditions, not calibrated catch probabilities or forecast bias.",
            "Monthly distributions use UTC-hour means weighted equally; missing hours are not interpolated.",
            "Coordinates describe the present reference station; historical deployments, instruments and observing heights may change.",
            "Buoy surface temperature is not bottom temperature; observed waves are not beach breakers.",
            "Wave/SST buoy: wind and air-temperature observations are generally unavailable." if ident == "46215" else
            "Offshore Cape San Martin exposure differs from SLO nearshore water; wind is measured at buoy height, not standardized here to 10 m."]


def collect(region_id, mode, session, cache, previous=None, now=None, revalidate=False, max_files=MAX_FILES):
    now = now or datetime.now(timezone.utc)
    county, stations = STATIONS[region_id]
    prior = {s["stationId"]: s for s in (previous or {}).get("stations", [])} if (previous or {}).get("countyId") == county else {}
    if mode == "recent" and set(prior) != {s[0] for s in stations}:
        raise SystemExit("Recent refresh needs a matching published history; run the full backfill first")
    checkpoint_path = cache / f"{region_id}-checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {"schemaVersion": 1, "regionId": region_id, "records": {}}
    out, ok, budget = [], False, max_files
    for ident, name, lat, lon in stations:
        old, sources, annual = prior.get(ident), [], {}
        stamp_now = iso(int(now.timestamp() * 1000))
        archive = {"indexUrl": index_url(ident), "availableYears": [], "discoveredAt": stamp_now, "outcome": "error"}
        if mode == "full":
            try:
                _, text, source = fetch(session, archive["indexUrl"], "index")
                archive = {**archive, "availableYears": discover_years(text, ident, now), "discoveredAt": source["fetchedAt"], "outcome": "ok"}
                sources.append(source)
                ok = True
            except (OSError, ValueError) as error:
                sources.append({"url": archive["indexUrl"], "role": "index", "outcome": "error", "fetchedAt": stamp_now, "error": str(error)})
                archive = {**old["archive"], "outcome": "error"} if old else archive
            for year in archive["availableYears"] if archive["outcome"] == "ok" else []:
                budget -= 1
                if budget < 0:
                    raise SystemExit(f"Annual archives exceed the --max-files={max_files} budget; review the scope")
                try:
                    text, source = annual_receipt(session, cache, checkpoint, ident, year, revalidate)
                    observations, qc = parse(text, now, year)
                    annual[year] = hourly(observations)
                    sources.append({**source, "parsedRows": qc["acceptedRows"], "rejectedRows": qc["rejectedRows"]})
                    ok = True
                except (OSError, ValueError) as error:
                    sources.append({"url": annual_url(ident, year), "role": "annual", "year": year, "outcome": "error", "fetchedAt": stamp_now, "error": str(error)})
                atomic(checkpoint_path, checkpoint, compact=False)
        else:
            archive, sources = old["archive"], [s for s in old["sources"] if s["role"] != "recent"]
        try:
            _, text, source = fetch(session, recent_url(ident), "recent")
            observations, qc = parse(text, now)
            recent = recent_summary(observations, qc, now)
            sources.append({**source, "parsedRows": qc["acceptedRows"], "rejectedRows": qc["rejectedRows"]})
            ok = True
        except (OSError, ValueError) as error:
            sources.append({"url": recent_url(ident), "role": "recent", "outcome": "error", "fetchedAt": stamp_now, "error": str(error)})
            recent = None
            if old:  # keep the last measured series, aged honestly, with its original receipt
                last = old["recent"]["lastObservedAt"]
                recent = {**old["recent"], "stale": not last or now.timestamp() * 1000 - epoch(last) > 3 * HOUR}
                sources += [s for s in old["sources"] if s["role"] == "recent" and s["outcome"] == "ok"][-1:]
        recent = recent or recent_summary({}, dict.fromkeys(QC_KEYS, 0), now)
        if mode == "full" and (annual or not old):
            baseline = seasonal(annual)
        else:  # recent mode, or every annual archive failed: keep the published baseline and its receipts
            baseline = old["baseline"]
            sources += [s for s in old["sources"] if s["role"] == "annual" and s["outcome"] == "ok"] if mode == "full" else []
        out.append({"stationId": ident, "name": name, "lat": lat, "lon": lon, "recent": recent, "baseline": baseline,
                    "archive": archive, "sources": sources, "limitations": limitations(ident)})
    if not ok:
        raise SystemExit("Every NDBC history request failed; the published history is kept")
    return {"schemaVersion": 1, "countyId": county, "generatedAt": iso(int(datetime.now(timezone.utc).timestamp() * 1000)),
            "recentWindowDays": WINDOW_DAYS, "stations": out}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("full", "recent"), required=True)
    parser.add_argument("--region", default="morro-bay", choices=sorted(STATIONS))
    parser.add_argument("--cache", type=Path, default=Path("var/ndbc-history"))
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revalidate", action="store_true", help="refetch annual archives even when the checkpoint verifies")
    parser.add_argument("--max-files", type=int, default=MAX_FILES)
    args = parser.parse_args()
    previous = json.loads(args.previous.read_text()) if args.previous and args.previous.exists() else None
    args.cache.mkdir(parents=True, exist_ok=True)
    session = http.Session(allowed_hosts=[HOST], min_interval={HOST: 1.0})
    bundle = collect(args.region, args.mode, session, args.cache, previous, revalidate=args.revalidate, max_files=args.max_files)
    atomic(args.output, bundle)
    print(json.dumps({"generatedAt": bundle["generatedAt"], "stations": [
        {"id": s["stationId"], "years": len(s["baseline"]["years"]), "recentHours": s["recent"]["observedHours"],
         "lastObservedAt": s["recent"]["lastObservedAt"], "failures": sum(x["outcome"] == "error" for x in s["sources"])}
        for s in bundle["stations"]]}))


if __name__ == "__main__":
    main()
