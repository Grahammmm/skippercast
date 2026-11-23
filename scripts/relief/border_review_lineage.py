#!/usr/bin/env python3
"""Compare saved border-gap digests with exact bytes in an offline fixture directory.

Use water.json, support.json (optional), window.json and boundary.json in that
directory. This does not validate geometry, recompute areas or assess approval.
Exit 0 for matching inputs (or absent, unrecorded support), 1 for discrepancies,
and 2 when the report or fixture directory cannot be used.
"""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
from stat import S_ISREG

from skippercast.relief.package import decode_document, is_sha256

_ROLES = ("water", "support", "window", "boundary")


def _disposition(path: Path, expected: object, *, optional: bool) -> str:
    if not (is_sha256(expected) or (optional and expected is None)):
        return "invalid_digest"
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "unknown" if expected is None else "missing"
    except OSError:
        return "unreadable"
    if not S_ISREG(mode):
        return "unreadable"
    if expected is None:
        return "unrecorded"
    try:
        with path.open("rb") as source:
            actual = file_digest(source, "sha256").hexdigest()
    except OSError:
        return "unreadable"
    return "match" if actual == expected else "mismatch"


def check_lineage(report_path: Path, fixture_dir: Path) -> dict[str, str]:
    """Return one byte-lineage disposition per role for an unambiguous digest map."""
    if not fixture_dir.is_dir():
        raise ValueError("expected an existing fixture directory")
    digests = decode_document(report_path.read_bytes()).get("sha256")
    if not isinstance(digests, dict) or digests.keys() != set(_ROLES):
        raise ValueError("sha256 map must contain exactly water, support, window and boundary")
    return {
        role: _disposition(fixture_dir / f"{role}.json", digests[role], optional=role == "support")
        for role in _ROLES
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="saved border-depth-gap report JSON")
    parser.add_argument("--fixture-dir", required=True, type=Path, help="directory of role-named .json fixtures")
    args = parser.parse_args()
    try:
        dispositions = check_lineage(args.report, args.fixture_dir)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"inputs": dispositions, "approval": "not_assessed"}))
    return int(any(state not in ("match", "unknown") for state in dispositions.values()))


if __name__ == "__main__":
    raise SystemExit(main())
