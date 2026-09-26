#!/usr/bin/env python3
"""Fetch official CDFW MPA polygons over the Point Buchon research envelope."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.prepare_regional_mpas import source_url, validate_response


BOUNDS = [-121.02, 35.10, -120.79, 35.33]
EXPECTED = {"Morro Bay SMRMA", "Point Buchon SMCA", "Point Buchon SMR"}


def collect():
    url = source_url(BOUNDS)
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast Point Buchon MPA research review"}), timeout=45) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("Official CDFW MPA query failed or redirected")
        raw = response.read(6_000_001)
    if not raw or len(raw) > 6_000_000:
        raise ValueError("Official CDFW MPA response is empty or oversized")
    result = json.loads(raw)
    features = validate_response(result, BOUNDS, len(EXPECTED))
    if {row["properties"]["NAME"] for row in features} != EXPECTED:
        raise ValueError("Official Point Buchon MPA identity set changed")
    result.update(source_url=url, checked_at=datetime.now(timezone.utc).isoformat(),
                  verification_sha256=hashlib.sha256(raw).hexdigest(),
                  status="research-closure-screen-only")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = (Path(__file__).resolve().parents[1] / "var/review").resolve()
    output = args.output.resolve()
    if not output.is_relative_to(root):
        raise ValueError("Point Buchon raw MPA review must stay under var/review")
    report = collect()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(f"CDFW Point Buchon research MPAs: {len(report['features'])}")


if __name__ == "__main__":
    main()
