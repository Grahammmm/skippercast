"""Report saved synthetic QA asset attribution, not visual QA or release clearance.

Run ``python -m scripts.relief.socal_child_asset_join metadata.json`` from the
repo root. The JSON document has an ``assets`` list of objects with explicit
``asset_id``, ``camera_id`` and ``child_id`` strings. Asset IDs are opaque:
this report does not open image files or inspect their bytes.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from scripts.relief.socal_camera_context import camera_context
from skippercast.relief.package import decode_document


def join_saved_assets(metadata: Path) -> dict:
    """Return one row per mapped camera/child pair; an empty list means no match."""
    records = decode_document(metadata.read_bytes()).get("assets")
    if not isinstance(records, list):
        raise ValueError("Expected an assets list in saved QA metadata")
    by_camera_child: dict[tuple[str, str], list[str]] = defaultdict(list)
    fields = ("camera_id", "child_id", "asset_id")
    for row in records:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(field), str) and row[field].strip() for field in fields
        ):
            raise ValueError("Each QA asset requires explicit camera_id, child_id and asset_id")
        by_camera_child[row["camera_id"], row["child_id"]].append(row["asset_id"])

    context = camera_context()
    return {
        "release_id": context["release_id"],
        "rows": [
            {"camera_id": camera["id"], "child_id": child_id,
             "asset_ids": by_camera_child.get((camera["id"], child_id), [])}
            for camera in context["cameras"]
            for child_id in camera["contributors"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Join saved synthetic QA asset metadata to SoCal cameras.")
    parser.add_argument("metadata", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(join_saved_assets(args.metadata), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
