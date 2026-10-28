"""Report NOAA ENC danger-layer coverage for the research inventory job.

Fail closed on a missing, corrupt or incomplete snapshot. Only an explicit
``upstream_unavailable`` receipt written by ``refresh_enc_hazards.py`` (after
its bounded retries exhausted against NOAA's transient "Could not find service"
500) downgrades a scope to a warning instead of a failure. Absence alone is
never accepted as an outage: the receipt must exist and name the scope.

The workflow entry point (``main``) uses ``report_bound``, which additionally
binds every scope to the run-status record written by the refresh command for
the *expected invocation* (one workflow run attempt, or one named local run).
A scope is healthy only when its status names exactly that invocation, is
terminal (``success`` or ``upstream_unavailable``), and names the expected
artifact whose bytes match the recorded SHA-256 and whose ``checked_at`` and
scope match the status. Anything else - no expected invocation, a status from a
different run or attempt, missing, corrupt, in-progress or failed status, or a
missing, renamed, replaced or mismatched artifact - fails closed, so output
left by an earlier run or attempt can never stand in for this one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

SCOPES = ("santa-barbara-island", "point-reyes-tomales", "h11967-greenwood-tile")
EXPECTED_RECEIPTS = 18
RUN_STATUS_SUFFIX = ".run-status.json"
TERMINAL_SUCCESS = "success"
TERMINAL_UNAVAILABLE = "upstream_unavailable"

# Must match refresh_enc_hazards.resolve_invocation (pinned by a parity test).
INVOCATION_ENV = "ENC_INVOCATION_ID"
INVOCATION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def resolve_invocation(explicit=None, environ=None):
    """Return the expected invocation identity, or None when none is defined.

    Order: explicit ``--invocation``, then ``ENC_INVOCATION_ID``, then GitHub
    Actions' ``github:<GITHUB_RUN_ID>:<GITHUB_RUN_ATTEMPT>``.
    """
    environ = os.environ if environ is None else environ
    candidate = explicit if explicit is not None else (environ.get(INVOCATION_ENV) or None)
    if candidate is None:
        run_id, attempt = environ.get("GITHUB_RUN_ID"), environ.get("GITHUB_RUN_ATTEMPT")
        if not (run_id and attempt):
            return None
        candidate = f"github:{run_id}:{attempt}"
    if not isinstance(candidate, str) or not INVOCATION_PATTERN.fullmatch(candidate):
        raise ValueError("Invalid ENC invocation identity")
    return candidate


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


def _load_bound_artifact(directory, scope, status, expected_name):
    """Return (data, problem). ``problem`` is None only for a bound artifact.

    The status must name exactly ``expected_name``; the file must exist, hash
    to the recorded ``artifact_sha256``, parse as a JSON object and carry the
    status's ``scope_id`` and ``checked_at``.
    """
    if (status.get("schema_version") != 1 or status.get("scope_id") != scope
            or not isinstance(status.get("checked_at"), str) or not status.get("checked_at")):
        return None, "mismatched current invocation status"
    if status.get("artifact") != expected_name:
        return None, (f"status names artifact {status.get('artifact')!r}, "
                      f"expected {expected_name!r}")
    digest = status.get("artifact_sha256")
    if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
        return None, "status has no valid artifact_sha256"
    path = Path(directory) / expected_name
    if not path.is_file():
        return None, f"current status without its artifact {expected_name}"
    try:
        raw = path.read_bytes()
    except OSError:
        return None, f"unreadable artifact {expected_name}"
    if hashlib.sha256(raw).hexdigest() != digest:
        return None, f"artifact {expected_name} does not match the status SHA-256"
    try:
        data = json.loads(raw)
    except ValueError:
        return None, f"corrupt artifact {expected_name}"
    if (not isinstance(data, dict) or data.get("scope_id") != scope
            or data.get("checked_at") != status.get("checked_at")):
        return None, f"artifact {expected_name} mismatched with current invocation status"
    return data, None


def report_bound(directory, scopes=SCOPES, *, invocation):
    """Bind each scope to the expected invocation's run status and report it.

    This is the workflow-selected reporter. ``invocation`` is the identity this
    run expects (see ``resolve_invocation``); it is required. A current outage
    is reported even when a historical valid snapshot is still on disk (that
    snapshot is only labeled last-known), and a later success retires an
    obsolete active outage without erasing its receipt.
    """
    if not isinstance(invocation, str) or not INVOCATION_PATTERN.fullmatch(invocation):
        raise ValueError("report_bound requires a valid expected invocation identity")
    lines = [f"\n## NOAA ENC danger review (invocation {invocation})"]
    unhealthy = []
    for scope in scopes:
        status_path = Path(directory) / (scope + RUN_STATUS_SUFFIX)
        snapshot = Path(directory) / (scope + ".geojson")
        if not status_path.is_file():
            lines.append(f"{scope}: no current invocation status (missing/in-progress/failed)")
            unhealthy.append(scope)
            continue
        try:
            status = json.loads(status_path.read_text())
        except (ValueError, OSError):
            status = None
        if not isinstance(status, dict):
            lines.append(f"{scope}: corrupt current invocation status")
            unhealthy.append(scope)
            continue
        recorded = status.get("invocation")
        if recorded != invocation:
            lines.append(f"{scope}: status belongs to invocation {recorded!r}, not the current "
                         f"{invocation!r}; this run did not refresh the scope")
            unhealthy.append(scope)
            continue
        state = status.get("status")
        if state == TERMINAL_SUCCESS:
            data, problem = _load_bound_artifact(directory, scope, status, scope + ".geojson")
            if problem is None and not snapshot_ok(data, scope):
                problem = "incomplete or unexpected snapshot for current success status"
            if problem is not None:
                lines.append(f"{scope}: {problem}")
                unhealthy.append(scope)
                continue
            lines.append(f"{scope}: {len(data['features'])} charted features across "
                         f"{EXPECTED_RECEIPTS} complete layer queries; retrieved "
                         f"{data['checked_at']}. Not navigation clearance.")
            continue
        if state == TERMINAL_UNAVAILABLE:
            data, problem = _load_bound_artifact(directory, scope, status,
                                                 scope + ".unavailable.json")
            if problem is None and (not receipt_unavailable(data, scope)
                                    or data.get("invocation") != invocation):
                problem = "outage receipt mismatched with current invocation status"
            if problem is not None:
                lines.append(f"{scope}: {problem}")
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
                                 f"{prior.get('checked_at')} (precedes the current outage; not current).")
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
    parser.add_argument("--invocation",
        help="Expected run identity (default: $ENC_INVOCATION_ID, "
             "else github:$GITHUB_RUN_ID:$GITHUB_RUN_ATTEMPT)")
    args = parser.parse_args()
    invocation = resolve_invocation(args.invocation)
    if invocation is None:
        lines = ["\n## NOAA ENC danger review",
                 "No expected invocation identity: pass --invocation, set "
                 "ENC_INVOCATION_ID, or run inside GitHub Actions."]
        unhealthy = list(SCOPES)
    else:
        lines, unhealthy = report_bound(args.directory, invocation=invocation)
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
