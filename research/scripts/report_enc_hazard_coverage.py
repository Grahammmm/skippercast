"""Report NOAA ENC danger-layer coverage for the research inventory job.

Fail closed on a missing, corrupt or incomplete snapshot. Only an explicit
``upstream_unavailable`` receipt written by ``refresh_enc_hazards.py`` (after
its bounded retries exhausted against NOAA's transient "Could not find service"
500) downgrades a scope to a warning instead of a failure. Absence alone is
never accepted as an outage: the receipt must exist and name the scope.

The workflow entry point (``main``) uses ``report_bound``, which additionally
binds every scope to its current-invocation run-status record written by the
refresh command. A terminal ``success`` or ``upstream_unavailable`` status is
the only thing that satisfies a run; a missing, corrupt, mismatched, in-progress
or failed status fails closed, so a stale snapshot or receipt from an earlier
invocation can never stand in for this one.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

SCOPES = ("santa-barbara-island", "point-reyes-tomales", "h11967-greenwood-tile")
EXPECTED_RECEIPTS = 18
RUN_STATUS_SUFFIX = ".run-status.json"
TERMINAL_SUCCESS = "success"
TERMINAL_UNAVAILABLE = "upstream_unavailable"


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


def _status_record_ok(status, scope):
    return (isinstance(status, dict)
            and status.get("schema_version") == 1
            and status.get("scope_id") == scope
            and isinstance(status.get("checked_at"), str)
            and status.get("checked_at"))


def report_bound(directory, scopes=SCOPES):
    """Bind each scope to its current-invocation run status and report it.

    This is the workflow-selected reporter. Per scope the authoritative current
    status must be terminal (``success`` or ``upstream_unavailable``) and its
    ``checked_at`` must match the artifact it names; anything else — missing,
    corrupt, mismatched, in-progress or failed — fails closed. A current outage
    is reported even when a historical valid snapshot is still on disk (that
    snapshot is only labeled last-known), and a later success retires an
    obsolete active outage without erasing its receipt.
    """
    lines = ["\n## NOAA ENC danger review"]
    unhealthy = []
    for scope in scopes:
        status_path = Path(directory) / (scope + RUN_STATUS_SUFFIX)
        snapshot = Path(directory) / (scope + ".geojson")
        receipt = Path(directory) / (scope + ".unavailable.json")
        if not status_path.is_file():
            lines.append(f"{scope}: no current invocation status (missing/in-progress/failed)")
            unhealthy.append(scope)
            continue
        try:
            status = json.loads(status_path.read_text())
        except (ValueError, OSError):
            lines.append(f"{scope}: corrupt current invocation status")
            unhealthy.append(scope)
            continue
        state = status.get("status") if isinstance(status, dict) else None
        if state == TERMINAL_SUCCESS:
            if not _status_record_ok(status, scope):
                lines.append(f"{scope}: mismatched current success status")
                unhealthy.append(scope)
                continue
            if not snapshot.is_file():
                lines.append(f"{scope}: current success status without its snapshot")
                unhealthy.append(scope)
                continue
            try:
                data = json.loads(snapshot.read_text())
            except (ValueError, OSError):
                lines.append(f"{scope}: corrupt snapshot for current success status")
                unhealthy.append(scope)
                continue
            if not snapshot_ok(data, scope) or data.get("checked_at") != status.get("checked_at"):
                lines.append(f"{scope}: snapshot mismatched with current invocation status")
                unhealthy.append(scope)
                continue
            lines.append(f"{scope}: {len(data['features'])} charted features across "
                         f"{EXPECTED_RECEIPTS} complete layer queries; retrieved "
                         f"{data['checked_at']}. Not navigation clearance.")
            continue
        if state == TERMINAL_UNAVAILABLE:
            if not _status_record_ok(status, scope):
                lines.append(f"{scope}: mismatched current upstream-unavailable status")
                unhealthy.append(scope)
                continue
            if not receipt.is_file():
                lines.append(f"{scope}: current upstream-unavailable status without its receipt")
                unhealthy.append(scope)
                continue
            try:
                data = json.loads(receipt.read_text())
            except (ValueError, OSError):
                lines.append(f"{scope}: corrupt outage receipt for current status")
                unhealthy.append(scope)
                continue
            if not receipt_unavailable(data, scope) or data.get("checked_at") != status.get("checked_at"):
                lines.append(f"{scope}: outage receipt mismatched with current invocation status")
                unhealthy.append(scope)
                continue
            lines.append(f"{scope}: upstream_unavailable - NOAA ENC Direct did not answer "
                         f"after bounded retries; no charted-danger snapshot this run "
                         f"({data.get('checked_at')}). Not navigation clearance.")
            if snapshot.is_file():
                try:
                    prior = json.loads(snapshot.read_text())
                except (ValueError, OSError):
                    prior = None
                if isinstance(prior, dict) and snapshot_ok(prior, scope):
                    lines.append(f"{scope}: last-known charted-danger snapshot from "
                                 f"{prior['checked_at']} (precedes the current outage; not current).")
            continue
        if state in ("in-progress", "failed"):
            lines.append(f"{scope}: current invocation status is {state} (not a terminal outcome)")
            unhealthy.append(scope)
            continue
        lines.append(f"{scope}: nonterminal or unexpected current invocation status")
        unhealthy.append(scope)
    return lines, unhealthy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("var/research-daily/enc-hazards"))
    args = parser.parse_args()
    lines, unhealthy = report_bound(args.directory)
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
