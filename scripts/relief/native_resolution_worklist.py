#!/usr/bin/env python3
"""Make a blank source-review worklist from the C29 CSV and its C24 identity receipt."""

import argparse
import csv
import json
import re
from pathlib import Path

REGIONS = ("monterey-point-sur", "santa-cruz-monterey-bay")
BLANKS = ("proposed_native_resolution_m", "reviewer_evidence_reference")
MISSING = {"missing_catalog_original_hash", "missing_catalog_value"}


def build_worklist(receipt, worksheet):
    if receipt["schema"] != "sc-c24-resolution-evidence/1" or not receipt["originals"]:
        raise ValueError("expected a nonempty C24 original-source receipt")
    originals = receipt["originals"]
    seen, selections = set(), set()
    worklist = []
    for row in worksheet:
        digest = row["original_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or digest not in originals:
            raise ValueError(f"worksheet key is not an original digest: {digest!r}")
        if digest in seen:
            raise ValueError(f"duplicate worksheet original: {digest}")
        seen.add(digest)
        record = originals[digest]
        status = record["catalog_resolution_status"]
        if status not in MISSING or record["reviewed_native_resolution_m"] is not None:
            raise ValueError(f"original is not an unresolved review task: {digest}")
        memberships = {region: [] for region in REGIONS}
        if not record["memberships"]:
            raise ValueError(f"original has no memberships: {digest}")
        for member in record["memberships"]:
            region, selection = member["region"], member["selection_id"]
            key = (region, selection)
            if region not in memberships or not selection or key in selections:
                raise ValueError(f"invalid or duplicate regional membership: {key}")
            selections.add(key)
            memberships[region].append(selection)
        for ids in memberships.values():
            ids.sort()
        expected = {"source_id": record["source_id"], "catalog_status": status,
                    **{region: "; ".join(ids) for region, ids in memberships.items()},
                    **dict.fromkeys(BLANKS, "")}
        if any(row.get(field) != value for field, value in expected.items()):
            raise ValueError(f"worksheet mismatch for original: {digest}")
        worklist.append({"original_sha256": digest, "source_id": record["source_id"],
                         "catalog_status": status, "memberships": memberships,
                         **dict.fromkeys(BLANKS, "")})
    if seen != originals.keys():
        raise ValueError("worksheet omits original sources from the receipt")
    return sorted(worklist, key=lambda row: row["original_sha256"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worksheet", type=Path)
    parser.add_argument("identity_receipt", type=Path)
    args = parser.parse_args()
    try:
        receipt = json.loads(args.identity_receipt.read_bytes())
        with args.worksheet.open(encoding="utf-8", newline="") as stream:
            worksheet = csv.DictReader(stream, strict=True)
            if not worksheet.fieldnames or len(worksheet.fieldnames) != len(set(worksheet.fieldnames)):
                raise ValueError("missing or duplicate worksheet columns")
            worklist = build_worklist(receipt, worksheet)
    except (OSError, ValueError, TypeError, KeyError, csv.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(worklist, indent=2))


if __name__ == "__main__":
    main()
