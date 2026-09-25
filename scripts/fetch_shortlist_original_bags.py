"""Cache only the exact NOAA BAGs referenced by a reviewed habitat shortlist."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.inspect_noaa_bag_grids import download


MAX_BYTES = 50_000_000


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def selected_sources(queue: dict, context: dict) -> list[dict]:
    if queue.get("scope") != "original-habitat-site-review-queue" or queue.get("fishing_target") is not False:
        raise ValueError("Research-only shortlist required")
    features = {f["properties"]["id"]: f for f in context.get("features", [])}
    if len(features) != queue["source_context_outlines"]:
        raise ValueError("Incomplete exact source context")
    selected = {}
    for row in queue["research_shortlist"]:
        p = features[row["context_id"]]["properties"]
        if p.get("fishing_target") is not False or p["survey_id"] != row["survey_id"]:
            raise ValueError("Original BAG identity or research gate changed")
        url = p["noaa_bag_url"]
        digest = p["noaa_bag_sha256"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("Unpinned original BAG")
        old = selected.get(url)
        if old is not None and old["sha256"] != digest:
            raise ValueError("Conflicting NOAA source digest")
        selected[url] = {"survey_id": p["survey_id"], "url": url, "sha256": digest}
    return sorted(selected.values(), key=lambda row: (row["survey_id"], row["url"]))


def fetch(queue: dict, context: dict, cache: Path) -> list[dict]:
    receipts = []
    for row in selected_sources(queue, context):
        url = row["url"]
        name = row["survey_id"] + "-" + hashlib.sha256(url.encode()).hexdigest()[:16] + ".bag"
        path = cache / name
        if not path.is_file() or sha(path) != row["sha256"]:
            download(url, path, MAX_BYTES)
        if path.stat().st_size > MAX_BYTES or sha(path) != row["sha256"]:
            raise ValueError("Downloaded original BAG differs from pinned NOAA source")
        receipts.append({"survey_id": row["survey_id"], "url": url,
                         "sha256": row["sha256"], "bytes": path.stat().st_size,
                         "cache_path": str(path)})
    return receipts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queue", required=True, type=Path)
    p.add_argument("--context", required=True, type=Path)
    p.add_argument("--cache", type=Path, default=Path("var/noaa-native-cache"))
    args = p.parse_args()
    rows = fetch(json.loads(args.queue.read_text()), json.loads(args.context.read_text()), args.cache)
    print(json.dumps({"pinned_original_bags": len(rows), "total_bytes": sum(x["bytes"] for x in rows)}))


if __name__ == "__main__":
    main()
