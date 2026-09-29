#!/usr/bin/env python3
"""Pin one complete original BSS03 CARIS TPE line from a bounded archive read.

The member is proprietary HDCS and has not been converted to sounding or
grid uncertainty. This audit proves availability and lineage only.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import Request, urlopen

from research.scripts.audit_bss03_caris_acquisition import URL


PREFIX_BYTES = 67_108_864
ARCHIVE_SIZE = 42_090_312_342
MEMBER = "BSS_Block03/45HaroldHeath_PPK/2011-277/20111004_140647_Harold_Heath7125/TPE"
OUTPUT = Path("research/receipts/bss03-caris-original-tpe-member-lead.json")


def fetch():
    with urlopen(Request(URL, headers={"User-Agent": "SkipperCast survey audit/1.0",
                                       "Range": f"bytes=0-{PREFIX_BYTES - 1}"}), timeout=180) as response:
        if response.status != 206 or response.headers.get("Content-Range") != f"bytes 0-{PREFIX_BYTES - 1}/{ARCHIVE_SIZE}":
            raise ValueError("BSS03 original CARIS archive range changed")
        raw = response.read(PREFIX_BYTES + 1)
    if len(raw) != PREFIX_BYTES:
        raise ValueError("BSS03 CARIS bounded range incomplete")
    return raw


def build(raw, prefix_bytes=PREFIX_BYTES, tpe_bytes=37_668_488):
    if len(raw) != prefix_bytes:
        raise ValueError("BSS03 CARIS bounded range length changed")
    member_bytes = None
    following_member = None
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r|gz") as archive:
            for member in archive:
                if member.name == MEMBER:
                    if member.size != tpe_bytes:
                        raise ValueError("BSS03 CARIS TPE size changed")
                    member_bytes = archive.extractfile(member).read(member.size + 1)
                    if len(member_bytes) != member.size:
                        raise ValueError("BSS03 CARIS TPE incomplete")
                elif member_bytes is not None:
                    following_member = member.name
                    break
    except (EOFError, OSError, tarfile.TarError) as exc:
        raise ValueError("BSS03 CARIS archive prefix ended before full TPE member") from exc
    if not member_bytes or not following_member or not member_bytes.startswith(b"HDCS"):
        raise ValueError("BSS03 CARIS TPE member or following TAR header missing")
    return {
        "schema_version": 1,
        "scope": "bss03-original-caris-complete-single-line-tpe-member",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "archive_url": URL,
        "full_archive_bytes": ARCHIVE_SIZE,
        "bounded_prefix_bytes": PREFIX_BYTES,
        "bounded_prefix_sha256": hashlib.sha256(raw).hexdigest(),
        "complete_tpe_member": MEMBER,
        "tpe_line_date_from_member_path": "2011-10-04",
        "released_grid_metadata_survey_dates": ["2011-11-03", "2011-11-04", "2011-11-14", "2011-11-15", "2011-12-08"],
        "tpe_line_date_matches_released_grid_metadata_dates": False,
        "tpe_member_bytes": len(member_bytes),
        "tpe_member_sha256": hashlib.sha256(member_bytes).hexdigest(),
        "tpe_magic": "HDCS",
        "following_member_header": following_member,
        "official_export_documentation_url": "https://docs.teledynecaris.com/docs/8.0/hips%20and%20sips/CARIS%20HIPS%20and%20SIPS%20Help/CARISBatch_HIPS.42.18.html",
        "tpe_values_decoded": False,
        "tpe_confidence_or_units_verified": False,
        "tpe_to_released_grid_lineage_verified": False,
        "grid_cell_upper_uncertainty_verified": False,
        "mllw_depth_qualified": False,
        "fishing_target": False,
        "exportable": False,
        "limitations": "One complete per-line HDCS TPE member is present near the beginning of the 42 GB official CARIS archive. Its path dates to October 4, 2011, whereas released Block 03 grid metadata list November and December survey dates; the line is not shown to contribute to that grid. It has not been decoded into sounding TPU values, mapped to accepted depth soundings, or shown to include a full tide/datum uncertainty bound. A complete single line does not cover a candidate patch. CARIS ExportHIPS can export DEPTH_TPU and POSITION_TPU, but an actual licensed export from contributing lines and source-to-grid crosswalk are still needed.",
    }


def stable(report):
    return {k: v for k, v in report.items() if k != "checked_at"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes() if args.input else fetch()
    report = build(raw)
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit("BSS03 CARIS TPE member changed; review before promotion")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Complete CARIS TPE member: {report['tpe_member_bytes']} bytes; decoding still required")


if __name__ == "__main__":
    main()
