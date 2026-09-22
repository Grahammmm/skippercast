"""Collect NOAA buoy observations for the half-hourly public conditions feed."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

from .collect import source, stamp
from .parsers import ndbc
from .settings import settings, previous_for_region

BUOYS = (
    ("diablo", "46215", "Diablo Canyon", False),
    ("diablo-spectrum", "46215", "Diablo Canyon swell and wind waves", True),
    ("offshore", "46028", "Cape San Martin · 55 nm WNW of Morro Bay", False),
)


def collect(now=None, previous=None, region_id="morro-bay"):
    now = now or datetime.now(timezone.utc)
    previous = previous_for_region(previous, region_id)
    region = settings(region_id)["region"]
    station = region["stations"]
    buoys = (("diablo", station["nearshore_buoy"], station["nearshore_buoy_name"], False),
             ("diablo-spectrum", station["nearshore_buoy"], station["nearshore_buoy_name"] + " swell and wind waves", True),
             ("offshore", station["offshore_buoy"], station["offshore_buoy_name"], False))

    aliases = {key: f"buoy-{ident}{'-spectrum' if spectral else ''}" for key, ident, _, spectral in buoys}
    unique = {}
    for stations in [station, *[c['stations'] for c in region.get('contexts',{}).values()]]:
        for kind, spectral in [('nearshore',False),('nearshore',True),('offshore',False)]:
            ident=stations[kind+'_buoy']; key=f"buoy-{ident}{'-spectrum' if spectral else ''}"
            unique[key]=(key,ident,stations[kind+'_buoy_name'],spectral)
    if region.get("contexts"):
        buoys=tuple(unique.values())
    else:
        aliases={}

    def one(item):
        ident, station, name, spectral = item
        url = f"https://www.ndbc.noaa.gov/data/realtime2/{station}.{'spec' if spectral else 'txt'}"

        def read(client):
            data = ndbc(client.get(url), station, spectral)
            # Keep enough rows for waves reported less frequently than wind.
            data["observations"] = sorted(data["observations"], key=lambda r: r["time"], reverse=True)[:24]
            return data

        row = source(ident, name, "observation", url, 2, read, now,
                     previous.get("sources", {}).get(ident))
        row["station_url"] = f"https://www.ndbc.noaa.gov/station_page.php?station={station}"
        return ident, row

    with ThreadPoolExecutor(max_workers=3) as pool:
        sources = dict(pool.map(one, buoys))
    issues=[key for key,s in sources.items() if s["status"]!="ok"]
    for alias, key in aliases.items(): sources[alias]={**sources[key],"id":alias}
    return {
        "schema_version": 1,
        "region_id": region_id,
        "generated_at": stamp(now),
        "completed_at": stamp(),
        "schedule_minutes": 30,
        "sources": sources,
        "health": {
            "status": "ok" if all(s["status"] == "ok" for s in sources.values()) else "degraded",
            "issues": issues,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--region", default="morro-bay")
    args = parser.parse_args()
    previous = None
    if args.previous and args.previous.exists():
        previous = json.loads(args.previous.read_text())
        if previous.get("schema_version") != 1:
            raise ValueError("Unsupported previous observation feed")
    data = collect(previous=previous, region_id=args.region)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n")
    tmp.replace(args.output)
    print(json.dumps({"completed_at": data["completed_at"], **data["health"]}))


if __name__ == "__main__":
    main()
