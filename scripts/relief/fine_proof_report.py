#!/usr/bin/env python3
"""Report fine-zoom proof as text or a JSON array ordered by zoom.

Each JSON record has inclusive XYZ tile bounds and certified tile IDs in
numeric (z, x, y) order. The SHA-256 covers the source GeoTIFF bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from skippercast.relief import fine_proof


def summarize(path):
    proof = fine_proof.read(path)
    counts = dict(certified=0, uncertified=0, unproven=0)
    certified_tiles = []
    for x in range(proof.x0, proof.x1 + 1):
        for y in range(proof.y0, proof.y1 + 1):
            if proof.certified(proof.zoom, x, y):
                counts['certified'] += 1
                certified_tiles.append(f'{proof.zoom}/{x}/{y}')
            else:
                row = (y - proof.y0) * fine_proof.TILE
                col = (x - proof.x0) * fine_proof.TILE
                tile = proof.proven[row:row + fine_proof.TILE, col:col + fine_proof.TILE]
                counts['uncertified' if tile.any() else 'unproven'] += 1
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return {
        'zoom': proof.zoom,
        'raster_sha256': digest,
        'tile_range': dict(x0=proof.x0, y0=proof.y0, x1=proof.x1, y1=proof.y1),
        **counts,
        'certified_tiles': certified_tiles,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Report fine-zoom proof rasters.')
    parser.add_argument('proof', metavar='PROOF', nargs='+', type=Path)
    parser.add_argument('--json', action='store_true', help='print a JSON array')
    args = parser.parse_args(argv)
    reports = {}
    for path in args.proof:
        try:
            report = summarize(path)
        except fine_proof.FineProofError as exc:
            print(f'invalid {exc}', file=sys.stderr)
            return 1
        zoom = report['zoom']
        if zoom in reports:
            print('duplicate zoom', file=sys.stderr)
            return 1
        reports[zoom] = report

    ordered = [reports[zoom] for zoom in sorted(reports)]
    if args.json:
        print(json.dumps(ordered))
    else:
        for report in ordered:
            bounds = report['tile_range']
            print(
                f"z{report['zoom']} sha256={report['raster_sha256']} "
                f"tiles={bounds['x0']}/{bounds['y0']}..{bounds['x1']}/{bounds['y1']} "
                f"certified={report['certified']} uncertified={report['uncertified']} "
                f"unproven={report['unproven']}"
            )
    return 0


if __name__ == '__main__':
    sys.exit(main())
