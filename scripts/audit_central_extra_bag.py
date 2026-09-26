#!/usr/bin/env python3
"""Replay one bounded original NOAA BAG inspection omitted by the earlier audit."""

import argparse
import hashlib
import json
from pathlib import Path

from scripts.inspect_noaa_bag_grids import download, inspect_file


def audit(pin, products, cache, fetch):
    survey = next((row for row in products["surveys"] if row["id"] == pin["survey_id"]), None)
    if (pin.get("schema_version") != 1 or survey is None
            or pin["source_url"] not in survey["products"]["bag"]
            or pin["source_bytes"] > 1_000_000):
        raise ValueError("Unreviewed NOAA source pin")
    path = cache / Path(pin["source_url"]).name
    if not path.is_file():
        if not fetch:
            raise FileNotFoundError(path)
        download(pin["source_url"], path, 1_000_000)
    if (path.stat().st_size != pin["source_bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != pin["source_sha256"]):
        raise ValueError("Pinned NOAA source changed")
    native = inspect_file(path, pin["survey_id"])
    return {
        "schema_version": 1,
        "scope": "original-noaa-f00844-fifth-bag-coverage-audit",
        "survey_id": pin["survey_id"],
        "source_url": pin["source_url"],
        "source_sha256": pin["source_sha256"],
        "source_bytes": pin["source_bytes"],
        "native": native,
        "fishing_target": False,
        "exportable": False,
        "limitations": "Original MLLW BAG overview has no refinements at or below 4 m; its 43 m grid cannot locate individual fishing rocks. Source metadata and native-cell overlap with substrate are separate gates.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=Path, default=Path("catalog/central-extra-bag-pin.json"))
    parser.add_argument("--products", type=Path, default=Path("dist/data/noaa-survey-products.json"))
    parser.add_argument("--cache", type=Path, default=Path("var/noaa-native-cache"))
    parser.add_argument("--output", type=Path, default=Path("dist/data/f00844-original-fifth-bag-review.json"))
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    result = audit(json.loads(args.pin.read_text()), json.loads(args.products.read_text()), args.cache, args.fetch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["survey_id"], result["native"]["refinement_grids_at_most_4m"])


if __name__ == "__main__":
    main()
