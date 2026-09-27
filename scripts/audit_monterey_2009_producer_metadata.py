#!/usr/bin/env python3
"""Pin the producer's general Monterey 2009 survey metadata without inferring a datum."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


URL = ("https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/"
       "CentralMontereyBay/multibeam/data/version1/metadata/"
       "MontereyPen_BigSur_CSMP_Metadata.txt")
SHA256 = "bf9933a8d24c5a33c8465cf93efd4e0f6f2497236377e2fb1680071fd126e567"


def evaluate(raw: bytes) -> dict:
    actual = hashlib.sha256(raw).hexdigest()
    if actual != SHA256:
        raise ValueError("Producer metadata changed; review before reusing claims")
    text = raw.decode("latin1")
    section = text.split("\r\nMonterey Bay\r\n", 1)[1].split(
        "------------------------------------------", 1)[0]
    required = {
        "survey_dates": "Central MB North\tSeptember 3, 5-11, 2009",
        "sonar": "200 KHz/ 400 KHz Reson 7125 sonar",
        "position_attitude": "Applanix POS/MV 320 v4 system",
        "nominal_position_spec": "position accuracy ± 2m",
        "tide_control": "KGPS altitude data were used to account for tide cycle fluctuations",
        "sound_speed": "sound velocity profiles were collected with an Applied Microsystems SVPlus sound velocimeter",
    }
    missing = [name for name, phrase in required.items() if phrase not in section]
    if missing:
        raise ValueError(f"Producer metadata no longer supports {missing}")
    return {
        "schema_version": 1,
        "scope": "monterey-2009-producer-general-metadata-review",
        "source_url": URL,
        "source_sha256": actual,
        "source_producer": "CSU Monterey Bay Seafloor Mapping Lab",
        "original_survey": "Central Monterey Bay North/South 2009",
        "documented_controls": {
            "sonar": "Reson 7125, 200/400 kHz",
            "navigation_attitude": "Applanix POS/MV 320 v4 with Cnav-enabled NAVCON 2050 GPS",
            "nominal_vessel_position_accuracy_m": 2,
            "tide_method_general": "KGPS altitude used to account for tidal fluctuations",
            "sound_speed": "Applied Microsystems SVPlus profiles",
        },
        "not_established_by_general_metadata": [
            "Which correction and vertical datum were applied to each selected processed GSF line",
            "Output MLLW conversion, epoch, sign and local spatial separation",
            "Achieved bottom-beam horizontal accuracy or source-to-camera registration",
            "Per-beam or gridded upper total propagated depth uncertainty",
            "An independent validation survey or fishable patch clearance",
        ],
        "mllw_depth_qualified": False,
        "fishing_target": False,
        "exportable": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(
        "dist/data/monterey-2009-producer-metadata-review.json"))
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    with urlopen(URL, timeout=30) as response:
        report = evaluate(response.read())
    if args.verify:
        old = json.loads(args.verify.read_text())
        if report != old:
            raise SystemExit("Producer metadata receipt changed; review before promotion")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("Pinned CSUMB general metadata; selected-line datum and upper TPU still unknown")


if __name__ == "__main__":
    main()
