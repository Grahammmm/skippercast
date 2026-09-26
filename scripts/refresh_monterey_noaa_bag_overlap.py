#!/usr/bin/env python3
"""Recheck exact Monterey BAG non-overlap against pinned official source bytes."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.audit_monterey_noaa_bag_overlap import audit
from skippercast.platform.bottom_targets import source_url_allowed


def download(binding, target):
    url = binding["bag_url"]
    if not source_url_allowed(url) or f"/{binding['survey_id']}/BAG/" not in url:
        raise ValueError("Unreviewed NOAA BAG source")
    request = Request(url, headers={"User-Agent": "SkipperCast original BAG source review"})
    with urlopen(request, timeout=60) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("BAG source status or redirect changed")
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with target.open("wb") as output:
            while chunk := response.read(1_048_576):
                size += len(chunk)
                if size > 30_000_000:
                    raise ValueError("BAG source exceeds bounded review size")
                output.write(chunk)
                digest.update(chunk)
    if digest.hexdigest() != binding["bag_sha256"]:
        raise ValueError("Original NOAA BAG bytes changed; review required")
    return size


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--output", type=Path, default=Path("var/review/monterey-bag-overlap"))
    args = p.parse_args()
    root = args.root
    bindings = json.loads((root / "catalog/monterey-original-bag-overlap-bindings.json").read_text())
    context_path = root / "dist/data/usgs-offshore-monterey-hard-context.geojson"
    pixel_path = root / "dist/data/monterey-original-300-pixel-review.json"
    context = json.loads(context_path.read_text())
    pixel = json.loads(pixel_path.read_text())
    if (bindings.get("schema_version") != 1
            or bindings.get("claim") != "no-measured-native-cells-inside-these-17-outlines"
            or len(bindings.get("bindings", [])) != 4):
        raise ValueError("Unreviewed Monterey BAG overlap contract")
    ids = set()
    for binding in bindings["bindings"]:
        sid = binding["survey_id"]
        if sid in ids or sid not in {"W00431", "W00433", "W00444", "W00447"}:
            raise ValueError("Duplicate or unexpected original BAG")
        ids.add(sid)
        bag = args.output / (sid + ".bag")
        download(binding, bag)
        report = audit(bag, sid, binding["bag_url"], binding["bag_sha256"], context, pixel)
        report["context_sha256"] = hashlib.sha256(context_path.read_bytes()).hexdigest()
        report["pixel_review_sha256"] = hashlib.sha256(pixel_path.read_bytes()).hexdigest()
        published = json.loads((root / binding["review_path"]).read_text())
        compared = ("file_sha256", "context_sha256", "pixel_review_sha256", "outline_count",
                    "outlines_with_measured_cells", "measured_native_cells_inside_research_outlines",
                    "nominal_200_300ft_cells_below_cap_with_uncertainty_margin_inside_research_outlines",
                    "outlines")
        if any(report[key] != published[key] for key in compared):
            raise ValueError(f"{sid} original measured-cell overlap changed; review required")
        output = args.output / (sid + "-fresh-overlap.json")
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{sid}: original BAG source and zero-overlap result unchanged")


if __name__ == "__main__":
    main()
