"""Audit original USGS DS 781 camera observations without promoting fishing spots.

The cruise logs contain time-stamped observations along survey transects. Their
fields vary by cruise, and the camera position has variable unknown accuracy.
This summary is for deciding where to review native evidence, not navigation.
"""

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

import shapefile
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely.strtree import STRtree


MAX_ARCHIVE_BYTES = 10_000_000
ROCK_CLASSES = {"rock", "boulder", "cobble"}


def load_archive(root, cruise, expected_sha, base_url, download):
    filename = f"{cruise}_video_observations.zip"
    path = root / filename
    if not path.exists():
        if not download:
            raise FileNotFoundError(f"Missing {path}; rerun with --download-missing")
        request = Request(base_url + filename, headers={"User-Agent": "SkipperCast source audit/1.0"})
        with urlopen(request, timeout=30) as response:
            if response.url != base_url + filename:
                raise ValueError(f"Unexpected redirect for {filename}: {response.url}")
            raw = response.read(MAX_ARCHIVE_BYTES + 1)
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise ValueError(f"Oversized original archive: {filename}")
        root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    raw = path.read_bytes()
    if len(raw) > MAX_ARCHIVE_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError(f"Original archive size/hash mismatch: {filename}")
    return raw


def open_original_zip(raw):
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        files = archive.namelist()
        shp = next(name for name in files if name.lower().endswith(".shp"))
        base = shp[:-4]
        suffixes = {name.lower(): name for name in files}

        def entry(ext):
            return archive.read(suffixes[(base + ext).lower()])

        projection = entry(".prj").decode("utf-8", errors="replace")
        if "WGS_1984" not in projection and "WGS 84" not in projection:
            raise ValueError("Unreviewed coordinate reference system")
        reader = shapefile.Reader(shp=BytesIO(entry(".shp")),
                                  shx=BytesIO(entry(".shx")),
                                  dbf=BytesIO(entry(".dbf")))
        return reader


def first_field(record, *names):
    for name in names:
        if name in record:
            return record[name]
    return None


def sector_for(lat, sectors):
    for sector in sectors:
        south, north = sector["latitude"]
        if south <= lat < north or lat == 42.0 and north == 42.0:
            return sector["id"]
    return None


def audit(manifest, sectors, cache, outlines, *, download=False, checked_at=None):
    checked_at = checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    transformer = Transformer.from_crs(4326, 32610, always_xy=True).transform
    polygons = [transform(transformer, shape(feature["geometry"]))
                for feature in outlines["features"]]
    tree = STRtree(polygons) if polygons else None
    by_sector = {s["id"]: Counter() for s in sectors}
    cruises = []
    cape = Counter()
    for cruise, expected_sha in sorted(manifest["archives"].items()):
        raw = load_archive(cache, cruise, expected_sha, manifest["base_url"], download)
        reader = open_original_zip(raw)
        field_names = {field.name for field in reader.fields[1:]}
        has_rockfish = bool(field_names & {"rockfish", "ROCKFISH"})
        has_lingcod = bool(field_names & {"lingcod", "LINGCOD"})
        counts = Counter()
        dates = []
        for item in reader.iterShapeRecords():
            if not item.shape.points:
                continue
            lon, lat = item.shape.points[0]
            if not (-125 <= lon <= -117 and 32.0 <= lat <= 42.1):
                raise ValueError(f"Out-of-range original camera position in {cruise}")
            row = item.record.as_dict()
            sector_id = sector_for(lat, sectors)
            scope = by_sector[sector_id] if sector_id else None
            for counter in (counts, scope):
                if counter is not None:
                    counter["records"] += 1
            date_value = first_field(row, "DATE", "Date", "Date_", "STARTOFENT", "StartofEnt")
            if isinstance(date_value, date):
                dates.append(date_value.isoformat())
            major = str(first_field(row, "MAJOR_GEO") or "").strip().lower()
            if not major:
                continue  # Transit/test/log entries are not seabed observations.
            rockfish = first_field(row, "rockfish", "ROCKFISH")
            lingcod = first_field(row, "lingcod", "LINGCOD")
            for counter in (counts, scope):
                if counter is None:
                    continue
                counter["bottom_observations"] += 1
                if major in ROCK_CLASSES:
                    counter["rock_boulder_cobble_observations"] += 1
                if has_rockfish:
                    counter["rockfish_field_observations"] += 1
                if isinstance(rockfish, (int, float)) and rockfish > 0:
                    counter["rockfish_positive_observations"] += 1
                if has_lingcod:
                    counter["lingcod_field_observations"] += 1
                if isinstance(lingcod, (int, float)) and lingcod > 0:
                    counter["lingcod_positive_observations"] += 1
            if tree and cruise == "c210nc":
                point = transform(transformer, Point(lon, lat))
                near = tree.query(point.buffer(250))
                if any(polygons[index].distance(point) <= 250 for index in near):
                    cape["bottom_observations_within_250m"] += 1
                if any(polygons[index].intersects(point) for index in near):
                    cape["bottom_observations_inside_display_outlines"] += 1
        cruises.append({
            "id": cruise,
            "source_url": manifest["base_url"] + f"{cruise}_video_observations.zip",
            "sha256": expected_sha,
            "bounds_wgs84": [round(float(v), 6) for v in reader.bbox],
            "first_observation_date": min(dates) if dates else None,
            "last_observation_date": max(dates) if dates else None,
            "has_rockfish_field": has_rockfish,
            "has_lingcod_field": has_lingcod,
            **dict(counts),
        })
    return {
        "schema_version": 1,
        "scope": "usgs-ds781-statewide-original-video-audit",
        "checked_at": checked_at,
        "catalog_url": manifest["catalog_url"],
        "position_caveat": "USGS describes horizontal camera positions as highly variable, on the order of 10 meters. Counts are dated transect evidence, not verified fishing spots or proof that adjacent unsampled seabed has the same habitat.",
        "species_caveat": "Positive rockfish/lingcod codes are historical visual observations, not catch, abundance, current presence, or permission to fish.",
        "sector_caveat": "Latitude-band assignments are a discovery index, not verified survey coverage throughout a sector.",
        "fishing_target": False,
        "exportable": False,
        "cruises": cruises,
        "sectors": [{"id": s["id"], **dict(by_sector[s["id"]])} for s in sectors],
        "cape_mendocino_outline_check": {
            "source_cruise": "c210nc",
            "display_outline_count": len(polygons),
            "radius_m": 250,
            "bottom_observations_within_250m": cape["bottom_observations_within_250m"],
            "bottom_observations_inside_display_outlines": cape["bottom_observations_inside_display_outlines"],
            **dict(cape),
            "video_verified_outlines": 0,
            "reason": "No direct camera overlap was found; near matches would require a position-accuracy review before attribution.",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("catalog/usgs-video-cruises.json"))
    parser.add_argument("--sectors", type=Path, default=Path("catalog/coastal-sectors.json"))
    parser.add_argument("--cache", type=Path, default=Path("var/usgs-video-cache"))
    parser.add_argument("--outlines", type=Path, default=Path("dist/data/cape-mendocino-native-hard-context.geojson"))
    parser.add_argument("--output", type=Path, default=Path("dist/data/usgs-video-observation-audit.json"))
    parser.add_argument("--download-missing", action="store_true")
    args = parser.parse_args()
    result = audit(json.loads(args.manifest.read_text()),
                   json.loads(args.sectors.read_text())["sectors"], args.cache,
                   json.loads(args.outlines.read_text()), download=args.download_missing)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Audited {len(result['cruises'])} original cruises, {sum(x.get('records', 0) for x in result['cruises'])} records")


if __name__ == "__main__":
    main()
