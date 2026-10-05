"""Load and check a charter fleet region: ``regions/<STATE>/fleet.json`` plus ``catalog/fleet/``.

``load_region(ident)`` validates the region file against
``schemas/fleet-region.schema.json`` and the three catalogs against the same
schema's ``$defs``, then runs the cross-reference checks a schema cannot
express (design section 3):

- every geofence is a closed, simple polygon containing its port point and the
  points of the port's landings, and no port point lies in another port's
  geofence;
- ``home_port`` ids exist in ``catalog/home-ports.json`` and ``region`` ids are
  coastal regions (``regions/<id>/region.json``) whose bounds hold the port;
- every binding names a registered adapter and no URL in the file is on an
  off-limits host (``catalog/fleet/off-limits.json``);
- the AIS bounding box contains every port and landing;
- season parts cover each month once; thresholds are ordered sensibly;
- ``resolver_overrides`` only touch fields the resolver catalog defines, and
  every resolver priority names a known source kind.

Any problem raises ``FleetConfigError`` listing all of them. The loader returns
frozen dataclasses; nothing here is specific to one state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from .. import validate
from ..paths import repo_root
from ..platform.contracts import read_json

__all__ = ["ADAPTERS", "SPECIAL_SOURCES", "FleetConfigError", "FleetRegion", "Port", "Landing", "Ais",
           "Agency", "Binding", "ResolverRule", "check_document", "load_region", "region_ids", "off_limits_host",
           "point_in_polygon", "ring_is_simple"]

STATE_ID = re.compile(r"^[A-Z]{2}$")
SCHEMA_KIND = "fleet-region"

# Adapter ids a binding may name (design section 6). CF-10 moves the registry to
# skippercast.fleet.adapters; this set must stay equal to it.
ADAPTERS = frozenset({"fcc-uls", "uscg-psix", "teck-reports", "landing-pages", "directories",
                      "operator-site", "google-places", "file-import", "ais-static"})
# Fact sources that are not adapters but can win a field in the resolver.
SPECIAL_SOURCES = frozenset({"admin", "operator", "osint"})


class FleetConfigError(ValueError):
    """A fleet region or catalog file is invalid; ``problems`` lists every finding."""

    def __init__(self, source: str, problems: list[str]):
        self.source = source
        self.problems = list(problems)
        shown = "; ".join(self.problems[:8]) + (f"; ... {len(self.problems) - 8} more" if len(self.problems) > 8 else "")
        super().__init__(f"{source}: {len(self.problems)} problem(s): {shown}")


@dataclass(frozen=True)
class Port:
    id: str
    name: str
    point: tuple[float, float]                 # (lat, lon)
    home_port: str | None
    region: str | None
    waters: tuple[str, ...]
    geofence: tuple[tuple[float, float], ...]  # closed outer ring, (lon, lat)
    geofence_source: str

    def contains(self, lat: float, lon: float) -> bool:
        return point_in_polygon(lon, lat, self.geofence)


@dataclass(frozen=True)
class Landing:
    id: str
    name: str
    port: str
    point: tuple[float, float]
    website: str | None


@dataclass(frozen=True)
class Ais:
    source: str
    south: float
    west: float
    north: float
    east: float
    message_types: tuple[str, ...]
    mmsi_filter: bool

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east


@dataclass(frozen=True)
class Agency:
    id: str
    name: str
    kind: str
    notes: str
    records_request_url: str | None


@dataclass(frozen=True)
class Binding:
    id: str
    adapter: str
    enabled: bool
    params: Mapping[str, Any]
    rights: str
    note: str | None = None


@dataclass(frozen=True)
class ResolverRule:
    priority: tuple[str, ...]
    min_confidence: float


@dataclass(frozen=True)
class FleetRegion:
    id: str
    name: str
    timezone: str
    status: str
    ports: tuple[Port, ...]
    landings: tuple[Landing, ...]
    ais: Ais
    agencies: tuple[Agency, ...]
    sources: tuple[Binding, ...]
    thresholds: Mapping[str, Any]
    seasons: Mapping[str, tuple[int, ...]]
    resolver: Mapping[str, ResolverRule]       # catalog merged with the region's overrides
    off_limits: tuple[str, ...]
    lead_score: Mapping[str, float]
    path: Path = field(compare=False)

    def port(self, ident: str) -> Port:
        for item in self.ports:
            if item.id == ident:
                return item
        raise KeyError(ident)

    def binding(self, ident: str) -> Binding:
        for item in self.sources:
            if item.id == ident:
                return item
        raise KeyError(ident)

    def enabled_sources(self) -> tuple[Binding, ...]:
        return tuple(b for b in self.sources if b.enabled)

    def is_off_limits(self, url: str) -> bool:
        return off_limits_host(url, self.off_limits) is not None


# ---------------------------------------------------------------- geometry

def point_in_polygon(x: float, y: float, ring) -> bool:
    """Even-odd ray casting; ``ring`` is a closed sequence of (x, y)."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y):
            cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < cross:
                inside = not inside
    return inside


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _segments_touch(a, b, c, d) -> bool:
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    if ((o1 > 0) != (o2 > 0)) and ((o3 > 0) != (o4 > 0)) and o1 and o2 and o3 and o4:
        return True
    return ((o1 == 0 and _on_segment(a, b, c)) or (o2 == 0 and _on_segment(a, b, d))
            or (o3 == 0 and _on_segment(c, d, a)) or (o4 == 0 and _on_segment(c, d, b)))


def ring_is_simple(ring) -> bool:
    """True when the closed ring has at least three distinct vertices and no edge touches a non-adjacent edge."""
    points = [tuple(p) for p in ring]
    if len(points) < 4 or points[0] != points[-1] or len(set(points[:-1])) != len(points) - 1:
        return False
    edges = list(zip(points, points[1:]))
    count = len(edges)
    for i in range(count):
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue  # adjacent edges share a vertex by construction
            if _segments_touch(*edges[i], *edges[j]):
                return False
    area = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in edges) / 2
    return abs(area) > 0


# ---------------------------------------------------------------- hosts

def _host(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.lower().rstrip(".") if host else None


def off_limits_host(url: str, hosts) -> str | None:
    """The off-limits host ``url`` falls under (the host itself or a subdomain), else None."""
    host = _host(url)
    if not host:
        return None
    for blocked in hosts:
        if host == blocked or host.endswith("." + blocked):
            return blocked
    return None


def _strings(node, where):
    if isinstance(node, str):
        yield where, node
    elif isinstance(node, Mapping):
        for key, value in node.items():
            yield from _strings(value, f"{where}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{where}[{index}]")


# ---------------------------------------------------------------- loading

def region_ids(root: Path | None = None) -> list[str]:
    """Ids of every committed fleet region (``regions/<STATE>/fleet.json``)."""
    root = Path(root) if root else repo_root()
    return sorted(p.parent.name for p in (root / "regions").glob("*/fleet.json") if STATE_ID.match(p.parent.name))


def _schema_problems(document, pointer: str | None = None) -> list[str]:
    checker = validate.validator(SCHEMA_KIND)
    if pointer:
        checker = checker.evolve(schema={"$ref": f"{checker.schema['$id']}#/$defs/{pointer}"})
    rows = []
    for error in sorted(checker.iter_errors(document), key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        rows.append(f"{where}: {error.message[:300]}")
    return rows


def _load_catalogs(root: Path):
    found = {}
    for name, pointer in (("resolver", "resolver_catalog"), ("off-limits", "off_limits_catalog"),
                          ("lead-score", "lead_score_catalog")):
        path = root / "catalog/fleet" / f"{name}.json"
        document = read_json(path)
        problems = _schema_problems(document, pointer)
        if not problems:
            problems = _catalog_problems(name, document)
        if problems:
            raise FleetConfigError(str(path.relative_to(root)), problems)
        found[name] = document
    return found


def _catalog_problems(name, document) -> list[str]:
    problems = []
    if name == "resolver":
        for key, rule in document["fields"].items():
            unknown = [s for s in rule["priority"] if s not in ADAPTERS | SPECIAL_SOURCES]
            if unknown:
                problems.append(f"fields/{key}: unknown source kind(s) {unknown}")
    elif name == "off-limits":
        hosts = [row["host"] for row in document["hosts"]]
        if len(set(hosts)) != len(hosts):
            problems.append("hosts: duplicate host")
    elif name == "lead-score":
        total = sum(document["weights"].values())
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            problems.append(f"weights: sum to {total}, expected 1")
    return problems


def _duplicates(rows, label) -> list[str]:
    seen, problems = set(), []
    for row in rows:
        if row["id"] in seen:
            problems.append(f"{label}: duplicate id {row['id']!r}")
        seen.add(row["id"])
    return problems


def _region_problems(doc, catalogs, root: Path) -> list[str]:
    problems = []
    off_limits = [row["host"] for row in catalogs["off-limits"]["hosts"]]
    for label in ("ports", "landings", "agencies", "sources"):
        problems += _duplicates(doc[label], label)
    problems += _duplicates(doc["seasons"]["parts"], "seasons.parts")

    home_ports = {row["id"] for row in read_json(root / "catalog/home-ports.json")["ports"]}
    rings = {}
    for port in doc["ports"]:
        where = f"ports/{port['id']}"
        ring = [tuple(p) for p in port["geofence"]["coordinates"][0]]
        lat, lon = port["point"]
        if not ring_is_simple(ring):
            problems.append(f"{where}: geofence is not a closed simple polygon")
        elif not point_in_polygon(lon, lat, ring):
            problems.append(f"{where}: geofence does not contain the port point")
        rings[port["id"]] = ring
        if port["home_port"] is not None and port["home_port"] not in home_ports:
            problems.append(f"{where}: home_port {port['home_port']!r} is not in catalog/home-ports.json")
        if port["region"] is not None:
            config = root / "regions" / port["region"] / "region.json"
            if not config.is_file():
                problems.append(f"{where}: region {port['region']!r} has no regions/<id>/region.json")
            else:
                west, south, east, north = read_json(config)["bounds"]
                if not (south <= lat <= north and west <= lon <= east):
                    problems.append(f"{where}: point lies outside the bounds of region {port['region']!r}")
    for port in doc["ports"]:
        lat, lon = port["point"]
        for other, ring in rings.items():
            if other != port["id"] and point_in_polygon(lon, lat, ring):
                problems.append(f"ports/{port['id']}: point lies inside the geofence of port {other!r}")

    landing_ids = {row["id"] for row in doc["landings"]}
    for landing in doc["landings"]:
        where = f"landings/{landing['id']}"
        ring = rings.get(landing["port"])
        if ring is None:
            problems.append(f"{where}: unknown port {landing['port']!r}")
        elif not point_in_polygon(landing["point"][1], landing["point"][0], ring):
            problems.append(f"{where}: point is outside the geofence of port {landing['port']!r}")

    for binding in doc["sources"]:
        where = f"sources/{binding['id']}"
        if binding["adapter"] not in ADAPTERS:
            problems.append(f"{where}: adapter {binding['adapter']!r} is not registered")
        ref = binding["params"].get("landing")
        if ref is not None and ref not in landing_ids:
            problems.append(f"{where}: params.landing {ref!r} is not a landing id")

    for where, value in _strings({k: doc[k] for k in ("landings", "agencies", "sources")}, "$"):
        if "://" in value:
            blocked = off_limits_host(value, off_limits)
            if blocked:
                problems.append(f"{where[2:]}: {value!r} is on off-limits host {blocked}")
            elif not value.startswith("https://") and where.startswith("$.sources"):
                problems.append(f"{where[2:]}: {value!r} is not https")

    (south, west), (north, east) = doc["ais"]["bbox"]
    if not (south < north and west < east):
        problems.append("ais.bbox: expected [[south, west], [north, east]] with south < north and west < east")
    else:
        for label in ("ports", "landings"):
            for row in doc[label]:
                lat, lon = row["point"]
                if not (south <= lat <= north and west <= lon <= east):
                    problems.append(f"{label}/{row['id']}: point lies outside ais.bbox")

    months = sorted(m for part in doc["seasons"]["parts"] for m in part["months"])
    if months != list(range(1, 13)):
        problems.append("seasons.parts: months must cover 1-12 exactly once")

    activity = doc["thresholds"]["activity"]
    match = doc["thresholds"]["match"]
    if match["review_min"] > match["auto_merge"]:
        problems.append("thresholds.match: review_min is above auto_merge")
    if activity["troll"]["min_sog_kn"] >= activity["troll"]["max_sog_kn"]:
        problems.append("thresholds.activity.troll: min_sog_kn must be below max_sog_kn")
    if activity["drift"]["max_sog_kn"] >= activity["troll"]["min_sog_kn"]:
        problems.append("thresholds.activity: drift max_sog_kn must be below troll min_sog_kn")

    catalog_fields = catalogs["resolver"]["fields"]
    for key, override in doc["resolver_overrides"].items():
        if key not in catalog_fields:
            problems.append(f"resolver_overrides/{key}: not a field in catalog/fleet/resolver.json")
        unknown = [s for s in override.get("priority", []) if s not in ADAPTERS | SPECIAL_SOURCES]
        if unknown:
            problems.append(f"resolver_overrides/{key}: unknown source kind(s) {unknown}")
    return problems


def _freeze(node):
    if isinstance(node, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in node.items()})
    if isinstance(node, list):
        return tuple(_freeze(v) for v in node)
    return node


def _build(doc, catalogs, path: Path) -> FleetRegion:
    resolver = {}
    for key, rule in catalogs["resolver"]["fields"].items():
        merged = {**rule, **doc["resolver_overrides"].get(key, {})}
        resolver[key] = ResolverRule(tuple(merged["priority"]), float(merged["min_confidence"]))
    (south, west), (north, east) = doc["ais"]["bbox"]
    ais = doc["ais"]
    return FleetRegion(
        id=doc["id"], name=doc["name"], timezone=doc["timezone"], status=doc["status"],
        ports=tuple(Port(p["id"], p["name"], tuple(p["point"]), p["home_port"], p["region"], tuple(p["waters"]),
                         tuple(tuple(c) for c in p["geofence"]["coordinates"][0]), p["geofence_source"])
                    for p in doc["ports"]),
        landings=tuple(Landing(x["id"], x["name"], x["port"], tuple(x["point"]), x["website"]) for x in doc["landings"]),
        ais=Ais(ais["source"], south, west, north, east, tuple(ais["message_types"]), ais["mmsi_filter"]),
        agencies=tuple(Agency(a["id"], a["name"], a["kind"], a["notes"], a["records_request_url"]) for a in doc["agencies"]),
        sources=tuple(Binding(b["id"], b["adapter"], b["enabled"], _freeze(b["params"]), b["rights"], b.get("note"))
                      for b in doc["sources"]),
        thresholds=_freeze(doc["thresholds"]),
        seasons=MappingProxyType({p["id"]: tuple(p["months"]) for p in doc["seasons"]["parts"]}),
        resolver=MappingProxyType(resolver),
        off_limits=tuple(row["host"] for row in catalogs["off-limits"]["hosts"]),
        lead_score=MappingProxyType(dict(catalogs["lead-score"]["weights"])),
        path=path,
    )


def check_document(doc, root: Path | None = None) -> list[str]:
    """Every problem in an already-parsed fleet region document (schema first, then cross-references)."""
    root = Path(root) if root else repo_root()
    problems = _schema_problems(doc)
    if problems:
        return problems
    return _region_problems(doc, _load_catalogs(root), root)


def load_region(ident: str, root: Path | None = None) -> FleetRegion:
    """Validate ``regions/<ident>/fleet.json`` and the fleet catalogs and return the typed region.

    Raises FleetConfigError on any problem, and validate.MissingDependency when
    jsonschema is not installed.
    """
    root = Path(root) if root else repo_root()
    if not isinstance(ident, str) or not STATE_ID.match(ident):
        raise FleetConfigError(repr(ident), ["fleet region ids are two upper-case letters"])
    path = root / "regions" / ident / "fleet.json"
    label = f"regions/{ident}/fleet.json"
    if not path.is_file():
        raise FleetConfigError(label, ["file not found"])
    try:
        doc = read_json(path)
    except ValueError as error:
        raise FleetConfigError(label, [f"invalid JSON: {error}"]) from None
    catalogs = _load_catalogs(root)
    problems = _schema_problems(doc)
    if not problems and doc["id"] != ident:
        problems.append(f"id {doc['id']!r} does not match its directory")
    if not problems:
        problems = _region_problems(doc, catalogs, root)
    if problems:
        raise FleetConfigError(label, problems)
    return _build(doc, catalogs, path)
