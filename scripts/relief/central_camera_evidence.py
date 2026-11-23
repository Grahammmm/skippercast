"""Identify a configured Central Coast camera recipe without rendering.

From the repo root: python -m scripts.relief.central_camera_evidence big-sur-coast

Each camera tuple is [id, longitude, latitude, size_m, zoom], in loader order.
The SHA-256 covers the other output fields as compact, key-sorted UTF-8 JSON
(no trailing newline; integral numbers use integer spelling). It identifies
only the review recipe, not a stage, a rendered image or a coverage verdict.
"""

import argparse
from hashlib import sha256
import json
from typing import TypedDict, cast

from skippercast.paths import repo_root
from skippercast.relief import render_config

from scripts.relief.central_camera_bounds import REGIONS


class _Preview(TypedDict):
    id: str
    center: list[int | float]
    size_m: int | float
    zoom: int | float


def _number(value: int | float) -> int | float:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('region', choices=REGIONS)
    region = parser.parse_args(argv).region
    if not (repo_root() / 'regions' / region / 'render.json').is_file():
        # A synthesized fallback window is not a configured review recipe.
        parser.error(f'{region}: missing render.json')

    style_version, _ = render_config.resolve_style(region)
    cameras = []
    for preview in cast(list[_Preview], render_config.previews(region)):
        lon, lat = preview['center']
        cameras.append((preview['id'], _number(lon), _number(lat),
                        _number(preview['size_m']), _number(preview['zoom'])))

    recipe = dict(region=region, style_version=style_version, cameras=cameras)
    canonical = json.dumps(recipe, sort_keys=True, separators=(',', ':'), allow_nan=False)
    print(json.dumps({**recipe, 'sha256': sha256(canonical.encode('utf-8')).hexdigest()}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
