"""Read committed ledger evidence without rebuilding surveys or claiming live publication."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sys


def render(ledger):
    if not isinstance(ledger, dict):
        raise ValueError("Ledger is not an object")
    if not isinstance(ledger.get("input_hash"), str) or not ledger["input_hash"]:
        raise ValueError("Ledger input_hash missing or not text")
    reaches = ledger.get("reaches")
    if not isinstance(reaches, list) or not reaches:
        raise ValueError("Missing reach coverage")
    grouped = defaultdict(list)
    seen = set()
    for i, reach in enumerate(reaches):
        if not isinstance(reach, dict):
            raise ValueError(f"Reach {i} is not an object")
        for key in ("id", "region"):
            if not isinstance(reach.get(key), str) or not reach[key]:
                raise ValueError(f"Reach {i} missing {key}")
        if "status" in reach and not isinstance(reach["status"], str):
            raise ValueError(f"Reach {i} status not text")
        if "screen" in reach and not isinstance(reach["screen"], dict):
            raise ValueError(f"Reach {i} screen not an object")
        if reach["id"] in seen:
            raise ValueError("Duplicate reach")
        seen.add(reach["id"])
        for field in ("tier1_km2", "tier2_km2", "selected_valid_km2"):
            value = reach.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Missing or invalid measured coverage: " + field)
        grouped[reach["region"]].append(reach)
    lines = ["# Committed seafloor status", "",
             "Ledger input hash: `" + ledger["input_hash"] + "`", "",
             "| Region | Reaches | Valid survey reaches | Screen-ready with habitat | Other states | Tier 1 km² | Tier 2 km² | Live publication |",
             "| --- | ---: | ---: | ---: | --- | ---: | ---: | --- |"]
    for region, rows in sorted(grouped.items()):
        states = defaultdict(int)
        for row in rows:
            states[row.get("status", "unknown")] += 1
        lines.append("| " + " | ".join([
            region, str(len(rows)), str(sum(r["selected_valid_km2"] > 0 for r in rows)),
            str(sum(r.get("screen", {}).get("status") == "ready" and r["tier2_km2"] > 0 for r in rows)),
            ", ".join(f"{k}: {v}" for k, v in sorted(states.items())),
            f'{sum(r["tier1_km2"] for r in rows):.6f}',
            f'{sum(r["tier2_km2"] for r in rows):.6f}', "Not verified by this report"]) + " |")
    lines += ["", f"Total reaches: {len(reaches)}.", "",
              "Tier areas are ledger measurements, not catch probability. A screened status",
              "with zero selected survey area is not useful measured coverage. Screen-ready",
              "counts describe saved screens, not current season/gear clearance. Publication",
              "requires current manifest/hash and live HTTP/range receipts; this offline report",
              "does not contact storage or infer publication from processing state.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=Path("dist/data/seafloor-ledger.json"))
    args = parser.parse_args()
    try:
        report = render(json.loads(args.ledger.read_text()))
    except OSError as error:
        sys.exit(f"seafloor_status: {type(error).__name__}: {error.strerror or 'read failed'}")
    except ValueError as error:
        sys.exit(f"seafloor_status: {error}")
    print(report, end="")
