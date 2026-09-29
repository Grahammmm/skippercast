#!/usr/bin/env python3
"""Fail when the public live-conditions feed is older than allowed.

The live job publishes every 30 minutes to R2 (what the site serves) and to the
`conditions` branch. If it stops (failing tests, a broken source, an expired or
revoked token), the app keeps serving the last generation and nothing looks
wrong. This check turns that silence into a visible failure and a GitHub issue.

The public route (`<FEEDS_PUBLIC_BASE>/feeds/conditions/latest.json`) is what
users get, so it decides the result. The GitHub branch copy is fetched second
and its age reported as a secondary signal: a fresh branch next to a stale
public route points at R2 publication.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from urllib.request import Request, urlopen

# The workers.dev host always serves the Worker (and R2). Set FEEDS_PUBLIC_BASE to
# https://skippercast.com once that custom domain is attached (docs/cloudflare.md).
DEFAULT_PUBLIC_BASE = "https://skippercast.g4651.workers.dev"
FEED_PATH = "/feeds/conditions/latest.json"
FEED = "https://raw.githubusercontent.com/Grahammmm/skippercast/conditions/latest.json"


def public_url(base=None):
    base = (base or os.environ.get("FEEDS_PUBLIC_BASE") or DEFAULT_PUBLIC_BASE).rstrip("/")
    return base + FEED_PATH


def feed_time(feed):
    """The feed's publication stamp: published_at, else completed_at/generated_at."""
    return feed.get("published_at") or feed.get("completed_at") or feed.get("generated_at")


def feed_age(feed, now):
    """Return the age of a published feed, or raise ValueError if it is unreadable."""
    stamp = feed_time(feed)
    if not isinstance(stamp, str):
        raise ValueError("feed has no completion time")
    completed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if completed.tzinfo is None:
        raise ValueError("feed completion time has no timezone")
    return now - completed


def verdict(feed, now, max_age, label="Live conditions feed"):
    """Return (ok, message)."""
    try:
        age = feed_age(feed, now)
    except (ValueError, TypeError, AttributeError) as error:
        return False, f"{label} is unreadable: {error}"
    hours = age.total_seconds() / 3600
    run = f", run {feed['run_id']}" if feed.get("run_id") else ""
    if age > max_age:
        return False, (f"{label} is stale: last published {feed_time(feed)} "
                       f"({hours:.1f} h ago{run}; limit {max_age.total_seconds() / 3600:.0f} h).")
    return True, f"{label} is fresh: published {hours:.1f} h ago{run}."


def fetch_json(url):
    request = Request(url, headers={"User-Agent": "SkipperCast-freshness-check/1.0", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def check(url, now, max_age, label, fetch=fetch_json):
    try:
        feed = fetch(url)
    except Exception as error:  # network, HTTP or JSON failure all mean "not confirmed fresh"
        return False, f"{label} could not be fetched: {error}"
    return verdict(feed, now, max_age, label)


def run(public, github, now, max_age, fetch=fetch_json):
    """Check the public route (decisive) and the GitHub copy (reported). Return (ok, message)."""
    ok, public_message = check(public, now, max_age, f"Public conditions feed ({public})", fetch)
    github_ok, github_message = check(github, now, max_age, "GitHub conditions branch", fetch)
    if not github_ok:
        github_message += " (secondary signal)"
    return ok, public_message + "\n" + github_message


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--public-base", help=f"site serving /feeds/ (default: $FEEDS_PUBLIC_BASE or {DEFAULT_PUBLIC_BASE})")
    parser.add_argument("--url", "--github-url", dest="github_url", default=FEED, help="GitHub branch copy (secondary)")
    parser.add_argument("--max-age-hours", type=float, default=3)
    args = parser.parse_args(argv)
    ok, message = run(public_url(args.public_base), args.github_url, datetime.now(timezone.utc),
                      timedelta(hours=args.max_age_hours))
    print(message)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
