#!/usr/bin/env python3
"""Print a Central relief data-PR body from explicitly selected local snapshots.

Run with the test, survey or publish extra. Paths are relative to --scratch-root
(or absolute paths inside it). The caller supplies the full base commit SHA and
an independently recorded SHA-256 of its pointer bytes, or explicitly declares
that this commit has no pointer. This tool does not attest to Git provenance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True

from skippercast.relief import envelope, package, receipts  # noqa: E402

if __package__:
    from .central_stage_handoff import CENTRAL_RELEASES
    from .pointer_diff import diff_fields
else:
    from central_stage_handoff import CENTRAL_RELEASES
    from pointer_diff import diff_fields

_SHARED_FIELDS = ('style', 'bounds', 'minzoom', 'maxzoom', 'sources')


def _scratch_file(root: Path, path: Path) -> Path:
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            raise ValueError('input path must be inside --scratch-root') from None
    return package.artifact_path(root, path.as_posix())


def _identity(generation, release_sha256, envelope_sha256, archive_sha256, size, digest_root):
    return [
        f'- Generation: `{generation}`',
        f'- Envelope SHA-256: `{envelope_sha256}`',
        f'- Release SHA-256: `{release_sha256}`',
        f'- Archive SHA-256: `{archive_sha256}` ({size} bytes)',
        f'- Digest root SHA-256: `{digest_root}`',
    ]


def _body(verified: envelope.VerifiedArtifacts, base_sha: str, base: dict | None,
          base_pointer_sha256: str | None) -> str:
    release = verified.release
    archive = next(row for row in verified.layers if row['path'] == package.ARCHIVE)
    lines = [
        f'## Central relief data: `{release["region"]}`', '',
        'Pre-review form only. Artifact verification is not R8 confirmation or STAGE evidence.', '',
        '### Candidate', '',
        *_identity(verified.generation, verified.release_sha256, verified.envelope_sha256,
                   archive['sha256'], archive['bytes'], release['digest_root_sha256']),
        f'- Packaging code commit: `{release["code_sha"]}`',
        f'- QA report SHA-256: `{verified.qa_sha256}`', '',
        '### Selected base', '',
        f'- Base commit (operator-selected): `{base_sha}`',
    ]
    if base is None:
        lines.append('- First release (operator-declared): no prior pointer or generation.')
    else:
        lines.extend([
            f'- Base pointer SHA-256 (exact supplied bytes): `{base_pointer_sha256}`',
            *_identity(base['generation'], base['release_sha256'], base['envelope_sha256'],
                       base['sha256'], base['bytes'], base['digest_root_sha256']),
        ])
    lines.extend(['', 'Confirm the selected commit and its pointer state before use.', '',
                  '### Style, bounds, zooms and sources', ''])
    changes = diff_fields(base or {}, release, _SHARED_FIELDS)
    if changes:
        # JSON quotes control characters. Keep any markup or fences in source
        # strings inert even when the body is pasted verbatim into GitHub.
        text = json.dumps(changes, indent=2, sort_keys=True).replace('`', r'\u0060').replace('<', r'\u003c')
        lines.extend(['```json', text, '```'])
    else:
        lines.append('No changes to the shared fields.')
    lines.extend([
        '', '### Attended confirmations — pending', '',
        '- [ ] Designated R8 verifier card and envelope-bound confirmation: ______',
        '- [ ] STAGE authorization and scope for these exact assets: ______',
        '- [ ] STAGE hosted read-back evidence for the selected commit and assets (after merge): ______',
    ])
    return '\n'.join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch-root', required=True, type=Path, help='local snapshot directory')
    parser.add_argument('--envelope', required=True, type=Path, help='REGION/review/GEN/envelope.json')
    parser.add_argument('--base-sha', required=True, help='full 40-character lowercase Git commit SHA')
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--base-pointer', type=Path)
    selection.add_argument('--first-release', action='store_true')
    parser.add_argument('--base-pointer-sha256', help='expected digest of the raw base pointer bytes')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{40}', args.base_sha):
        parser.error('--base-sha must be a full 40-character lowercase Git commit SHA')
    if args.first_release and args.base_pointer_sha256 is not None:
        parser.error('--base-pointer-sha256 cannot accompany --first-release')
    if args.base_pointer is not None and not package.is_sha256(args.base_pointer_sha256):
        parser.error('--base-pointer requires a full --base-pointer-sha256')

    try:
        root = args.scratch_root.absolute()
        path = _scratch_file(root, args.envelope)
        if len(path.parents) < 3 or not path.parents[2].is_relative_to(root):
            raise ValueError('envelope region directory must be inside --scratch-root')
        if path.parents[2].name not in CENTRAL_RELEASES:
            raise ValueError('expected a Central release region')
        verified = envelope.verify_artifacts(path)
        base = None
        if args.base_pointer is not None:
            raw = _scratch_file(root, args.base_pointer).read_bytes()
            if receipts.sha256_bytes(raw) != args.base_pointer_sha256:
                raise ValueError('base pointer bytes do not match --base-pointer-sha256')
            base = package.decode_document(raw)
            package.validate_schema(base, package.pointer_schema())
            if base['region'] != verified.release['region']:
                raise ValueError('base pointer belongs to a different region')
        body = _body(verified, args.base_sha, base, args.base_pointer_sha256)
    except (OSError, ValueError, RecursionError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
