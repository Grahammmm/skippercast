"""Small, explicit contracts shared by regional authoring and scheduled jobs.

Catalogs are reviewed configuration, never instructions returned by a provider.
The web app receives public artifacts only; local paths and credentials stay out.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
REPO = Path(__file__).resolve().parents[3]
PUBLIC_RIGHTS = {"public-domain", "CC0-1.0", "CC-BY-4.0", "CC-BY-NC-4.0", "facts-only"}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    def invalid(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(Path(path).read_text(), object_pairs_hook=_unique,
                      parse_constant=invalid)


def stamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(encoded)
    tmp.replace(path)
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded)}


def public_url(value):
    u = urlsplit(value)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in (None, 443):
        raise ValueError(f"Expected a public HTTPS URL: {value}")
    if u.hostname in {"localhost", "metadata.google.internal"} or u.hostname.endswith((".local", ".internal")):
        raise ValueError("Internal source URL is not permitted")
    try:
        address = ipaddress.ip_address(u.hostname)
    except ValueError:
        if "." not in u.hostname:
            raise ValueError("Source hostname must be public")
    else:
        if not address.is_global:
            raise ValueError("Non-public source address is not permitted")
    return value


def within(root, relative):
    p = (Path(root) / relative).resolve()
    if not p.is_relative_to(Path(root).resolve()) or ".." in Path(relative).parts or Path(relative).is_absolute():
        raise ValueError(f"Path escapes the publication root: {relative}")
    return p


def bbox(value):
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in value):
        raise ValueError("A bounding box must contain west, south, east, north")
    west, south, east, north = value
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Invalid WGS84 bounding box; split antimeridian regions")
    return value


def indexed(document, key):
    if document.get("schema_version") != 1:
        raise ValueError(f"Unsupported {key} schema")
    result = {}
    for item in document[key]:
        ident = item.get("id", "")
        if not ID.fullmatch(ident) or ident in result:
            raise ValueError(f"Invalid or duplicate {key} id: {ident}")
        result[ident] = item
    return result


def load_catalogs(root=REPO):
    root = Path(root)
    needs = indexed(read_json(root / "catalog/data-needs.json"), "needs")
    sources = indexed(read_json(root / "catalog/sources.json"), "sources")
    for ident, source in sources.items():
        public_url(source["documentation_url"])
        if not set(source["needs"]) <= needs.keys():
            raise ValueError(f"Unknown need on source {ident}")
        if source["review_status"] not in {"approved", "candidate", "restricted", "unavailable"}:
            raise ValueError(f"Invalid review status on {ident}")
        if source["review_status"] == "approved" and source["rights"]["license"] not in PUBLIC_RIGHTS:
            raise ValueError(f"Unresolved redistribution rights for {ident}")
        if source.get("bounds"):
            bbox(source["bounds"])
    return needs, sources


def load_region(ident, root=REPO):
    if not ID.fullmatch(ident):
        raise ValueError("Invalid region id")
    root = Path(root)
    region = read_json(root / "regions" / ident / "region.json")
    validate_region(region, *load_catalogs(root), root=root)
    if region["id"] != ident:
        raise ValueError("Region directory and id differ")
    return region


def validate_region(region, needs, sources, root=REPO):
    if region.get("schema_version") != 1 or not ID.fullmatch(region.get("id", "")):
        raise ValueError("Invalid region schema or id")
    bounds = bbox(region["bounds"])
    ZoneInfo(region["timezone"])
    if region["status"] not in {"active", "preview", "draft"}:
        raise ValueError("Unknown region publication state")
    if isinstance(region["boat"]["bottom_depth_limit_ft"], bool) or not 0 < region["boat"]["bottom_depth_limit_ft"] <= 2000:
        raise ValueError("Invalid regional depth limit")
    if isinstance(region["boat"]["cruise_knots"], bool) or not 0 < region["boat"]["cruise_knots"] <= 100:
        raise ValueError("Invalid cruise speed")
    targets = read_json(Path(root) / 'catalog/targets.json')['targets']
    if not region.get('species') or len(region['species']) != len(set(region['species'])) or not set(region['species']) <= targets.keys():
        raise ValueError('Regional species selectors must be distinct reviewed target IDs')
    for ident in region['species']:
        target=targets[ident]
        if target.get('kind') not in {'reef','soft','habitat','pelagic','offshore'} or target.get('control_mode') not in {'bottom','water-column','boat-comfort'}:
            raise ValueError('Target habitat and control method must be explicit')
        if not target.get('source_species') or not target.get('name') or not isinstance(target.get('habitat_kinds'),list):
            raise ValueError('Target has no biological evidence grouping')
    for area in region.get('map',{}).get('focus_areas',[]):
        bbox(area['bounds'])
        if not ID.fullmatch(area.get('id','')) or not area.get('name'):raise ValueError('Invalid regional map focus')
        if area.get('forecast_point') and area['forecast_point'] not in {p['id'] for p in region['forecast_points']}:
            raise ValueError('Map focus has no matching regional forecast sample')
    seen = set()
    for point in region["forecast_points"]:
        if point["id"] in seen:
            raise ValueError("Duplicate regional forecast point")
        seen.add(point["id"])
        if not bounds[0] <= point["longitude"] <= bounds[2] or not bounds[1] <= point["latitude"] <= bounds[3]:
            raise ValueError("Forecast sample lies outside its region bounds")
    contexts=region.get('contexts',{})
    for ident, context in contexts.items():
        if not ID.fullmatch(ident) or not context.get('name'):raise ValueError('Invalid local context')
        for key in ('coastal','offshore'):
            if not re.fullmatch(r'[A-Z]{3}\d{3}',context['marine_zones'].get(key,'')) or context['marine_zones'][key] not in region['marine_zones'].values():raise ValueError('Local marine zone must be in the scheduled zone set')
        stations=context['stations']
        if not re.fullmatch(r'\d{7}',stations.get('tide','')) or not re.fullmatch(r'[A-Z0-9]{4}',stations.get('airport','')):raise ValueError('Invalid local station identity')
        for key in ('nearshore_buoy','offshore_buoy'):
            if not re.fullmatch(r'[A-Za-z0-9]{5}',stations.get(key,'')):raise ValueError('Invalid local buoy identity')
    if any(p.get('context') and p['context'] not in contexts for p in region['forecast_points']):raise ValueError('Forecast sample has no local context')
    if region.get('default_forecast_point') and region['default_forecast_point'] not in seen:raise ValueError('Unknown default forecast point')
    if region.get('closure_check'):
        public_url(region['closure_check']['url'])
        if region['closure_check']['source_id'] not in region['source_bindings'].get('protected-areas',[]):raise ValueError('Closure check needs a reviewed boundary source binding')
    for need, bindings in region["source_bindings"].items():
        if need not in needs:
            raise ValueError(f"Unknown regional data need: {need}")
        if not isinstance(bindings, list) or len(bindings) != len(set(bindings)):
            raise ValueError("Source bindings must be distinct source ids in preferred order")
        for ident in bindings:
            if ident not in sources or need not in sources[ident]["needs"]:
                raise ValueError(f"Source {ident} cannot fulfill {need}")
    for asset in region["assets"].values():
        if asset is not None:
            within(Path(root) / "dist", asset)
    for name in ("daily_feed", "conditions_feed", "intelligence_feed"):
        if region.get(name):
            public_url(region[name])
    intelligence=region.get('intelligence')
    if intelligence:
        if intelligence.get('regional_current_model')!='wcofs' or intelligence.get('wind_ensemble_model')!='gfs025' or intelligence.get('wave_ensemble_provider')!='noaa-gefs':
            raise ValueError('A new ocean/ensemble provider needs a reviewed adapter')
        for role,need in [('hfr','surface-currents'),('regional_current','surface-currents'),('wind_ensemble','wind-ensemble'),('wave_ensemble','wave-ensemble'),('spectra','wave-observations')]:
            source_id=intelligence.get('providers',{}).get(role)
            if source_id not in region['source_bindings'].get(need,[]) or sources[source_id]['review_status']!='approved':
                raise ValueError('Intelligence provider must have an approved regional source binding: '+role)
        if not intelligence.get('verification_stations'):raise ValueError('Verification requires reviewed station metadata')
        for station in intelligence['verification_stations']:
            if not re.fullmatch(r'[A-Za-z0-9]{5}',station['id']) or not (-90<=station['latitude']<=90 and -180<=station['longitude']<=180):raise ValueError('Invalid verification station')
            public_url(station['source_url'])
    return region


def need_status(region, needs, sources):
    """Coverage is not inferred from HTTP success or an institution's name."""
    result = []
    for ident, need in needs.items():
        bindings = region["source_bindings"].get(ident, [])
        approved = [s for s in bindings if sources[s]["review_status"] == "approved"]
        candidates = [s for s in bindings if sources[s]["review_status"] == "candidate"]
        evidence = region.get("coverage", {}).get(ident, {})
        status = evidence.get("status", "missing") if approved else "research" if candidates else "missing"
        if status not in {"ready", "partial", "missing", "research", "not-applicable"}:
            raise ValueError(f"Invalid coverage state: {ident}")
        result.append({"id": ident, "name": need["name"], "status": status,
                       "sources": bindings, "approved_sources": approved,
                       "reason": evidence.get("reason", "No reviewed regional coverage yet."),
                       "gates": need.get("gates", [])})
    return result


def requirement_report(region, root=REPO):
    needs, sources = load_catalogs(root)
    statuses = need_status(region, needs, sources)
    gates = {}
    for item in statuses:
        for gate in item["gates"]:
            gates.setdefault(gate, []).append(item)
    return {"schema_version": 1, "region_id": region["id"], "region_name": region["name"],
            "needs": statuses,
            "capabilities": {gate: {"ready": all(i["status"] in {"ready", "not-applicable"} for i in items),
                                    "gaps": [i["id"] for i in items if i["status"] not in {"ready", "not-applicable"}]}
                             for gate, items in gates.items()},
            "note": "Readiness describes reviewed source coverage. Current freshness and legal permission require separate checks."}
