"""Print an inert JSON request for one configured Central Coast camera center.

From the repo root, run ``python -m scripts.relief.central_shot_request --help``.
The array is for use from that same checkout. The expected hashes identify the
verified envelope and release; shots itself does not enforce these pins or
select a generation from an envelope. Check the current package before using
the array. Zoom, capture, QA and review stay in the existing pipeline.
"""
import argparse
import json
from pathlib import Path
from typing import cast

from scripts.relief.central_camera_bounds import REGIONS
from skippercast.paths import repo_root
from skippercast.relief import envelope, package, render_config


def _local_path(text: str) -> Path:
    if not text or '://' in text or text.startswith(('//', '~')):
        raise argparse.ArgumentTypeError('expected an explicit local filesystem path')
    return Path(text)


def _inside(bounds, lon, lat):
    west, south, east, north = bounds
    return west <= lon <= east and south <= lat <= north


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--region', required=True, choices=REGIONS)
    parser.add_argument('--camera', required=True, help='exact preview ID in the region render.json')
    parser.add_argument('--out', required=True, type=_local_path, help='local scratch OUT directory')
    parser.add_argument('--envelope', required=True, type=_local_path,
                        help='OUT/<region>/review/<generation>/envelope.json')
    parser.add_argument('--basemap', required=True, type=_local_path, help='local basemap PMTiles file')
    args = parser.parse_args(argv)

    try:
        directory = repo_root() / 'regions' / args.region
        # Don't let the shared loader substitute its default fishing camera.
        if not (directory / 'render.json').is_file():
            raise ValueError(f'{args.region}: missing render.json')
        cameras = {row['id']: row['center'] for row in render_config.previews(args.region)}
        # The render loader refuses duplicate IDs before returning the previews.
        if args.camera not in cameras:
            raise ValueError(f'{args.region}: unknown camera {args.camera!r}')
        lon, lat = cast(list[float], cameras[args.camera])
        region = package.decode_document((directory / 'region.json').read_bytes())
        if not _inside(region['bounds'], lon, lat):
            raise ValueError(f'{args.region}/{args.camera}: center is outside region bounds')

        out = args.out.resolve(strict=True)
        review = args.envelope.absolute()
        if len(review.parents) < 4 or review.parents[3] != out:
            raise ValueError('envelope must be under the explicit OUT directory')
        verified = envelope.verify_artifacts(review)
        if verified.release['region'] != args.region:
            raise ValueError('envelope belongs to another region')
        if not _inside(verified.release['bounds'], lon, lat):
            raise ValueError(f'{args.region}/{args.camera}: center is outside release bounds')
        basemap = args.basemap.resolve(strict=True)
        if not basemap.is_file():
            raise ValueError('basemap must be a local file')
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    # Hashes are request metadata, not unsupported shots arguments.
    print(json.dumps({
        'camera_id': args.camera,
        'expected_release_sha256': verified.release_sha256,
        'expected_envelope_sha256': verified.envelope_sha256,
        'argv': ['python', '-B', 'scripts/relief/region.py', 'shots', '--region', args.region,
                 '--out', str(out), '--basemap', str(basemap), '--lon', str(lon), '--lat', str(lat)],
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
