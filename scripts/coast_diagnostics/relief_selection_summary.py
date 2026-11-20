"""Summarize relief select's file-row decisions without exposing input details."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re


NOTE = "These are file rows, not surveys, coverage, or rights clearance."
# Match the registry's ID format (schemas/common.schema.json).
SOURCE_ID = re.compile(r"[a-z][a-z0-9-]{1,63}")
# Exact producer messages only. Never use the input reason itself as a label:
# select also stores arbitrary exception text in that field.
REASON_GROUPS = {
    "registry_unbound": ("no_unambiguous_registry_binding",),
    "registry_display_held": ("registry_excluded", "registry_public_display_not_allowed"),
    "registry_display_allowed": (
        "registry_public_display_allowed", "registry_owner_public_display_allowed",
    ),
    "normalization_needed": (
        "no_admissible_normalized_twin",
        "external mask or auxiliary metadata requires normalization",
        "not an admissible single-band projected metre elevation grid",
        "raw vertical metre units are not explicit; normalize first",
    ),
    "normalized_input_review": (
        "ambiguous_normalized_twins", "normalized path escapes its content bucket",
        "normalized sidecar does not bind this original metre elevation grid",
        "grid.tif: normalized pin mismatch", "support.tif: normalized pin mismatch",
        "normalized sidecar geometry mismatch",
        "support raster must be aligned uint8 on the elevation grid",
    ),
    "original_input_review": (
        "duplicate_census_path", "original_missing", "invalid_original_sha256",
        "original census hash changed", "not a local path", "unsafe input path",
        "symlink input refused",
    ),
    "datum_or_sign_review": ("unsupported vertical datum or sign",),
    "outside_region": ("grid does not overlap region",),
    "not_elevation": ("not_elevation",),
}
REASON_CATEGORY = {
    reason: category for category, reasons in REASON_GROUPS.items() for reason in reasons
}


def summarize(files):
    counts = Counter()
    for row in files:
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id):
            source_id = None
        decision = row.get("decision")
        if decision not in ("included", "skipped"):
            decision = "other"
        reason = row.get("reason")
        category = REASON_CATEGORY.get(reason, "other") if isinstance(reason, str) else "other"
        counts[source_id, decision, category] += 1
    rows = []
    for key in sorted(counts, key=lambda key: (key[0] is None, key[0] or "", *key[1:])):
        source_id, decision, category = key
        rows.append(dict(source_id=source_id, decision=decision, reason_category=category, count=counts[key]))
    return {"note": NOTE, "total_rows": len(files), "counts": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path, metavar="selection.json")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args()
    try:
        doc = json.loads(args.selection.read_bytes())
    except (OSError, ValueError):
        parser.error("cannot read selection JSON")
    files = doc.get("files") if isinstance(doc, dict) else None
    if not isinstance(files, list) or not all(isinstance(row, dict) for row in files):
        parser.error("expected a selection object with a files array of row objects")

    summary = summarize(files)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Total file rows: {summary['total_rows']}")
        print(NOTE)
        print("source_id\tdecision\treason_category\trows")
        for row in summary["counts"]:
            print(row["source_id"] or "(unbound)", row["decision"], row["reason_category"],
                  row["count"], sep="\t")


if __name__ == "__main__":
    main()
