"""Pin CSUMB public-data policy and original BSS/SCC source terms.

The general data-library policy is not a license for a particular original
archive. This audit keeps the producer policy and source metadata separate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

from skippercast.platform.contracts import atomic_json


POLICY = "https://csumb.edu/undersea/sfml-data-library/"
BSS = ("https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/"
       "BSS_Block01/multibeam/data/version1/metadata/BigSurSouth_BSS_Project.xml")
SCC = ("https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/"
       "SCC_Block04/multibeam/data/version1/metadata/SCC_CSMP_Metadata.txt")
ARCHIVES = {
    "csumb-bss-block01-native-candidate": "BSS",
    "csumb-bss-block02-native-candidate": "BSS",
    "csumb-bss-block03-native-candidate": "BSS",
    "csumb-bss-block12-native-candidate": "BSS",
    "csumb-bss-block13-native-candidate": "BSS",
    "csumb-scc-block04-native-candidate": "SCC",
    "csumb-scc-block05-native-candidate": "SCC",
    "csumb-scc-block06-native-candidate": "SCC",
}


def fetch(url: str) -> bytes:
    if url not in (POLICY, BSS, SCC):
        raise ValueError("Source policy URL is outside reviewed primary publishers")
    req = urllib.request.Request(url, headers={"User-Agent": "SkipperCast source policy audit/1.0"})
    with urllib.request.urlopen(req, timeout=35) as response:
        if response.status != 200:
            raise ValueError("Official source policy unavailable")
        raw = response.read(500_001)
    if not raw or len(raw) > 500_000:
        raise ValueError("Official source policy missing or too large")
    return raw


def audit(policy_raw: bytes, bss_raw: bytes, scc_raw: bytes) -> dict:
    policy = policy_raw.decode("utf-8", "replace")
    bss = bss_raw.decode("utf-8", "replace")
    scc = scc_raw.decode("utf-8", "replace")
    required_policy = ("These data are not copyrighted",
                       "Data used in this study were acquired, processed, archived, and distributed by the Seafloor Mapping Lab",
                       "for-profit enterprise is not authorized without the express permission",
                       "NOT to be used for navigational purposes")
    if any(phrase not in policy for phrase in required_policy):
        raise ValueError("CSUMB public-data policy changed")
    if (bss.count("To be determined by Seafloor Mapping Lab- California State University Monterey Bay and contractor(s)") < 2
            or "<accconst>" not in bss or "<useconst>" not in bss):
        raise ValueError("Original Big Sur South archive terms changed")
    if "Seafloor Mapping Lab at California State University Monterey Bay" not in scc:
        raise ValueError("Original South Central Coast producer metadata changed")
    return {
        "schema_version": 1,
        "scope": "csumb-original-source-use-policy-review",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_pages": [
            {"url": POLICY, "sha256": hashlib.sha256(policy_raw).hexdigest(), "role": "current producer data-library policy"},
            {"url": BSS, "sha256": hashlib.sha256(bss_raw).hexdigest(), "role": "original Big Sur South project metadata"},
            {"url": SCC, "sha256": hashlib.sha256(scc_raw).hexdigest(), "role": "original South Central Coast project metadata"},
        ],
        "affected_candidate_ids": sorted(ARCHIVES),
        "producer_policy": {
            "copyright_claim": "not copyrighted",
            "public_use": "available for public use with requested producer attribution",
            "for_profit_use": "not authorized without express CSUMB permission",
            "navigation": "not for navigation",
        },
        "bss_source_specific_access_and_use": "to be determined by producer and contractors",
        "scc_source_specific_license": "not stated in inspected informal metadata",
        "website_redistribution_cleared": False,
        "fishing_target": False,
        "exportable": False,
        "limitations": "General CSUMB data-library policy and NOAA archive access do not resolve the original BSS project's expressly undetermined use constraints or establish a specific license for SCC derived products. This receipt grants no public derived-grid publication, commercial use, chart depth or fishing location.",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--verify", type=Path)
    a = p.parse_args()
    result = audit(fetch(POLICY), fetch(BSS), fetch(SCC))
    if a.verify:
        old = json.loads(a.verify.read_text())
        normalized = lambda row: {k: v for k, v in row.items() if k != "checked_at"}
        if normalized(result) != normalized(old):
            raise ValueError("Official CSUMB source-policy pages changed; review before promotion")
    atomic_json(a.output, result)
    print(json.dumps({"candidate_sources": len(ARCHIVES), "website_redistribution_cleared": False}))


if __name__ == "__main__":
    main()
