"""Compile a bounded, reviewed original-BAG habitat release for two islands.

Requires the optional GIS environment: numpy, scipy, rasterio, shapely, pyproj,
h5py. Raw NOAA files remain in var/. Hash changes require a source review.
The shared publication workflow integrates the emitted atlas/index fragments;
this compiler never replaces a regional atlas or an existing bottom index.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import urllib.request

import h5py
import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.features import shapes
from scipy.spatial import cKDTree
from shapely import make_valid, contains_xy
from shapely.geometry import Point, box, shape, mapping
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from skippercast.platform.bottom_targets import (VERSION, sha256, source_url_allowed,
    bag_metadata, cells_qualified, vr_transform, fresh_closures, terrain_metrics, contained_outline, target_prefix)
from skippercast.platform.contracts import atomic_json, read_json
from skippercast.platform.qualified_scope import _held_original_surveys


def polygons(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [p for g in getattr(geometry, "geoms", []) for p in polygons(g)]


def acquire(spec, cache, fetch=False):
    """Only fixed reviewed URLs, sizes and hashes; complete validated HTTP ranges."""
    if not source_url_allowed(spec["url"]) or not 0 < spec["bytes"] <= 160_000_000:
        raise ValueError("Unreviewed source URL or size")
    path = cache / spec["filename"]
    if path.name != spec["filename"] or path.suffix != ".bag":
        raise ValueError("Invalid reviewed cache filename")
    receipt_path = path.with_suffix(".receipt.json")
    if not path.exists():
        if not fetch:
            raise ValueError("Missing reviewed source; run --fetch: " + path.name)
        cache.mkdir(parents=True, exist_ok=True)
        chunk = 1024 * 1024
        def get_piece(i):
            lo, hi = i*chunk, min((i+1)*chunk, spec["bytes"])-1
            request = urllib.request.Request(spec["url"], headers={"Range": f"bytes={lo}-{hi}"})
            with urllib.request.urlopen(request, timeout=60) as response:
                if not source_url_allowed(response.url):
                    raise ValueError("Unexpected source redirect")
                if response.status != 206 or response.headers.get("Content-Range") != f"bytes {lo}-{hi}/{spec['bytes']}":
                    raise ValueError("Changed/incomplete remote product")
                raw = response.read(hi-lo+2)
                if len(raw) != hi-lo+1:
                    raise ValueError("Incomplete source range")
                return raw
        temporary = path.with_suffix(".partial")
        try:
            with ThreadPoolExecutor(max_workers=4) as pool, temporary.open("wb") as stream:
                for raw in pool.map(get_piece, range(math.ceil(spec["bytes"]/chunk))):
                    stream.write(raw)
            if sha256(temporary) != spec["sha256"]:
                raise ValueError("Source changed; new content requires review")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        atomic_json(receipt_path, {"url":spec["url"], "retrieved_at":datetime.now(timezone.utc).isoformat(),
            "http_status":206, "bytes":spec["bytes"], "sha256":spec["sha256"],
            "acquisition":"Complete file via bounded 1 MiB ranges; four concurrent requests"})
    if path.stat().st_size != spec["bytes"] or sha256(path) != spec["sha256"]:
        raise ValueError("Source digest or size mismatch")
    if not receipt_path.exists():
        raise ValueError("Source acquisition receipt missing")
    receipt = read_json(receipt_path)
    if receipt.get("sha256") != spec["sha256"] or receipt.get("url") != spec["url"]:
        raise ValueError("Acquisition receipt does not identify this reviewed source")
    return path, receipt


def read_native(path, spec, habitat, config):
    """Read actual VR supergrids, never the low-resolution BAG overview.

The native affine is tested against GDAL's supergrid reader. Finite native cell
footprints are polygonized without interpolation. Invalid cells are subtracted
even where a neighboring supergrid support rectangle overlaps them.
    """
    with rasterio.open(path) as overview:
        left, bottom = overview.bounds.left, overview.bounds.bottom
        cx, cy = overview.res
    good_parts, bad_parts, samples = [], [], []
    counts = {"native_nodes":0, "qualified_nodes":0, "native_grids":0, "native_resolution_counts":{}}
    with h5py.File(path) as handle:
        root = handle["BAG_root"]
        metadata = bag_metadata(root["metadata"][:].tobytes().decode().rstrip("\0"), spec["survey_id"])
        if metadata["metadata_sha256"] != spec["metadata_sha256"]:
            raise ValueError("Unreviewed BAG metadata")
        crs = CRS.from_wkt(metadata["horizontal_wkt"])
        # These hash-reviewed legacy WKTs wrap NAD83 in an explicit zero-shift
        # binding to WGS84. Validate the underlying projection rather than
        # mistaking the BoundCRS wrapper for a different UTM reference.
        horizontal = crs.source_crs if crs.is_bound else crs
        if not horizontal.equals(CRS.from_user_input(spec["horizontal_crs"]),ignore_axis_order=True):
            raise ValueError("BAG horizontal reference changed")
        if root["varres_tracking_list"].size or root["tracking_list"].size:
            raise ValueError("A tracked/overridden BAG needs separate review")
        meta = root["varres_metadata"][:]
        refinement = root["varres_refinements"]
        if refinement.ndim != 2 or refinement.shape[0] != 1 or refinement.shape[1] > 30_000_000:
            raise ValueError("Unsupported or oversized refinement array")
        interested = habitat.buffer(350)
        indices = np.argwhere((meta["dimensions_x"] > 0) & (meta["resolution_x"] <= config["maximum_native_cell_m"]))
        for row, col in indices:
            m = meta[row,col]
            dx, dy, nx, ny = float(m["resolution_x"]), float(m["resolution_y"]), int(m["dimensions_x"]), int(m["dimensions_y"])
            if not (0 < dx == dy <= 4 and 0 < nx <= 128 and 0 < ny <= 128):
                raise ValueError("Unsupported native supergrid")
            affine = vr_transform(left,bottom,cx,cy,int(row),int(col),m)
            footprint = box(affine.c,affine.f-ny*dy,affine.c+nx*dx,affine.f)
            if not footprint.intersects(interested):
                continue
            offset, n = int(m["index"]), nx*ny
            if offset+n > refinement.shape[1]:
                raise ValueError("Truncated BAG refinement")
            raw = refinement[0,offset:offset+n].reshape((ny,nx))[::-1,:]
            a,u = raw["depth"],raw["depth_uncrt"]
            valid = np.isfinite(a) & (a < 0) & (a > -3000) & np.isfinite(u) & (u > 0) & (u < 100)
            qualified = cells_qualified(a,u,dx,limit_ft=config["depth_limit_ft"],minimum_ft=config["minimum_depth_ft"],
                planning_margin_m=config["planning_margin_m"],maximum_uncertainty_m=config["maximum_product_uncertainty_m"])
            counts["native_grids"] += 1
            counts["native_nodes"] += int(valid.sum())
            counts["qualified_nodes"] += int(qualified.sum())
            counts["native_resolution_counts"][str(dx)] = counts["native_resolution_counts"].get(str(dx),0)+int(valid.sum())
            # The terrain sample pool must obey the same depth and product-
            # uncertainty screen as the published footprint. Keeping every
            # measured node here exhausted the regional memory budget on
            # larger original surveys and let unqualified cells enter the
            # display grid even though they could not create a target.
            yy,xx = np.nonzero(qualified)
            if len(xx):
                samples.append(np.column_stack((affine.c+(xx+.5)*dx,affine.f-(yy+.5)*dy,
                    a[qualified],u[qualified],np.full(len(xx),dx))))
            if not footprint.intersects(habitat):
                continue
            # All native cells, including nodata, participate in the geometric screen.
            for polygon,value in shapes(qualified.astype("uint8"), transform=affine):
                target = good_parts if value else bad_parts
                target.append(shape(polygon))
    if not good_parts or not samples:
        raise ValueError("No supported original-survey cells intersect this habitat")
    print(spec["survey_id"],counts,flush=True)
    support = unary_union(good_parts).difference(unary_union(bad_parts))
    support = support.buffer(-config["native_footprint_erosion_m"]).intersection(habitat)
    points = np.concatenate(samples)
    if len(points) > 12_000_000:
        raise ValueError("Regional sample budget exceeded")
    return support,points,metadata,counts


def numeric_view(points, tree, center, spec, target_id, region_id):
    """4 m bin means of actual 1–4 m source nodes; gaps are never filled."""
    cell, width = 4,129
    ids = tree.query_ball_point(center,370)
    p = points[ids]
    col = np.floor((p[:,0]-center[0])/cell + 64.5).astype(int)
    row = np.floor((center[1]-p[:,1])/cell + 64.5).astype(int)
    inside = (col>=0)&(col<width)&(row>=0)&(row<width)
    p,col,row = p[inside],col[inside],row[inside]
    index = row*width+col
    counts = np.bincount(index,minlength=width*width)
    sums = np.bincount(index,weights=p[:,2],minlength=width*width)
    okay = counts>0
    values = np.full(width*width,-32768,dtype="<i2")
    mean = sums[okay]/counts[okay]
    values[okay] = np.rint(mean*10).astype("<i2")
    return {"schema_version":1,"region_id":region_id,"target_id":target_id,
        "source_id":spec["id"],"source_url":spec["documentation_url"],"source_sha256":spec["sha256"],
        "producer":"NOAA/NOS", "survey_year":int(spec["survey_start"][:4]),
        "survey_date":spec["survey_start"]+" to "+spec["survey_end"],
        "vertical_datum":"MLLW","horizontal_crs":spec["horizontal_crs"],
        "width":width,"height":width,"cell_m":cell,"native_cell_m":float(max(p[:,4])),
        "native_resolution_range_m":[float(min(p[:,4])),float(max(p[:,4]))],
        "span_m":512,"center_pixel":[64,64],"target_offset_m":[0,0],
        "coverage_fraction":round(float(okay.mean()),4),
        "depth_range_ft":[round(float(-mean.max())/.3048,1),round(float(-mean.min())/.3048,1)],
        "relief_m":round(float(mean.max()-mean.min()),3),"encoding":"base64-int16-le",
        "elevation_unit_m":.1,"nodata":-32768,"elevations":base64.b64encode(values.tobytes()).decode(),
        "source_interpolation":"No gap interpolation. 4 m display cells average depth- and uncertainty-qualified native 1–4 m node values falling inside each display bin; native resolution is retained separately.",
        "depth_qualified":True,"fishing_target":True,
        "limitations":"Historical numerical terrain view, not a photograph or navigation chart. The 512 m image can extend beyond the qualified footprint and depth band. Display means are not used to qualify depths. No rock dimensions or fish presence are inferred. "+spec["limitations"]}


def compile_source(spec, path, config, habitat_features, closed, out, bottom):
    crs = CRS.from_user_input(spec["horizontal_crs"])
    to_native = Transformer.from_crs(4326,crs,always_xy=True).transform
    to_geo = Transformer.from_crs(crs,4326,always_xy=True).transform
    hs = [f for f in habitat_features if f["properties"].get("island")==spec["island"] and f["properties"].get("habitat_kind")=="rock"]
    if not hs:
        raise ValueError("No reviewed hard habitat footprint for "+spec["island"])
    hard = unary_union([transform(to_native,make_valid(shape(f["geometry"]))) for f in hs])
    exclusion = transform(to_native,closed).buffer(config["closure_clearance_m"])
    hard = hard.difference(exclusion)
    support,points,metadata,counts = read_native(path,spec,hard,config)
    support = contained_outline(support.difference(exclusion),config["minimum_area_m2"])
    if support.is_empty:
        raise ValueError("No complete qualified geometry remains after closure screening")
    tree = cKDTree(points[:,:2])
    candidates=[]
    for part in polygons(support):
        inner=part.buffer(-12)
        if inner.is_empty:
            continue
        seeds=[inner.representative_point()]
        minx,miny,maxx,maxy=inner.bounds
        spacing=config["candidate_spacing_m"]
        for x in np.arange(math.ceil(minx/spacing)*spacing,maxx,spacing):
            for y in np.arange(math.ceil(miny/spacing)*spacing,maxy,spacing):
                p=Point(x,y)
                if inner.contains(p):seeds.append(p)
        for point in seeds:
            outline=contained_outline(part.intersection(point.buffer(200)),config["minimum_area_m2"])
            if outline.is_empty or not outline.contains(point):
                continue
            ids=tree.query_ball_point([point.x,point.y],250)
            samples=points[ids]
            on_hard=contains_xy(support,samples[:,0],samples[:,1])
            samples=samples[on_hard]
            if len(samples)<20:
                continue
            hard_area=support.intersection(point.buffer(250)).area
            metrics=terrain_metrics(samples[:,0],samples[:,1],samples[:,2],samples[:,4],hard_area_m2=hard_area)
            candidates.append((metrics["habitat_score"],point,outline,metrics))
    candidates.sort(key=lambda q:(-q[0],q[1].x,q[1].y))
    chosen=[]
    for item in candidates:
        if len(chosen)>=config["maximum_targets_per_island"]:break
        if all(item[1].distance(other[1])>=config["target_spacing_m"] for other in chosen):chosen.append(item)
    targets,areas,views=[],[],{}
    for _,point,outline,rating in chosen:
        key=hashlib.sha256(f"{spec['id']}:{point.x:.3f}:{point.y:.3f}".encode()).hexdigest()[:10]
        prefix=target_prefix(config)
        target_id,area_id=prefix+"-"+key,prefix+"-AREA-"+key
        coordinate=transform(to_geo,point)
        query=tree.query_ball_point([point.x,point.y],205)
        samples=points[query]
        # Include every native cell whose support square can touch the outline,
        # even if its center lies just outside. This conservative envelope may
        # include extra neighbors, but cannot understate boundary-cell depths.
        touching=outline.buffer(config["maximum_native_cell_m"]/math.sqrt(2))
        samples=samples[contains_xy(touching,samples[:,0],samples[:,1])]
        if not len(samples):continue
        # Qualification was done on whole native cells, not just these summary centers.
        depths=-samples[:,2]/.3048
        maximum_with_uncertainty=float(max(-samples[:,2]+samples[:,3]+config["planning_margin_m"])/.3048)
        nearest=points[tree.query([point.x,point.y])[1]]
        if not cells_qualified(nearest[2:3],nearest[3:4],nearest[4],limit_ft=config["depth_limit_ft"],
                minimum_ft=config["minimum_depth_ft"],planning_margin_m=config["planning_margin_m"],
                maximum_uncertainty_m=config["maximum_product_uncertainty_m"])[0]:
            raise ValueError("Representative target center failed native qualification")
        longitude,latitude=round(coordinate.x,7),round(coordinate.y,7)
        geo=mapping(transform(to_geo,outline))
        qualification={"policy":VERSION,"native_datum":"MLLW","planning_margin_m":config["planning_margin_m"],
            "maximum_product_uncertainty_m":config["maximum_product_uncertainty_m"],
            "max_depth_including_uncertainty_and_margin_ft":round(maximum_with_uncertainty,3),
            "closure_clearance_m":config["closure_clearance_m"],"full_geometry_screened":True,
            "source_cell_count_in_outline":len(samples),"verified_catches":False,
            "native_resolution_limit_m":config["maximum_native_cell_m"],
            "note":"Chart-datum depth screen plus reported product uncertainty and a 2 m planning allowance; not a tide forecast, navigation route or catch probability."}
        target={"id":target_id,"name":target_id+"-"+rating["habitat_grade"],
            "label":spec["island_name"]+" · surveyed hard-bottom patch", "source_id":spec["id"],
            "source_name":spec["name"],"source_url":spec["documentation_url"],"producer":"NOAA/NOS",
            "latitude":latitude,"longitude":longitude,"feature_type":"reef area search target",
            "terrain_interpretation":"Original NOAA multibeam terrain intersects historical mapped hard substrate. Search the supported outline with a sounder; fish and individual boulders are not verified.",
            "habitat_score":rating["habitat_score"],"habitat_grade":rating["habitat_grade"],"rank":0,
            "confidence":"Moderate","center_depth_ft":round(float(-nearest[2])/.3048,1),
            "neighborhood_depth_ft":[math.floor(float(min(depths))*10)/10,math.ceil(float(max(depths))*10)/10],
            "vertical_datum":"MLLW","survey_year":int(spec["survey_start"][:4]),
            "native_resolution_range_m":[float(min(samples[:,4])),float(max(samples[:,4]))],
            "analysis_cell_m":4,"rating":rating,"qualification":qualification,
            "metrics":{"relief_210m_m":None,"rugose_or_bedrock_fraction_210m":None,
                "plane_residual_rms_250m_m":rating["plane_residual_rms_m"],
                "rough_habitat_within_250m_ha":round(support.intersection(point.buffer(250)).area/10000,3)},
            "area_ids":[area_id],"drift_id":None,"species":["reef"],"depth_qualified":True,
            "fishing_target":True,"fishing_export":True,"evidence_status":"Measured-depth-qualified habitat candidate; no verified catch at this coordinate.",
            "ais_status":"No verified charter AIS evidence at this target.","special_note":spec["limitations"],
            "survey_flags":["Historical substrate; no field validation at this target","Native bathymetry and product uncertainty, not boulder measurements"],
            "recorded_validation":{"datum":"MLLW","missing_depth":False,"native_center_depth_ft":float(-nearest[2])/.3048,
                "minimum_ft":float(min(depths)),"maximum_ft":float(max(depths)),"closure_clearance_m":outline.distance(transform(to_native,closed)),
                "geometry_basis":"Entire retained native-cell footprint, then inward erosion and historical hard-substrate intersection. A complete 100 m circle is not claimed."}}
        area={"id":area_id,"source_id":spec["id"],"source_url":spec["documentation_url"],
            "area_ha":round(outline.area/10000,3),"target_ids":[target_id],"geometry":geo,
            "extent_note":"A supported search patch within 200 m of the marker, clipped to original NOAA native-depth cells, historical hard substrate and buffered closures. It is not the whole reef.",
            "map_resolution_m":4,"outline_simplification_m":1,"qualification":qualification,
            "recorded_validation":{"missing_depth":False,"minimum_ft":float(min(depths)),"maximum_ft":float(max(depths)),
                "native_cells":len(samples),"closure_clearance_m":outline.distance(transform(to_native,closed)),"datum":"MLLW"}}
        # Full geometry and serialized precision are checked, not just a centroid.
        if shape(geo).intersects(closed) or not support.covers(outline):
            raise ValueError("Output geometry escaped the qualified footprint")
        tile=numeric_view(points,tree,[point.x,point.y],spec,target_id,config["region_id"])
        receipt=atomic_json(bottom/(target_id+".json"),tile)
        views[target_id]={"status":"surveyed","path":f"regions/{config['region_id']}/bottom/{target_id}.json",
            "source_id":spec["id"],"coverage_fraction":tile["coverage_fraction"],**receipt}
        targets.append(target);areas.append(area)
    summary={"source_id":spec["id"],"island":spec["island"],"targets":len(targets),"qualified_support_km2":round(support.area/1e6,5),
        "published_search_area_km2":round(sum(a["area_ha"] for a in areas)/100,5),
        "complete_island_coverage":False,"historical_habitat_feature_ids":[f["properties"]["id"] for f in hs],
        "native_cells":counts,"metadata":metadata}
    return targets,areas,views,summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=ROOT/"regions/southern-california/bottom-sources.reviewed.json")
    parser.add_argument("--cache",type=Path,default=ROOT/"var/island-targets")
    parser.add_argument("--output",type=Path,default=ROOT/"dist/regions/southern-california/qualified-bottom")
    parser.add_argument("--fetch",action="store_true")
    parser.add_argument("--research-only",action="store_true",
        help="Allow held surveys only in an unpublished var/ output directory")
    args=parser.parse_args();config=read_json(args.config)
    now=datetime.now(timezone.utc).isoformat()
    try:
        if config.get("status")!="reviewed":raise ValueError("Input manifest is not reviewed")
        target_prefix(config)
        held = _held_original_surveys(ROOT)
        held_inputs = {s["survey_id"] for s in config["sources"]} & held
        if held_inputs and not args.research_only:
            raise ValueError("Original NOAA survey is held from fishing promotion: " + ", ".join(sorted(held_inputs)))
        if args.research_only and not args.output.resolve().is_relative_to((ROOT/"var").resolve()):
            raise ValueError("Research-only output must stay under var/")
        args.output.mkdir(parents=True,exist_ok=True)
        habitat_path=ROOT/config["habitat_path"]
        if sha256(habitat_path)!=config["habitat_sha256"]:raise ValueError("Derived habitat input changed; review its footprint before promotion")
        habitat=read_json(habitat_path)
        if habitat.get("region_id")!=config["region_id"]:raise ValueError("Wrong-region habitat source")
        closure_polys,closure_receipts=[],[]
        for item in config["closure_inputs"]:
            path=ROOT/item["path"];data=read_json(path)
            fresh_closures(data,minimum_features=item["minimum_features"],region_id=config["region_id"])
            closure_polys.extend(make_valid(shape(f["geometry"])) for f in data["features"])
            closure_receipts.append({"path":item["path"],"checked_at":data["checked_at"],"sha256":sha256(path),"features":len(data["features"]),"source_url":data["source_url"]})
        closed=unary_union(closure_polys)
        targets,areas,views,summaries,receipts=[],[],{},[],[]
        # Tiles are new stable IDs. No existing index changes until the final manifest.
        bottom=args.output.parent/"bottom";bottom.mkdir(exist_ok=True)
        for spec in config["sources"]:
            path,receipt=acquire(spec,args.cache,args.fetch);receipts.append(receipt)
            ts,aa,vv,summary=compile_source(spec,path,config,habitat["features"],closed,args.output,bottom)
            targets.extend(ts);areas.extend(aa);views.update(vv);summaries.append(summary)
        if not targets:raise ValueError("No qualified targets; existing release retained")
        targets.sort(key=lambda t:(-t["habitat_score"],t["id"]))
        for rank,t in enumerate(targets,1):t["rank"]=rank
        sources=[{**s,"url":s["documentation_url"],"native_data_url":s["url"],"survey_year":int(s["survey_start"][:4]),"datum":"MLLW"} for s in config["sources"]]
        atlas={"schema_version":1,"region_id":config["region_id"],"edition":VERSION,"title":"Original NOAA island habitat candidates",
            "fishing_depth_limit_ft":config["depth_limit_ft"],"source_validation_date":now[:10],
            "source_validation_note":"Original native BAG depth and product-uncertainty screen. Historical hard substrate; no verified catch or charter evidence. Current rules and closure freshness remain required at use/export time.",
            "targets":targets,"areas":areas,"drifts":[],"sources":sources}
        quality={"schema_version":1,"region_id":config["region_id"],"generated_at":now,"status":"qualified-partial",
            "transformation_version":VERSION,"config_sha256":sha256(args.config),"habitat_sha256":config["habitat_sha256"],
            "source_receipts":receipts,"sources":sources,"closure_receipts":closure_receipts,"summary":summaries,
            "target_count":len(targets),"area_count":len(areas),"bottom_views":len(views),
            "claims":{"measured_datum":"MLLW","depth_qualified":True,"catch_calibrated":False,"boulder_size_measured":False,"complete_island_coverage":False},
            "limits":["Native 1–4 m gridded depth is not sounding accuracy or an individual rock inventory.","Published habitat ranks are transparent physical proxies, not calibrated bite probabilities.","Original BAG surveys are historical; the 2006 hard/soft substrate interpretation lacks target-specific field validation.","The 2 m planning allowance is not a tide or bottom-current prediction.","MPA/GEA geometry is screened at build time and again by the app; current species seasons and actual trip access are separate."]}
        index={"schema_version":1,"region_id":config["region_id"],"views":views,
            "sources":{s["id"]:{"source_id":s["id"],"sha256":s["sha256"],"url":s["url"],"survey_year":int(s["survey_start"][:4]),"vertical_datum":"MLLW"} for s in config["sources"]}}
        artifacts={}
        for name,value in [("atlas.json",atlas),("quality.json",quality),("bottom-index-fragment.json",index)]:
            artifacts[name]=atomic_json(args.output/name,value)
        atomic_json(args.output/"manifest.json",{"schema_version":1,"region_id":config["region_id"],"status":"ready",
            "generated_at":now,"transformation_version":VERSION,"artifacts":artifacts})
        atomic_json(args.output/"health.json",{"checked_at":now,"status":"ready","targets":len(targets)})
        print(json.dumps({"targets":len(targets),"areas":len(areas),"bottom_views":len(views),"output":str(args.output)}))
    except Exception as exc:
        atomic_json(args.output/"health.json",{"checked_at":now,"status":"held","reason":str(exc),"previous_release_retained":True})
        raise


if __name__=="__main__":
    main()
