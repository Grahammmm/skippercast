#!/usr/bin/env python3
"""Hold a changed Point Buchon research screen for review at monthly refresh."""

import argparse
import json
from pathlib import Path


FIELDS = ("scope", "grid_m", "review_margin_m", "cdfw_mpa_feature_count",
          "noaa_gea_feature_count", "noaa_enc_danger_feature_count",
          "noaa_enc_query_layers", "official_geometry_sha256", "totals",
          "qualified_waypoints", "fishing_target", "exportable")


def compare(reviewed, current):
    for row in (reviewed, current):
        if (row.get("fishing_target") is not False or row.get("exportable") is not False
                or row.get("qualified_waypoints") != 0):
            raise ValueError("Point Buchon research-only release gate changed")
    changed = [key for key in FIELDS if reviewed.get(key) != current.get(key)]
    if changed:
        raise ValueError("Point Buchon source or screening change needs review: " + ", ".join(changed))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed", type=Path,
                        default=Path("dist/data/point-buchon-rov-access-triage.json"))
    parser.add_argument("--current", type=Path, required=True)
    args = parser.parse_args()
    compare(json.loads(args.reviewed.read_text()), json.loads(args.current.read_text()))
    print("Point Buchon research block screen unchanged")


if __name__ == "__main__":
    main()
