"""Check a screenshot camera against a local release's sparse relief digest index.

Exit 0 for a completed advisory (including missing tiles), 1 for pin mismatch,
and 2 for invalid or unreadable input. This does not verify the tile archive or
predict what will paint. Pass the package's release/<generation>/release.json.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

# Direct execution should use this checkout and not create bytecode files.
if __name__ == '__main__':
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from skippercast.relief import digests, package, receipts

ADVISORY = 'A missing centre tile does not mean an empty viewport.'
MERCATOR_LIMIT = math.degrees(math.atan(math.sinh(math.pi)))


class PinMismatch(ValueError):
    """The expected pins disagree, or the pinned bytes do not match."""


def centre_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    """XYZ with north at y=0; clamp the poles and the +180° grid edge."""
    width = 1 << zoom
    lat = max(-MERCATOR_LIMIT, min(MERCATOR_LIMIT, lat))
    x = math.floor((lon + 180) / 360 * width)
    y = math.floor((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * width)
    return max(0, min(width - 1, x)), max(0, min(width - 1, y))


def pinned_bytes(region: Path, layer: dict) -> bytes:
    path = layer['path']
    # Read once; hash and parse the same bytes, not separate opens of the file.
    with package.artifact_path(region, path).open('rb') as stream:
        raw = stream.read(layer['bytes'] + 1)
    if len(raw) != layer['bytes'] or receipts.sha256_bytes(raw) != layer['sha256']:
        raise PinMismatch(f'SHA-256 or size mismatch: {path}')
    return raw


def read_chunk(raw: bytes, block_x: int, block_y: int) -> set[tuple[int, int]]:
    rows = json.loads(raw.decode('utf-8'))
    if not isinstance(rows, list):
        raise ValueError('invalid digest chunk')
    entries = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError('invalid digest row')
        x, y, sha = row
        if (type(x) is not int or x // digests.BLOCK_SIZE != block_x
                or type(y) is not int or y // digests.BLOCK_SIZE != block_y
                or not package.is_sha256(sha) or (x, y) in entries):
            raise ValueError('invalid digest row')
        entries.add((x, y))
    return entries


def inspect(release_path: Path, lon: float, lat: float, zooms: list[int] | None) -> list[dict]:
    if not (math.isfinite(lon) and -180 <= lon <= 180 and math.isfinite(lat) and -90 <= lat <= 90):
        raise ValueError('expected finite longitude in [-180, 180] and latitude in [-90, 90]')
    release = package.decode_document(release_path.read_bytes())
    if release.get('schema') != package.RELEASE_SCHEMA or release.get('private') is not False:
        raise ValueError('expected a public relief release')
    low, high = release.get('minzoom'), release.get('maxzoom')
    if type(low) is not int or type(high) is not int or not 8 <= low <= high <= digests.MAX_RELIEF_ZOOM:
        raise ValueError('invalid release capture zoom range')
    if zooms is None:
        # Same app zooms as qa_shots.mjs. The 256px relief source cancels
        # the engine's one-level MapLibre zoom offset, so these are XYZ zooms.
        zooms = [z for z in (low, 10, 13, 15, high) if low <= z <= high]
    elif any(not low <= z <= high for z in zooms):
        raise ValueError(f'capture zooms must be within the release range [{low}, {high}]')

    # Use the package reader for layer shape, uniqueness, and the root pin.
    root_key = package.DIGEST_ROOT
    root_sha = release.get('digest_root_sha256')
    rows = release.get('layers')
    if isinstance(rows, list) and rows:
        root_rows = [row for row in rows if isinstance(row, dict) and row.get('path') == root_key]
        if not root_rows or (len(root_rows) == 1 and root_rows[0].get('sha256') != root_sha):
            raise PinMismatch('digest root is not bound to its release layer')
    layers = {row['path']: row for row in package.release_layers(release)}
    region = release_path.absolute().parent.parent.parent
    root = package.decode_document(pinned_bytes(region, layers[root_key]))
    if root.keys() != {'chunks'} or not isinstance(root['chunks'], dict):
        raise ValueError('invalid digest root inventory')
    chunks = root['chunks']
    prefix = root_key.removesuffix('root.json')
    results = []
    for z in sorted(set(zooms)):
        x, y = centre_tile(lon, lat, z)
        bx, by = x // digests.BLOCK_SIZE, y // digests.BLOCK_SIZE
        name = f'{z}/{bx}_{by}.json'
        layer = layers.get(prefix + name)
        indexed = False
        if name in chunks or layer is not None:
            expected = chunks.get(name)
            if layer is None or layer['sha256'] != expected:
                raise PinMismatch(f'digest chunk does not match its release layer: {name}')
            indexed = (x, y) in read_chunk(pinned_bytes(region, layer), bx, by)
        results.append(dict(z=z, x=x, y=y, status='indexed' if indexed else 'missing'))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Check centre tiles against a local relief digest index.')
    parser.add_argument('--release', required=True, type=Path)
    parser.add_argument('--lon', required=True, type=float)
    parser.add_argument('--lat', required=True, type=float)
    parser.add_argument('--zooms', nargs='+', type=int, help='default: the screenshot capture zooms')
    parser.add_argument('--json', action='store_true', help='emit one JSON result, including on release errors')
    args = parser.parse_args(argv)
    try:
        tiles = inspect(args.release, args.lon, args.lat, args.zooms)
    except (OSError, ValueError, OverflowError) as exc:
        mismatch = isinstance(exc, PinMismatch)
        status = 'pin_mismatch' if mismatch else 'invalid'
        if args.json:
            print(json.dumps(dict(status=status, error=str(exc))))
        else:
            print(f"{status.replace('_', ' ').capitalize()}: {exc}", file=sys.stderr)
        return 1 if mismatch else 2
    if args.json:
        print(json.dumps(dict(status='checked', tiles=tiles, advisory=ADVISORY)))
    else:
        for row in tiles:
            print('{z}/{x}/{y}: {status}'.format(**row))
        print(ADVISORY)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
