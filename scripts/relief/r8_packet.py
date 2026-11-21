#!/usr/bin/env python3
"""Print evidence for R8 review without approving or publishing a release."""
import argparse
from pathlib import Path
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True
    # Use the same checkout as the CLI, not another editable install.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from skippercast.relief import envelope, package, receipts


def _current_envelope(out: Path, region_id: str) -> Path:
    region = receipts.Region(out, region_id)
    # The package receipt selects the current release generation. Do not scan
    # historical envelopes or run receipt checks that can take stage locks.
    receipt = package.artifact_path(region.dir, 'stages/package.json')
    doc = package.decode_document(receipt.read_bytes())
    problem = receipts.validate_receipt(doc, region_id, 'package', None)
    if problem:
        raise package.ReleaseError(f'invalid package receipt: {problem}')
    if doc['status'] != 'ok':
        raise package.ReleaseError(f'package receipt status is {doc["status"]}')
    return region.dir / 'review' / doc['generation'] / 'envelope.json'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='r8_packet.py', description=__doc__)
    parser.add_argument('--out', required=True, type=Path, metavar='OUT')
    parser.add_argument('regions', nargs='+', metavar='REGION')
    args = parser.parse_args(argv)
    if len(args.regions) > 3:
        parser.error('expected at most 3 regions')
    for region in args.regions:
        try:
            receipts.check_names('envelope', region=region)
        except receipts.ReceiptError as exc:
            parser.error(str(exc))

    status = 0
    for region in args.regions:
        try:
            verified = envelope.verify_artifacts(_current_envelope(args.out, region))
        except (OSError, ValueError) as exc:
            reason = ' '.join(str(exc).splitlines())
            print(f'NOT READY {region}: {reason}')
            status = 1
            continue
        print(
            f'READY {region}\n'
            f'  generation: {verified.generation}\n'
            f'  envelope.json sha256: {verified.envelope_sha256}\n'
            f'  release.json sha256: {verified.release_sha256}\n'
            f'  qa.json sha256: {verified.qa_sha256}\n'
            f'  layers: {len(verified.layers)}\n'
            f'APPROVED release {region} envelope={verified.envelope_sha256}'
        )
    return status


if __name__ == '__main__':
    sys.exit(main())
