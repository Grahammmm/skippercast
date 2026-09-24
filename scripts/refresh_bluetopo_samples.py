"""Recheck pinned BlueTopo source samples; hold newer schemes for review."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen
import xml.etree.ElementTree as ET

from scripts.audit_bluetopo_tile import audit
from scripts.audit_nbs_modeling_tile import sha256, verified_file


BUCKET = "https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/"
SCHEME_PREFIX = "BlueTopo/_BlueTopo_Tile_Scheme/"


def listed_schemes(raw):
    root = ET.fromstring(raw)
    namespace = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    if root.findtext("s:IsTruncated", namespaces=namespace) == "true":
        raise ValueError("BlueTopo scheme listing is truncated")
    return sorted(node.text for node in root.findall("s:Contents/s:Key", namespace)
                  if node.text and node.text.startswith(SCHEME_PREFIX)
                  and node.text.endswith(".gpkg"))


def refresh(manifest, cache):
    tiles = manifest["tile_ids"]
    if not tiles or len(tiles) != len(set(tiles)):
        raise ValueError("BlueTopo sample tile IDs are empty or repeated")
    sector_tiles = manifest.get("sector_tile_ids")
    if sector_tiles is not None and (len(sector_tiles) != len(tiles) or set(sector_tiles.values()) != set(tiles)):
        raise ValueError("BlueTopo sample does not identify one distinct tile per review sector")
    scheme_url = manifest["scheme_url"]
    if (urlparse(scheme_url).scheme != "https"
            or urlparse(scheme_url).hostname != "noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com"
            or not urlparse(scheme_url).path.lstrip("/").startswith(SCHEME_PREFIX)):
        raise ValueError("BlueTopo scheme is outside the reviewed NOAA source")
    scheme = cache / Path(urlparse(scheme_url).path).name
    verified_file(scheme_url, manifest["scheme_sha256"], scheme, True)
    listing_url = BUCKET + "?" + urlencode({"list-type": "2", "prefix": SCHEME_PREFIX, "max-keys": 1000})
    with urlopen(listing_url, timeout=30) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Oversized BlueTopo scheme listing")
    listed = listed_schemes(raw)
    if not listed:
        raise ValueError("BlueTopo scheme listing incomplete")
    current = scheme_url.removeprefix(BUCKET)
    if current not in listed:
        raise ValueError("Pinned BlueTopo scheme missing from publisher listing")
    rows = [audit(scheme, tile, cache, fetch=True) for tile in tiles]
    if any(row["fishing_target"] or row["exportable"] for row in rows):
        raise ValueError("BlueTopo source review cannot publish fishing targets")
    return {"schema_version": 1, "scope": "bluetopo-pinned-source-sample-refresh",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "pinned_scheme_url": scheme_url, "pinned_scheme_sha256": sha256(scheme),
            "latest_listed_scheme_key": listed[-1], "newer_scheme_available": listed[-1] != current,
            "selection_basis": manifest.get("selection_basis"),
            "sector_tile_ids": sector_tiles, "tiles": rows,
            "fishing_target": False, "exportable": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("catalog/bluetopo-statewide-sample.json"))
    parser.add_argument("--cache", type=Path, default=Path("var/bluetopo-cache"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = refresh(json.loads(args.manifest.read_text()), args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(len(result["tiles"]), "source tiles audited; newer scheme:", result["newer_scheme_available"])


if __name__ == "__main__":
    main()
