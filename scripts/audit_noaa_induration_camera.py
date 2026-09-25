"""Sample NOAA's 2017 West Coast substrate composite at original camera records.

One actual camera observation per distinct qualifying transect is a bounded
source-delivery and agreement check. It is not a fishing-spot generator.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from scripts.audit_usgs_video_observations import first_field, load_archive, open_original_zip, sector_for


SERVICE = "https://maps.fisheries.noaa.gov/server/rest/services/WestCoast/USWestCoast_SeafloorInduration_v2017/MapServer"
CLASSES = {1: "hard", 2: "mixed", 3: "soft"}
QUALITY_VALUES = {10, 19, 24, 33, 43, 57, 62, 71, 86, 100}
# Three raster cells were matched to the publisher's rendered legend on 2026-09-24.
# They are source-code probes, not fishing positions or habitat claims.
CLASS_PROBES = ((-123.7312, 38.9085, "hard"),
                (-123.7315975, 38.9094475, "mixed"),
                (-123.7307075, 38.9094475, "soft"))


def fetch_json(url):
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "maps.fisheries.noaa.gov":
        raise ValueError("NOAA substrate request left the reviewed publisher host")
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast source audit/1.0"}), timeout=30) as response:
        if urlparse(response.url).scheme != "https" or urlparse(response.url).hostname != "maps.fisheries.noaa.gov":
            raise ValueError("NOAA substrate response redirected away from publisher")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Oversized NOAA substrate response")
    value = json.loads(raw)
    if "error" in value:
        raise ValueError(f"NOAA substrate service error: {value['error']}")
    return value, hashlib.sha256(raw).hexdigest()


def validate_service(metadata, legend):
    layers = {item["id"]: item["name"] for item in metadata.get("layers", [])}
    if (metadata.get("mapName") != "U.S. West Coast Seafloor Induration (v.2017)"
            or layers.get(0) != "Induration (hard, mixed, soft)" or layers.get(2) != "Data Quality"):
        raise ValueError("NOAA substrate service identity changed")
    labels = {item["layerId"]: [entry["label"] for entry in item["legend"]]
              for item in legend.get("layers", [])}
    if labels.get(0) != ["hard", "mixed", "soft"] or labels.get(2) != ["1.0", "1.9", "2.4", "3.3", "4.3", "5.7", "6.2", "7.1", "8.6", "10.0"]:
        raise ValueError("NOAA substrate class or quality legend changed")


def representative_records(audit):
    if (audit.get("scope") != "statewide-original-camera-regular-bag-discovery-review"
            or audit.get("fishing_target") is not False or audit.get("exportable") is not False):
        raise ValueError("Exact historical camera/BAG source review required")
    groups = defaultdict(set)
    archive_sha = {}
    for row in audit["pair_reviews"]:
        cruise, digest = row["cruise"], row["camera_archive_sha256"]
        if cruise in archive_sha and archive_sha[cruise] != digest:
            raise ValueError("Camera archive digest changed across BAG pairs")
        archive_sha[cruise] = digest
        for transect in row["transects"]:
            key = (cruise, transect["date"], transect["line"])
            indices = transect["camera_record_indices"]
            if len(indices) != transect["window_count"]:
                raise ValueError("Original camera record indices are incomplete")
            groups[key].update(indices)
    return [(cruise, day, line, sorted(indices)[len(indices) // 2])
            for (cruise, day, line), indices in sorted(groups.items())], archive_sha


def parse_identify(response):
    found = {}
    for item in response.get("results", []):
        layer = item["layerId"]
        if layer in found:
            raise ValueError("Duplicate NOAA substrate layer in one identify response")
        if layer in {0, 2}:
            found[layer] = int(item["attributes"]["Raster.Value"])
    if not found:
        return None
    if set(found) != {0, 2} or found[0] not in CLASSES or found[2] not in QUALITY_VALUES:
        raise ValueError("Unrecognized NOAA substrate class or data-quality value")
    return {"induration_code": found[0], "induration": CLASSES[found[0]],
            "data_quality_code": found[2], "data_quality_of_10": found[2] / 10}


def identify_url(lon, lat):
    if not (-125 <= lon <= -117 and 32 <= lat <= 42.1):
        raise ValueError("Camera position is outside California source review")
    query = {"geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}, separators=(",", ":")),
             "geometryType": "esriGeometryPoint", "sr": "4326", "layers": "all:0,2",
             "tolerance": "0", "mapExtent": f"{lon-.01},{lat-.01},{lon+.01},{lat+.01}",
             "imageDisplay": "800,800,96", "returnGeometry": "false", "f": "json"}
    return SERVICE + "/identify?" + urlencode(query)


def verify_class_codes(fetch):
    checked = []
    for lon, lat, expected in CLASS_PROBES:
        result, digest = fetch(identify_url(lon, lat))
        parsed = parse_identify(result)
        if parsed is None or parsed["induration"] != expected:
            raise ValueError("NOAA induration pixel codes no longer match the reviewed legend")
        checked.append({"expected_class": expected, "response_sha256": digest})
    return checked


def audit_samples(source, manifest, cache, sectors, *, fetch=fetch_json):
    reps, archive_sha = representative_records(source)
    metadata, metadata_sha = fetch(SERVICE + "?f=pjson")
    legend, legend_sha = fetch(SERVICE + "/legend?f=pjson")
    validate_service(metadata, legend)
    code_probes = verify_class_codes(fetch)
    readers = {}
    rows = []
    for cruise, day, line, index in reps:
        if cruise not in readers:
            raw = load_archive(cache, cruise, manifest["archives"][cruise], manifest["base_url"], False)
            if hashlib.sha256(raw).hexdigest() != archive_sha[cruise]:
                raise ValueError("Original camera archive does not match reviewed pair")
            readers[cruise] = open_original_zip(raw)
        reader = readers[cruise]
        item = reader.shapeRecord(index)
        original = item.record.as_dict()
        observed = first_field(original, "STARTOFENT", "StartofEnt", "DATE", "Date", "Date_")
        observed_day = observed.isoformat() if isinstance(observed, date) else str(observed)[:10]
        if observed_day != day or str(first_field(original, "LINE", "Line")) != line or not item.shape.points:
            raise ValueError("Representative original camera record identity changed")
        lon, lat = item.shape.points[0]
        response, response_sha = fetch(identify_url(lon, lat))
        sample = parse_identify(response)
        rows.append({"cruise": cruise, "date": day, "line": line,
                     "camera_record_index": index, "sector_id": sector_for(lat, sectors),
                     "service_response_sha256": response_sha,
                     "status": "ok" if sample is not None else "no_data",
                     "sample": sample})
    kinds = Counter(row["sample"]["induration"] for row in rows if row["sample"])
    qualities = Counter(str(row["sample"]["data_quality_of_10"]) for row in rows if row["sample"])
    return {"schema_version": 1, "scope": "noaa-2017-induration-historical-camera-research-sample",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "service_url": SERVICE, "service_metadata_sha256": metadata_sha,
            "service_legend_sha256": legend_sha,
            "class_code_probe_receipts": code_probes,
            "camera_archive_sha256": dict(sorted(archive_sha.items())),
            "upstream_camera_review_sha256": hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "source_2017_cell_m": 25,
            "sampling_method": "One exact original USGS camera record, chosen by the middle sorted record index, from each distinct qualifying dated transect; record IDs are deduplicated across NOAA BAG files. NOAA layer 0 induration and layer 2 source-data quality are sampled at that position. Three fixed publisher-map probe cells check the reviewed class-code mapping on every run.",
            "sampled_transects": len(rows), "class_counts": dict(kinds),
            "quality_counts": dict(sorted(qualities.items(), key=lambda item: float(item[0]))),
            "rows": rows,
            "limitations": ["The sampled camera record does not classify its whole transect or nearby unsampled water.",
                            "This 2017 composite is a 25 m synthesis of older, mixed-quality inputs, not a new 2026 survey or an independent measurement where it reuses USGS/NOAA sources.",
                            "Data quality is the source's 1–10 classification score, not SkipperCast fishing quality or a catch probability.",
                            "Historical camera position uncertainty is on the order of 10 m; a single 25 m composite cell may disagree at a boundary.",
                            "No fishing target, waypoint, drift or bottom-rock image may be published from this sample alone."],
            "fishing_target": False, "exportable": False}


def audit_qualified_context(context, context_bytes, reconciliation, chart_screen, *, fetch=fetch_json):
    """Cross-check original-grid-screened camera windows against NOAA classes.

    Keep input coordinates in the private review cache. The public result has
    only evidence IDs and aggregate classes, never new fishing coordinates.
    """
    expected = next((row['historical_camera_windows'] for row in reconciliation['comparison']
                     if row['nbs_status'] == 'locally_qualified_90pct'
                     and row['original_bag_status'] == 'original_locally_qualified_90pct'), None)
    survey = reconciliation['original_survey_id']
    features = context.get('features', [])
    if (context.get('scope') != 'unpublished-historical-camera-window-research'
            or context.get('fishing_target') is not False or context.get('exportable') is not False
            or reconciliation.get('fishing_target') is not False
            or chart_screen.get('survey_id') != survey
            or chart_screen.get('candidate_research_context_sha256') != hashlib.sha256(context_bytes).hexdigest()
            or chart_screen.get('original_grid_qualified_historical_camera_windows_checked') != expected
            or not isinstance(expected, int) or expected < 1 or len(features) != expected):
        raise ValueError('Original-grid camera context or pinned chart receipt changed')
    metadata, metadata_sha = fetch(SERVICE + '?f=pjson')
    legend, legend_sha = fetch(SERVICE + '/legend?f=pjson')
    validate_service(metadata, legend)
    probes = verify_class_codes(fetch)
    rows = []
    for feature in features:
        props = feature.get('properties', {})
        if (feature.get('geometry', {}).get('type') != 'Point' or props.get('survey_id') != survey
                or props.get('fishing_target') is not False or props.get('exportable') is not False):
            raise ValueError('Unreviewed camera research feature')
        lon, lat = feature['geometry']['coordinates']
        response, digest = fetch(identify_url(lon, lat))
        sample = parse_identify(response)
        if sample is None:
            raise ValueError('A qualified camera window has no NOAA substrate value')
        rows.append({'source_window_id': props['id'], 'sample': sample,
                     'response_sha256': digest})
    if len({row['source_window_id'] for row in rows}) != expected:
        raise ValueError('Duplicate camera research window')
    classes = Counter(row['sample']['induration'] for row in rows)
    qualities = Counter(str(row['sample']['data_quality_of_10']) for row in rows)
    return {'schema_version': 1,
            'scope': 'original-bag-camera-versus-noaa-2017-induration-research',
            'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'survey_id': survey, 'source_context_sha256': hashlib.sha256(context_bytes).hexdigest(),
            'source_reconciliation_sha256': hashlib.sha256(json.dumps(reconciliation, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'service_url': SERVICE, 'service_metadata_sha256': metadata_sha,
            'service_legend_sha256': legend_sha, 'class_code_probe_receipts': probes,
            'camera_windows_checked': expected, 'source_2017_cell_m': 25,
            'class_counts': dict(classes),
            'quality_counts': dict(sorted(qualities.items(), key=lambda item: float(item[0]))),
            'rows': rows, 'fishing_target': False, 'exportable': False,
            'limitations': [
                'Camera windows on one historical transect are correlated observations, not separate fishing spots.',
                'The 2017 25 m composite may reuse the same sonar or video source and is not necessarily independent measurement.',
                'NOAA source quality is not SkipperCast fishing quality, fish presence or catch probability.',
                'Cell boundaries and historical camera position error can change a point classification.',
                'Original survey holidays, charted and uncharted hazards, complete closures, local rules and approach remain unqualified.'
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=Path("dist/data/noaa-statewide-regular-camera-review.json"))
    parser.add_argument("--manifest", type=Path, default=Path("catalog/usgs-video-cruises.json"))
    parser.add_argument("--sectors", type=Path, default=Path("catalog/coastal-sectors.json"))
    parser.add_argument("--camera-cache", type=Path, default=Path("var/usgs-video-cache"))
    parser.add_argument("--output", type=Path, default=Path("dist/data/noaa-induration-camera-review.json"))
    parser.add_argument("--qualified-context", type=Path,
                        help="Private original-grid-qualified camera GeoJSON for a bounded source review")
    parser.add_argument("--reconciliation", type=Path)
    parser.add_argument("--chart-screen", type=Path)
    args = parser.parse_args()
    if args.qualified_context:
        if not args.reconciliation or not args.chart_screen:
            raise ValueError('Qualified context needs reconciliation and chart receipts')
        raw = args.qualified_context.read_bytes()
        result = audit_qualified_context(json.loads(raw), raw,
                   json.loads(args.reconciliation.read_text()), json.loads(args.chart_screen.read_text()))
    else:
        if args.reconciliation or args.chart_screen:
            raise ValueError('Reconciliation and chart receipts require a qualified context')
        result = audit_samples(json.loads(args.review.read_text()), json.loads(args.manifest.read_text()),
                               args.camera_cache, json.loads(args.sectors.read_text())["sectors"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result.get("sampled_transects", result.get("camera_windows_checked")),
          "historical camera records sampled;", result["class_counts"])


if __name__ == "__main__":
    main()
