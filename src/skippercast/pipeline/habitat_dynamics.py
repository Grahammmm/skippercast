"""Dated pelagic water-mass context at source resolution, never a bite forecast.

The public manifest is small. Immutable 0.5-degree JSON tiles retain original
sample coordinates and all populated forecast steps. Missing pixels stay absent.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from urllib.parse import quote, urlparse

from .collect import Client, source, stamp
from .parsers import erddap_metadata, erddap_query, erddap_grid
from .ocean import dap, bounds_indices
from ..platform.contracts import REPO, atomic_json, load_region, load_catalogs, read_json

METHOD = "pelagic-context-v1"
TILE_DEGREES = .5
MAX_NATIVE_CELLS = 150_000
WCOFS_URL = "https://opendap.co-ops.nos.noaa.gov/thredds/"
WCOFS_DOC = "https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html"
HMS_DOC = "https://www.fisheries.noaa.gov/s3/2024-10/Amend8-HMS-FMP-AppendixF-June28-Att-2.pdf"

# Broad evidence ranges, not fitted optima, legal limits, or absence thresholds.
SPECIES_METHODS = {
    "albacore": {"temperature_range_c": [12, 21], "range_meaning": "99% of SST encountered by tagged eastern-Pacific juvenile albacore in the cited synthesis; not an optimum or a presence/absence boundary.",
                 "life_stage": "Juvenile eastern-Pacific albacore", "source_url": HMS_DOC},
    "yellowfin": {"temperature_range_c": [(64-32)*5/9, (88-32)*5/9], "range_meaning": "NOAA's broad species-wide favored temperature range; not a Southern California bite curve.",
                  "life_stage": "General species context; fish depth and life stage still needed", "source_url": "https://www.fisheries.noaa.gov/species/pacific-yellowfin-tuna"},
    "bluefin": {"temperature_range_c": None, "range_meaning": "No locally validated single surface-temperature optimum. Fish use multiple depths and forage fields.",
                "life_stage": "Size and fish depth unresolved", "source_url": "https://www.fisheries.noaa.gov/species/pacific-bluefin-tuna"},
    "dorado": {"temperature_range_c": None, "range_meaning": "Warm-water and floating-material context; no locally validated numeric optimum applied.",
               "life_stage": "General pelagic context", "source_url": HMS_DOC},
    "yellowtail": {"temperature_range_c": None, "range_meaning": "Mobile predators; current local bait, fish depth and identification are needed.",
                  "life_stage": "General species context", "source_url": "https://www.fisheries.noaa.gov/west-coast/science-data/yellowtail-research-southwest"},
}


def epoch(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None: raise ValueError("Timezone required")
        return value.timestamp()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError("Timezone required")
    return parsed.timestamp()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def frame_for_time(layer, selected_time, now):
    """Same policy for collector consumers and browser: nearest native frame only.

    Observation/analysis can accompany a future trip only as dated context. A
    forecast may be sampled within 90 minutes, but never beyond its actual span.
    """
    result = {"frame": None, "mode": None, "reason": None}
    try:
        selected, clock = epoch(selected_time), epoch(now)
        sample = epoch(layer.get("issued_at") or layer.get("sample_at"))
        frames = [f for f in layer.get("frames", []) if f.get("valid_cells", 0) > 0 and finite(f.get("time"))]
        if layer.get("status") not in ("ok", "retained") or not frames:
            return {**result, "reason": "Source unavailable or no populated cells"}
        age = (clock-sample)/3600
        if age < -1 or age > layer["max_age_hours"]:
            return {**result, "reason": "Source is outside its freshness window"}
        if layer["kind"] == "forecast":
            times = [f["time"] for f in frames]
            if selected < min(times) or selected > max(times):
                return {**result, "reason": "No ocean forecast at the selected time"}
            frame = min(frames, key=lambda f: abs(f["time"]-selected))
            if abs(frame["time"]-selected) > 90*60:
                return {**result, "reason": "Missing forecast step; no interpolation across the gap"}
            return {"frame": frame, "mode": "forecast", "reason": "Native three-hour model frame; not a fish forecast"}
        frames = [f for f in frames if f["time"] <= selected]
        if not frames:
            return {**result, "reason": "Analysis was not valid by the selected time"}
        return {"frame": max(frames, key=lambda f: f["time"]), "mode": "observed-context",
                "reason": "Dated surface context, not a forecast for the trip date"}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {**result, "reason": "Invalid product timing metadata"}


def species_support(species, temperature_c, gradient_c_per_km=None):
    """Transparent evidence flags instead of an invented combined catch score."""
    method = SPECIES_METHODS.get(species)
    if not method: return {"supported": False, "catch_probability": None, "reason": "No reviewed pelagic method for this target"}
    band = method["temperature_range_c"]
    compatible = band[0] <= temperature_c <= band[1] if band and finite(temperature_c) else None
    return {"supported": True, "temperature_within_reference_range": compatible,
            "temperature_range_c": band, "temperature_gradient_c_per_km": gradient_c_per_km if finite(gradient_c_per_km) else None,
            "habitat_score": None, "catch_probability": None, "method": method,
            "reason": "Physical search context only; no locally validated catch or absence inference"}


def gradients(rows, resolution, temp_index=2, error_index=None):
    """Centered native-grid temperature gradient, never across missing neighbors.

    Error support uses the sum of reported standard errors conservatively; it is
    not a confidence interval because spatial error covariance is unavailable.
    """
    dy, dx = resolution
    lookup = {(round(r[0], 6), round(r[1], 6)): r for r in rows}
    output = []
    for row in rows:
        lat, lon = row[:2]
        neighbors = [lookup.get((round(lat, 6), round(lon-dx, 6))), lookup.get((round(lat, 6), round(lon+dx, 6))),
                     lookup.get((round(lat-dy, 6), round(lon, 6))), lookup.get((round(lat+dy, 6), round(lon, 6)))]
        gradient = supported = None
        if all(n is not None and finite(n[temp_index]) for n in neighbors):
            west, east, south, north = neighbors
            gx = (east[temp_index]-west[temp_index])/(2*dx*111.195*math.cos(math.radians(lat)))
            gy = (north[temp_index]-south[temp_index])/(2*dy*111.195)
            gradient = round(math.hypot(gx, gy), 5)
            if error_index is not None and all(finite(n[error_index]) for n in neighbors):
                supported = int(abs(east[temp_index]-west[temp_index]) > east[error_index]+west[error_index]
                                or abs(north[temp_index]-south[temp_index]) > north[error_index]+south[error_index])
        output.append([*row, gradient, *([supported] if error_index is not None else [])])
    return output


def _bounds(region):
    b = region["bounds"]
    if len(b) != 4 or not all(finite(v) for v in b) or not (-180 <= b[0] < b[2] <= 180 and -80 <= b[1] < b[3] <= 80):
        raise ValueError("Invalid region bounds")
    return b


def _resolution(meta):
    g = meta["attrs"]["NC_GLOBAL"]
    step = [abs(float(g["geospatial_lat_resolution"])), abs(float(g["geospatial_lon_resolution"]))]
    if not all(0 < s <= .25 for s in step): raise ValueError("Unsupported source resolution")
    return step


def satellite(client, region, request, kind):
    """Use the reviewed ERDDAP adapter without its historical display stride."""
    if request.get("adapter") == "noaa-ncss-sst":
        from .noaa_sst import fetch
        west, south, east, north = _bounds(region)
        grid = fetch(client, {"latitude": [south, north], "longitude": [west, east]})
        samples = {(r["latitude"], r["longitude"]): r for r in grid["samples"]}
        resolution = [.05, .05]
        times = {grid["sample_at"]}
        metadata_url = grid["catalog_url"]
        dataset = grid["dataset"]
        meta = {"attrs": {"NC_GLOBAL": {"license": grid["license"]}}}
    elif request.get("adapter") == "noaa-ncss-chlorophyll":
        from .noaa_chlorophyll import fetch
        west, south, east, north = _bounds(region)
        grid = fetch(client, {"latitude": [south, north], "longitude": [west, east]})
        samples = {(r["latitude"], r["longitude"]): r for r in grid["samples"]}
        resolution = [.0375, .0375]
        times = {grid["sample_at"]}
        metadata_url = grid["catalog_url"]
        dataset = grid["dataset"]
        meta = {"attrs": {"NC_GLOBAL": {"license": grid["license"]}}}
    else:
        samples, resolution, times, metadata_url, dataset, meta = _erddap_satellite(client, region, request, kind)
    return _satellite_layer(samples, resolution, times, metadata_url, dataset, meta, kind, _bounds(region))


def _erddap_satellite(client, region, request, kind):
    base, dataset, variables = request["base_url"], request["dataset"], request["variables"]
    metadata_url = f"{base}/info/{dataset}/index.json"
    meta = erddap_metadata(client.get(metadata_url, True)); resolution = _resolution(meta)
    west, south, east, north = _bounds(region)
    expected = (math.ceil((east-west)/resolution[1])+2)*(math.ceil((north-south)/resolution[0])+2)
    if expected > MAX_NATIVE_CELLS: raise ValueError("Region exceeds native-grid budget; split it into regional packages")
    # Small reads stay inside the shared 5 MB decompressed HTTP budget.
    chunks = []
    for yi in range(math.ceil((north-south)/.5)):
        for xi in range(math.ceil((east-west)/.5)):
            chunks.append({"latitude": [south+yi*.5, min(north, south+(yi+1)*.5)],
                           "longitude": [west+xi*.5, min(east, west+(xi+1)*.5)]})
    def get_chunk(bounds):
        query = erddap_query(meta, variables, bounds, 1)
        url = f"{base}/griddap/{dataset}.json?"+quote(query, safe=",:()")
        return erddap_grid(client.get(url, True), meta, variables, kind)
    with ThreadPoolExecutor(max_workers=4) as pool: parts = list(pool.map(get_chunk, chunks))
    samples = {}; times = set()
    for part in parts:
        times.add(part["sample_at"])
        for row in part["samples"]:
            key = (row["latitude"], row["longitude"])
            if key in samples and samples[key] != row: raise ValueError("Conflicting overlapping satellite tiles")
            samples[key] = row
    if len(times) != 1: raise ValueError("Mixed satellite valid times")
    return samples, resolution, times, metadata_url, dataset, meta


def _satellite_layer(samples, resolution, times, metadata_url, dataset, meta, kind, bounds):
    west, south, east, north = bounds
    rows = []
    for (lat, lon), row in sorted(samples.items()):
        if not (south-resolution[0]/2 <= lat <= north+resolution[0]/2 and west-resolution[1]/2 <= lon <= east+resolution[1]/2):
            raise ValueError("Satellite cell outside requested regional extent")
        if kind == "sst":
            mask = row.get("mask")
            temp, error = row.get("analysed_sst"), row.get("analysis_error")
            # Only open ocean: exclude land/lakes/ice and unknown mask bits.
            if mask != 1 or not finite(temp) or not -2.5 <= temp <= 40: continue
            error = error if finite(error) and 0 <= error <= 10 else None
            rows.append([lat, lon, temp, error])
        else:
            value = row.get("chlorophyll")
            if finite(value) and .001 <= value <= 100: rows.append([lat, lon, value])
    if kind == "sst":
        # Keep the native NOAA or MUR grid resolution; analysis is not observational precision.
        rows = gradients(rows, resolution, error_index=3)
        fields = ["latitude", "longitude", "temperature_c", "analysis_error_c", "temperature_gradient_c_per_km", "thermal_contrast_supported"]
        limitations = f"Daily L4 foundation SST analysis, partly interpolated. Native {resolution[0]:.2f}° grid spacing is not independent observational accuracy. Surface only; not bottom temperature or fish presence. Error support is not a confidence interval."
    else:
        fields = ["latitude", "longitude", "chlorophyll_mg_m3"]
        limitations = "Daily MODIS ocean-color observation; clouds and failed retrievals remain gaps. Approximately 4.6 km pixels; chlorophyll is not bait biomass or immediate feeding activity."
    when = times.pop()
    return {"kind": "analysis" if kind == "sst" else "observation", "sample_at": when,
            "resolution_degrees": resolution, "horizontal_datum": "WGS84", "fields": fields,
            "frames": [{"time": int(epoch(when)), "cells": rows, "valid_cells": len(rows), "total_cells": len(samples)}],
            "valid_cells": len(rows), "total_cells": len(samples), "source_url": metadata_url.replace("index.json", "index.html"),
            "dataset": dataset, "license": meta["attrs"]["NC_GLOBAL"].get("license"), "native_stride": 1, "limitations": limitations}


def _block(das, name):
    match = re.search(r"\b"+re.escape(name)+r"\s*\{(.*?)\}", das, re.S)
    if not match: raise ValueError("Missing WCOFS variable metadata: "+name)
    return match[1]


def wcofs_surface(client, region, now):
    """Temperature and current from the same populated model cells and cycle."""
    chosen = None
    for day in (now, now-timedelta(days=1)):
        directory = f"NOAA/WCOFS/MODELS/{day:%Y/%m/%d}/"
        try: catalog = client.get(WCOFS_URL+"catalog/"+directory+"catalog.xml")
        except Exception: continue
        files = sorted(set(re.findall(r"wcofs\.t\d{2}z\.\d{8}\.regulargrid\.f\d{3}\.nc", catalog)))
        if files:
            cycles = [(datetime.strptime(m[2]+m[1], "%Y%m%d%H").replace(tzinfo=timezone.utc), f)
                      for f in files if (m := re.search(r"t(\d{2})z\.(\d{8})", f))]
            cycle = max(t for t, _ in cycles)
            chosen = directory, cycle, [f for t, f in cycles if t == cycle]
            break
    if not chosen: raise ValueError("No populated WCOFS forecast catalog in the last two dates")
    directory, cycle, files = chosen
    base = WCOFS_URL+"dodsC/"+directory; first = base+files[0]
    dds, das = client.get(first+".dds"), client.get(first+".das")
    for variable, units in (("temp", "Celsius"), ("u_eastward", "meters second-1"), ("v_northward", "meters second-1"), ("Depth", "m")):
        if f'String units "{units}";' not in _block(das, variable): raise ValueError("WCOFS units changed: "+variable)
    if 'String flag_meanings "land, water";' not in _block(das, "mask"): raise ValueError("WCOFS wet-mask contract changed")
    unit = re.search(r'String units "(seconds|hours|days) since ([^"]+)"', _block(das, "time"))
    if not unit: raise ValueError("Unknown WCOFS time unit")
    origin = datetime.fromisoformat(unit[2].strip().replace("UTC", "").strip().replace("Z", "+00:00"))
    if origin.tzinfo is None: origin = origin.replace(tzinfo=timezone.utc)
    factor = {"seconds": 1, "hours": 3600, "days": 86400}[unit[1]]
    dims = {k: int(v) for k, v in re.findall(r"\[(ny|nx) = (\d+)\]", dds)}
    axes = dap(client, first, f'Latitude[0:1:{dims["ny"]-1}][0],Longitude[0][0:1:{dims["nx"]-1}],Depth')
    if axes["Depth"][0] != 0: raise ValueError("Requested WCOFS layer is not surface")
    west, south, east, north = _bounds(region)
    y0, y1 = bounds_indices(axes["Latitude"], south, north); x0, x1 = bounds_indices(axes["Longitude"], west, east)
    lat = axes["Latitude"][y0:y1+1]; lon = axes["Longitude"][x0:x1+1]
    n = len(lat)*len(lon)
    if n > 15_000: raise ValueError("WCOFS regional subset exceeds grid budget")
    dy, dx = abs(lat[1]-lat[0]), abs(lon[1]-lon[0])
    if not .039 <= dy <= .041 or not .039 <= dx <= .041: raise ValueError("WCOFS regular-grid spacing changed")
    cut = f"[{y0}:1:{y1}][{x0}:1:{x1}]"
    query = f"Latitude{cut},Longitude{cut},mask{cut},temp[0][0]{cut},u_eastward[0][0]{cut},v_northward[0][0]{cut},time"
    forecast_files = [f for f in files if 0 <= int(re.search(r"\.f(\d+)", f)[1]) <= 72 and int(re.search(r"\.f(\d+)", f)[1]) % 3 == 0]
    def get_frame(filename):
        a = dap(client, base+filename, query)
        keys = ["Latitude", "Longitude", "mask", "temp", "u_eastward", "v_northward"]
        if any(len(a[k]) != n for k in keys) or len(a["time"]) != 1: raise ValueError("Incomplete WCOFS grid")
        when = origin.timestamp()+a["time"][0]*factor; fh = int(re.search(r"\.f(\d+)", filename)[1])
        if abs(when-(cycle.timestamp()+fh*3600)) > 60: raise ValueError("WCOFS valid time disagrees with cycle")
        rows = []
        for latitude, longitude, mask, temperature, u, v in zip(*(a[k] for k in keys), strict=True):
            if not south <= latitude <= north or not west <= longitude <= east: raise ValueError("WCOFS coordinate drift")
            if mask != 1 or not finite(temperature) or not -2.5 <= temperature <= 40: continue
            u = round(u, 4) if finite(u) and abs(u) <= 5 else None
            v = round(v, 4) if finite(v) and abs(v) <= 5 else None
            if u is None or v is None: u = v = None
            rows.append([round(latitude, 6), round(longitude, 6), round(temperature, 4), u, v])
        return {"time": int(when), "cells": gradients(rows, [round(dy, 6), round(dx, 6)]),
                "valid_cells": len(rows), "total_cells": n, "source_file": filename}
    with ThreadPoolExecutor(max_workers=4) as pool: frames = sorted(pool.map(get_frame, forecast_files), key=lambda f: f["time"])
    if not frames: raise ValueError("No WCOFS forecast steps returned")
    return {"kind": "forecast", "issued_at": stamp(cycle), "resolution_degrees": [round(dy, 6), round(dx, 6)],
            "horizontal_datum": "NAD83", "vertical_layer": "surface 0 m", "surface_only": True,
            "fields": ["latitude", "longitude", "temperature_c", "u_mps", "v_mps", "temperature_gradient_c_per_km"],
            "frames": frames, "valid_cells": sum(f["valid_cells"] for f in frames), "total_cells": n*len(frames),
            "valid_from": frames[0]["time"], "valid_through": frames[-1]["time"], "source_url": WCOFS_DOC,
            "license": "Public NOAA model data; retain attribution", "native_stride": 1,
            "limitations": "Approximately 4 km model with three-hour output and at most 72-hour forecast. NOAA regular-grid interpolation is retained; no SkipperCast spatial or temporal gap filling. Surface flow is not bottom flow, boat drift or fish movement. Assimilates SST and HF radar; agreement with those inputs is not independent validation."}


def publish_tiles(layer, target, region_id):
    """Write content-addressed tiles first; only then publish the manifest."""
    groups = {}
    for frame in layer["frames"]:
        for cell in frame["cells"]:
            lat, lon = cell[:2]
            tile_id = (math.floor(lon/TILE_DEGREES), math.floor(lat/TILE_DEGREES))
            tile = groups.setdefault(tile_id, {})
            tile.setdefault(frame["time"], []).append(cell)
    descriptors = []
    for (xi, yi), frames in sorted(groups.items()):
        bounds = [xi*TILE_DEGREES, yi*TILE_DEGREES, (xi+1)*TILE_DEGREES, (yi+1)*TILE_DEGREES]
        item = {"schema_version": 1, "region_id": region_id, "layer_id": layer["id"], "bounds": bounds,
                "resolution_degrees": layer["resolution_degrees"], "fields": layer["fields"],
                "frames": [{"time": t, "cells": cells, "valid_cells": len(cells)} for t, cells in sorted(frames.items())]}
        data = (json.dumps(item, separators=(",", ":"), allow_nan=False)+"\n").encode()
        sha = hashlib.sha256(data).hexdigest()
        name = f"habitat-tiles/{layer['id']}-{xi}-{yi}-{sha[:16]}.json"
        path = target/name; path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp"); tmp.write_bytes(data); tmp.replace(path)
        descriptors.append({"path": name, "bounds": bounds, "sha256": sha, "bytes": len(data)})
    manifest = {k: v for k, v in layer.items() if k != "frames"}
    manifest["frames"] = [{k: v for k, v in f.items() if k != "cells"} for f in layer["frames"]]
    manifest["tiles"] = descriptors
    return manifest


def _cleanup_tiles(target, layers):
    referenced = {t["path"] for layer in layers.values() for t in layer.get("tiles", [])}
    folder = target/"habitat-tiles"
    if not folder.is_dir(): return
    for path in folder.iterdir():
        name = "habitat-tiles/"+path.name
        if path.is_file() and re.fullmatch(r"habitat-tiles/(?:sst-analysis|chlorophyll-observation|wcofs-surface-forecast)--?\d+--?\d+-[a-f0-9]{16}\.json", name) and name not in referenced:
            path.unlink()


def _copy_previous_tiles(layer, prior_dir, target):
    # Public path is derived from this compiler, never provider/user text.
    for tile in layer.get("tiles", []):
        name = tile["path"]
        if not re.fullmatch(r"habitat-tiles/[a-z-]+--?\d+--?\d+-[a-f0-9]{16}\.json", name):
            raise ValueError("Invalid previous tile path")
        data = (prior_dir/name).read_bytes()
        if len(data) != tile["bytes"] or hashlib.sha256(data).hexdigest() != tile["sha256"]:
            raise ValueError("Previous tile integrity check failed")
        dest = target/name; dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() != (prior_dir/name).resolve(): shutil.copyfile(prior_dir/name, dest)


def run(region_id, output, previous_root=None, now=None):
    now = now or datetime.now(timezone.utc); output = Path(output)
    region = load_region(region_id); _, catalog = load_catalogs()
    target = output/"regions"/region_id; prior_dir = Path(previous_root)/"regions"/region_id if previous_root else None
    prior_path = prior_dir/"habitat-dynamics.json" if prior_dir else None
    previous = read_json(prior_path) if prior_path and prior_path.is_file() else {}
    if previous and (previous.get("schema_version") != 1 or previous.get("region_id") != region_id or previous.get("bounds") != region["bounds"] or previous.get("method") != METHOD):
        raise ValueError("Previous habitat product has incompatible identity, bounds or method")
    jobs = []
    for kind, ident in (("sst", "sst-analysis"), ("chlorophyll", "chlorophyll-observation")):
        source_id = region["pipeline_sources"].get(kind); cfg = catalog[source_id]
        need = "sea-temperature" if kind == "sst" else "chlorophyll"
        compatible = {"sst": {"erddap-grid", "noaa-ncss-sst"}, "chlorophyll": {"erddap-grid", "noaa-ncss-chlorophyll"}}
        if cfg["review_status"] != "approved" or cfg["adapter"] not in compatible[kind] or source_id not in region["source_bindings"][need]:
            raise ValueError("Habitat collection requires reviewed regional satellite bindings")
        request = cfg["request"]
        if urlparse(request["base_url"]).hostname not in cfg["allowed_hosts"]: raise ValueError("Unreviewed satellite host")
        jobs.append((ident, source_id, cfg, request["max_age_hours"], lambda c, q={**request, "adapter": cfg["adapter"]}, k=kind: satellite(c, region, q, k)))
    cfg = catalog["noaa-wcofs"]
    if region.get("intelligence", {}).get("regional_current_model") == "wcofs":
        if cfg["review_status"] != "approved" or cfg["adapter"] != "wcofs-dap2" or any("noaa-wcofs" not in region["source_bindings"][need] or need not in cfg["needs"] for need in ("sea-temperature", "surface-currents")):
            raise ValueError("WCOFS temperature needs reviewed temperature and current bindings")
        jobs.append(("wcofs-surface-forecast", "noaa-wcofs", cfg, 36, lambda c: wcofs_surface(c, region, now)))
    layers, sources = {}, {}
    for ident, source_id, cfg, max_age, loader in jobs:
        old_layer = previous.get("layers", {}).get(ident); old_source = previous.get("sources", {}).get(ident)
        # Six-hour product cache retains source clocks and receipts. It is not a new observation.
        recent = old_source and old_source.get("status") in ("ok", "missing") and old_layer and 0 <= epoch(now)-epoch(old_source.get("checked_at")) < 6*3600
        if recent:
            _copy_previous_tiles(old_layer, prior_dir, target)
            layers[ident] = old_layer; sources[ident] = {**old_source, "reused": True}; continue
        result = source(ident, cfg["name"], "forecast" if ident.startswith("wcofs") else "analysis" if ident.startswith("sst") else "observation", cfg["documentation_url"], max_age, loader, now)
        data = result.pop("data")
        sources[ident] = {**result, "source_id": source_id, "rights": cfg["rights"]}
        if data:
            layer = {**data, "id": ident, "source_id": source_id, "status": result["status"], "max_age_hours": max_age}
            layers[ident] = publish_tiles(layer, target, region_id)
        elif old_layer and old_source:
            try:
                _copy_previous_tiles(old_layer, prior_dir, target)
                layers[ident] = {**old_layer, "status": "retained"}
                sources[ident].update(status="retained", data_retrieved_at=old_source.get("data_retrieved_at"), last_success_at=old_source.get("last_success_at"))
            except (OSError, ValueError) as error:
                sources[ident]["retention_issue"] = str(error)
    # A cloud-masked but successfully decoded scene is an ecological coverage
    # gap, not a broken acquisition job. Stale source clocks remain failures.
    issues = [key for key, s in sources.items() if s["status"] not in ("ok", "missing")]
    coverage_gaps = []
    for key, layer in layers.items():
        fraction = layer.get("valid_cells", 0)/layer["total_cells"] if layer.get("total_cells") else 0
        layer["coverage_fraction"] = round(fraction, 5)
        layer["coverage_denominator"] = "All requested source grid cells, including land and masked cells; repeated for each forecast frame"
        if fraction < .1: coverage_gaps.append(key)
        try:
            age = (epoch(now)-epoch(layer.get("issued_at") or layer.get("sample_at")))/3600
            if age < -1 or age > layer["max_age_hours"]:
                if key not in issues: issues.append(key)
        except (ValueError, TypeError, KeyError, AttributeError):
            if key not in issues: issues.append(key)
    product = {"schema_version": 1, "method": METHOD, "region_id": region_id, "bounds": region["bounds"],
               "generated_at": stamp(now), "completed_at": stamp(), "layers": layers, "sources": sources,
               "species_methods": {k: v for k, v in SPECIES_METHODS.items() if k in region["species"]},
               "interpretation": "Dated physical habitat context. Species thermal references and gradients are transparent search clues, not calibrated catch scores, legal permission or comfort ratings.",
               "health": {"status": "degraded" if issues or coverage_gaps else "ok", "issues": issues, "coverage_gaps": coverage_gaps}}
    atomic_json(target/"habitat-dynamics.json", product)
    atomic_json(target/"habitat-health.json", {"schema_version": 1, "region_id": region_id, "generated_at": stamp(now), **product["health"]})
    _cleanup_tiles(target, layers)
    return product


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-root", type=Path)
    args = parser.parse_args()
    product = run(args.region, args.output, args.previous_root)
    print(json.dumps({"region_id": product["region_id"], "health": product["health"], "layers": {k: {"frames": len(v["frames"]), "tiles": len(v["tiles"]), "valid_cells": v["valid_cells"]} for k, v in product["layers"].items()}}, indent=2))
