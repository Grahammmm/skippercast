"""Research-only original geology/native-grid/MPA overlap for San Simeon.

No point coordinates, MLLW depths, fish scores or export records are produced.
The CSUMB datum/rights and local access gates remain unresolved.
"""

import argparse
import hashlib
import io
import json
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
import shapefile
from pyproj import Transformer
from rasterio.features import rasterize
from scipy.ndimage import label
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from audit_csumb_scc_native import acquire, digest, file_digest


ROOT = Path(__file__).resolve().parents[1]


def fetch_geology(spec, cache, fetch):
    path = cache / "Geology_SanSimeon.zip"
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(path)
        cache.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".partial")
        try:
            with urllib.request.urlopen(spec["archive_url"], timeout=45) as response:
                if response.status != 200 or urllib.parse.urlsplit(response.url).hostname != "pubs.usgs.gov":
                    raise ValueError("Unexpected USGS source response")
                if int(response.headers.get("Content-Length", "-1")) != spec["archive_bytes"]:
                    raise ValueError("USGS archive size changed")
                temporary.write_bytes(response.read(spec["archive_bytes"] + 1))
            if temporary.stat().st_size != spec["archive_bytes"] or file_digest(temporary) != spec["archive_sha256"]:
                raise ValueError("USGS source changed or incomplete")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if path.stat().st_size != spec["archive_bytes"] or file_digest(path) != spec["archive_sha256"]:
        raise ValueError("USGS original archive digest changed")
    return path


def geology_shapes(path, spec):
    with zipfile.ZipFile(path) as archive:
        if digest(archive.read("Geology_SanSimeon_metadata.txt")) != spec["metadata_member_sha256"]:
            raise ValueError("USGS source metadata changed")
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("shp", "shx", "dbf", "prj"):
                member = f"Geology_SanSimeon.{name}"
                (Path(tmp) / member).write_bytes(archive.read(member))
            projection = (Path(tmp) / "Geology_SanSimeon.prj").read_text()
            if "WGS_1984_UTM_Zone_10N" not in projection or spec["shapefile_crs"] != "EPSG:32610":
                raise ValueError("USGS geology coordinate system changed")
            source = shapefile.Reader(str(Path(tmp) / "Geology_SanSimeon.shp"))
            if len(source) != spec["expected_polygon_count"]:
                raise ValueError("USGS geology polygon count changed")
            transform_crs = Transformer.from_crs("EPSG:32610", "EPSG:26910", always_xy=True).transform
            pure, composite = [], 0
            for item in source.iterShapeRecords():
                code = item.record.as_dict()["MapUnitAbb"]
                if code in spec["composite_sediment_over_bedrock_units_excluded"]:
                    composite += 1
                if code in spec["pure_bedrock_units"]:
                    interior = transform(transform_crs, shape(item.shape.__geo_interface__)).buffer(-10)
                    if not interior.is_empty:
                        pure.append((interior, 1))
            if not pure or not composite:
                raise ValueError("Unexpected USGS geology class coverage")
            return pure, composite


def current_mpas(snapshot):
    url = json.loads(snapshot.read_text())["source_url"]
    prefix = "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?"
    if not url.startswith(prefix):
        raise ValueError("Unreviewed MPA authority")
    with urllib.request.urlopen(url, timeout=45) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("Unexpected MPA source response")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("MPA source response oversized")
    data = json.loads(raw)
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    params.update({"returnCountOnly": "true", "returnGeometry": "false", "f": "json"})
    count_url = prefix + urllib.parse.urlencode(params)
    with urllib.request.urlopen(count_url, timeout=45) as response:
        count = json.loads(response.read(100_000)).get("count")
    features = data.get("features", [])
    if data.get("exceededTransferLimit") or not isinstance(count, int) or count < 8 or len(features) != count:
        raise ValueError("MPA query incomplete")
    project = Transformer.from_crs("EPSG:4326", "EPSG:26910", always_xy=True).transform
    polygons = [transform(project, shape(feature["geometry"])) for feature in features]
    return unary_union(polygons).buffer(100), {"url": url, "sha256": digest(raw), "count": count,
                                                 "checked_at": datetime.now(timezone.utc).isoformat()}


def extract_grid(bundle, member, expected_sha, grid, destination):
    raw = bundle.extractfile(member).read()
    if digest(raw) != expected_sha:
        raise ValueError("Native CSUMB grid member changed")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for item in archive.infolist():
            name = Path(item.filename)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Unsafe grid archive path")
            if item.filename.startswith("ArcViewGrids/") and not item.is_dir():
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))
    return destination / grid


def inspect_block(spec, cache, pure_bedrock, protected, fetch):
    archive = acquire(spec, cache, fetch)
    if archive.stat().st_size != spec["archive_bytes"] or file_digest(archive) != spec["archive_sha256"]:
        raise ValueError("CSUMB original archive changed")
    with tarfile.open(archive, "r:gz") as bundle, tempfile.TemporaryDirectory() as tmp:
        bathy_path = extract_grid(bundle, spec["bathymetry_member"], spec["bathymetry_member_sha256"],
                                  spec["bathymetry_grid"], Path(tmp) / "bathy")
        terrain_path = extract_grid(bundle, spec["habitat_member"], spec["habitat_member_sha256"],
                                    spec["habitat_grid"], Path(tmp) / "terrain")
        with rasterio.open(bathy_path) as bathy, rasterio.open(terrain_path) as terrain:
            if bathy.crs.to_epsg() != 26910 or terrain.crs != bathy.crs or terrain.transform != bathy.transform:
                raise ValueError("Native geology screen grids misaligned")
            elevation = bathy.read(1, masked=True)
            roughness = terrain.read(1, masked=True)
            measured = ~np.ma.getmaskarray(elevation) & ~np.ma.getmaskarray(roughness)
            bedrock = rasterize(pure_bedrock, out_shape=bathy.shape, transform=bathy.transform, dtype="uint8") == 1
            excluded = rasterize([(protected, 1)], out_shape=bathy.shape, transform=bathy.transform, dtype="uint8") == 1
            rough = np.isin(roughness.data, (-1, -31))
            # Source datum remains NAVD88; this band is a workload filter, never a fishing-depth gate.
            nominal_band = (elevation.data <= -7.62) & (elevation.data >= -60.96)
            overlap = measured & bedrock & rough & nominal_band
            retained = overlap & ~excluded
            labels, components = label(retained)
            sizes = np.bincount(labels[retained], minlength=components + 1)
            return {"source_id": spec["id"], "source_archive_sha256": spec["archive_sha256"],
                    "measured_aligned_cells": int(measured.sum()),
                    "pure_bedrock_inset_rough_nominal_navd_cells": int(overlap.sum()),
                    "inside_mpa_100m_buffer_cells": int((overlap & excluded).sum()),
                    "outside_mpa_100m_buffer_cells": int(retained.sum()),
                    "connected_components_after_screen": int(components),
                    "components_at_least_0_25_ha": int(np.count_nonzero(sizes[1:] >= 625)),
                    "components_at_least_1_ha": int(np.count_nonzero(sizes[1:] >= 2500)),
                    "largest_component_ha": round(float(sizes[1:].max(initial=0)) * 4 / 10_000, 3),
                    "cell_area_m2": 4,
                    "publication_status": "research-only; no certified MLLW depth or fishing coordinates"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geology", type=Path, default=ROOT / "catalog/usgs-sansimeon-geology.json")
    parser.add_argument("--sources", type=Path, default=ROOT / "catalog/csumb-scc-native-sources.json")
    parser.add_argument("--mpa-snapshot", type=Path, default=ROOT / "dist/data/protected-areas.geojson")
    parser.add_argument("--geology-cache", type=Path, default=ROOT / "var/usgs-native-cache")
    parser.add_argument("--csumb-cache", type=Path, default=ROOT / "var/noaa-native-cache")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/csumb-sansimeon-bedrock-overlap-review.json")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    geology = json.loads(args.geology.read_text())
    pure, composites = geology_shapes(fetch_geology(geology, args.geology_cache, args.fetch), geology)
    protected, mpa_receipt = current_mpas(args.mpa_snapshot)
    sources = json.loads(args.sources.read_text())["sources"]
    records = [inspect_block(source, args.csumb_cache, pure, protected, args.fetch) for source in sources]
    report = {"schema_version": 1, "scope": "original-geology-native-grid-mpa-overlap",
              "reviewed_at": datetime.now(timezone.utc).isoformat(), "status": "research-only",
              "geology_source": {"id": geology["id"], "url": geology["archive_url"],
                                 "sha256": geology["archive_sha256"], "pure_bedrock_polygons_after_10m_inset": len(pure),
                                 "excluded_composite_sediment_polygons": composites},
              "mpa_source": mpa_receipt, "blocks": records,
              "limitations": ["NAVD88 nominal band is not converted or qualified MLLW fishing depth.",
                              "A rough cell and mapped bedrock polygon are related interpretations of historical survey data, not independent fish observations.",
                              "The three source grids overlap; block cell counts must not be summed as unique area.",
                              "The 100 m MPA buffer is a research screen, not legal clearance, navigation clearance or a species-specific rule review.",
                              "No output coordinate, waypoint, habitat rating or export is approved."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".partial")
    temporary.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"blocks": len(records), "output": str(args.output)}))


if __name__ == "__main__":
    main()
