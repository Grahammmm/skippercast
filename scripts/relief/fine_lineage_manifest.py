#!/usr/bin/env python3
"""Join a saved fine_proof_report.py --json report to local bytes, on stdout.

Exit 0 for a complete byte join, 2 for an incomplete join, and 1 for invalid
input (no manifest). Proof rasters are hashed, not decoded or re-certified.
The envelope digest is verified context, not an attestation about fine output.
"""
import argparse
import json
from pathlib import Path
import sys

from skippercast.relief import envelope, package, receipts

ZOOMS = (16, 17)


def _unique_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON member in proof summary')
        result[key] = value
    return result


def _summary_hashes(raw):
    rows = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_members)
    if not isinstance(rows, list):
        raise ValueError('proof summary must be a JSON array')
    hashes = {}
    for row in rows:
        zoom = row.get('zoom') if isinstance(row, dict) else None
        if type(zoom) is not int or zoom not in ZOOMS:
            raise ValueError('proof summary rows must have integer zoom 16 or 17')
        if zoom in hashes:
            raise ValueError(f'duplicate z{zoom} in proof summary')
        digest = row.get('raster_sha256')
        if not package.is_sha256(digest):
            raise ValueError(f'z{zoom} requires a raster_sha256 in the proof summary')
        if digest in hashes.values():
            raise ValueError('z16 and z17 must declare distinct raster_sha256 values')
        hashes[zoom] = digest
    return hashes


def _artifact_hash(path):
    if path is None:
        return None
    try:
        return receipts.sha256_file(path)
    except FileNotFoundError:
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bind a saved fine-proof report to local artifact bytes.')
    parser.add_argument('--summary', required=True, type=Path, help='saved RMSC-90 JSON report')
    parser.add_argument('--envelope', required=True, type=Path, help='local fixture review envelope')
    parser.add_argument('--z16', type=Path, help='local z16 proof raster')
    parser.add_argument('--z17', type=Path, help='local z17 proof raster')
    args = parser.parse_args(argv)

    try:
        raw = args.summary.read_bytes()
        declared = _summary_hashes(raw)
        verified = envelope.verify_artifacts(args.envelope)
        proofs = []
        for zoom, path in zip(ZOOMS, (args.z16, args.z17)):
            expected = declared.get(zoom)
            actual = _artifact_hash(path)
            missing = [name for name, digest in [('summary_row', expected), ('artifact', actual)]
                       if digest is None]
            if missing:
                proofs.append(dict(zoom=zoom, status='incomplete', missing=missing))
            elif actual != expected:
                raise ValueError(f'z{zoom} proof bytes do not match summary raster_sha256')
            else:
                proofs.append(dict(zoom=zoom, status='matched', raster_sha256=actual))
    except (OSError, ValueError) as exc:
        print(f'invalid: {exc}', file=sys.stderr)
        return 1

    complete = all(row['status'] == 'matched' for row in proofs)
    manifest = {
        'status': 'complete' if complete else 'incomplete',
        'summary_sha256': receipts.sha256_bytes(raw),
        'envelope_sha256': verified.envelope_sha256,
        'proofs': proofs,
        'scope': 'Offline byte binding only; the envelope does not approve fine output.',
    }
    print(json.dumps(manifest, indent=2))
    return 0 if complete else 2


if __name__ == '__main__':
    sys.exit(main())
