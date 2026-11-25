#!/usr/bin/env python3
"""Preview human-entered source resolutions without writing a catalog or approving a source.

Use the untouched C29 worksheet and C24 identity receipt as the baseline. The
proposal CSV may be a separate copy of the worksheet or contain only the original
digest, proposed_native_resolution_m and reviewer_evidence_reference columns.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

if __package__:
    from .native_resolution_worklist import BLANKS, build_worklist
else:
    from native_resolution_worklist import BLANKS, build_worklist

ORIGINAL = "original_sha256"
RESOLUTION, CITATION = BLANKS


def preview(receipt, baseline, proposals):
    worklist = build_worklist(receipt, baseline)
    known = {row[ORIGINAL] for row in worklist}
    entered = defaultdict(list)
    for row in proposals:
        digest = row[ORIGINAL]
        if digest not in known:
            raise ValueError(f"proposal key is not an exact original digest: {digest!r}")
        value, citation = row[RESOLUTION].strip(), row[CITATION].strip()
        if value or citation:
            entered[digest].append((value, citation))
    for row in worklist:
        candidates = entered[row[ORIGINAL]]
        valid, problems = {}, set()
        for value, citation in candidates:
            if not value or not citation:
                problems.add("missing-value-or-citation")
                continue
            # Ordinary metric decimals only: no signs, exponents, NaN, units or inferred conversions.
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) or Decimal(value) <= 0:
                problems.add("invalid-resolution")
                continue
            valid.setdefault((Decimal(value), citation), value)
        if len(valid) > 1:
            problems.add("conflicting-proposals")
        if not candidates:
            problems.add("no-proposal")
        if not problems:
            (_, citation), value = next(iter(valid.items()))
            row.update({RESOLUTION: value, CITATION: citation})
        row.update(preview_status="unresolved" if problems else "proposal-only",
                   reasons=sorted(problems))
    eligible = sum(row["preview_status"] == "proposal-only" for row in worklist)
    return {"schema": "sc-native-resolution-review-preview/1", "scope": "proposal-only; not reviewed or applied",
            "eligible_proposals": eligible, "unresolved": len(worklist) - eligible, "originals": worklist}


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        names = reader.fieldnames or []
        if not {ORIGINAL, *BLANKS}.issubset(names) or len(names) != len(set(names)):
            raise ValueError(f"missing or duplicate worksheet columns: {path.name}")
        rows = list(reader)
        if any(None in row or None in row.values() for row in rows):
            raise ValueError(f"wrong worksheet row width: {path.name}")
        return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("identity_receipt", type=Path)
    parser.add_argument("proposals", type=Path)
    parser.add_argument("--identity-sha256", required=True)
    args = parser.parse_args()
    try:
        raw = args.identity_receipt.read_bytes()
        if hashlib.sha256(raw).hexdigest() != args.identity_sha256:
            raise ValueError("C24 identity receipt does not match its pin")
        report = preview(json.loads(raw), read_csv(args.baseline), read_csv(args.proposals))
    except (OSError, ValueError, TypeError, KeyError, csv.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
