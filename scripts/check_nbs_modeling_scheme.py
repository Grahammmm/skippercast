"""Fetch the pinned NOAA NBS Modeling scheme and flag newer unreviewed versions."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen
import xml.etree.ElementTree as ET

from scripts.audit_nbs_modeling_tile import verified_file


HOST = "noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com"
PREFIX = "Test-and-Evaluation/Modeling/_Modeling_Tile_Scheme/"


def latest_key(raw):
    root = ET.fromstring(raw)
    namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    if root.findtext("s3:IsTruncated", namespaces=namespace) != "false":
        raise ValueError("Incomplete NOAA NBS scheme listing")
    keys = [element.text for element in root.findall("s3:Contents/s3:Key", namespace)]
    candidates = [key for key in keys if key and key.startswith(PREFIX)
                  and key.rsplit("/", 1)[-1].startswith("Modeling_Tile_Scheme_")
                  and key.endswith(".gpkg")]
    if not candidates:
        raise ValueError("No NOAA NBS Modeling tile scheme found")
    return max(candidates)


def check(manifest, cache, *, list_bytes=None):
    if manifest.get("schema_version") != 1 or manifest.get("scope") != "reviewed-noaa-nbs-modeling-tile-scheme":
        raise ValueError("Unexpected NBS scheme manifest")
    scheme_url = manifest["scheme_url"]
    listed_url = manifest["bucket_list_url"]
    if (urlparse(scheme_url).hostname != HOST or urlparse(listed_url).hostname != HOST
            or not urlparse(scheme_url).path.lstrip("/").startswith(PREFIX)
            or not listed_url.endswith("max-keys=1000")):
        raise ValueError("Unreviewed NBS scheme source")
    verified_file(scheme_url, manifest["scheme_sha256"], cache, True)
    if list_bytes is None:
        with urlopen(listed_url, timeout=30) as response:
            list_bytes = response.read(2_000_001)
        if len(list_bytes) > 2_000_000:
            raise ValueError("Oversized NOAA NBS scheme listing")
    latest = latest_key(list_bytes)
    pinned = urlparse(scheme_url).path.lstrip("/")
    if latest < pinned:
        raise ValueError("Pinned NBS scheme is newer than provider listing")
    return {"schema_version": 1, "scope": "nbs-modeling-scheme-health",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "pinned_scheme_url": scheme_url, "pinned_scheme_sha256": manifest["scheme_sha256"],
            "latest_listed_scheme_key": latest,
            "status": "current" if latest == pinned else "new-scheme-needs-review",
            "automatic_fishing_target_promotion": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("catalog/nbs-modeling-sample.json"))
    parser.add_argument("--cache", type=Path, default=Path("var/nbs-cache/modeling-tile-scheme.gpkg"))
    parser.add_argument("--output", type=Path, default=Path("var/review/nbs-modeling-scheme-health.json"))
    args = parser.parse_args()
    result = check(json.loads(args.manifest.read_text()), args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"], result["latest_listed_scheme_key"])


if __name__ == "__main__":
    main()
