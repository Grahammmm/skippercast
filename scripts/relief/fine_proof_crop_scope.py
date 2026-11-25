#!/usr/bin/env python3
"""Scope whole-file fine-proof totals to a same-zoom XYZ crop, offline.

Input is the JSON array from fine_proof_report.py --json. Tile endpoints
are inclusive. This summary does not use tile IDs, inspect the raster, or
establish coverage by any other proof or emitted tiles.
"""
import argparse
import json
from pathlib import Path


BOUNDS = ('x0', 'y0', 'x1', 'y1')
COUNTS = ('certified', 'uncertified', 'unproven')


def rectangle(zoom, values):
    x0, y0, x1, y1 = values
    if (not all(type(value) is int for value in values)
            or not (0 <= x0 <= x1 < 1 << zoom and 0 <= y0 <= y1 < 1 << zoom)):
        raise ValueError('XYZ bounds must be inclusive integers inside the zoom grid')
    return x0, y0, x1, y1


def tile_count(bounds):
    x0, y0, x1, y1 = bounds
    return (x1 - x0 + 1) * (y1 - y0 + 1)


def crop_scope(reports, zoom, crop):
    if type(zoom) is not int or zoom not in (16, 17):
        raise ValueError('crop zoom must be 16 or 17')
    crop = rectangle(zoom, crop)
    if not isinstance(reports, list) or any(not isinstance(row, dict) for row in reports):
        raise ValueError('expected a fine-proof report JSON array')
    matches = [row for row in reports if type(row.get('zoom')) is int and row['zoom'] == zoom]
    if len(matches) != 1:
        raise ValueError(f'expected exactly one proof summary at z{zoom}')
    report = matches[0]
    if not isinstance(report.get('tile_range'), dict):
        raise ValueError('expected a proof tile_range object')
    proof = rectangle(zoom, tuple(report['tile_range'][key] for key in BOUNDS))
    totals = {key: report[key] for key in COUNTS}
    if (any(type(value) is not int or value < 0 for value in totals.values())
            or sum(totals.values()) != tile_count(proof)):
        raise ValueError('whole-proof totals must partition the proof rectangle')

    overlap = (max(crop[0], proof[0]), max(crop[1], proof[1]),
               min(crop[2], proof[2]), min(crop[3], proof[3]))
    if overlap[0] > overlap[2] or overlap[1] > overlap[3]:
        relation, certified, overlap = 'disjoint', 0, None
        note = 'No tiles in the crop can be certified by this proof; other evidence is not assessed.'
    elif overlap == proof:
        relation, certified = 'contains_proof', totals['certified']
        note = 'The entire proof lies inside the crop; any area outside the proof is not assessed.'
    else:
        relation, certified = 'partial_overlap', None
        note = 'Whole-proof totals do not locate certified tiles; no crop count is inferred.'
    return {
        'zoom': zoom,
        'crop_tile_range': dict(zip(BOUNDS, crop)),
        'proof_tile_range': dict(zip(BOUNDS, proof)),
        'relation': relation,
        'intersection_tile_range': dict(zip(BOUNDS, overlap)) if overlap else None,
        'intersection_tile_count': tile_count(overlap) if overlap else 0,
        'whole_proof_totals': totals,
        'crop_certified_by_this_proof': certified,
        'note': note,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Scope whole-file fine-proof totals to an XYZ crop.')
    parser.add_argument('report', type=Path, help='local JSON from fine_proof_report.py --json')
    parser.add_argument('--crop', type=int, nargs=5, required=True,
                        metavar=('Z', 'X0', 'Y0', 'X1', 'Y1'), help='inclusive XYZ bounds')
    args = parser.parse_args(argv)
    zoom, *crop = args.crop
    try:
        with args.report.open(encoding='utf-8') as source:
            result = crop_scope(json.load(source), zoom, crop)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'invalid crop or proof report: {exc}\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
