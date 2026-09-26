#!/usr/bin/env python3
"""Fail monthly research refresh when source geometry or screen result changes."""

import argparse
import json
from pathlib import Path


FIELDS = ("scope", "grid_m", "review_margin_m", "depth_datum", "bands",
          "cdfw_feature_count", "noaa_gea_feature_count",
          "noaa_enc_query_layers", "noaa_enc_charted_danger_features",
          "official_geometry_sha256", "fishing_target", "exportable",
          "qualified_waypoints")


def compare(reviewed, current):
    if (reviewed.get("fishing_target") is not False
            or reviewed.get("exportable") is not False
            or current.get("fishing_target") is not False
            or current.get("exportable") is not False):
        raise ValueError("Estero research-only release gate changed")
    changed = [field for field in FIELDS if reviewed.get(field) != current.get(field)]
    if changed:
        raise ValueError("Estero source or screening change needs review: " + ", ".join(changed))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed", type=Path,
                        default=Path("dist/data/estero-2012-depth-class-closure-block-review.json"))
    parser.add_argument("--current", required=True, type=Path)
    args = parser.parse_args()
    compare(json.loads(args.reviewed.read_text()), json.loads(args.current.read_text()))
    print("Estero source geometry and research block screen unchanged")


if __name__ == "__main__":
    main()
