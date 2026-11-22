"""Measure addressed PNG payload bytes for two windows in one local relief candidate.

Run from the repo root with ``python -m scripts.relief.central_viewport_byte_fit``.
Use a stable, disposable scratch copy of the candidate. This is an offline byte
check, not network timing, coverage, approval, or delivery evidence.
Exit 0 for two FIT views, 1 for OVER, 2 for invalid input or an INCOMPLETE view.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import struct
import sys
import zlib

from scripts.check_relief_budget import ARCHIVE_MAX, VIEWS, tiles_in_view
from scripts.relief.central_camera_bounds import REGIONS
from skippercast.relief import envelope, package
from skippercast.seafloor.rough_first import read_tiles

DEVICES = {'desktop': VIEWS['desktop 1200x800'], 'phone': VIEWS['phone 390x844']}
MAX_ADDRESSED_TILES = 250_000  # read_tiles builds a table for the entire archive
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _window(device, tokens):
    width, height, _ = DEVICES[device]
    limit = tiles_in_view(width, height)
    if not 1 <= len(tokens) <= limit:
        raise ValueError(f'{device}: expected 1–{limit} tile addresses')
    coords = set()
    for token in tokens:
        if not re.fullmatch(r'[0-9]{1,2}/[0-9]{1,8}/[0-9]{1,8}', token):
            raise ValueError(f'{device}: expected z/x/y tile addresses')
        z, x, y = map(int, token.split('/'))
        if z > 26 or max(x, y) >= 1 << z:
            raise ValueError(f'{device}: coordinate outside the PMTiles tile grid')
        if (z, x, y) in coords:
            raise ValueError(f'{device}: repeated tile address')
        coords.add((z, x, y))
    if len({z for z, _, _ in coords}) != 1:
        raise ValueError(f'{device}: mixed zooms in one window')
    return sorted(coords)


def _archive_size(size):
    if not 127 <= size <= ARCHIVE_MAX:
        raise ValueError(f'PMTiles archive size outside 127–{ARCHIVE_MAX} bytes')


def _payload_lengths(path, pin, requested):
    with path.open('rb') as file:
        size = os.fstat(file.fileno()).st_size
        _archive_size(size)
        if size != pin['bytes']:
            raise ValueError('PMTiles archive size changed after envelope verification')
        # As in relief QA, map read-only and pass views, not archive-sized byte copies.
        with mmap.mmap(file.fileno(), size, access=mmap.ACCESS_READ) as archive, memoryview(archive) as view:
            if hashlib.sha256(view).hexdigest() != pin['sha256']:
                raise ValueError('PMTiles archive hash changed after envelope verification')
            if archive[:8] != b'PMTiles\x03' or archive[98:100] != b'\x01\x02':
                raise ValueError('expected PMTiles v3 with uncompressed PNG payloads')
            addressed = struct.unpack_from('<Q', archive, 72)[0]
            if not 1 <= addressed <= MAX_ADDRESSED_TILES:
                raise ValueError(f'PMTiles addressed tile count outside 1–{MAX_ADDRESSED_TILES}')
            try:
                tiles = read_tiles(view)
            except (OSError, ValueError, IndexError, EOFError, zlib.error) as exc:
                # Drop the reader traceback (which can retain tile views) before unmapping.
                failure = str(exc)
            else:
                try:
                    lengths = {}
                    for coord in requested & tiles.keys():
                        blob = tiles[coord]
                        if blob[:len(PNG_SIGNATURE)] != PNG_SIGNATURE:
                            raise ValueError('requested tile is not a PNG payload')
                        lengths[coord] = len(blob)
                    return lengths
                finally:
                    for blob in tiles.values():
                        blob.release()
            raise ValueError(f'cannot read PMTiles index: {failure}')


def _measure(scratch, review, region, windows):
    scratch = scratch.resolve(strict=True)
    if not scratch.is_dir():
        raise ValueError('scratch root must be a directory')
    absolute = scratch / review
    if not absolute.is_relative_to(scratch):
        raise ValueError('envelope must be inside the scratch root')
    review = package.artifact_path(scratch, absolute.relative_to(scratch).as_posix())
    if review.parts[-4:-2] != (region, 'review') or review.name != 'envelope.json':
        raise ValueError('expected the requested region’s review/<generation>/envelope.json')
    archive = package.artifact_path(review.parents[2], package.ARCHIVE)
    _archive_size(archive.stat().st_size)
    verified = envelope.verify_artifacts(review)
    pin = next(row for row in verified.layers if row['path'] == package.ARCHIVE)
    lengths = _payload_lengths(archive, pin, set().union(*windows.values()))
    views = {}
    for device, coords in windows.items():
        _, _, cap = DEVICES[device]
        missing = [coord for coord in coords if coord not in lengths]
        total = sum(lengths[coord] for coord in coords if coord in lengths)
        views[device] = dict(window=coords, measured_bytes=total, cap_bytes=cap, missing_tiles=missing,
                             status='INCOMPLETE' if missing else 'FIT' if total <= cap else 'OVER')
    report = dict(region=verified.release['region'], generation=verified.generation,
                  envelope_sha256=verified.envelope_sha256, views=views,
                  scope='Offline PNG payload bytes only; INCOMPLETE totals are partial, not byte fits.')
    statuses = {view['status'] for view in views.values()}
    return report, 2 if 'INCOMPLETE' in statuses else int('OVER' in statuses)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch-root', required=True, type=Path, help='directory containing the local candidate')
    parser.add_argument('--envelope', required=True, type=Path, help='path inside the scratch root (or relative to it)')
    parser.add_argument('--region', required=True, choices=REGIONS)
    for device in DEVICES:
        parser.add_argument(f'--{device}', required=True, action='extend', nargs='+', metavar='Z/X/Y',
                            help='tile coordinates for this view at one zoom')
    args = parser.parse_args(argv)
    try:
        windows = {device: _window(device, getattr(args, device)) for device in DEVICES}
        report, code = _measure(args.scratch_root, args.envelope, args.region, windows)
    except (OSError, ValueError) as exc:
        print(f'invalid: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
