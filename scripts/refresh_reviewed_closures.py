"""Recheck regional closure snapshots without silently accepting boundary changes.

The reviewed geometry remains authoritative for this release only while a fresh
official response matches it exactly. A changed response requires a new review.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from skippercast.platform.contracts import atomic_json, read_json


def fetch(url):
    if not url.startswith((
        "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?",
        "https://www.fisheries.noaa.gov/s3/",
    )):
        raise ValueError("Closure source is not on the reviewed official allowlist")
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast closure verification"}), timeout=45) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("Closure source redirected or returned an unexpected status")
        raw = response.read(6_000_001)
    if not raw or len(raw) > 6_000_000:
        raise ValueError("Closure response is empty or oversized")
    return raw


def refresh(region):
    base = ROOT / "dist" / "regions" / region
    results = []
    for filename in ("protected-areas.geojson", "groundfish-exclusions.geojson"):
        path = base / filename
        snapshot = read_json(path)
        if snapshot.get("region_id") != region or not snapshot.get("features"):
            raise ValueError("Wrong-region or empty closure snapshot: " + filename)
        raw = fetch(snapshot["source_url"])
        digest = hashlib.sha256(raw).hexdigest()
        if filename == "protected-areas.geojson":
            fresh = json.loads(raw)
            if fresh.get("exceededTransferLimit") or fresh.get("features") != snapshot["features"]:
                raise ValueError("Official MPA geometry changed; review required")
        elif digest != snapshot.get("source_sha256"):
            raise ValueError("Official federal closure coordinates changed; review required")
        results.append((path, snapshot, digest))
    checked = datetime.now(timezone.utc).isoformat()
    for path, snapshot, digest in results:
        snapshot["checked_at"] = checked
        snapshot["verification_sha256"] = digest
        atomic_json(path, snapshot)
    return {"region_id": region, "checked_at": checked, "sources": [
        {"path": str(path.relative_to(ROOT)), "features": len(snapshot["features"]), "sha256": digest}
        for path, snapshot, digest in results]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="southern-california")
    print(json.dumps(refresh(parser.parse_args().region)))
