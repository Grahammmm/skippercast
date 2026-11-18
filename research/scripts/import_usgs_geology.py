"""Import a reviewed USGS SIM 3327 geology ZIP as context, never fishing targets."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import box, shape, mapping
from shapely.ops import transform, unary_union
from shapely import make_valid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from skippercast.platform.contracts import REPO, load_region, atomic_json, read_json, within


CATALOG = REPO / "catalog" / "usgs-sansimeon-geology.json"


def authenticate_archive(path, catalog):
    """Return immutable archive bytes and their reviewed release digest."""
    archive = Path(path).read_bytes()
    actual = hashlib.sha256(archive).hexdigest()
    if actual != catalog["archive_sha256"]:
        raise ValueError("San Simeon geology ZIP digest differs from the reviewed release; review the source before rebuilding")
    return archive, actual


def require_metric_crs(crs, catalog):
    """Metric exclusions and area cutoffs assume the reviewed projected CRS in metres."""
    expected = CRS.from_user_input(catalog["shapefile_crs"])
    if not (crs == expected or crs.to_epsg() == expected.to_epsg()) or not crs.is_projected \
            or any(a.unit_name not in ("metre", "meter") for a in crs.axis_info):
        raise ValueError("San Simeon geology .prj is not the reviewed metric CRS " + catalog["shapefile_crs"])
    return crs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--region", required=True)
    p.add_argument("--zip", type=Path, required=True)
    args=p.parse_args()
    region=load_region(args.region)
    # This provider adapter deliberately accepts only this documented release.
    if "usgs-san-simeon" not in region["source_bindings"]["substrate"]:
        raise ValueError("San Simeon geology is not bound to this region")
    archive,digest=authenticate_archive(args.zip, read_json(CATALOG))
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        stem="Geology_SanSimeon"
        if any(info.file_size>25_000_000 for info in z.infolist()):
            raise ValueError("Archive member too large")
        reader=shapefile.Reader(**{key:io.BytesIO(z.read(stem+"."+key)) for key in ("shp","shx","dbf")})
        crs=require_metric_crs(CRS.from_wkt(z.read(stem+".prj").decode()), read_json(CATALOG))
        forward=Transformer.from_crs(4326,crs,always_xy=True).transform
        inverse=Transformer.from_crs(crs,4326,always_xy=True).transform
        extent=transform(forward,box(*region["fishing_bounds"]))
        mpas=read_json(within(REPO/"dist",region["assets"]["protected_areas"]))
        excluded=unary_union([transform(forward,shape(f["geometry"])) for f in mpas["features"]]).buffer(100)
        groups={}
        for feature in reader.iterShapeRecords():
            props=feature.record.as_dict()
            g=make_valid(shape(feature.shape.__geo_interface__)).intersection(extent).difference(excluded)
            if g.is_empty: continue
            unit=props["MapUnitAbb"]
            # Qms/... explicitly denotes a sediment veneer, not exposed bedrock.
            kind="mixed" if "/" in unit else "sediment" if unit.startswith("Q") else "rock"
            groups.setdefault((unit,props["UnitType"],kind),[]).append(g)
        features=[]
        for (unit,label,kind),shapes in groups.items():
            merged=unary_union(shapes).simplify(8,preserve_topology=True).difference(excluded)
            parts=list(merged.geoms) if merged.geom_type=="MultiPolygon" else [merged]
            for part in parts:
                if part.geom_type!="Polygon" or part.area<25_000: continue
                point=part.representative_point();lon,lat=inverse(point.x,point.y)
                features.append({"type":"Feature","geometry":mapping(transform(inverse,part)),"properties":{
                    "id":f"CSS-GEO-{len(features)+1:03d}","unit":unit,"label":label,"kind":kind,
                    "latitude":lat,"longitude":lon,"area_km2":round(part.area/1e6,3),
                    "source_id":"usgs-san-simeon","source_url":"https://pubs.usgs.gov/sim/3327/",
                    "publication_year":2015,"depth_qualified":False,"fishing_target":False}})
    result={"type":"FeatureCollection","schema_version":1,"region_id":region["id"],"features":features,
        "source":{"id":"usgs-san-simeon","url":"https://pubs.usgs.gov/sim/3327/downloads/Geology_SanSimeon.zip",
        "sha256":digest,"publication_year":2015,
        "attribution":"U.S. Geological Survey, Watt and others, SIM 3327 (2015)",
        "derivation":"WGS84 reprojection; regional crop; dissolve adjacent units; 8 m simplification; 100 m MPA exclusion; minimum 0.025 km² pieces.",
        "limitations":"Regional geological interpretation, not depth-qualified habitat, catch evidence, boulder measurements or navigation. Sediment veneers may cover bedrock; no depth is inferred."}}
    atomic_json(within(REPO/"dist",region["assets"]["geology"]),result)
    print(json.dumps({"region":region["id"],"geological_context_areas":len(features),"fishing_targets":0}))


if __name__=="__main__": main()
