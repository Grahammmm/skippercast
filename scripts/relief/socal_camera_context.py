"""Report geography context for the existing Southern California review cameras.

Run with ``python -m scripts.relief.socal_camera_context`` from the repo root.
Contributors are child region IDs whose configured bounds contain the camera
center (edges included). A hit grants neither a separate release nor source
clearance; the release ID stays Southern California's for every camera.
"""

import argparse
import json
from pathlib import Path
from typing import cast

from skippercast.paths import repo_root
from skippercast.platform.contracts import bbox
from skippercast.relief import render_config
from skippercast.relief.package import decode_document

RELEASE_ID = "southern-california"
CHILD_IDS = ("channel-islands-north", "outer-islands-borderland", "san-diego")


def _child_bounds(regions: Path, child_id: str) -> list[float]:
    path = regions / child_id / "region.json"
    region = decode_document(path.read_bytes())
    if region.get("id") != child_id:
        raise ValueError(f"Region directory and id differ for {child_id}")
    return bbox(region.get("bounds"))


def camera_context() -> dict:
    """Read the config projection without rendering or writing artifacts."""
    regions = repo_root() / "regions"
    recipe = regions / RELEASE_ID / "render.json"
    if not recipe.is_file():
        # The general previews loader can synthesize a default; review cannot.
        raise FileNotFoundError(f"Expected configured render recipe: {recipe}")
    cameras = render_config.previews(RELEASE_ID)
    bounds = [(child_id, _child_bounds(regions, child_id)) for child_id in CHILD_IDS]
    rows = []
    for camera in cameras:
        lon, lat = cast(list[float], camera["center"])
        contributors = [
            child_id
            for child_id, (west, south, east, north) in bounds
            if west <= lon <= east and south <= lat <= north
        ]
        rows.append({**camera, "contributors": contributors})
    return {"release_id": RELEASE_ID, "cameras": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report SoCal camera context (geography only, not release or source clearance)."
    )
    parser.parse_args(argv)
    print(json.dumps(camera_context(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
