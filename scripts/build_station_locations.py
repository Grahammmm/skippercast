"""Bounded NOAA point metadata for existing station selections (CI6-18).

Manual refresh only; builds/tests stay offline. Full provider receipts stay in
ignored var/station-locations. This does not select stations or change failover.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.request import urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
URLS = {
    "ndbc": "https://www.ndbc.noaa.gov/activestations.xml",
    "coops": "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions",
}


def configured():
    wanted = {"ndbc": set(), "coops": set()}
    for path in sorted((ROOT / "regions").glob("*/region.json")):
        region = json.loads(path.read_text())
        for context in [region, *region.get("contexts", {}).values()]:
            stations = context.get("stations", {})
            for role in ("tide", "nearshore_buoy", "offshore_buoy"):
                provider = "coops" if role == "tide" else "ndbc"
                ids = [stations.get(role), *stations.get("roles", {}).get(role, {}).get("stations", [])]
                wanted[provider].update(x for x in ids if x)
    # The already-bound SLO county is the only coast county today. Verify this
    # extraction against the typed county module in the offline acceptance test.
    county = (ROOT / "packages/coast/src/counties.ts").read_text()
    wanted["coops"].update(re.findall(r"tideStation:\{id:'([^']+)'", county))
    wanted["ndbc"].update(re.findall(r"temperatureStationId:'([^']+)'", county))
    for block in re.findall(r"buoys:\[(.*?)\]", county, re.S):
        wanted["ndbc"].update(re.findall(r"id:'([^']+)'", block))
    return wanted


def main():
    wanted = configured()
    receipts = ROOT / "var/station-locations"
    receipts.mkdir(parents=True, exist_ok=True)
    sources, stations = {}, {}
    for provider, url in URLS.items():
        with urlopen(url, timeout=60) as response:
            raw = response.read()
        retrieved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        (receipts / (provider + (".xml" if provider == "ndbc" else ".json"))).write_bytes(raw)
        sources[provider] = {"url": url, "retrieved_at": retrieved, "sha256": sha256(raw).hexdigest()}
        rows = [dict(s.attrib) for s in ET.fromstring(raw).findall("station")] if provider == "ndbc" else json.loads(raw)["stations"]
        for ident in sorted(wanted[provider]):
            matches = [r for r in rows if r["id"] == ident]
            if len(matches) != 1:
                raise ValueError(f"{provider}:{ident}: expected one inventory row, got {len(matches)}")
            row = matches[0]
            lat, lon = float(row["lat"]), float(row["lon" if provider == "ndbc" else "lng"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError(f"Invalid coordinates for {ident}")
            stations[f"{provider}:{ident}"] = {
                "provider": provider, "id": ident, "name": row["name"], "latitude": lat, "longitude": lon,
                **({"program": row.get("pgm", "NDBC"), "owner": row.get("owner", "NDBC")} if provider == "ndbc" else
                   {"type": row.get("type"), "reference_id": row.get("reference_id")}),
            }
    output = {"schema_version": 1, "sources": sources, "stations": stations}
    (ROOT / "catalog/station-locations.json").write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"stations": {p: len(ids) for p, ids in wanted.items()}, "sources": sources}, indent=2))


if __name__ == "__main__":
    main()
