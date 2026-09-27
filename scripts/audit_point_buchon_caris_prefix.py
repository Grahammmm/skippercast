#!/usr/bin/env python3
"""Inspect bounded original CARIS archive prefixes for datum and error leads.

The original projects are multi-gigabyte gzip tarballs. An 8 MiB byte-range
can verify their first project definition and early members, but cannot inventory
all members or establish the released GSF/USGS vertical datum or total error.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
import zlib


PREFIX_SIZE = 8 * 1024 * 1024
ARCHIVES = {
    "PointBuchon": {
        "url": "https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/Point_Buchon/multibeam/data/version2/ancillary/Point_Buchon_caris.tar.gz",
        "total_bytes": 3593471369,
        "prefix_sha256": "c022c4d9f8d7b51d3dfb2b5627298acf8c2eed98d0d279389d8351a1076217a8",
    },
    "PointBuchon_Control": {
        "url": "https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/Point_Buchon_Control/multibeam/data/version2/ancillary/Point_Buchon_Cntrl_caris.tar.gz",
        "total_bytes": 5117036653,
        "prefix_sha256": "df01ebb5872bffe6b15c006149d864625439ad270b95c409dfa9915e4e9be5a6",
    },
}


def fetch_prefix(url, total_bytes):
    request = Request(url, headers={"Range": f"bytes=0-{PREFIX_SIZE-1}",
                                    "User-Agent": "Mozilla/5.0 (SkipperCast source audit)"})
    with urlopen(request, timeout=90) as response:
        content_range = response.headers.get("Content-Range", "")
        body = response.read(PREFIX_SIZE + 1)
        status = response.status
    if (status != 206 or content_range != f"bytes 0-{PREFIX_SIZE-1}/{total_bytes}"
            or len(body) != PREFIX_SIZE):
        raise ValueError("Original NCEI CARIS bounded byte range changed")
    return body


def inspect_prefix(compressed, expected_sha):
    if len(compressed) != PREFIX_SIZE or hashlib.sha256(compressed).hexdigest() != expected_sha:
        raise ValueError("Original NCEI CARIS prefix bytes changed")
    decompressor = zlib.decompressobj(31)
    data = decompressor.decompress(compressed, 50_000_001)
    if len(data) > 50_000_000 or decompressor.unconsumed_tail:
        raise ValueError("Original NCEI CARIS prefix expansion exceeds reviewed size")
    entries, project_text, offset = [], None, 0
    while offset + 512 <= len(data):
        header = data[offset:offset + 512]
        if not header.strip(b"\0"):
            break
        name = header[:100].split(b"\0", 1)[0].decode("ascii")
        try:
            size = int(header[124:136].strip(b"\0 ") or b"0", 8)
        except ValueError as exc:
            raise ValueError("Original NCEI CARIS tar member size changed") from exc
        if size < 0 or size > 200_000_000:
            raise ValueError("Original NCEI CARIS tar member exceeds reviewed size")
        content_start = offset + 512
        if name.endswith(".hpf") and project_text is None:
            if size > 5000 or content_start + size > len(data):
                raise ValueError("Original NCEI CARIS project definition unavailable")
            project_text = data[content_start:content_start + size].decode("ascii")
        entries.append({"member": name, "declared_bytes": size})
        offset = content_start + ((size + 511) // 512) * 512
    if not project_text:
        raise ValueError("Original NCEI CARIS prefix lacks project definition")
    match = re.search(r"^PROJECTION\s*=\s*(\S+)", project_text, re.M)
    if not match or match.group(1) != "AUTO_UTM,WG84_10N":
        raise ValueError("Original NCEI CARIS project frame changed")
    return {"project_definition_projection": match.group(1),
            "project_definition_sha256": hashlib.sha256(project_text.encode()).hexdigest(),
            "complete_tar_headers_visible_in_prefix": len(entries),
            "tpe_member_names_visible_in_prefix": [item["member"] for item in entries
                                                   if item["member"].endswith("/TPE")],
            "tide_member_names_visible_in_prefix": [item["member"] for item in entries
                                                    if item["member"].endswith("/Tide")],
            "prefix_not_complete_archive": True}


def audit(fetcher=fetch_prefix):
    surveys = []
    for name, spec in ARCHIVES.items():
        prefix = fetcher(spec["url"], spec["total_bytes"])
        surveys.append({"survey_id": name, "source_url": spec["url"],
                        "archive_total_bytes": spec["total_bytes"],
                        "inspected_compressed_prefix_bytes": PREFIX_SIZE,
                        "compressed_prefix_sha256": spec["prefix_sha256"],
                        **inspect_prefix(prefix, spec["prefix_sha256"])})
    return {"schema_version": 1, "scope": "point-buchon-2007-original-caris-prefix-acquisition-lead",
            "surveys": surveys, "qualified_waypoints": 0, "fishing_target": False,
            "exportable": False,
            "limitation": "The bounded compressed prefixes show project definitions and a few early tar members only. WGS84 UTM is a horizontal project frame, not a vertical datum. A visible TPE member is an undecoded binary and does not prove total uncertainty for the selected GSF line or later USGS raster. Obtain a targeted custodian extract or process the full CARIS projects before depth qualification."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(audit(), indent=2) + "\n"
    if args.verify and args.verify.read_text() != encoded:
        raise SystemExit("Point Buchon original CARIS prefix changed; review before using")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded)


if __name__ == "__main__":
    main()
