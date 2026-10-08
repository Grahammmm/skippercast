"""SLO County beach water-contact statuses (SurfSafeSLO public ArcGIS view).

    python -m skippercast.pipeline.beach_health --root var/live [--region morro-bay]

The output carries `packages/coast` `BeachWaterQuality` rows plus one
`SourceStatus`, the subset of `Enrichment` that FE-84 merges into the coast
report. Rows are the county's factual status text and its page link only.
The public view publishes no sample or effective date, so `sampledAt` is
always null and `sampleDateAvailable` false; `fetchedAt` is our retrieval
time, recorded separately and never a sample date. The view's edit time is
ignored. A failed or incomplete response yields no rows and an `error` source,
so a failure never reads as open beaches. Ported from `fish`
`src/providers/enrichment.ts` (`parseBeachQuality`, the water-quality job).
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from urllib.parse import urlencode

from .. import http
from ..platform.contracts import atomic_json

HOST = "services6.arcgis.com"
SERVICE_PREFIX = f"https://{HOST}/M6e56DqzbdJf20YO/arcgis/rest/services/"
MAX_BYTES = 750_000
POLL_MINUTES = 55  # the county samples weekly; poll about hourly, as fish did
LABEL = "SLO County beach water-contact status"
# region id -> the reviewed binding (fish `enrichmentBindings.slo.waterQuality` and the SLO county areas).
BINDINGS = {
    "morro-bay": {
        "countyId": "slo",
        "id": "slo-beach-water-quality",
        "serviceUrl": SERVICE_PREFIX + "SurfSafeSLO_Public_View/FeatureServer/0",
        "pageUrl": "https://www.slocounty.ca.gov/departments/slo-health/public-health/environmental-health-services/"
                   "all-environmental-health-services/recreational-health/beach-water-quality-monitoring",
        "bounds": ((-121.34, 34.92), (-120.51, 35.82)),  # (west, south), (east, north)
        "areas": (("north", 35.57, -121.10), ("central", 35.365, -120.85), ("south", 35.17, -120.74)),
    },
}


def iso(moment):
    """UTC ISO string with milliseconds, as JavaScript's toISOString writes it."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def query_url(binding):
    return binding["serviceUrl"] + "/query?" + urlencode({"where": "1=1", "outFields": "*", "outSR": "4326", "f": "json"}, safe="*")


def count_url(binding):
    return binding["serviceUrl"] + "/query?" + urlencode({"where": "1=1", "returnCountOnly": "true", "f": "json"})


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def nearest_area(binding, lat, lon):
    scale = math.cos(math.radians(lat))
    return min(binding["areas"], key=lambda a: math.hypot(a[1] - lat, (a[2] - lon) * scale))[0]


def parse(payload, expected_count, binding, fetched_at):
    """ArcGIS query JSON -> BeachWaterQuality rows. Raises ValueError on any incomplete or unexpected response."""
    if not isinstance(payload, dict):
        raise ValueError("Unexpected beach water-quality response")
    if payload.get("error"):
        error = payload["error"]
        detail = (error.get("message") or error.get("code")) if isinstance(error, dict) else error
        raise ValueError(f"ArcGIS error: {detail}")
    features = payload.get("features")
    if (not isinstance(features, list) or payload.get("exceededTransferLimit") is True
            or not isinstance(expected_count, int) or expected_count <= 0 or len(features) != expected_count):
        raise ValueError("Incomplete beach water-quality response")
    wkid = (payload.get("spatialReference") or {}).get("wkid")
    if wkid and wkid != 4326:
        raise ValueError("Unexpected beach coordinate reference system")
    (west, south), (east, north) = binding["bounds"]
    rows, seen = [], set()
    for feature in features:
        attributes = feature.get("attributes") if isinstance(feature, dict) else None
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        lat, lon = (geometry or {}).get("y"), (geometry or {}).get("x")
        if (not isinstance(attributes, dict) or not _number(lat) or not _number(lon)
                or not south <= lat <= north or not west <= lon <= east):
            raise ValueError("Invalid/out-of-county beach geometry")
        key = next((attributes[k] for k in ("GlobalID_2", "Station", "FID") if attributes.get(k) is not None), None)
        if key is None or str(key) == "":
            raise ValueError("Missing beach identity")
        ident = str(key)
        if ident in seen:
            raise ValueError("Duplicate beach identity")
        seen.add(ident)
        station = attributes.get("Station") if isinstance(attributes.get("Station"), str) else None
        notes = [n for n in (_text(attributes.get("AdvisoryMessage")), _text(attributes.get("AdvisoryNotes"))) if n]
        rows.append({
            "id": ident,
            "name": _text(attributes.get("Station_Na")) or station or "Unnamed sampling site",
            "lat": lat, "lon": lon,
            "status": _text(attributes.get("Status")) or "Unknown",
            "advisory": " · ".join(dict.fromkeys(notes)) or None,
            # The public view has no sample or effective time; its edit time is not a sample date.
            "sampledAt": None,
            "fetchedAt": fetched_at,
            "sourceId": binding["id"],
            "url": binding["pageUrl"],
            "areaId": nearest_area(binding, lat, lon),
            "stationCode": station,
            "sampleDateAvailable": False,
        })
    return sorted(rows, key=lambda r: r["name"])


def _json(session, url):
    if not url.startswith(SERVICE_PREFIX):
        raise ValueError("Unreviewed beach service host")
    body = session.get(url, timeout=12, max_bytes=MAX_BYTES, allowed_hosts=[HOST], allowed_prefixes=[SERVICE_PREFIX]).body
    return json.loads(body or b"null")


def collect(region_id, session, now=None):
    """The region's beach-health feed, or None when the region has no reviewed binding."""
    binding = BINDINGS.get(region_id)
    if binding is None:
        return None
    url = query_url(binding)
    clock = lambda: iso(now or datetime.now(timezone.utc))  # noqa: E731
    fetched_at = clock()
    try:
        count = _json(session, count_url(binding))
        payload = _json(session, url)
        fetched_at = clock()  # retrieval time, after both responses; never a sample time
        if not isinstance(count, dict) or count.get("error") or not isinstance(count.get("count"), int) or isinstance(count.get("count"), bool):
            raise ValueError("Beach source count unavailable")
        rows = parse(payload, count["count"], binding, fetched_at)
        source = {"id": binding["id"], "label": LABEL, "url": url, "kind": "observation", "outcome": "ok", "fetchedAt": fetched_at}
    except (OSError, ValueError) as error:  # http errors are OSError or ValueError; nothing partial is kept
        rows = []
        source = {"id": binding["id"], "label": LABEL, "url": url, "kind": "observation", "outcome": "error",
                  "fetchedAt": fetched_at, "error": str(error)[:300]}
    return {"schemaVersion": 1, "countyId": binding["countyId"], "regionId": region_id,
            "generatedAt": clock(), "waterQuality": rows, "sources": [source]}


def due(path, now, minutes=POLL_MINUTES):
    """True unless `path` holds a successful fetch from the last `minutes`."""
    try:
        source = json.loads(Path(path).read_text())["sources"][0]
        fetched = datetime.fromisoformat(source["fetchedAt"].replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return True
    return source.get("outcome") != "ok" or not 0 <= (now - fetched).total_seconds() < minutes * 60


def publish(root, session, now=None, regions=None):
    """Write `<root>/regions/<id>/beach-health.json` for each bound region whose last good fetch is over the poll interval old.

    Returns {region id: source outcome, or "kept" when the published file is recent enough}.
    """
    now = now or datetime.now(timezone.utc)
    outcomes = {}
    for region_id in regions or sorted(BINDINGS):
        path = Path(root) / "regions" / region_id / "beach-health.json"
        if not due(path, now):
            outcomes[region_id] = "kept"
            continue
        feed = collect(region_id, session)
        atomic_json(path, feed)
        outcomes[region_id] = feed["sources"][0]["outcome"]
    return outcomes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="feed root, e.g. var/live")
    parser.add_argument("--region", action="append", choices=sorted(BINDINGS), help="limit to this region (repeatable)")
    args = parser.parse_args(argv)
    outcomes = publish(args.root, http.Session(allowed_hosts=[HOST]), regions=args.region)
    print(json.dumps(outcomes))
    # An error source is published (no rows), so the cycle continues; the exit code only flags it.
    return 1 if "error" in outcomes.values() else 0


if __name__ == "__main__":
    raise SystemExit(main())
