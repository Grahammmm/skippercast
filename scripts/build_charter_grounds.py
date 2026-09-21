"""Build dated charter-report evidence and conservative *search* outlines.

Usage: python scripts/build_charter_grounds.py REPORT_RESEARCH WAYPOINT_RESEARCH
Inputs are separately collected public trip facts and the reviewed USGS grids.
The search windows are editorial geographic interpretations, NEVER boat tracks.
Requires the same GIS dependencies as build_habitat_regions.py.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes, geometry_mask
from rasterio.warp import Resampling
from scipy.ndimage import binary_erosion
from shapely.geometry import Point, box, shape, mapping
from shapely.ops import transform, unary_union
from pyproj import Transformer
from build_habitat_regions import coarse

ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = [
    {"id": "CHARTER-PECHO", "label": "Pecho Rock", "source_id": "PointBuchon",
     "precision": "Named landmark vicinity", "location_confidence": "Approximate",
     "anchor": [-120.81661, 35.17938], "radius_nm": 1.25,
     "anchor_source": "https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=170559",
     "boundary_note": "Search water within 1.25 nautical miles of the Pecho Rock landmark, clipped to reviewed survey coverage, depth and closure screens. The radius is a planning choice; captains did not publish this boundary.",
     "approach": "Use the reported vicinity to narrow your search, then inspect the separate reef candidates with your sounder. Pecho Rock itself is an above-water landmark, not a fishing waypoint."},
    {"id": "CHARTER-DIABLO", "label": "Diablo coast", "reported_ground": "Diablo", "source_id": "PointBuchon",
     "precision": "Named coastal vicinity", "location_confidence": "Approximate",
     "anchor": [-120.8563888889, 35.2063888889], "radius_nm": 2,
     "anchor_source": "https://www.govinfo.gov/content/pkg/CFR-2025-title33-vol2/pdf/CFR-2025-title33-vol2-sec165-1155.pdf",
     "boundary_note": "Search water within 2 nautical miles of the Diablo Canyon geographic reference, clipped to reviewed survey coverage, depth and buffered closures. The report says only Diablo; the surviving southern search water is our interpretation, not the charter's track.",
     "approach": "Investigate structure outside the Diablo Canyon security zone and Point Buchon MPAs. The plant and its intake/discharge waters are not fishing targets. Use current official boundaries before choosing an approach."},
    {"id": "CHARTER-MORRO", "label": "Morro Bay coast", "reported_ground": "Morro Bay", "source_id": "MorroBay",
     "precision": "Broad regional name", "location_confidence": "Low · regional only",
     "bounds": [-121.02, 35.30, -120.80, 35.43],
     "anchor_source": "https://doi.org/10.5066/P9HEZNRO",
     "boundary_note": "The report names Morro Bay without identifying a reef or direction. This broad search outline uses the reviewed offshore Morro Bay survey between 35.30° and 35.43° N, clipped to depths and buffered closures. Those limits are planning choices, not reported fishing positions.",
     "approach": "Treat this as regional context. Fiesta and Rita G reports do not distinguish the exact reefs they visited. Use the separate habitat grades and sounder to choose a specific place."},
]


def compact_geometry(poly, geo):
    # Precision is storage only; six decimals do not represent location accuracy.
    return json.loads(json.dumps(mapping(transform(geo, poly)), default=float),
                      parse_float=lambda x: round(float(x), 6))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("reports", type=Path)
    p.add_argument("research", type=Path)
    args = p.parse_args()
    facts = json.loads((args.reports / "trip-facts.json").read_text())
    sources = json.loads((args.research / "data/candidate-pool.json").read_text())["sources"]
    closed_path = args.research / "data/closed-area-screen.geojson"
    closed = json.loads(closed_path.read_text())
    utm = Transformer.from_crs(4326, 32610, always_xy=True).transform
    geo = Transformer.from_crs(32610, 4326, always_xy=True).transform
    exclusion = transform(utm, shape(closed["features"][0]["geometry"])).buffer(505)
    atlas = json.loads((ROOT / "dist/data/atlas.json").read_text())
    output = []
    for definition in DEFINITIONS:
        name = definition.get("reported_ground", definition["label"])
        records = [r for r in facts["records"] if r["ground"] == name]
        assert records, name
        src = next(s for s in sources if s["key"] == definition["source_id"])
        window = (Point(utm(*definition["anchor"])).buffer(definition["radius_nm"] * 1852)
                  if "anchor" in definition else transform(utm, box(*definition["bounds"])))
        with rasterio.open(args.research / src["analysis_file"]) as grid:
            with rasterio.open(src["bath"]) as bath:
                shallow = -coarse(bath, grid, Resampling.max) / .3048
                deep = -coarse(bath, grid, Resampling.min) / .3048
                coverage = coarse(bath, grid, Resampling.min, True) == 255
            allowed = ~geometry_mask([mapping(exclusion)], grid.shape, grid.transform, invert=True, all_touched=True)
            inside_window = geometry_mask([mapping(window)], grid.shape, grid.transform, invert=True)
            mask = coverage & allowed & inside_window & (shallow >= 25) & (deep <= 195)
            mask = binary_erosion(mask, iterations=2)
            polygons = [shape(g) for g, v in shapes(mask.astype("uint8"), mask=mask, transform=grid.transform) if v]
            # Keep real connected water; do not bridge deep water or survey gaps.
            display = unary_union([poly.buffer(-12).simplify(8, preserve_topology=True)
                                   for poly in polygons if poly.area >= 100000])
            parts = list(display.geoms) if display.geom_type == "MultiPolygon" else [display]
            display = unary_union([part for part in parts if not part.is_empty and part.area >= 100000])
            assert not display.is_empty, name
            geometry = compact_geometry(display, geo)
            # Validate the actual rounded, simplified published outline, including edges.
            published = transform(utm, shape(geometry))
            touched = geometry_mask([mapping(published)], grid.shape, grid.transform, invert=True, all_touched=True)
            assert np.all(coverage[touched]) and np.all(allowed[touched]), name
            assert shallow[touched].min() >= 25 and deep[touched].max() <= 195, name
            assert published.distance(exclusion) > 0, name
            depth = [round(float(shallow[touched].min()), 1), round(float(deep[touched].max()), 1)]
        anchor = max(parts, key=lambda x: x.area).representative_point()
        lon, lat = geo(anchor.x, anchor.y)
        reports = [{"date": r["date"], "boat": r["boat"], "species": r["species"],
                    "source_url": r["source_url"], "boat_source_url": r["vessel_source_url"]}
                   for r in records]
        # Dedupe only exact records. Separate boats on one date remain separate trips.
        reports = list({(r["date"], r["boat"], r["source_url"]): r for r in reports}.values())
        reports.sort(key=lambda r: (r["date"], r["boat"]), reverse=True)
        nearby = [t for t in atlas["targets"] if published.covers(Point(utm(t["longitude"], t["latitude"])))]
        nearby.sort(key=lambda t: (-t["habitat_score"], t["id"]))
        output.append({**definition, "reported_ground": name, "evidence_type": "published_named_ground",
                       "map_species": ["lingcod", "rockfish"], "report_count": len(reports),
                       "report_dates": sorted(set(r["date"] for r in reports)),
                       "boats": sorted(set(r["boat"] for r in reports)),
                       "latest_report": max(r["date"] for r in reports), "reports": reports,
                       "latitude": round(lat, 6), "longitude": round(lon, 6), "geometry": geometry,
                       "area_km2": round(published.area / 1e6, 2), "depth_ft": depth,
                       "survey_year": src["survey_year"], "datum": "MLLW", "survey_source": src["source_url"],
                       "nearby_target_ids": [t["id"] for t in nearby],
                       "ais_verified": False, "exact_position_published": False,
                       "depth_of_reported_trips": None, "catch_probability": None})
        print(name, len(reports), "reports", len(set(r['date'] for r in reports)), "dates", depth,
              round(published.area / 1e6, 2), "km²", len(nearby), "survey candidates", flush=True)
    coverage = [{"date": c["date"], "status": c["status"],
                 "source_url": "https://www.socalfishreports.com/dock_totals/boats.php?date=" + c["date"],
                 **({"local_trip_count": len(c["records"])} if c["status"] == "ok" else {"error": c["error"]})}
                for c in facts["coverage"]]
    for item in coverage:
        meta = args.reports / "raw" / ("counts-" + item["date"] + ".meta.json")
        if meta.exists():
            m = json.loads(meta.read_text())
            item.update({k: m[k] for k in ["retrieved_at", "sha256"]})
    counts = Counter(r["ground"] or "Not reported" for r in facts["records"])
    dataset = {"schema_version": 1, "audit_date": "2026-09-21", "grounds": output,
               "coverage": {"from": min(c["date"] for c in coverage), "through": max(c["date"] for c in coverage),
                            "dates_checked": len(coverage), "dates_available": sum(c["status"] == "ok" for c in coverage),
                            "local_trips": len(facts["records"]), "ground_counts": dict(counts),
                            "mapped_single_ground_trips": sum(a["report_count"] for a in output), "pages": coverage},
               "method": "Landing-reported daily trip facts. Only single named-ground records are linked to an area; multi-ground trips are not allocated. Names are geographic evidence, not GPS fixes. Constructed search outlines use reviewed USGS 2008 bathymetry, fully covered native cells aggregated to a 10 m grid, 25–195 ft MLLW, buffered closure exclusions (505 m), 20 m erosion, 12 m inward buffer then 8 m simplification, and connected parts >=0.1 km². Actual published outline rechecked with all-touched cells. No gaps are bridged. Sounder depths change with tide. No catch ranking, track reconstruction or precise charter-to-reef attribution.",
               "source_links": [{"title": "Patriot Sportfishing · operator", "url": "https://www.patriotsportfishing.com/"},
                                {"title": "Virg’s Landing · fish-count provider attribution", "url": "https://www.virgslanding.com/boats/ritag.php"},
                                {"title": "CDFW · Point Buchon boundaries", "url": "https://wildlife.ca.gov/Conservation/Marine/MPAs/Point-Buchon"},
                                {"title": "33 CFR 165.1155 · published security-zone rule (2025 edition)", "url": DEFINITIONS[1]["anchor_source"]}],
               "closure_screen": {"sha256": hashlib.sha256(closed_path.read_bytes()).hexdigest(),
                                  "geometry_date": "2026-09-16", "mpa_page_checked": "2026-09-21",
                                  "security_reference": "2025 CFR edition read 2026-09-21; current eCFR direct read returned HTTP 406. Recheck current restrictions.",
                                  "buffer_m": 505},
               "limitations": ["Reported catches and places are supplied to the report publisher; not independently observed.",
                               "Report counts measure this sample, not popularity, fishing effort, catch rate or today's bite.",
                               "Out Front is ambiguous. Point Sal, Purisima Point and Shell Beach are outside the requested Avila–Cambria area.",
                               "No complete-season or complete-fleet coverage is claimed. The mapped layer currently supports lingcod and rockfish only.",
                               "The existing AIS sample still contains zero independently verified local charter identities."]}
    dest = ROOT / "dist/data/charter-grounds.json"
    dest.write_text(json.dumps(dataset, separators=(",", ":")) + "\n")
    print("Wrote", dest.name, dest.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
