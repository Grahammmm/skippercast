"""Compile reviewed island habitat context and honest measured terrain windows.

Requires numpy, rasterio, shapely, pyproj, pyogrio, requests and remotezip.
The default uses hashed, previously downloaded files in --cache. --fetch acquires
missing files from the reviewed public endpoints; --refresh rechecks all inputs.
New source versions fail their digest check rather than silently becoming approved.
No output is a fishing target or a claim that a common vertical datum is verified.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import zipfile

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.features import geometry_mask, shapes
from rasterio.windows import Window, from_bounds
from pyogrio.raw import read as read_vector
from shapely import make_valid, clip_by_rect, from_wkb
from shapely.geometry import box, mapping, shape, Point
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from skippercast.platform.contracts import atomic_json, read_json

CONFIG = ROOT / "regions/southern-california/habitat-sources.json"
OUT = ROOT / "dist/regions/southern-california"
WORK_CRS = CRS.from_epsg(26910)
TO_WORK = Transformer.from_crs(4326, WORK_CRS, always_xy=True).transform
TO_GEO = Transformer.from_crs(WORK_CRS, 4326, always_xy=True).transform
TRANSFORMATION = "socal-habitat-v1"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [p for g in getattr(geometry, "geoms", []) for p in parts(g)]


def ensure_inputs(config, cache: Path, fetch: bool, refresh: bool):
    """Acquire only pinned public products; retain bounded per-input receipts."""
    cache.mkdir(parents=True, exist_ok=True)
    bathy = config["sources"]["bathymetry"]
    files = [config["sources"][k] for k in ("substrate", "kelp")]
    files += [{**f, "url": bathy["url"], "member": "CINMS_bathy_merge_2024/" + f["filename"]}
              for f in bathy["files"]]
    receipts = []
    for spec in files:
        path = cache / spec["filename"]
        receipt_path = path.with_suffix(path.suffix + ".receipt.json")
        if refresh or not path.exists():
            if not fetch:
                raise ValueError(f"Missing reviewed source {spec['filename']}; use --fetch")
            # Imported here so an offline build needs no network packages.
            print("Acquire", spec["filename"], flush=True)
            if "member" in spec:
                import remotezip
                with remotezip.RemoteZip(spec["url"], timeout=60) as archive:
                    info = archive.getinfo(spec["member"])
                    if info.file_size > spec["maximum_bytes"]:
                        raise ValueError("Remote archive member exceeds reviewed size cap")
                    data = archive.read(spec["member"])
                status = 206
            else:
                import requests
                with requests.get(spec["url"], timeout=(15, 60), stream=True) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    for chunk in response.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > spec["maximum_bytes"]:
                            raise ValueError("Remote product exceeds reviewed size cap")
                        chunks.append(chunk)
                    data, status = b"".join(chunks), response.status_code
            if hashlib.sha256(data).hexdigest() != spec["sha256"]:
                raise ValueError("Source changed: review the new product before replacing the snapshot")
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
            atomic_json(receipt_path, {"url": spec["url"], "archive_member": spec.get("member"),
                "retrieved_at": datetime.now(timezone.utc).isoformat(), "http_status": status,
                "sha256": spec["sha256"], "bytes": len(data)})
        if path.stat().st_size > spec["maximum_bytes"] or digest(path) != spec["sha256"]:
            raise ValueError("Cached source failed the reviewed digest: " + spec["filename"])
        if not receipt_path.exists():
            # Initial reviewed import was downloaded before this adapter was written.
            # File completion time is retained as acquisition metadata, not survey time.
            atomic_json(receipt_path, {"url": spec["url"], "archive_member": spec.get("member"),
                "retrieved_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "retrieval_time_basis": "Initial download file completion time",
                "http_status": 206 if "member" in spec else 200,
                "sha256": spec["sha256"], "bytes": path.stat().st_size})
        receipts.append(read_json(receipt_path))
    return receipts


def vectors(path: Path, field: str, config):
    """Return actual interpreted polygons in the work CRS, preserving native codes."""
    with zipfile.ZipFile(path) as archive:
        stem = next(n[:-4] for n in archive.namelist() if n.endswith(".shp"))
        if any(i.file_size > 300_000_000 for i in archive.infolist()):
            raise ValueError("Unexpected oversized vector archive member")
        crs = CRS.from_wkt(archive.read(stem + ".prj").decode())
        # Kelp .prj contains an irrelevant vertical CRS. Only the horizontal CRS is used.
        if crs.is_compound:
            crs = crs.sub_crs_list[0]
        convert = Transformer.from_crs(crs, WORK_CRS, always_xy=True).transform
        aoi = unary_union([box(*i["bounds"]) for i in config["islands"] if not i.get("withheld")])
        source_aoi = transform(Transformer.from_crs(4326,crs,always_xy=True).transform,aoi)
        # GDAL reads massive multipart kelp polygons in C. pyshp's ring-to-hole
        # classification is quadratic for these original statewide source files.
        _, _, geometries, fields = read_vector("/vsizip/" + str(path.resolve()) + "/" + stem + ".shp",
            columns=[field], bbox=source_aoi.bounds, force_2d=True)
        result = []
        for code, wkb in zip(fields[0], geometries):
            # Regional cropping precedes expensive validity/reprojection on statewide
            # multipart files; source inputs and native class codes remain unchanged.
            polygon = clip_by_rect(from_wkb(wkb),*source_aoi.bounds)
            if polygon.is_empty:
                continue
            if not polygon.is_valid:
                polygon = make_valid(polygon)
            polygon = polygon.intersection(source_aoi)
            polygon = transform(convert,polygon)
            result.append((code, polygon))
        return result


def exclusions(config):
    """Screen complete geometry, with positive clearance from every closure boundary."""
    all_polygons, receipts = [], []
    for filename, minimum in (("protected-areas.geojson", 50), ("groundfish-exclusions.geojson", 8)):
        path = OUT / filename
        data = read_json(path)
        if len(data.get("features", [])) < minimum:
            raise ValueError("Missing/incomplete closure snapshot: " + filename)
        all_polygons += [transform(TO_WORK, make_valid(shape(f["geometry"]))) for f in data["features"]]
        receipts.append({"filename": filename, "sha256": digest(path), "features": len(data["features"])})
    return unary_union(all_polygons).buffer(config["closure_clearance_m"]), receipts


def depth_mask(spec, island, cache: Path, config):
    """Conservative 8m display mask: every native cell must exist and meet the band.

    Read bounded blocks so the large sparse 2m regional raster never enters RAM as
    a whole. Both min and max are retained; no interpolation or nearest-neighbor
    sample is allowed to claim an entire display cell is shallower than 200ft.
    """
    with rasterio.open(cache / spec["filename"]) as grid:
        source_crs = CRS.from_user_input(spec["documented_crs"])
        if not math.isclose(grid.res[0], spec["cell_m"]) or not math.isclose(grid.res[1], spec["cell_m"]):
            raise ValueError("Source resolution differs from reviewed metadata")
        to_source = Transformer.from_crs(4326, source_crs, always_xy=True).transform
        to_work = Transformer.from_crs(source_crs, WORK_CRS, always_xy=True).transform
        roi = transform(to_source, box(*island["bounds"]))
        win = from_bounds(*roi.bounds, grid.transform)
        factor = int(config["display_cell_m"] / spec["cell_m"])
        c0 = max(0, int(math.floor(win.col_off / factor) * factor))
        r0 = max(0, int(math.floor(win.row_off / factor) * factor))
        c1 = min(grid.width // factor * factor, int(math.ceil((win.col_off + win.width) / factor) * factor))
        r1 = min(grid.height // factor * factor, int(math.ceil((win.row_off + win.height) / factor) * factor))
        if c1 <= c0 or r1 <= r0:
            return [], 0, None
        area, collected = 0, []
        depth_values = []
        # 1024 native cells per axis bounds each allocation; seams disappear on dissolve.
        step = 1024 // factor * factor
        for row in range(r0, r1, step):
            for col in range(c0, c1, step):
                w, h = min(step, c1-col), min(step, r1-row)
                a = grid.read(1, window=Window(col, row, w, h))
                valid = np.isfinite(a) & (a != grid.nodata) & (a < 0) & (a >= -config["depth_limit_ft"] * .3048)
                mask = valid.reshape(h//factor, factor, w//factor, factor).all(axis=(1, 3))
                if not mask.any():
                    continue
                native_kept = np.repeat(np.repeat(mask, factor, 0), factor, 1)
                depth_values.extend([float(-a[native_kept].max()), float(-a[native_kept].min())])
                area += int(mask.sum()) * config["display_cell_m"] ** 2
                affine = grid.window_transform(Window(col,row,w,h)) * rasterio.Affine.scale(factor)
                collected += [transform(to_work, shape(g)) for g, val in shapes(mask.astype("uint8"), mask=mask, transform=affine) if val == 1]
        return collected, area, [min(depth_values), max(depth_values)] if depth_values else None


def public_source(spec):
    return {k:v for k,v in spec.items() if k not in ("files", "filename", "maximum_bytes")}


def stored_geometry(geometry):
    """Keep all vertices but avoid publishing meaningless binary-float digits.

    Seven decimal degrees change each coordinate by less than a centimetre here;
    that storage precision is not a claim of survey accuracy. It is negligible
    beside the inward depth-mask margin and 75m exclusion clearance.
    """
    def rounded(values):
        if isinstance(values, (int, float)):
            return round(values, 7)
        return [rounded(value) for value in values]
    result = mapping(geometry)
    return {"type":result["type"], "coordinates":rounded(result["coordinates"])}


def feature(polygon, kind, island, spec, codes, config, depth_screened=False):
    geo = transform(TO_GEO, polygon)
    location = geo.representative_point()
    key = hashlib.sha256((island["id"] + kind + polygon.wkb_hex).encode()).hexdigest()[:12]
    labels = {"rock":"mapped hard substrate", "sediment":"mapped soft substrate", "kelp":"historical kelp"}
    return {"type":"Feature", "geometry":stored_geometry(geo), "properties":{
        "id":"SCI-HAB-" + key, "name":island["name"] + " · " + labels[kind],
        "island":island["id"], "island_name":island["name"], "habitat_kind":kind,
        "latitude":round(location.y,7), "longitude":round(location.x,7), "bounds":[round(v,7) for v in geo.bounds],
        "area_km2":round(polygon.area / 1e6, 5), "source_id":spec["id"],
        "source_url":spec["documentation_url"], "source_date":spec.get("survey_date") or spec["publication_date"],
        "publication_date":spec["publication_date"], "native_source_codes":sorted(set(codes)),
        "native_resolution_m":spec.get("native_resolution_m"),
        "depth_qualified":False, "depth_screened":depth_screened, "fishing_target":False,
        "fishing_export":False, "bottom_view":False,
        "depth_screen_limit_ft":config["depth_limit_ft"] if depth_screened else None,
        "depth_note":"All retained 8m display cells have native merged-grid values shallower than 200ft; common vertical datum and per-cell uncertainty are unconfirmed." if depth_screened else "No complete native-depth screen is available for this historical kelp area.",
        "limitations":spec["limitations"],
        "evidence_kind":"historical-habitat-context", "catch_evidence":False,
        "charter_evidence":False, "quality_grade":None}}


def compile_views(features, config, cache: Path, output: Path):
    bathy = config["sources"]["bathymetry"]
    records, sources = {}, {}
    candidates = {}
    for island in config["islands"]:
        # Prioritize larger distinct hard/soft patches, then kelp; no duplicate marker grid.
        fs = [f for f in features if f["properties"]["island"] == island["id"]]
        fs.sort(key=lambda f:(f["properties"]["habitat_kind"] == "kelp", -f["properties"]["area_km2"]))
        candidates[island["id"]] = fs[:config["maximum_bottom_views_per_island"]]
    for spec in bathy["files"]:
        path = cache / spec["filename"]
        sources[spec["filename"]] = {"source_id":bathy["id"], "sha256":spec["sha256"], "bytes":path.stat().st_size,
            "url":bathy["url"], "archive_member":"CINMS_bathy_merge_2024/"+spec["filename"],
            "survey_year":"1998–2022", "native_cell_m":spec["cell_m"], "vertical_datum":bathy["vertical_datum"]}
        with rasterio.open(path) as grid:
            crs = CRS.from_user_input(spec["documented_crs"])
            to_source = Transformer.from_crs(4326, crs, always_xy=True)
            for island in config["islands"]:
                if island.get("bathymetry") != spec["group"] or island.get("withheld"):
                    continue
                for f in candidates[island["id"]]:
                    p = f["properties"]
                    if p["id"] in records:
                        continue
                    x, y = to_source.transform(p["longitude"],p["latitude"])
                    row,col = grid.index(x,y)
                    a = grid.read(1, window=Window(col-64,row-64,129,129), boundless=True, masked=True)
                    mask = np.ma.getmaskarray(a) | ~np.isfinite(a.data) | (a.data >= 0) | (a.data < -3000)
                    if mask[64,64] or (~mask).mean() < .25:
                        continue
                    valid = a.data[~mask]
                    encoded = np.full(a.shape,-32768,dtype="<i2")
                    encoded[~mask] = np.rint(valid * 10).astype("<i2")
                    item = {"schema_version":1,"region_id":config["region_id"],"target_id":p["id"],
                        "source_id":bathy["id"],"source_sha256":spec["sha256"],"source_url":bathy["doi"],
                        "producer":"NOAA NCCOS/NCEI",
                        "source_interpolation":"The published source includes IDW interpolation of variable-resolution BAG cells and linear vertical shifts to NOAA hydrographic reference surveys. This compiler preserves source gaps and adds no interpolation.",
                        "survey_year":"1998–2022","survey_date":bathy["survey_date"],"publication_date":bathy["publication_date"],
                        "vertical_datum":bathy["vertical_datum"],"horizontal_crs":spec["documented_crs"],
                        "embedded_horizontal_crs":grid.crs.to_wkt(),
                        "crs_note":"Use the archive documentation's NAD83 UTM zone. Santa Barbara Island TIFF embeds an unnamed GRS80 datum; it is not relabeled as a precise survey datum.",
                        "width":129,"height":129,"cell_m":spec["cell_m"],"native_cell_m":spec["cell_m"],
                        "span_m":128*spec["cell_m"],"center_pixel":[64,64],
                        "target_offset_m":[round(x-grid.xy(row,col)[0],3),round(y-grid.xy(row,col)[1],3)],
                        "coverage_fraction":round(float((~mask).mean()),4),
                        "depth_range_ft":[round(float(-valid.max())/.3048,1),round(float(-valid.min())/.3048,1)],
                        "relief_m":round(float(valid.max()-valid.min()),2),"encoding":"base64-int16-le",
                        "elevation_unit_m":.1,"nodata":-32768,"elevations":base64.b64encode(encoded.tobytes()).decode(),
                        "fishing_target":False,"depth_qualified":False,
                        "limitations":"Measured-source merged bathymetry context, not a photo or surveyed fishing target. " + bathy["limitations"] + " The image spans beyond the habitat outline; surrounding depths can exceed 200ft. No further gap interpolation is applied."}
                    receipt = atomic_json(output / (p["id"] + ".json"),item)
                    records[p["id"]] = {"status":"surveyed","path":"regions/southern-california/bottom/"+p["id"]+".json",
                        **receipt,"source_id":bathy["id"],"coverage_fraction":item["coverage_fraction"]}
                    p.update({"bottom_view":True,"survey_cell_m":spec["cell_m"],"vertical_datum":bathy["vertical_datum"],
                        "view_depth_range_ft":item["depth_range_ft"],"view_relief_m":item["relief_m"],"view_coverage_fraction":item["coverage_fraction"]})
    for f in features:
        records.setdefault(f["properties"]["id"],{"status":"unavailable","reason":"No representative measured window in this release; the habitat footprint remains context."})
    atomic_json(output / "index.json",{"schema_version":1,"region_id":config["region_id"],"views":records,"sources":sources})
    return sum(p["status"] == "surveyed" for p in records.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache",type=Path,default=ROOT/"var/socal-habitat")
    parser.add_argument("--fetch",action="store_true")
    parser.add_argument("--refresh",action="store_true")
    args = parser.parse_args()
    config = read_json(CONFIG)
    receipts = ensure_inputs(config,args.cache,args.fetch or args.refresh,args.refresh)
    closed, closure_receipts = exclusions(config)
    print("Read historical substrate polygons",flush=True)
    substrate = vectors(args.cache/config["sources"]["substrate"]["filename"],"SUBSTRATE",config)
    print("Read dated kelp polygons",flush=True)
    kelp = vectors(args.cache/config["sources"]["kelp"]["filename"],"Class_Name",config)
    features, summary = [], []
    for island in config["islands"]:
        print("Compile",island["name"],flush=True)
        roi = transform(TO_WORK,box(*island["bounds"]))
        if island.get("withheld"):
            summary.append({**island,"features":0,"coverage_status":"withheld","gaps":[island["reason"]]})
            continue
        mask_parts, sampled_area = [], 0
        for spec in config["sources"]["bathymetry"]["files"]:
            if spec["group"] != island.get("bathymetry"):
                continue
            pieces, area, depths = depth_mask(spec,island,args.cache,config)
            mask_parts += pieces
            sampled_area += area
        mask = unary_union(mask_parts).intersection(roi).difference(closed) if mask_parts else None
        # Erosion prevents display simplification from expanding into unmeasured/deeper cells.
        if mask is not None:
            mask = unary_union([part.simplify(2,preserve_topology=True) for part in parts(mask.buffer(-4))
                                if part.area >= config["minimum_substrate_area_m2"]]).difference(closed)
            hard = unary_union([g.intersection(roi) for value,g in substrate if value == "hard" and g.intersects(roi)])
            for code in ("hard","soft"):
                original = unary_union([g.intersection(roi) for value,g in substrate if value == code and g.intersects(roi)])
                if code == "soft":
                    # The published compilation adds hard-bottom interpretations to
                    # an older soft layer. Do not display the same patch as both.
                    original = original.difference(hard)
                interpreted = make_valid(original).intersection(mask).difference(closed)
                for polygon in parts(interpreted):
                    if polygon.area < config["minimum_substrate_area_m2"]:
                        continue
                    features.append(feature(polygon,"rock" if code == "hard" else "sediment",island,
                        config["sources"]["substrate"],[code],config,True))
        # Keep true dated kelp geometry, including unsurveyed shallows. It never qualifies depth.
        groups = [(value,g.intersection(roi)) for value,g in kelp if g.intersects(roi)]
        if groups:
            result = unary_union([g for _,g in groups]).difference(closed)
            for polygon in parts(result):
                if polygon.area < config["minimum_kelp_area_m2"]:
                    continue
                polygon = polygon.simplify(2,preserve_topology=True).difference(closed)
                codes = [value for value,g in groups if g.intersects(polygon)]
                features.append(feature(polygon,"kelp",island,config["sources"]["kelp"],codes,config))
        island_features = [f for f in features if f["properties"]["island"] == island["id"]]
        counts = dict(Counter(f["properties"]["habitat_kind"] for f in island_features))
        summary.append({**island,"features":len(island_features),"habitat_counts":counts,
            "coverage_status":"partial","depth_screened_area_km2":round(mask.area/1e6,3) if mask is not None else 0,
            "gaps":["Unmapped and excluded areas remain blank; box is a browsing extent, not a habitat outline.",
                    "Substrate is a variable-resolution 2006 interpretation; kelp was observed in September 2016.",
                    "No common vertical datum or per-cell uncertainty was established; no fishing/export qualification."] +
                   (["No reviewed bathymetry imported for this island."] if not island.get("bathymetry") else [])})
    features.sort(key=lambda f:(f["properties"]["island"],f["properties"]["habitat_kind"],-f["properties"]["area_km2"]))
    if not features:
        raise ValueError("An empty import cannot replace the prior release")
    for f in features:
        if transform(TO_WORK,shape(f["geometry"])).intersects(closed.buffer(-1)):
            raise ValueError("Published full geometry intersects closure clearance")
    stage = tempfile.TemporaryDirectory(prefix="validated-habitat-",dir=args.cache)
    stage_path = Path(stage.name)
    view_count = compile_views(features,config,args.cache,stage_path/"bottom")
    data = {"type":"FeatureCollection","schema_version":1,"region_id":config["region_id"],
        "created_at":datetime.now(timezone.utc).isoformat(),"transformation_version":TRANSFORMATION,
        "features":features,"summary":{"islands":summary,"habitat_areas":len(features),"bottom_views":view_count,"fishing_targets":0},
        "source":{"name":"Reviewed NOAA merged bathymetry, NOAA historical substrate and CDFW dated kelp",
            "sources":{k:public_source(v) for k,v in config["sources"].items()},"receipts":receipts,
            "closure_receipts":closure_receipts,"closure_clearance_m":config["closure_clearance_m"],
            "coordinate_storage_precision_degrees":1e-7,
            "derivation":"Full native-cell depth screening to 200ft; 8m conservative display aggregation, 4m inward margin, historical substrate intersection; dated kelp polygons; 75m MPA/GEA clearance; no San Clemente habitat due to unverified active access.",
            "limitations":"Context outlines are not fishing targets. Apparent precision of bathymetric masks does not improve the old substrate classification. Kelp is historical, not live. Reef relief does not establish individual rocks or catch probability. Numeric bottom views preserve source gaps and actual resolution."}}
    asset_receipt = atomic_json(stage_path/"survey-habitat.geojson",data)
    # Invariants and tile digests are checked before any public asset is replaced.
    index = read_json(stage_path/"bottom/index.json")
    if view_count > 128 or not 0 < len(features) < 5000:
        raise ValueError("Unexpected public layer size")
    for identifier, record in index["views"].items():
        if record["status"] != "surveyed":
            continue
        path = stage_path/"bottom"/(identifier+".json")
        if digest(path) != record["sha256"]:
            raise ValueError("Measured window hash mismatch")
        tile = read_json(path)
        z = np.frombuffer(base64.b64decode(tile["elevations"]),dtype="<i2")
        if len(z) != 129*129 or z[64*129+64] == -32768:
            raise ValueError("Invalid measured window geometry or masked center")
    for path in sorted((stage_path/"bottom").glob("*.json")):
        if path.name != "index.json":
            atomic_json(OUT/"bottom"/path.name,read_json(path))
    atomic_json(OUT/"bottom/index.json",index)
    atomic_json(OUT/"survey-habitat.geojson",data)
    atomic_json(ROOT/"regions/southern-california/habitat-receipts.json",{
        "schema_version":1,"region_id":config["region_id"],"transformation_version":TRANSFORMATION,
        "configuration_sha256":digest(CONFIG),"compiler_sha256":digest(Path(__file__)),
        "sources":receipts,"closure_sources":closure_receipts,"summary":data["summary"],
        "outputs":{"survey-habitat.geojson":asset_receipt,
            "bottom/index.json":{"sha256":digest(OUT/"bottom/index.json"),"bytes":(OUT/"bottom/index.json").stat().st_size},
            "bottom_tiles":{"count":view_count,"digests":"See bottom/index.json; each tile has its own SHA-256 and size"}}})
    stage.cleanup()
    print(json.dumps({"features":len(features),"bottom_views":view_count,"islands":summary},indent=2))


if __name__ == "__main__":
    main()
