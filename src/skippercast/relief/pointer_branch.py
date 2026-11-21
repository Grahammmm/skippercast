"""Write an approved region release (pointer + depth contours) onto a new local branch.

    region.py pointer-branch --region <id> --out <OUT> --approval FILE --envelope FILE
                             --repo <clean clone> [--branch data/<id>-<generation 12 hex>]

The data PR changes exactly ``catalog/relief/<id>.json`` and
``catalog/depth-contours/<id>.geojson``. The approval file comes from the attended
operator's trusted R8 path: this command binds bytes and authenticates nobody.

Order: ``envelope.verify_chain`` first; then the current done ``contours`` receipt's
``layers/contours/contours.geojson`` is re-hashed against that receipt, its
``provenance.region_id`` checked, and the same bytes passed to the platform's
unchanged catalog-input validator (``depth_contours.check_contours`` with the clone's
catalogs and region), so a branch the catalog build would reject is never written.
Every one of these refusals happens before any Git command. Only then is Git read:
``previous`` is the clone HEAD's pointer (None when absent), ``build_pointer`` makes
the pointer and it is validated against the clone HEAD's ``pointer.schema.json``.
``rollback.write_branch`` commits both files (signed off) on a new branch.

The pointer bytes are ``receipts.canonical`` (the committed cross-language pointer
fixtures); the contours bytes are the receipt's bytes, never rewritten. Nothing here
pushes, opens a PR, merges or uploads. Exit 0 written, 1 refused, 2 usage.
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from hashlib import sha256
import os
from pathlib import Path
import sys

from skippercast.platform import contracts, depth_contours
from skippercast.relief import envelope, package, receipts, rollback

CONTOURS_STAGE = 'contours'
CONTOURS_OUTPUT = 'layers/contours/contours.geojson'
SCHEMA_PATH = 'catalog/relief/pointer.schema.json'


class PointerBranchError(ValueError):
    """The data branch cannot be written."""


def paths(region: str) -> tuple[str, str]:
    """The pointer and depth-contour catalog paths of ``region`` (the rollback paths)."""
    return rollback._region_paths(region)


def contour_bytes(region: receipts.Region) -> bytes:
    """The current done contours receipt's catalog-input bytes, re-hashed against it."""
    verdict = receipts.check(region, CONTOURS_STAGE)
    if not verdict.done:
        raise PointerBranchError(f'contours receipt is not done: {verdict.state}: {verdict.reason}')
    rows = [row for row in (verdict.receipt or {}).get('outputs', []) if row.get('path') == CONTOURS_OUTPUT]
    if len(rows) != 1:
        raise PointerBranchError(f'contours receipt does not list {CONTOURS_OUTPUT}')
    raw = package.artifact_path(region.dir, CONTOURS_OUTPUT).read_bytes()
    # Hash the bytes this command will commit, not an earlier read by the done rule.
    if rows[0]['sha256'] != receipts.sha256_bytes(raw) or rows[0]['bytes'] != len(raw):
        raise PointerBranchError(f'{CONTOURS_OUTPUT} does not match the contours receipt')
    doc = package.decode_document(raw)
    provenance = doc.get('provenance')
    if not isinstance(provenance, dict) or provenance.get('region_id') != region.id:
        raise PointerBranchError(f'{CONTOURS_OUTPUT} is not region {region.id}')
    return raw


def check_catalog_input(repo: Path, region_id: str, raw: bytes) -> None:
    """Refuse bytes the platform build's catalog-input validator would refuse.

    Reads the clone's catalogs and region file (its work tree; write_branch later
    requires it to equal HEAD). The validator is called unchanged and the bytes are
    never converted: a done stage output may still fail it (for example an
    ``unstated`` survey date that only the stage's selected-source validator allows).
    """
    _, sources = contracts.load_catalogs(repo)
    region = contracts.read_json(repo / 'regions' / region_id / 'region.json')
    if not isinstance(region, dict) or region.get('id') != region_id:
        raise PointerBranchError(f'regions/{region_id}/region.json is not region {region_id}')
    collection = package.decode_document(raw)
    try:
        depth_contours.check_contours(collection, region, sources)
    except (KeyError, TypeError) as exc:
        raise PointerBranchError(f'catalog validator refused the contours: {exc!r}') from exc


def _parser() -> argparse.ArgumentParser:
    def region_id(text):
        if not receipts.REGION_ID.fullmatch(text):
            raise argparse.ArgumentTypeError(f'invalid region id: {text!r}')
        return text

    out = os.environ.get('SC_RELIEF_OUT') or None
    parser = argparse.ArgumentParser(prog='region.py pointer-branch',
                                     description='Write an approved release onto a new local branch.')
    parser.add_argument('--region', required=True, type=region_id, help='region id')
    parser.add_argument('--out', type=Path, default=out, required=out is None,
                        help='pipeline output root OUT (default $SC_RELIEF_OUT)')
    parser.add_argument('--approval', required=True, type=Path, help="the trusted R8 path's approval.json")
    parser.add_argument('--envelope', required=True, type=Path, help='review/<generation>/envelope.json')
    parser.add_argument('--repo', required=True, type=Path, help='root of a clean clone')
    parser.add_argument('--branch', help='new branch (default: data/<region>-<generation 12 hex>)')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    region_id = args.region
    pointer_path, contours_path = paths(region_id)
    try:
        # C1: byte binding of the approved chain comes before anything else.
        verified = envelope.verify_chain(args.approval, args.envelope)
        generation = verified.release['generation']
        region = receipts.Region(args.out, region_id)
        if verified.region_dir.resolve() != region.dir or verified.release['region'] != region_id:
            raise PointerBranchError(f'envelope is not a release of OUT/{region_id}')
        # C2: no Git command runs before these refusals.
        contours = contour_bytes(region)
        check_catalog_input(args.repo, region_id, contours)

        git = rollback.GitCli(args.repo)
        if git.run(['git', 'rev-parse', '--show-prefix']) != b'\n':
            raise PointerBranchError('--repo must point to the root of the clone')
        head_pointer = git.show('HEAD', pointer_path)
        previous = package.decode_document(head_pointer) if head_pointer is not None else None
        if previous is not None and previous.get('generation') == generation:
            raise PointerBranchError(f'HEAD already points {region_id} at generation {generation}')
        schema = git.show('HEAD', SCHEMA_PATH)
        if schema is None:
            raise PointerBranchError(f'HEAD has no {SCHEMA_PATH}')
        pointer = envelope.build_pointer(args.approval, args.envelope, previous=previous)
        package.validate_schema(pointer, package.decode_document(schema))
        state = {pointer_path: receipts.canonical(pointer), contours_path: contours}

        # C3: the shared writer; only the two paths, one signed-off commit.
        branch = args.branch or f'data/{region_id}-{generation[:12]}'
        rollback.write_branch(args.repo, region_id, state, branch=branch, run=git.run,
                              message=f'Release relief for {region_id} generation {generation}')
        commit = git.run(['git', 'rev-parse', 'HEAD']).decode('ascii').strip()
    except (ValueError, OSError) as exc:
        # ReleaseError, ReceiptError, RollbackError and this module's errors are ValueErrors.
        print(f'region.py pointer-branch: {exc}', file=sys.stderr)
        return 1

    print(f'Branch: {branch}\nCommit: {commit}')
    for path, payload in state.items():
        print(f'{path}: {sha256(payload).hexdigest()}')
    print('Not pushed.')
    return 0
