#!/usr/bin/env python3
"""Raise a stale published feed to the team once, then age it (SC-LAUNCH-6).

Reads the `stale_feeds` events that scripts/check_feed_freshness.py --report writes (one per stale feed, never one
per missing record) and keeps one GitHub issue per feed per staleness event, labelled `feed-stale`:

  * first seen  -> the issue is opened. Its body is the one alert line: feed name, last successful publish, how late.
  * still stale -> one comment `still: N h ...` per STILL_HOURS since the issue opened, never one per hourly check.
                   A second pass inside the same interval changes nothing (the comments are the state).
  * recovered   -> the issue is closed with a comment saying how long the feed was stale.

Same shape as AgentOrange's bin/unitfeed.py + bin/alertowner.py (modes/ALERTS.log: one line when first seen, a
`still: N h` line on a fixed interval, a closed line). Runs from the hourly Live feed freshness workflow
(.github/workflows/feed-freshness.yml); it replaces that workflow's old "comment the whole message every hour" and
"close everything" stale-feed steps. The issue lands in the repository's notifications: the owner and anyone
watching the repo see it.

Usage: feed_stale_alert.py --report FILE [--stale true|false] [--dry-run]
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys

LABEL = "feed-stale"
TITLE = "Published feed is stale: "
STILL_HOURS = 6
RUNBOOK = "docs/operations/runbooks/feed-stale.md"


def parse(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def describe(event):
    """The alert text for one event: feed, last successful publish, how late."""
    feed = event["feed"]
    if event.get("last_published") is None:
        reason = f" ({event['reason']})" if event.get("reason") else ""
        return f"STALE {feed}: no readable publish time{reason}; cannot say when it last published."
    return (f"STALE {feed}: last published {event['last_published']} ({event['age_hours']:.1f} h ago), "
            f"{event['late_hours']:.1f} h past its {event['limit_hours']:g} h limit.")


def still_line(event, opened_hours):
    return f"still: {opened_hours:d} h - {describe(event)}"


def plan(events, issues, now, still_hours=STILL_HOURS):
    """Decide the actions for one pass. events: stale_feeds list; issues: open feed-stale issues
    [{number, title, createdAt, comments: [{body}]}]. Returns [("create"|"comment"|"close", payload...)]."""
    by_title = {i["title"]: i for i in issues}
    actions, wanted = [], set()
    for event in events:
        title = TITLE + event["feed"]
        wanted.add(title)
        issue = by_title.get(title)
        if issue is None:
            actions.append(("create", title, describe(event)))
            continue
        opened = (now - parse(issue["createdAt"])).total_seconds() / 3600
        due = math.floor(opened / still_hours)
        done = sum(1 for c in issue.get("comments", []) if c.get("body", "").startswith("still: "))
        if due > done:
            actions.append(("comment", issue["number"], still_line(event, due * still_hours)))
    for issue in issues:
        if issue["title"] not in wanted:
            hours = (now - parse(issue["createdAt"])).total_seconds() / 3600
            actions.append(("close", issue["number"], f"Recovered: published again after about {hours:.0f} h of alerts."
                            if issue["title"].startswith(TITLE) else "Replaced by one issue per stale feed (SC-LAUNCH-6)."))
    return actions


def gh(*args, **kw):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, **kw).stdout


def open_issues(runner=gh):
    return json.loads(runner("issue", "list", "--label", LABEL, "--state", "open", "--limit", "100",
                             "--json", "number,title,createdAt,comments"))


def apply(actions, runner=gh):
    for action in actions:
        if action[0] == "create":
            body = f"{action[2]}\n\nThis issue is the alert: it is not repeated every hour. A `still: N h` comment follows " \
                   f"every {STILL_HOURS} h while the feed stays stale, and the issue closes when it publishes again.\n\n" \
                   f"Runbook: {RUNBOOK}"
            runner("issue", "create", "--label", LABEL, "--title", action[1], "--body", body)
        elif action[0] == "comment":
            runner("issue", "comment", str(action[1]), "--body", action[2])
        else:
            runner("issue", "close", str(action[1]), "--comment", action[2])


def load_events(path, stale_flag):
    """stale_feeds from the report. A check that crashed before writing one (stale flag true, no events) still
    alerts, as a single `freshness-check` event: fail closed, never silent."""
    try:
        report = json.loads(Path(path).read_text())
        events = report.get("stale_feeds", [])
        stale = bool(report.get("stale"))
    except (OSError, ValueError):
        events, stale = [], stale_flag == "true"
    if stale and not events:
        events = [{"feed": "freshness-check", "last_published": None,
                   "reason": "the freshness check crashed or reported stale without naming a feed"}]
    return events


def main(argv=None, runner=gh, now=None):
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--report", required=True)
    parser.add_argument("--stale", default="false", choices=["true", "false"], help="used only when the report is unreadable")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    actions = plan(load_events(args.report, args.stale), open_issues(runner), now or datetime.now(timezone.utc))
    for action in actions:
        print(" | ".join(str(part) for part in action))
    if not args.dry_run:
        apply(actions, runner)
    print(f"feed_stale_alert: {len(actions)} action(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
