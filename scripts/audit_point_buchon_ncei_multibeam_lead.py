#!/usr/bin/env python3
"""Screen NCEI 2007 survey *catalog polygons* against original Point Buchon cells.

This only prioritizes acquisition of processed GSF soundings. A catalog polygon
does not establish populated soundings, their datum, uncertainty, or rights.
"""

import argparse
from collections import Counter
import gzip
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import struct
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from scripts.audit_point_buchon_original_pair import original_tiff


ROOT = Path(__file__).resolve().parents[1]
LAYER = "https://gis.ngdc.noaa.gov/arcgis/rest/services/multibeam_footprints/MapServer/0"
SURVEYS = {
    "PointBuchon": {"ids": {1732, 1733}, "ncei_id": "NEW2833"},
    "PointBuchon_Control": {"ids": {1734, 1735}, "ncei_id": "NEW2834"},
}
PROBES = {
    "PointBuchon": {
        "url": "https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/Point_Buchon/multibeam/data/version2/MB/reson8101/PB129-2245.gsf.mb121.gz",
        "sha256": "a3218f68647a8423bd395684044f88fc3b5ec19ab09e3bd4d87548f9d98efdb9",
        "inf_sha256": "b1ec6b1f308c47ab28157ecf4f037365e3caeb61424e5105f0ed84731e4bdb5c",
        "fnv_sha256": "b774793b4152d33306955ac1d5f3ae17f2f2633893ac0a2beb780a3050b96785",
    },
    "PointBuchon_Control": {
        "url": "https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/Point_Buchon_Control/multibeam/data/version2/MB/reson8101/MB299-1555.gsf.mb121.gz",
        "sha256": "a093e49ea552da7128e6e22b423b523f40c0bb29996fbab1214db04a09d664e8",
        "inf_sha256": "feafdf18577e67bf9068741e23c296a83f96169e2ac17a1b24b3a2d1abac0f52",
        "fnv_sha256": "a96a7b0e367b9e81d75999b03f1b1838059dc8f725f1cedfc2b8a3a206df3c10",
    },
}
LOWER_M, UPPER_M = 200 / 3.280839895, 300 / 3.280839895


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.words, self.links = [], []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.suppressed += 1
        if tag == "a":
            link = dict(attrs).get("href")
            if link:
                self.links.append(link)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.suppressed -= 1

    def handle_data(self, data):
        if not self.suppressed and data.strip():
            self.words.append(data.strip())

    @property
    def text(self):
        return re.sub(r"\s+", " ", " ".join(self.words))


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0 (SkipperCast source audit)"}), timeout=45) as response:
        limit = 20_000_000 if url.endswith(".gsf.mb121.gz") else 5_000_000
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("NCEI acquisition response exceeds reviewed size")
    return body


def catalog(fetcher=fetch):
    ids = sorted(set().union(*(spec["ids"] for spec in SURVEYS.values())))
    query = LAYER + "/query?" + urlencode({
        "where": "OBJECTID IN (" + ",".join(map(str, ids)) + ")",
        "outFields": "OBJECTID,NCEI_ID,SURVEY_ID,SURVEY_YEAR",
        "returnGeometry": "true", "outSR": "4326", "f": "json",
    })
    payload = json.loads(fetcher(query))
    features = payload.get("features")
    if not isinstance(features, list) or len(features) != len(ids) or payload.get("exceededTransferLimit"):
        raise ValueError("NCEI Point Buchon catalog result is incomplete")
    by_id = {}
    for feature in features:
        attr = feature.get("attributes", {})
        oid = attr.get("OBJECTID")
        if oid in by_id or oid not in ids or not feature.get("geometry", {}).get("rings"):
            raise ValueError("NCEI Point Buchon catalog geometry changed")
        by_id[oid] = feature
    for name, spec in SURVEYS.items():
        for oid in spec["ids"]:
            attr = by_id[oid]["attributes"]
            if (attr.get("SURVEY_ID") != name or attr.get("NCEI_ID") != spec["ncei_id"]
                    or attr.get("SURVEY_YEAR") != 2007):
                raise ValueError("NCEI Point Buchon catalog lineage changed")
    canonical = json.dumps([by_id[oid] for oid in ids], sort_keys=True, separators=(",", ":")).encode()
    return by_id, query, hashlib.sha256(canonical).hexdigest()


def archive_page(name, fetcher=fetch):
    page_url = f"https://www.ngdc.noaa.gov/ships/ventresca/{name}_mb.html"
    meta_url = ("https://www.ngdc.noaa.gov/metaview/page?xml=NOAA/NESDIS/NGDC/MGG/Multibeam/"
                f"iso/xml/{name}_Multibeam.xml&view=getDataView&header=none")
    page, metadata = Page(), Page()
    page.feed(fetcher(page_url).decode("utf-8", errors="replace"))
    metadata.feed(fetcher(meta_url).decode("utf-8", errors="replace"))
    gsf = [link.replace("http://", "https://", 1) for link in page.links if ".gsf.mb121.gz" in link]
    if len(gsf) < 50 or PROBES[name]["url"] not in gsf or "Vertical Datum: Unknown" not in metadata.text:
        raise ValueError("NCEI original archive listing or datum metadata changed")
    return {"page_url": page_url, "metadata_url": meta_url,
            "processed_gsf_link_count": len(gsf),
            "processed_gsf_first_url": sorted(gsf)[0],
            "metadata_vertical_datum": "Unknown",
            "archive_page_content_sha256": hashlib.sha256((page.text + "\n" + "\n".join(sorted(page.links))).encode()).hexdigest(),
            "metadata_content_sha256": hashlib.sha256(metadata.text.encode()).hexdigest()}


def parse_gsf_probe(compressed, expected_sha):
    if hashlib.sha256(compressed).hexdigest() != expected_sha or len(compressed) > 20_000_000:
        raise ValueError("Original NCEI GSF probe bytes changed or exceed reviewed size")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        data = source.read(80_000_001)
    if len(data) > 80_000_000:
        raise ValueError("NCEI GSF probe expansion exceeds reviewed size")
    offset, records, parameters = 0, Counter(), []
    while offset + 8 <= len(data):
        size, identifier = struct.unpack_from(">II", data, offset)
        kind = identifier & 0xFFF
        if (identifier & 0x80000000 or size > 10_000_000 or offset + 8 + size > len(data)
                or kind not in range(1, 13)):
            raise ValueError("NCEI GSF record header changed or is truncated")
        body = data[offset + 8:offset + 8 + size]
        records[kind] += 1
        if kind == 1 and (size != 12 or not body.startswith(b"GSF-v03.01")):
            raise ValueError("NCEI GSF version changed")
        if kind == 4:
            if len(body) < 10:
                raise ValueError("NCEI GSF processing record truncated")
            count = struct.unpack_from(">H", body, 8)[0]
            pos = 10
            for _ in range(count):
                if pos + 2 > len(body):
                    raise ValueError("NCEI GSF processing parameter truncated")
                length = struct.unpack_from(">H", body, pos)[0]
                pos += 2
                if pos + length > len(body):
                    raise ValueError("NCEI GSF processing parameter truncated")
                parameters.append(body[pos:pos + length].rstrip(b"\0").decode("ascii"))
                pos += length
        offset += 8 + size
    if offset != len(data) or records[1] != 1 or records[4] != 1 or records[2] < 1:
        raise ValueError("NCEI GSF probe is incomplete or has no pings/processing record")
    selected = [p for p in parameters if p.startswith(("TIDE_COMPENSATED=", "TIDAL_DATUM=", "GEOID="))]
    if sorted(selected) != sorted(("TIDE_COMPENSATED=YES", "TIDAL_DATUM=UNKNOWN", "GEOID=WGS-84")):
        raise ValueError("NCEI GSF datum or tide-processing parameters changed")
    return {"compressed_sha256": expected_sha, "gsf_version": "03.01",
            "swath_ping_records": records[2], "processing_parameters": selected,
            "datum_qualified": False}


def companion_urls(gsf_url):
    base = gsf_url.removesuffix(".gz")
    if base == gsf_url:
        raise ValueError("Unexpected GSF companion URL")
    return base.rsplit("/", 1)[0] + "/generated/" + base.rsplit("/", 1)[1] + ".inf", \
           base.rsplit("/", 1)[0] + "/generated/" + base.rsplit("/", 1)[1] + ".fnv"


def original_line_depth_range(data, expected_sha):
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError("Original NCEI generated line summary changed")
    match = re.search(rb"Minimum Depth:\s*([-\d.]+)\s+Maximum Depth:\s*([-\d.]+)", data)
    if not match:
        raise ValueError("Original NCEI generated line summary lacks depth range")
    lo, hi = map(float, match.groups())
    if not (0 <= lo <= UPPER_M and hi >= LOWER_M and hi >= lo):
        raise ValueError("NCEI selected line no longer spans nominal 200–300 ft")
    return {"inf_sha256": expected_sha, "minimum_depth_m_unknown_datum": lo,
            "maximum_depth_m_unknown_datum": hi}


def navigation_sample_cells(data, expected_sha, bathy, character):
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError("Original NCEI generated navigation changed")
    projector = Transformer.from_crs("EPSG:4326", bathy.crs, always_xy=True)
    cells, rows = set(), 0
    for line in data.decode("ascii").splitlines():
        values = line.split()
        if len(values) != 19:
            raise ValueError("Generated NCEI navigation row layout changed")
        port_lon, port_lat, star_lon, star_lat = map(float, values[15:19])
        if not (-121.2 < port_lon < -120.7 and -121.2 < star_lon < -120.7
                and 35.1 < port_lat < 35.4 and 35.1 < star_lat < 35.4):
            raise ValueError("Generated NCEI navigation outside reviewed Point Buchon bounds")
        rows += 1
        for fraction in (0, .25, .5, .75, 1):
            lon = port_lon * (1 - fraction) + star_lon * fraction
            lat = port_lat * (1 - fraction) + star_lat * fraction
            row, col = bathy.index(*projector.transform(lon, lat))
            if 0 <= row < bathy.height and 0 <= col < bathy.width:
                cells.add((row, col))
    if rows < 100 or not cells:
        raise ValueError("Generated NCEI swath navigation is incomplete")
    locations = [bathy.xy(row, col) for row, col in sorted(cells)]
    summary = {"no_paired_usgs_pixel": 0, "200_300ft_hard_flat": 0,
               "200_300ft_hard_rugose": 0, "200_300ft_soft_flat": 0,
               "outside_nominal_band": 0}
    for depth, kind in zip(bathy.sample(locations, masked=True), character.sample(locations, masked=True)):
        if np.ma.getmaskarray(depth)[0] or np.ma.getmaskarray(kind)[0]:
            summary["no_paired_usgs_pixel"] += 1
            continue
        if not LOWER_M <= -float(depth[0]) <= UPPER_M:
            summary["outside_nominal_band"] += 1
        else:
            label = {1: "soft_flat", 2: "hard_flat", 3: "hard_rugose"}.get(int(kind[0]))
            if label is None:
                raise ValueError("USGS seabed class changed")
            summary[f"200_300ft_{label}"] += 1
    return {"fnv_sha256": expected_sha, "navigation_rows": rows,
            "unique_usgs_pixels_at_five_interpolated_swath_positions_per_row": len(cells),
            "sampled_usgs_pixels_by_class": summary,
            "actual_gsf_beam_to_usgs_cell_overlap_verified": False}


def audit(bathy_zip, class_zip, fetcher=fetch):
    by_id, query, catalog_sha = catalog(fetcher)
    source = {name: archive_page(name, fetcher) for name in SURVEYS}
    probes = {name: parse_gsf_probe(fetcher(PROBES[name]["url"]), PROBES[name]["sha256"])
              for name in SURVEYS}
    line_ranges = {}
    navigation = {}
    for name in SURVEYS:
        inf_url, fnv_url = companion_urls(PROBES[name]["url"])
        line_ranges[name] = {"source_url": inf_url,
                             **original_line_depth_range(fetcher(inf_url), PROBES[name]["inf_sha256"])}
        navigation[name] = (fnv_url, fetcher(fnv_url))
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)
    footprints = {}
    for name, spec in SURVEYS.items():
        polygons = []
        for oid in spec["ids"]:
            for ring in by_id[oid]["geometry"]["rings"]:
                polygon = shape({"type": "Polygon", "coordinates": [ring]})
                if polygon.exterior.is_ccw:
                    raise ValueError("NCEI catalog polygon contains a hole or changed ring orientation")
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)
                polygons.append(transform(transformer.transform, polygon))
        footprints[name] = unary_union(polygons)
    counts = {name: {"nominal_usgs_200_300ft_hard_flat_cell_centers_in_catalog_polygon": 0,
                     "nominal_usgs_200_300ft_hard_rugose_cell_centers_in_catalog_polygon": 0}
              for name in SURVEYS}
    with rasterio.open(original_tiff(bathy_zip)) as bathy, rasterio.open(original_tiff(class_zip)) as character:
        if (bathy.shape != character.shape or bathy.transform != character.transform
                or str(bathy.crs) != "EPSG:32610"):
            raise ValueError("USGS Point Buchon original pair alignment changed")
        for _, window in bathy.block_windows(1):
            bounds = rasterio.windows.bounds(window, bathy.transform)
            possible = {name: geom for name, geom in footprints.items()
                        if geom.bounds[0] <= bounds[2] and geom.bounds[2] >= bounds[0]
                        and geom.bounds[1] <= bounds[3] and geom.bounds[3] >= bounds[1]}
            if not possible:
                continue
            d, c = bathy.read(1, window=window, masked=True), character.read(1, window=window, masked=True)
            dv, cv = np.ma.getdata(d), np.ma.getdata(c)
            valid = (~np.ma.getmaskarray(d) & ~np.ma.getmaskarray(c) & np.isfinite(dv)
                     & (-dv >= LOWER_M) & (-dv <= UPPER_M))
            if not np.any(valid & np.isin(cv, (2, 3))):
                continue
            affine = bathy.window_transform(window)
            for name, geom in possible.items():
                mask = geometry_mask([geom], out_shape=d.shape, transform=affine, invert=True)
                for code, label in ((2, "hard_flat"), (3, "hard_rugose")):
                    counts[name][f"nominal_usgs_200_300ft_{label}_cell_centers_in_catalog_polygon"] += int(
                        np.count_nonzero(valid & (cv == code) & mask))
        nav_screens = {name: {"source_url": navigation[name][0],
                              **navigation_sample_cells(navigation[name][1], PROBES[name]["fnv_sha256"],
                                                      bathy, character)}
                       for name in SURVEYS}
    return {"schema_version": 1, "scope": "point-buchon-2007-ncei-multibeam-acquisition-lead",
            "catalog_query_url": query, "catalog_geometry_sha256": catalog_sha,
            "usgs_original_bathymetry_sha256": "c825293fc999ad757b32ee2acefcae590690d451d12fd367b2f8b3e9e6d731d4",
            "usgs_original_character_sha256": "0a9579783e5318bfee0ebef8ede112f32c5a2202272338ae9eb1fd9e96df8bc1",
            "surveys": [{"survey_id": name, "ncei_id": spec["ncei_id"],
                         "catalog_feature_ids": sorted(spec["ids"]), **source[name], **counts[name]}
                        for name, spec in SURVEYS.items()],
            "processed_gsf_probes": probes,
            "selected_line_unknown_datum_depth_ranges": line_ranges,
            "selected_line_navigation_swath_screens": nav_screens,
            "limitation": "The two selected original processed GSF lines span nominal 200–300 ft and their generated swath navigation crosses original USGS hard/rugose pixels at sampled positions. Five interpolated points per navigation row are not actual valid sounding beams or complete coverage. NOAA ISO and these GSF processing records say tidal datum unknown despite tide compensation; the other archived lines remain unchecked. The USGS depth band also has unresolved output datum. No horizontal registration, product error, complete legal access, or fish catch odds are established.",
            "next_action": "Inspect original processed GSF sounding positions and processing lineage; obtain verified vertical datum, epoch and total uncertainty before any Point Buchon depth promotion.",
            "qualified_waypoints": 0, "fishing_target": False, "exportable": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bathy", type=Path, default=ROOT / "var/review/usgs-point-buchon/Bathymetry_OffshorePointBuchon.zip")
    parser.add_argument("--character", type=Path, default=ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = audit(args.bathy, args.character)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.verify and args.verify.read_text() != encoded:
        raise SystemExit("Point Buchon NCEI acquisition lead changed; review before using")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded)


if __name__ == "__main__":
    main()
