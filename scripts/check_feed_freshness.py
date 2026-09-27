#!/usr/bin/env python3
"""Fail when the published live-conditions feed is older than allowed.

The live job publishes to the `conditions` branch every 30 minutes. If it stops
(failing tests, a broken source, an expired token), the app keeps serving the
last generation and nothing looks wrong. This check turns that silence into a
visible failure and a GitHub issue.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import sys
from urllib.request import Request, urlopen

FEED = "https://raw.githubusercontent.com/Grahammmm/skippercast/conditions/latest.json"


def feed_age(feed, now):
    """Return the age of a published feed, or raise ValueError if it is unreadable."""
    stamp = feed.get("completed_at") or feed.get("generated_at")
    if not isinstance(stamp, str):
        raise ValueError("feed has no completion time")
    completed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if completed.tzinfo is None:
        raise ValueError("feed completion time has no timezone")
    return now - completed


def verdict(feed, now, max_age):
    """Return (ok, message)."""
    try:
        age = feed_age(feed, now)
    except (ValueError, TypeError) as error:
        return False, f"Live conditions feed is unreadable: {error}"
    hours = age.total_seconds() / 3600
    if age > max_age:
        return False, (f"Live conditions feed is stale: last published {feed['completed_at']} "
                       f"({hours:.1f} h ago; limit {max_age.total_seconds() / 3600:.0f} h).")
    return True, f"Live conditions feed is fresh: published {hours:.1f} h ago."


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=FEED)
    parser.add_argument("--max-age-hours", type=float, default=3)
    args = parser.parse_args()
    try:
        request = Request(args.url, headers={"User-Agent": "SkipperCast-freshness-check/1.0"})
        with urlopen(request, timeout=30) as response:
            feed = json.load(response)
    except Exception as error:  # network, HTTP or JSON failure all mean "not confirmed fresh"
        ok, message = False, f"Live conditions feed could not be fetched: {error}"
    else:
        ok, message = verdict(feed, datetime.now(timezone.utc), timedelta(hours=args.max_age_hours))
    print(message)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
