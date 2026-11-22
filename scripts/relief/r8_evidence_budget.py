#!/usr/bin/env python3
"""Estimate a Central R8 review batch's attachment bytes from synthetic metadata.

Supply a JSON object on stdin with an `artifacts` list of envelope layer records
(`path`, `sha256`, `bytes`) selected for the named batch. The cap applies to the
sum of unique payload bytes, not to each item or to transport overhead. Artifact
paths are labels only: nothing is opened, copied, verified, or published.
"""
import argparse
import json
import sys

from skippercast.relief.package import decode_document, is_sha256


def summarize(batch: str, artifacts: list[dict], attachment_cap_bytes: int) -> dict:
    if not isinstance(artifacts, list):
        raise ValueError('expected an artifacts list')
    if attachment_cap_bytes < 0:
        raise ValueError('attachment cap must be nonnegative')

    sizes: dict[str, int] = {}
    for index, row in enumerate(artifacts, 1):
        if (not isinstance(row, dict) or row.keys() != {'path', 'sha256', 'bytes'}
                or not isinstance(row['path'], str) or not row['path']
                or not is_sha256(row['sha256']) or type(row['bytes']) is not int or row['bytes'] < 1):
            raise ValueError(f'invalid envelope artifact record {index}: expected path, SHA256 and positive bytes')
        digest, size = row['sha256'], row['bytes']
        if sizes.setdefault(digest, size) != size:
            raise ValueError(f'conflicting sizes for SHA256 {digest}: {sizes[digest]} and {size} bytes')

    total = sum(sizes.values())
    # A digest identifies the unique item even if several packets give it different paths.
    largest = max(sizes.items(), key=lambda item: (item[1], item[0]), default=None)
    return {
        'batch': batch,
        'unique_bytes': total,
        'largest_item': {'sha256': largest[0], 'bytes': largest[1]} if largest else None,
        'attachment_cap_bytes': attachment_cap_bytes,
        'within_attachment_cap': total <= attachment_cap_bytes,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', required=True, help='label for the requested Central review batch')
    parser.add_argument('--attachment-cap-bytes', required=True, type=int)
    args = parser.parse_args(argv)
    try:
        doc = decode_document(sys.stdin.buffer.read())
        if doc.keys() != {'artifacts'}:
            raise ValueError('expected a JSON object containing only artifacts')
        report = summarize(args.batch, doc['artifacts'], args.attachment_cap_bytes)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
