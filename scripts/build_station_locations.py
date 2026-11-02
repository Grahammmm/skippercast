"""Bounded NOAA point metadata for existing station selections (CI6-18).

Manual refresh only; builds/tests stay offline. Full provider receipts stay in
ignored var/station-locations. This does not select stations or change failover.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
URLS = {
    "ndbc": "https://www.ndbc.noaa.gov/activestations.xml",
    "coops": "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions",
}
SAFE_KEY = re.compile(r"[A-Za-z0-9_-]{1,40}")  # other context keys are shown as "contexts.?"


def _shaped(value, kind, rel, field):
    if not isinstance(value, kind):  # a misshaped block is named, never iterated or split into characters
        raise SystemExit(f"build_station_locations: {rel}: {field} is not {'an object' if kind is dict else 'a list'}")
    return value


def configured(root=ROOT):
    wanted = {"ndbc": set(), "coops": set()}
    for path in sorted((root / "regions").glob("*/region.json")):
        try:
            region = json.loads(path.read_text())
        except (OSError, ValueError):
            raise SystemExit(f"build_station_locations: {path.relative_to(root)}: unreadable JSON") from None
        if not isinstance(region, dict):
            raise SystemExit(f"build_station_locations: {path.relative_to(root)}: not a JSON object")
        rel = path.relative_to(root)
        contexts = _shaped(region.get("contexts", {}), dict, rel, "contexts")
        for prefix, context in [("", region), *((f"contexts.{k if SAFE_KEY.fullmatch(k) else '?'}.", c) for k, c in contexts.items())]:
            _shaped(context, dict, rel, prefix[:-1])  # the region itself is already an object
            stations = context.get("stations")
            stations = {} if stations is None else _shaped(stations, dict, rel, f"{prefix}stations")
            roles = _shaped(stations.get("roles", {}), dict, rel, f"{prefix}stations.roles")
            for role in ("tide", "nearshore_buoy", "offshore_buoy"):
                provider = "coops" if role == "tide" else "ndbc"
                entry = _shaped(roles.get(role, {}), dict, rel, f"{prefix}stations.roles.{role}")
                ids = [stations.get(role), *_shaped(entry.get("stations", []), list, rel, f"{prefix}stations.roles.{role}.stations")]
                if any(x is not None and not isinstance(x, str) for x in ids):  # 0, false and [] are refused too
                    raise SystemExit(f"build_station_locations: {path.relative_to(root)}: {role} station id is not a string")
                wanted[provider].update(x for x in ids if x)
    # The already-bound SLO county is the only coast county today. Verify this
    # extraction against the typed county module in the offline acceptance test.
    try:
        county = (root / "packages/coast/src/counties.ts").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise SystemExit("build_station_locations: packages/coast/src/counties.ts: unreadable") from None
    wanted["coops"].update(re.findall(r"tideStation:\{id:'([^']+)'", county))
    wanted["ndbc"].update(re.findall(r"temperatureStationId:'([^']+)'", county))
    for block in re.findall(r"buoys:\[(.*?)\]", county, re.S):
        wanted["ndbc"].update(re.findall(r"id:'([^']+)'", block))
    return wanted


def _write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        try:
            handle.write(data), handle.flush(), os.fsync(handle.fileno())
            os.replace(handle.name, path)
        finally:  # after the replace the temp name is gone; after any error the temp file is removed here
            Path(handle.name).unlink(missing_ok=True)


def main(argv=None, *, root=ROOT, opener=urlopen):
    """Exit 0 after writing; a refusal is SystemExit("build_station_locations: ...") (one stderr line, exit 1)."""
    wanted = configured(root)
    errors, raws = [], {}
    sources, stations = {}, {}
    for provider, url in URLS.items():
        try:
            with opener(url, timeout=60) as response:
                raws[provider] = raw = response.read()
        except (OSError, ValueError) as error:  # HTTPError, URLError and timeouts are OSErrors
            errors.append(f"{provider}: fetch failed ({type(error).__name__})")
            continue
        retrieved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        sources[provider] = {"url": url, "retrieved_at": retrieved, "sha256": sha256(raw).hexdigest()}
        try:
            data = ET.fromstring(raw) if provider == "ndbc" else json.loads(raw)
        except (ET.ParseError, ValueError):
            errors.append(f"{provider}: unreadable inventory")
            continue
        rows = [dict(s.attrib) for s in data.findall("station")] if provider == "ndbc" else (data if isinstance(data, dict) else {}).get("stations")
        if not isinstance(rows, list):
            errors.append("coops: inventory has no stations list")
            continue
        for ident in sorted(wanted[provider]):
            matches = [r for r in rows if isinstance(r, dict) and r.get("id") == ident]
            if len(matches) != 1:
                errors.append(f"{provider}:{ident}: expected one inventory row, got {len(matches)}")
                continue
            row, coords = matches[0], []
            for key, limit in (("lat", 90), ("lon" if provider == "ndbc" else "lng", 180)):
                try:
                    coords.append(float(str(row.get(key))))  # via str(), so True and None are refused too
                except ValueError:
                    coords.append(float("nan"))
                if not abs(coords[-1]) <= limit:  # nan and inf fail this bound as well
                    errors.append(f"{provider}:{ident}: {key} {str(row.get(key))[:40]!r} is not a finite number within ±{limit}")
            if not isinstance(row.get("name"), str) or not row["name"].strip():
                errors.append(f"{provider}:{ident}: name missing or empty")
                continue
            lat, lon = coords
            stations[f"{provider}:{ident}"] = {
                "provider": provider, "id": ident, "name": row["name"], "latitude": lat, "longitude": lon,
                **({"program": row.get("pgm", "NDBC"), "owner": row.get("owner", "NDBC")} if provider == "ndbc" else
                   {"type": row.get("type"), "reference_id": row.get("reference_id")}),
            }
    if errors:  # nothing has been written yet
        raise SystemExit(f"build_station_locations: {'; '.join(errors[:10])} ({len(errors)} error{'s' * (len(errors) > 1)})")
    output = {"schema_version": 1, "sources": sources, "stations": stations}
    for rel, data in [*((f"var/station-locations/{p}.{'xml' if p == 'ndbc' else 'json'}", raws[p]) for p in URLS), ("catalog/station-locations.json", (json.dumps(output, indent=2, ensure_ascii=False) + "\n").encode())]:
        try:  # only after every wanted row passed; each file is replaced whole or not at all
            _write_atomic(root / rel, data)
        except OSError as error:
            raise SystemExit(f"build_station_locations: {rel}: write failed ({type(error).__name__})") from None
    print(json.dumps({"stations": {p: len(ids) for p, ids in wanted.items()}, "sources": sources}, indent=2))


if __name__ == "__main__":
    main()
