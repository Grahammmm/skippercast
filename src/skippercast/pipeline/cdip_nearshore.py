"""CDIP MOP alongshore nearshore model sites for the live conditions feed (FE-40).

Each site named in `regions/<id>/region.json` `nearshore_model.sites` is read from
CDIP's THREDDS OPeNDAP server as two small text responses (`.das` metadata and a
`.ascii` subset). The parsed record is the `packages/coast` `NearshoreSite`
(`packages/coast/src/enrichment-types.ts`) and the request outcome a
`SourceStatus` (`types.ts`), so FE-84 can serve SkipperCast's feed to the coast
report without a client change. Ported from `fish` `src/providers/enrichment.ts`.

Rules kept from the port:
- the site label and coordinates in the data must match the reviewed binding;
- the metadata contract (units, time origin, direction convention, quality-flag
  meanings) must be unchanged, and every array must be complete;
- native three-hour valid times are kept; no hourly samples are generated;
- only primary `good` samples are used: `insufficient_input` masks every value,
  `low_energy` keeps the height and masks period and direction; fill values and
  values outside the metadata's valid range stay null;
- `issuedAt` is the publisher's `date_issued`, never a creation, modification or
  fetch time; older than 48 hours is `stale`, absent is `unknown`.

A site that fails keeps its previous published record unchanged (with its
original fetch and issue clocks) while that fetch is under three hours old, the
fetch-age gate of `packages/coast` `freshNearshore`; otherwise it is published
as `availability: error` with no hours. Modelled significant height is not a
breaking-wave observation. Credit: data from CDIP, Scripps Institution of
Oceanography (https://cdip.ucsd.edu/).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re

from .. import http
from ..util.time import stamp
from .collect import publication

SOURCE_ID = "cdip-mop"
ADAPTER = "cdip-mop-dap2"
HOST = "thredds.cdip.ucsd.edu"
BASE = f"https://{HOST}/thredds/dodsC/cdip/model/MOP_alongshore/"
CREDIT = "Data from CDIP, Scripps Institution of Oceanography"
MAX_BYTES = 750_000
TIMEOUT_S = 12
ATTEMPTS = 3
FT_PER_M = 3.280839895
MAX_SAMPLES = 256
WINDOW_BEFORE, WINDOW_AFTER = timedelta(hours=3), timedelta(hours=72)
STALE_AFTER = timedelta(hours=48)
RETAIN_FOR = timedelta(hours=3)
FUTURE_SKEW = timedelta(minutes=5)
COORDINATE_TOLERANCE = 0.02
SITE_ID = re.compile(r"[A-Z]{1,2}\d{3,4}")
AREA_ID = re.compile(r"[a-z0-9-]{1,40}")
VARIABLES = ("waveTime,waveHs,waveTp,waveDp,waveFlagPrimary,waveFlagSecondary,"
             "metaLatitude,metaLongitude,metaWaterDepth,metaSiteLabel")
NUMBER = re.compile(r"NaN|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?", re.I)
UNITS = {"waveHs": "meter", "waveTp": "second", "waveDp": "degreeT"}
TIME_UNITS = "seconds since 1970-01-01 00:00:00 UTC"
PRIMARY_MEANINGS = "good not_evaluated questionable bad missing"
SECONDARY_MEANINGS = "unspecified insufficient_input low_energy"
GOOD, UNSPECIFIED, LOW_ENERGY = 1, 0, 2


def das_url(ident): return f"{BASE}{ident}_forecast.nc.das"
def data_url(ident): return f"{BASE}{ident}_forecast.nc.ascii?{VARIABLES}"
def page_url(ident): return f"https://cdip.ucsd.edu/mops/?mop={ident}"


def iso(moment):
    """JavaScript `toISOString()` form, as `fish` wrote it: milliseconds and `Z`."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_time(value):
    if not isinstance(value, str) or not re.match(r"\d{4}-\d\d-\d\dT", value):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def bindings(region, sources):
    """The region's reviewed sites as `NearshoreBinding`s; [] when the region binds none."""
    config = region.get("nearshore_model")
    if not config:
        return []
    source = sources.get(config.get("source_id"))
    if (not source or source.get("adapter") != ADAPTER or HOST not in source.get("allowed_hosts", [])
            or source.get("review_status") not in ("approved", "candidate")):
        raise ValueError("Nearshore model sites need a reviewed CDIP catalog source")
    west, south, east, north = region["bounds"]
    out, seen = [], set()
    for site in config.get("sites") or []:
        ident, name, area = site.get("id"), site.get("name"), site.get("area_id")
        lat, lon = site.get("lat"), site.get("lon")
        if not isinstance(ident, str) or not SITE_ID.fullmatch(ident) or ident in seen:
            raise ValueError(f"Invalid or duplicate CDIP site id: {ident!r}")
        if not (isinstance(name, str) and 0 < len(name.strip()) <= 80 and isinstance(area, str) and AREA_ID.fullmatch(area)):
            raise ValueError(f"CDIP site {ident} needs a name and an area id")
        if not (_finite(lat) and _finite(lon) and south <= lat <= north and west <= lon <= east):
            raise ValueError(f"CDIP site {ident} lies outside the region")
        seen.add(ident)
        out.append({"id": ident, "name": name.strip(), "areaId": area, "lat": lat, "lon": lon})
    if not out:
        raise ValueError("nearshore_model names no sites")
    return out


# ---- DAP2 text responses ------------------------------------------------------------

def _block(das, name):
    match = re.search(r"\b" + name + r"\s*\{([\s\S]*?)\n    \}", das)
    if not match:
        raise ValueError(f"Missing CDIP metadata: {name}")
    return match.group(1)


def _string(block, name):
    match = re.search(r'\bString ' + name + r' "((?:\\.|[^"\\])*)";', block)
    if not match:
        return None
    try:
        return json.loads('"' + match.group(1) + '"')
    except ValueError:
        return match.group(1)


def _number(block, name):
    match = re.search(r"\b(?:Float32|Float64|Int16|Int32|Byte) " + name + r" ([^;]+);", block)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _value(token):
    if token.startswith('"'):
        return json.loads(token)
    if not NUMBER.fullmatch(token):
        raise ValueError("Invalid DAP numeric value")
    return float(token)


def parse_dap_ascii(text):
    """DAP2 ASCII response -> {name: values}; an array shorter or longer than declared raises."""
    parts = re.split(r"\n-{10,}\s*\n", text)
    if len(parts) != 2:
        raise ValueError("Invalid DAP ASCII response")
    result = {}
    for group in re.split(r"\n\s*\n", parts[1].strip()):
        lines = group.splitlines()
        array = re.fullmatch(r"(\w+)\[(\d+)\]", lines[0].strip())
        if array:
            joined = " ".join(re.sub(r"^\s*(?:\[\d+\])+\s*,?\s*", "", line) for line in lines[1:])
            values = [v.strip() for v in joined.split(",") if v.strip()]
            if len(values) != int(array.group(2)):
                raise ValueError(f"Incomplete CDIP array: {array.group(1)}")
            result[array.group(1)] = [_value(v) for v in values]
            continue
        # Scalar records may be adjacent rather than separated by an empty line.
        for line in lines:
            scalar = re.fullmatch(r"(\w+),\s*(.*?)\s*", line.strip())
            if not scalar:
                raise ValueError("Unexpected DAP scalar")
            value = _value(scalar.group(2))
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Invalid DAP scalar value")
            result[scalar.group(1)] = [value]
    return result


def _range(block):
    """A value check from the variable's metadata: finite, not the fill value, inside valid_min..valid_max."""
    fill, low, high = (_number(block, key) for key in ("_FillValue", "valid_min", "valid_max"))
    return lambda v: (v if isinstance(v, float) and math.isfinite(v) and v != fill
                      and (low is None or v >= low) and (high is None or v <= high) else None)


def _flag(value):
    return int(value) if isinstance(value, float) and math.isfinite(value) and value.is_integer() else None


def parse_site(das, ascii_text, binding, fetched_at, now):
    """One site's DAS and ASCII -> `NearshoreSite`. Raises on any identity or contract change."""
    data, meta = parse_dap_ascii(ascii_text), _block(das, "NC_GLOBAL")
    if (data.get("metaSiteLabel") or [None])[0] != binding["id"]:
        raise ValueError("CDIP site identity mismatch")
    lat, lon = (data.get("metaLatitude") or [None])[0], (data.get("metaLongitude") or [None])[0]
    if not (_finite(lat) and _finite(lon) and abs(lat - binding["lat"]) <= COORDINATE_TOLERANCE
            and abs(lon - binding["lon"]) <= COORDINATE_TOLERANCE):
        raise ValueError("CDIP site coordinates mismatch")
    if _string(_block(das, "waveTime"), "units") != TIME_UNITS:
        raise ValueError("CDIP time origin changed")
    checks = {}
    for name, unit in UNITS.items():
        block = _block(das, name)
        if _string(block, "units") != unit:
            raise ValueError(f"CDIP units changed: {name}")
        if name == "waveDp" and _string(block, "standard_name") != "sea_surface_wave_from_direction":
            raise ValueError("CDIP direction convention changed")
        checks[name] = _range(block)
    if (_string(_block(das, "waveFlagPrimary"), "flag_meanings") != PRIMARY_MEANINGS
            or _string(_block(das, "waveFlagSecondary"), "flag_meanings") != SECONDARY_MEANINGS):
        raise ValueError("CDIP quality flag contract changed")
    times = data.get("waveTime")
    if not times or len(times) > MAX_SAMPLES:
        raise ValueError("Missing or oversized CDIP time axis")
    arrays = {}
    for key in ("waveHs", "waveTp", "waveDp", "waveFlagPrimary", "waveFlagSecondary"):
        if len(data.get(key) or []) != len(times):
            raise ValueError(f"Missing CDIP array: {key}")
        arrays[key] = data[key]

    samples, prior = [], -math.inf
    for i, seconds in enumerate(times):
        if not isinstance(seconds, float) or not seconds.is_integer() or seconds <= prior:
            raise ValueError("CDIP timestamps are not unique and increasing")
        prior = seconds
        primary, secondary = arrays["waveFlagPrimary"][i], arrays["waveFlagSecondary"][i]
        trusted = primary == GOOD and secondary in (UNSPECIFIED, LOW_ENERGY)
        spectral = trusted and secondary != LOW_ENERGY
        height = checks["waveHs"](arrays["waveHs"][i]) if trusted else None
        period = checks["waveTp"](arrays["waveTp"][i]) if spectral else None
        samples.append({"at": iso(datetime.fromtimestamp(int(seconds), timezone.utc)),
                        "waveFt": None if height is None else height * FT_PER_M,
                        "periodS": period if period is not None and period > 0 else None,
                        "directionDeg": checks["waveDp"](arrays["waveDp"][i]) if spectral else None,
                        "qualityFlag": _flag(primary), "secondaryFlag": _flag(secondary)})
    issued = parse_time(_string(meta, "date_issued"))
    if issued and issued - now > FUTURE_SKEW:
        raise ValueError("CDIP issue time is unexpectedly in the future")
    hours = [s for s in samples if now - WINDOW_BEFORE <= parse_time(s["at"]) <= now + WINDOW_AFTER]
    if not hours:
        raise ValueError("CDIP has no samples in the report window")
    if not any(h["waveFt"] is not None for h in hours):
        raise ValueError("CDIP report window has no good-quality wave heights")
    steps = {b - a for a, b in zip(times, times[1:])}
    depth = (data.get("metaWaterDepth") or [None])[0]
    return {**binding, "lat": lat, "lon": lon, "sourceId": f"cdip-{binding['id']}",
            "issuedAt": iso(issued) if issued else None, "fetchedAt": fetched_at, "hours": hours,
            "url": page_url(binding["id"]), "kind": "forecast", "availability": "available",
            "freshness": "unknown" if issued is None else ("stale" if now - issued > STALE_AFTER else "current"),
            # One native spacing for the whole file, else unreported (never the first gap alone).
            "temporalResolutionMinutes": int(steps.pop() // 60) if len(steps) == 1 else None,
            "waterDepthM": depth if _finite(depth) and depth >= 0 else None,
            "depthDatum": "Sea level; specific vertical datum is not supplied",
            "directionConvention": "from degrees true", "modelInputCycleAt": None, "validThrough": samples[-1]["at"]}


# ---- collection ---------------------------------------------------------------------

def fetch(session, url):
    """One bounded read: CDIP host and path only, 750 KB, 12 s per attempt, retried on 5xx/429."""
    response = session.get(url, headers={"Accept": "text/plain"}, timeout=TIMEOUT_S, max_bytes=MAX_BYTES,
                           attempts=ATTEMPTS, allowed_hosts=[HOST], allowed_prefixes=[BASE])
    return (response.body or b"").decode("utf-8")


def _retained(previous, binding, now):
    """The previous published record for this site, unchanged, while its fetch is under RETAIN_FOR old."""
    for site in (previous or {}).get("nearshore") or []:
        if not isinstance(site, dict) or site.get("id") != binding["id"]:
            continue
        fetched = parse_time(site.get("fetchedAt"))
        if (site.get("availability") == "available" and site.get("name") == binding["name"]
                and site.get("areaId") == binding["areaId"] and isinstance(site.get("hours"), list)
                and fetched and timedelta(0) <= now - fetched < RETAIN_FOR):
            return site
    return None


def collect_site(session, binding, now, previous=None):
    """(NearshoreSite, SourceStatus) for one site; a failure never raises."""
    ident, url = binding["id"], data_url(binding["id"])
    status = {"id": f"cdip-{ident}", "label": f"CDIP nearshore · {binding['name']}", "url": url, "kind": "forecast"}
    fetched_at = iso(datetime.now(timezone.utc))
    try:
        das, text = fetch(session, das_url(ident)), fetch(session, url)
        fetched_at = iso(datetime.now(timezone.utc))
        site = parse_site(das, text, binding, fetched_at, now)
        status.update(outcome="ok", fetchedAt=fetched_at, **{k: site[k] for k in ("issuedAt", "validThrough") if site[k]})
        return site, status
    except Exception as error:  # one site's failure must not block the others
        message = (str(error) or type(error).__name__)[:300]
        kept = _retained(previous, binding, now)
        if kept:
            message += f"; kept the previous record fetched {kept['fetchedAt']}"
        status.update(outcome="error", fetchedAt=fetched_at, error=message)
        return kept or {**binding, "sourceId": status["id"], "issuedAt": None, "fetchedAt": fetched_at, "hours": [],
                        "url": page_url(ident), "kind": "forecast", "availability": "error", "freshness": "unknown",
                        "temporalResolutionMinutes": None, "waterDepthM": None, "depthDatum": "Unknown",
                        "directionConvention": "from degrees true", "modelInputCycleAt": None, "validThrough": None,
                        "error": message}, status


def collect(region_id, sites, now=None, previous=None, session=None):
    """The region's `nearshore.json`: `nearshore` (NearshoreSite[]) and `sources` (SourceStatus[])."""
    now = now or datetime.now(timezone.utc)
    session = session or http.default_session()
    # Only this region's previous feed can lend a record; anything else is ignored, never fatal.
    if not isinstance(previous, dict) or previous.get("region_id") != region_id:
        previous = None
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda b: collect_site(session, b, now, previous), sites))
    issues = [status["id"] for _, status in results if status["outcome"] != "ok"]
    return {"schema_version": 1, "region_id": region_id, "generated_at": stamp(now), "completed_at": stamp(),
            **publication(), "source_id": SOURCE_ID, "credit": CREDIT, "credit_url": "https://cdip.ucsd.edu/",
            "nearshore": [site for site, _ in results], "sources": [status for _, status in results],
            "health": {"status": "degraded" if issues else "ok", "issues": issues}}


# ---- publication --------------------------------------------------------------------

def publish(region_id, target, previous_root=None, now=None, session=None):
    """Write `<target>/nearshore.json` for a region that binds sites; None when it binds none.

    The previous publication (`<previous_root>/regions/<id>/nearshore.json`) only lends
    recent records; a missing or unreadable one is ignored."""
    from ..platform.contracts import atomic_json, load_catalogs, load_region
    sites = bindings(load_region(region_id), load_catalogs()[1])
    if not sites:
        return None
    try:
        prior = json.loads((Path(previous_root) / "regions" / region_id / "nearshore.json").read_text())
    except (TypeError, OSError, ValueError):
        prior = None
    data = collect(region_id, sites, now, prior, session)
    atomic_json(Path(target) / "nearshore.json", data)
    return data


def main(argv=None):
    """Refresh each published region's nearshore feed. A region's failure warns and keeps its
    last published `nearshore.json`; it never blocks the buoy feed published beside it."""
    import argparse
    import sys
    from ..platform.contracts import REPO, read_json
    parser = argparse.ArgumentParser(description=main.__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True, help="var/live: writes regions/<id>/nearshore.json")
    parser.add_argument("--previous-root", type=Path)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    for path in sorted((REPO / "regions").glob("*/region.json")):
        region = read_json(path)
        if region.get("status") == "draft" or not region.get("nearshore_model"):
            continue
        ident = path.parent.name
        try:
            health = publish(ident, args.output / "regions" / ident, args.previous_root, now)["health"]
            print(json.dumps({"region_id": ident, **health}))
            if health["issues"]:
                print(f"::warning title=Nearshore {ident}::unavailable this cycle: {', '.join(health['issues'])}",
                      file=sys.stderr)
        except Exception as error:  # job boundary: one region's failure must not block the others
            print(f"::warning title=Nearshore {ident} not refreshed::{type(error).__name__}: {str(error)[:300]}",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
