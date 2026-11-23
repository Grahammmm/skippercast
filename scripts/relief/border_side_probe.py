#!/usr/bin/env python3
"""Compare known synthetic point memberships against a local boundary GeoJSON.

This checks geometry only, not jurisdiction or the provenance of the input.
"""

import argparse
from pathlib import Path

from shapely.geometry import Point

from skippercast.relief import border


def main(argv: list[str] | None = None) -> int:
    """Report every expected and observed membership; return 1 on a mismatch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("boundary", type=Path, help="bare Polygon or MultiPolygon GeoJSON")
    outcomes = ("inside", "outside", "on-edge")
    for outcome in outcomes:
        parser.add_argument(f"--{outcome}", action="append", type=float, nargs=2,
                            metavar=("LON", "LAT"), default=[], help="expected membership (repeatable)")
    args = parser.parse_args(argv)
    probes = [(outcome, lon, lat) for outcome in outcomes
              for lon, lat in getattr(args, outcome.replace("-", "_"))]
    if not probes:
        parser.error("supply at least one probe with --inside, --outside or --on-edge")
    if any(not (-180 <= lon <= 180 and -90 <= lat <= 90) for _, lon, lat in probes):
        parser.error("probes must be WGS84 longitude/latitude pairs")
    try:
        boundary, _ = border.load_boundary(args.boundary)
    except (border.BorderError, OSError) as exc:
        parser.exit(2, f"Cannot load boundary: {exc}\n")

    print("longitude\tlatitude\texpected\tobserved")
    all_match = True
    for expected, lon, lat in probes:
        point = Point(lon, lat)
        if boundary.touches(point):
            observed = "on-edge"  # Ambiguous: belongs to neither open side.
        elif boundary.contains(point):
            observed = "inside"
        else:
            observed = "outside"
        print(f"{lon}\t{lat}\t{expected}\t{observed}")
        all_match &= observed == expected
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
