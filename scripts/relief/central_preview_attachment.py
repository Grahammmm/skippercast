"""Attach a current Central camera recipe to one selected R8 review envelope.

Run from the repo root with explicit inputs under a caller-selected scratch
directory. Output is one JSON object;
base64-decode evidence_base64 to recover the exact input file bytes. This is
review context, not evidence that the historical capture used these cameras,
and does not grant approval or publication authority.
"""

import argparse
from base64 import b64encode
import json
from pathlib import Path
import subprocess
import sys

from scripts.relief.central_camera_bounds import REGIONS
from skippercast.relief import envelope, package, receipts


def bind_attachment(region: str, envelope_path: Path, evidence_path: Path,
                    *, scratch_root: Path, expected_evidence_sha256: str,
                    expected_envelope_sha256: str | None = None) -> dict[str, str]:
    """Verify artifacts and enforce the evidence pin and any supplied envelope pin."""
    if region not in REGIONS:
        raise package.ReleaseError('expected a Central Coast region')
    if not package.is_sha256(expected_evidence_sha256):
        raise package.ReleaseError('expected evidence SHA-256 must be 64 lowercase hex digits')
    if expected_envelope_sha256 is not None and not package.is_sha256(expected_envelope_sha256):
        raise package.ReleaseError('expected envelope SHA-256 must be 64 lowercase hex digits')
    # The verifier follows region-relative layer, release, and QA references.
    paths = (envelope_path, evidence_path)
    if len(envelope_path.parents) >= 3:
        paths += (envelope_path.parents[2],)
    try:
        root = scratch_root.resolve(strict=True)
        inside_scratch = root.is_dir() and all(path.resolve().is_relative_to(root) for path in paths)
    except RuntimeError as exc:  # Path.resolve reports symlink loops on Python 3.12.
        raise package.ReleaseError('could not resolve the scratch input paths') from exc
    if not inside_scratch:
        raise package.ReleaseError('envelope and evidence must be inside the scratch directory')

    verified = envelope.verify_artifacts(envelope_path)
    if expected_envelope_sha256 is not None and verified.envelope_sha256 != expected_envelope_sha256:
        raise package.ReleaseError('envelope SHA-256 does not match the explicit pin')
    if verified.release['region'] != region:
        raise package.ReleaseError('selected envelope belongs to another region')

    if not evidence_path.is_file():
        raise package.ReleaseError('camera evidence must be a local file')
    raw = evidence_path.read_bytes()
    evidence_sha256 = receipts.sha256_bytes(raw)
    if evidence_sha256 != expected_evidence_sha256:
        raise package.ReleaseError('evidence file SHA-256 does not match the explicit pin')
    evidence = package.decode_document(raw)
    if evidence.keys() != {'region', 'style_version', 'cameras', 'sha256'}:
        raise package.ReleaseError('unknown camera evidence schema')
    if evidence['region'] != region:
        raise package.ReleaseError('camera evidence belongs to another region')

    # Run the producer, not a second implementation of the configured recipe loader.
    configured = subprocess.run(
        [sys.executable, '-B', '-m', 'scripts.relief.central_camera_evidence', region],
        capture_output=True,
    )
    if configured.returncode != 0:
        raise package.ReleaseError('could not resolve the configured camera recipe')
    current_sha256 = package.decode_document(configured.stdout)['sha256']
    declared_sha256 = evidence.pop('sha256')
    # Use the producer's JSON spelling (including its default ASCII escaping).
    canonical = json.dumps(evidence, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if declared_sha256 != current_sha256 or receipts.sha256_bytes(canonical.encode('utf-8')) != current_sha256:
        raise package.ReleaseError('stale camera evidence: recipe does not match the current configured recipe')

    return {
        'region': region,
        'envelope_sha256': verified.envelope_sha256,
        'evidence_sha256': evidence_sha256,
        'evidence_base64': b64encode(raw).decode('ascii'),
        'scope': 'current review recipe only, not historical capture provenance',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('region', choices=REGIONS)
    parser.add_argument('--scratch-root', required=True, type=Path)
    parser.add_argument('--envelope', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--expected-evidence-sha256', required=True)
    parser.add_argument('--expected-envelope-sha256', help='require this verified envelope SHA-256')
    args = parser.parse_args(argv)
    try:
        attachment = bind_attachment(args.region, args.envelope, args.evidence,
                                     scratch_root=args.scratch_root,
                                     expected_evidence_sha256=args.expected_evidence_sha256,
                                     expected_envelope_sha256=args.expected_envelope_sha256)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(attachment, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
