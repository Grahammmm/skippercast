"""Render only allowlisted step outcomes and aggregate daily evidence metadata."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


# Workflow order, including the reports that can fail even if collection never ran.
STAGES = {
    "checkout": "Check out workflow sources",
    "node": "Set up Node",
    "python": "Set up Python",
    "install": "Install reviewed NOAA NetCDF decoder",
    "research": "Load pinned research engine",
    "parser": "Test evidence parsing and failure handling",
    "previous": "Load previous published facts",
    "collect": "Collect and validate public sources",
    "discussion": "Discover recent local fishing discussions",
    "access": "Audit source-document access",
    "coastal": "Refresh statewide regional and seasonal source checks",
    "groundfish": "Refresh NOAA federal groundfish areas",
    "surveys": "Discover NOAA BAG survey leads",
    "products": "Inventory original NOAA survey products",
    "publish": "Publish an atomic data snapshot",
    "verify": "Verify the public site serves this snapshot",
    "report-sources": "Report source health",
    "report-coastal": "Report coastal watch health",
    "report-groundfish": "Report federal groundfish area health",
    "report-discussion": "Report recent discussion coverage",
    "report-regulations": "Report regulation coverage in every region",
    "report-surveys": "Report NOAA survey discovery coverage",
    "report-products": "Report NOAA survey product coverage",
}
OPTIONAL = {"discussion", "groundfish", "surveys", "products"}


def first_failure(outcomes):
    first_optional = None
    for stage, label in STAGES.items():
        if outcomes.get(stage) == "failure":
            if stage not in OPTIONAL:
                return label, first_optional
            if first_optional is None:
                first_optional = label
        elif outcomes.get(stage) not in {"success", "skipped"}:
            # A missing or cancelled earlier step is not proof it passed.
            return "unknown", first_optional
    return "none", first_optional


def read_object(path):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    return obj if isinstance(obj, dict) else {}


def generation(path):
    stamp = read_object(path).get("generated_at")
    if isinstance(stamp, str):
        try:
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass
    return None


def affected_regions(path):
    rows = read_object(path).get("regions")
    if not isinstance(rows, list) or not rows:
        return "unknown"
    statuses = [row.get("status") if isinstance(row, dict) else None for row in rows]
    if not all(status in ("ok", "degraded", "failed") for status in statuses):
        return "unknown"
    return str(sum(status != "ok" for status in statuses))


def release_state(publish, previous, current):
    if publish == "skipped":
        return "retained — this run did not advance the pointer"
    if publish == "success" and previous is not None and current is not None:
        return "retained daily generation" if previous == current else "new daily generation"
    # The Git branch push precedes R2. A failed publisher may have advanced the branch.
    return "unknown"


def render(root, outcomes, now):
    failure, optional = first_failure(outcomes)
    previous = generation(root / "previous.json") if outcomes.get("previous") == "success" else None
    age = "unknown"
    if previous is not None and previous <= now:
        age = f"{int((now - previous).total_seconds() // 60)} min"
    collect = outcomes.get("collect")
    count = affected_regions(root / "daily/regions/index.json") if collect in {"success", "failure"} else "unknown"
    publish = outcomes.get("publish")
    current = generation(root / "published/latest.json") if publish == "success" else None
    verification = {"success": "passed", "failure": "failed", "skipped": "not run"}
    first = f"{optional} (non-blocking)" if optional else failure
    lines = ["", "## Daily evidence refresh", "", f"- First failed stage: {first}"]
    if optional:
        lines.append(f"- First blocking failure: {failure}")
    lines.extend([
        f"- Previous data-branch generation: {previous.isoformat() if previous else 'unknown'}",
        f"- Previous generation age at summary time: {age}",
        f"- Affected regions (degraded or failed in this attempt): {count}",
        f"- Release (data branch): {release_state(publish, previous, current)}",
        f"- Public site verification: {verification.get(outcomes.get('verify'), 'unknown')}",
        "", "Step outcomes identify a stage, not a cause or conditions freshness. "
        "See the [feed freshness runbook](https://github.com/Grahammmm/skippercast/blob/main/docs/operations/runbooks/feed-stale.md).", "",
    ])
    return "\n".join(lines)


def main():
    outcomes = dict(line.split("=", 1) for line in os.environ.get("DAILY_STAGE_OUTCOMES", "").splitlines() if "=" in line)
    summary = render(Path("var"), outcomes, datetime.now(timezone.utc))
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as output:
        output.write(summary)


if __name__ == "__main__":
    main()
