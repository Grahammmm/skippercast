"""Report configured Central Coast review camera centers against region bounds.

Run with ``python -m scripts.relief.central_camera_bounds`` from the repo root.
This checks only centers, not the extent of a window or any data coverage.
Exit 1 if any configured center is outside its region, otherwise 0 on success.
"""

import argparse

from skippercast.paths import repo_root
from skippercast.relief import render_config
from skippercast.relief.package import decode_document

REGIONS = (
    'big-sur-coast',
    'cambria-san-simeon',
    'south-big-sur-san-simeon',
    'monterey-point-sur',
    'point-arguello-conception',
    'santa-cruz-monterey-bay',
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    root = repo_root()
    has_outlier = False
    print('Configured review windows: center check only (not window extent or data coverage).')
    for region in REGIONS:
        directory = root / 'regions' / region
        # The shared loader falls back to fishing-centered defaults for missing
        # recipes. This preflight must report only explicitly configured windows.
        if not (directory / 'render.json').is_file():
            parser.error(f'{region}: missing render.json')
        west, south, east, north = decode_document((directory / 'region.json').read_bytes())['bounds']
        for preview in render_config.previews(region):
            lon, lat = preview['center']
            inside = west <= lon <= east and south <= lat <= north
            has_outlier = has_outlier or not inside
            status = 'IN_BOUNDS' if inside else 'OUT_OF_BOUNDS'
            print(
                f"{status} {region}/{preview['id']} center=({lon}, {lat}) "
                f"size_m={preview['size_m']} zoom={preview['zoom']}"
            )
    return int(has_outlier)


if __name__ == '__main__':
    raise SystemExit(main())
