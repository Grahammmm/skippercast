"""Report NOAA ENC danger-layer coverage for the research inventory job.

Fail closed on a missing, corrupt or incomplete snapshot. Only an explicit
``upstream_unavailable`` receipt written by ``refresh_enc_hazards.py`` (after
its bounded retries exhausted against NOAA's transient "Could not find service"
500) downgrades a scope to a warning instead of a failure. Absence alone is
never accepted as an outage: the receipt must exist and name the scope.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

SCOPES = ("santa-barbara-island", "point-reyes-tomales", "h11967-greenwood-tile")
EXPECTED_RECEIPTS = 18


def snapshot_ok(data, scope):
    return (data.get("status") == "charted-danger-screen-only"
            and data.get("scope_id") == scope
            and len(data.get("query_receipts", [])) == EXPECTED_RECEIPTS)


def receipt_unavailable(data, scope):
    return (data.get("status") == "upstream_unavailable"
            and data.get("scope_id") == scope)


def report(directory, scopes=SCOPES):
    """Return (lines, unhealthy). Writes nothing; the caller prints/summarizes."""
    lines = ["\n## NOAA ENC danger review"]
    unhealthy = []
    for scope in scopes:
        snapshot = Path(directory) / (scope + ".geojson")
        receipt = Path(directory) / (scope + ".unavailable.json")
        if snapshot.is_file():
            try:
                data = json.loads(snapshot.read_text())
            except (ValueError, OSError):
                lines.append(f"{scope}: corrupt snapshot")
                unhealthy.append(scope)
                continue
            if snapshot_ok(data, scope):
                lines.append(f"{scope}: {len(data['features'])} charted features across "
                             f"{EXPECTED_RECEIPTS} complete layer queries; retrieved "
                             f"{data['checked_at']}. Not navigation clearance.")
                continue
            lines.append(f"{scope}: incomplete or unexpected snapshot")
            unhealthy.append(scope)
            continue
        if receipt.is_file():
            try:
                data = json.loads(receipt.read_text())
            except (ValueError, OSError):
                lines.append(f"{scope}: corrupt outage receipt")
                unhealthy.append(scope)
                continue
            if receipt_unavailable(data, scope):
                lines.append(f"{scope}: upstream_unavailable - NOAA ENC Direct did not answer "
                             f"after bounded retries; no charted-danger snapshot this run "
                             f"({data.get('checked_at')}). Not navigation clearance.")
                continue
            lines.append(f"{scope}: unexpected outage receipt")
            unhealthy.append(scope)
            continue
        lines.append(f"{scope}: no NOAA ENC danger-layer snapshot produced")
        unhealthy.append(scope)
    return lines, unhealthy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("var/research-daily/enc-hazards"))
    args = parser.parse_args()
    lines, unhealthy = report(args.directory)
    text = "\n".join(lines) + "\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write(text)
    if unhealthy:
        raise SystemExit("NOAA ENC danger-layer review incomplete: " + ", ".join(unhealthy))


if __name__ == "__main__":
    main()
