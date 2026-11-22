#!/usr/bin/env python3
"""Explain one pixel of a local synthetic fine-proof GeoTIFF as JSON."""
import argparse
import json
from pathlib import Path
import sys

from skippercast.relief import fine_proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog='Pixel evidence only; no tile verdict.')
    parser.add_argument('proof', type=Path, help='local synthetic fine-proof GeoTIFF')
    parser.add_argument('z', type=int, help='XYZ tile zoom')
    parser.add_argument('x', type=int, help='XYZ tile column')
    parser.add_argument('y', type=int, help='XYZ tile row')
    parser.add_argument('col', type=int, help='zero-based pixel column from the tile’s left edge')
    parser.add_argument('row', type=int, help='zero-based pixel row from the tile’s top edge')
    args = parser.parse_args(argv)
    if not args.proof.is_file():
        parser.error('proof must be a local file')
    try:
        proof = fine_proof.read(args.proof)
    except fine_proof.FineProofError as exc:
        print(f'invalid fine proof: {exc}', file=sys.stderr)
        return 1

    z, x, y, col, row = args.z, args.x, args.y, args.col, args.row
    size = fine_proof.TILE
    result: dict[str, list[int] | str | int | float] = {'tile': [z, x, y], 'pixel': [col, row]}
    if z != proof.zoom or not (proof.x0 <= x <= proof.x1 and proof.y0 <= y <= proof.y1):
        result.update(status='out_of_extent', reason='XYZ tile is outside the proof extent at this zoom')
    elif not (0 <= col < size and 0 <= row < size):
        result.update(status='out_of_extent', reason='Local pixel is outside the tile extent')
    else:
        index = ((y - proof.y0) * size + row, (x - proof.x0) * size + col)
        if not proof.proven[index]:
            result.update(status='unproven', reason='No observation recorded (nodata)')
        else:
            cls = int(proof.cls[index])
            result['class'] = cls
            if cls == 3:
                result.update(status='proven', reason='Class 3 evidence at this pixel',
                              depth_m=abs(float(proof.elev[index])), spacing_m=float(proof.spacing[index]))
            else:
                result.update(status='observed_noncertified', reason='Observed class is not class 3')
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
