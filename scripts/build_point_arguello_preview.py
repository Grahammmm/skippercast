"""Assemble the bounded Point Arguello–Point Conception research preview.

The native NOAA/USGS outlines are historical context, never fishing targets.
This script is deliberately deterministic so source revisions require review.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[1]
ID = "point-arguello-conception"
SOURCE_SHA256 = "e0dac59edb3f0d6e6a506beb911d9c9eac07e1743b06deb817ec04ecd8f213db"


def read(path):
    return json.loads((ROOT / path).read_text())


def write(path, value):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def build():
    region = read("regions/humboldt-bay-cape-mendocino/region.json")
    region.update({
        "id": ID,
        "name": "Point Sal to Point Conception",
        "jurisdiction": "California · Central Groundfish Management Area",
        "jurisdiction_id": "california-central",
        "bounds": [-121.25, 34.45, -120.35, 35.07],
        "fishing_bounds": [-121.15, 34.45, -120.38, 35.03],
        "map": {
            "center": [34.70, -120.69], "zoom": 10,
            "locality_method": "Central management area ends at 34°27′ N. This browse extent is not a legal boundary, access clearance, or fishing-site recommendation.",
            "region_notice_ids": ["vandenberg-conception"],
            "discovery_bounds": [-121.25, 34.45, -120.35, 35.07],
            "local_areas": [],
            "focus_areas": [
                {"id": "point-sal", "name": "Point Sal outer coast", "bounds": [-121.12, 34.85, -120.52, 35.03], "forecast_point": "point-sal"},
                {"id": "point-arguello", "name": "Point Arguello", "bounds": [-120.82, 34.53, -120.43, 34.75], "forecast_point": "point-arguello"},
                {"id": "point-conception", "name": "Point Conception research", "bounds": [-120.64, 34.45, -120.38, 34.57], "forecast_point": "point-conception"},
            ],
        },
        "harbor": {
            "name": "Port San Luis · distant departure reference",
            "latitude": 35.1767, "longitude": -120.76,
            "entrance_note": "Port San Luis is north of this preview. Its tide predictions do not predict bar currents or establish a safe Point Arguello route. Recheck the actual harbor and Vandenberg maritime status before travel.",
            "information_url": "https://www.portsanluis.com/",
            "watch_keywords": ["Port San Luis", "Point Arguello", "Vandenberg"],
        },
        "forecast_points": [
            {"id": "point-sal", "name": "Off Point Sal", "latitude": 34.90, "longitude": -120.82, "context": "north-of-sal"},
            {"id": "point-arguello", "name": "Off Point Arguello", "latitude": 34.61, "longitude": -120.76, "context": "south-of-sal"},
            {"id": "point-conception", "name": "Off Point Conception", "latitude": 34.50, "longitude": -120.57, "context": "south-of-sal"},
            {"id": "offshore", "name": "Santa Maria offshore reference", "latitude": 34.82, "longitude": -121.06, "context": "north-of-sal", "offshore": True},
        ],
        "marine_zones": {"coastal": "PZZ645", "offshore": "PZZ670", "point-sal-south": "PZZ673"},
        "stations": {
            "tide": "9412110", "tide_name": "Port San Luis",
            "tide_note": "Port San Luis is a distant water-level reference, not Point Arguello bottom current or launch-zone clearance.",
            "airport": "KSMX", "airport_name": "Santa Maria airport · inland reference",
            "nearshore_buoy": "46215", "nearshore_buoy_name": "Diablo Canyon · distant wave reference",
            "offshore_buoy": "46011", "offshore_buoy_name": "Santa Maria · 21 NM NW of Point Arguello",
        },
        "contexts": {
            "north-of-sal": {"name": "Point Sal north", "marine_zones": {"coastal": "PZZ645", "offshore": "PZZ670"},
                             "stations": {"tide": "9412110", "tide_name": "Port San Luis · distant reference", "tide_note": "Water level only; no bottom-current or route clearance.", "airport": "KSMX", "airport_name": "Santa Maria inland", "nearshore_buoy": "46215", "nearshore_buoy_name": "Diablo Canyon · distant reference", "offshore_buoy": "46011", "offshore_buoy_name": "Santa Maria offshore"}},
            "south-of-sal": {"name": "Point Arguello and Conception", "marine_zones": {"coastal": "PZZ673", "offshore": "PZZ673"},
                             "stations": {"tide": "9412110", "tide_name": "Port San Luis · distant reference", "tide_note": "Water level only; no bottom-current or route clearance.", "airport": "KSMX", "airport_name": "Santa Maria inland", "nearshore_buoy": "46215", "nearshore_buoy_name": "Diablo Canyon · distant reference", "offshore_buoy": "46011", "offshore_buoy_name": "Santa Maria offshore"}},
        },
        "mpa": {"bounds": [-121.25, 34.45, -120.35, 35.07], "minimum_features": 1},
        "species": ["reef", "halibut", "salmon", "dungeness", "albacore", "bluefin"],
        "ecology_profile": "california-central",
        "coverage_note": "Central Coast research preview. Four larger historical hard-bottom outlines are displayed from 21 NOAA/USGS context candidates; zero fishing targets, routes, drifts or exports are qualified.",
        "landing_note": "The dated seabed outlines are not verified catch sites. Vandenberg launch zones and the Vandenberg and Point Conception no-take reserves need trip-time checks.",
        "landing_names": ["Point Sal", "Point Arguello", "Point Conception"],
    })
    region["source_names"] = {"H11952": "NOAA H11952 / USGS hard-bottom research", "H11953": "NOAA H11953 / USGS hard-bottom research"}
    region["source_bindings"]["catch-effort"] = ["noaa-survey-catches", "recfin"]
    region["source_bindings"]["charter-identity"] = []
    region["source_bindings"]["ais-history"] = ["noaa-ais"]
    region["coverage"] = {key: {"status": "research", "reason": "Regional source coverage, rights, precision, and freshness need review before this role can qualify a fishing recommendation."} for key in region["source_bindings"]}
    region["coverage"].update({
        "bathymetry": {"status": "partial", "reason": "Original 2008 NOAA H11952/H11953 MLLW BAG cells support bounded historical research outlines off Point Conception, not current chart or route clearance."},
        "substrate": {"status": "partial", "reason": "Original USGS 2 m hard/rugged class intersects screened native BAG cells only within a small dated footprint; it is not continuous sector coverage."},
        "protected-areas": {"status": "partial", "reason": "A dated CDFW MPA and federal GEA screen excludes mapped reserves in the research layer. Current full geometry and trip-time access remain separate gates."},
        "regulations": {"status": "partial", "reason": "Central management-area cards and the local Vandenberg/Point Conception notices are reviewed; in-season changes and exact position still need fresh checks."},
        "wind-forecast": {"status": "partial", "reason": "Local GFS and IFS samples are configured; first matched-hour collection is not yet verified."},
        "wave-forecast": {"status": "partial", "reason": "Local GFS Wave and WAM samples are configured; PZZ673 and return-route conditions need first live comparison."},
        "wave-observations": {"status": "partial", "reason": "NDBC 46011 is offshore; 46215 is a distant Diablo Canyon reference, not a Point Conception measurement."},
        "weather-observations": {"status": "partial", "reason": "NDBC 46011 offshore, PTGC1 Point Arguello coastal winds and KSMX inland conditions do not establish ground or entrance conditions."},
        "tides": {"status": "partial", "reason": "NOAA Port San Luis water-level predictions are a distant reference, not local bottom-current or launch-zone timing."},
        "harbor-access": {"status": "research", "reason": "Vandenberg danger zone 4 is always closed and other zones change during operations; the official live maritime update or Frontier Control must be checked. No automatic clearance is established."},
    })
    prefix = f"regions/{ID}"
    region["assets"] = {"atlas": f"{prefix}/atlas.json", "habitats": f"{prefix}/habitats.json", "protected_areas": f"{prefix}/protected-areas.geojson", "regulations": "data/regulations.json", "charters": None, "ais_evidence": None, "commercial_ais": None, "daily_evidence": None, "bottom_index": f"{prefix}/bottom/index.json", "geology": None, "ecology": f"{prefix}/ecology.json", "search_plans": f"{prefix}/search-plans.json", "survey_habitat": f"{prefix}/survey-habitat.geojson"}
    region["daily_feed"] = f"https://raw.githubusercontent.com/Grahammmm/skippercast/data/regions/{ID}/latest.json"
    region["conditions_feed"] = f"https://raw.githubusercontent.com/Grahammmm/skippercast/conditions/regions/{ID}/latest.json"
    region["intelligence_feed"] = f"https://raw.githubusercontent.com/Grahammmm/skippercast/conditions/regions/{ID}/intelligence.json"
    region["habitat_feed"] = f"https://raw.githubusercontent.com/Grahammmm/skippercast/conditions/regions/{ID}/habitat-dynamics.json"
    region["intelligence"]["ecology_profile"] = "california-central"
    region["intelligence"]["verification_stations"] = [{"id": "46011", "latitude": 34.937, "longitude": -120.999, "name": "Santa Maria offshore", "variables": ["wave_height", "wind_speed"], "source_url": "https://www.ndbc.noaa.gov/station_page.php?station=46011"}]
    write(f"regions/{ID}/region.json", region)
    source = ROOT / "dist/data/point-conception-native-hard-context.geojson"
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Original NOAA/USGS context changed; rerun source review")
    context = read("dist/data/point-conception-native-hard-context.geojson")
    if len(context["features"]) != 21 or any(f["properties"].get("fishing_target") is not False for f in context["features"]):
        raise ValueError("The pinned historical context changed")
    context["all_source_outline_count"] = len(context["features"])
    context["selection_min_display_area_m2"] = 2500
    context["features"] = [feature for feature in context["features"] if feature["properties"]["approx_display_area_m2"] >= 2500]
    if len(context["features"]) != 4:
        raise ValueError("Larger historical context count changed")
    to_native = Transformer.from_crs("EPSG:4326", "EPSG:26910", always_xy=True).transform
    to_map = Transformer.from_crs("EPSG:26910", "EPSG:4326", always_xy=True).transform
    for feature in context["features"]:
        properties = feature["properties"]
        original = transform(to_native, shape(feature["geometry"]))
        display = original.buffer(-3).simplify(2, preserve_topology=True)
        if display.is_empty or display.geom_type not in {"Polygon", "MultiPolygon"} or not original.covers(display):
            raise ValueError("Inward display simplification changed original extent")
        geometry = transform(to_map, display)
        feature["geometry"] = mapping(geometry)
        bounds = list(geometry.bounds)
        properties.update({"name": "Historical hard-bottom research · " + properties["survey_id"],
                           "habitat_kind": "rock", "species_ids": ["reef"],
                           "source_url": properties["usgs_metadata_urls"][0],
                           "source_date": properties["survey_dates"][-1][:10],
                           "area_km2": round(display.area / 1_000_000, 6),
                           "bounds": bounds,
                           "vertical_datum": "MLLW (original NOAA BAG)",
                           "depth_note": "A survey-component depth range is known, but no outline-specific cell distribution or route survey is established.",
                           "limitations": "Historical 2008 seabed class and soundings; no current chart, route, local military access, fish presence or present catch evidence.",
                           "depth_qualified": False, "fishing_export": False,
                           "display_note": "Historical original-grid research outline; not a fishing mark or route."})
    context["region_id"] = ID
    write(f"dist/{prefix}/survey-habitat.geojson", context)


if __name__ == "__main__":
    build()
