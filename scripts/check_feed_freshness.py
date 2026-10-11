#!/usr/bin/env python3
"""Fail when a published feed is old or its critical sources have been degraded too long.

The live job publishes every 30 minutes to R2 (what the site serves) and to the
`conditions` branch; the daily job publishes the `data` branch once a day. If
either stops (failing tests, a broken source, an expired or revoked token), the
app keeps serving the last generation and nothing looks wrong. This check turns
that silence into a visible failure and a GitHub issue.

A feed can also look fresh while its sources are not: a source that failed is
published as `retained` (last good data) or `stale`. Each source's status is
read, and every degraded one is reported by name with the age of its data when
the feed was built. Critical kinds (buoys, alerts, tides, forecast models; see
catalog/feed-health.json) fail the check once degraded past the feed's limit;
other kinds only warn.

The public route (`<FEEDS_PUBLIC_BASE>/feeds/<branch>/latest.json`) is what
users get, so it decides the result. The GitHub branch copy is fetched second
and its age reported as a secondary signal: a fresh branch next to a stale
public route points at R2 publication.

Exit status is a bit mask: 1 when a feed is stale or unreadable, 2 when a
critical source has been degraded past its limit (3 when both).
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

# The workers.dev host always serves the Worker (and R2). Set FEEDS_PUBLIC_BASE to
# https://skippercast.com once that custom domain is attached (docs/cloudflare.md).
DEFAULT_PUBLIC_BASE = "https://skippercast.g4651.workers.dev"
RAW = "https://raw.githubusercontent.com/Grahammmm/skippercast/"
FEED_PATH = "/feeds/conditions/latest.json"
FEED = RAW + "conditions/latest.json"
HEALTH_FILE = Path(__file__).resolve().parent.parent / "catalog" / "feed-health.json"

STALE, DEGRADED = 1, 2


def load_health(path=HEALTH_FILE):
    return json.loads(Path(path).read_text())


HEALTH = load_health()


def public_url(base=None, path=FEED_PATH):
    base = (base or os.environ.get("FEEDS_PUBLIC_BASE") or DEFAULT_PUBLIC_BASE).rstrip("/")
    return base + path


def parse_time(stamp):
    """An aware datetime from an ISO stamp, or None when absent, unparsable or naive."""
    if not isinstance(stamp, str):
        return None
    try:
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else None


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


def data_age_hours(source, feed):
    """How old a source's data was when the feed was built, in hours; None when it has no data time.

    The data's own clock (sample_at, issued_at) comes first, then when it was last
    retrieved; the feed's build clock is the source's checked_at, else the feed's.
    """
    data = source.get("data") if isinstance(source.get("data"), dict) else {}
    built = parse_time(source.get("checked_at")) or parse_time(feed.get("generated_at")) or parse_time(feed_time(feed))
    for stamp in (data.get("sample_at"), data.get("issued_at"), source.get("data_retrieved_at"), source.get("last_success_at")):
        value = parse_time(stamp)
        if value and built:
            return max(0.0, (built - value).total_seconds() / 3600)
    return None


def degraded_sources(feed, critical_kinds=None):
    """Every source whose status is not ok: [{id, status, kind, critical, age_hours}], critical first."""
    critical_kinds = set(HEALTH["critical_kinds"] if critical_kinds is None else critical_kinds)
    sources = feed.get("sources") if isinstance(feed, dict) else None
    rows = []
    for key, source in (sources or {}).items():
        if not isinstance(source, dict) or source.get("status") == "ok":
            continue
        rows.append({"id": source.get("id") or key, "status": source.get("status") or "unknown",
                     "kind": source.get("kind") or "unknown", "critical": source.get("kind") in critical_kinds,
                     "age_hours": data_age_hours(source, feed)})
    return sorted(rows, key=lambda row: (not row["critical"], row["id"]))


def source_verdict(feed, limit_hours, label, critical_kinds=None):
    """Return (ok, lines): ok is False when a critical source is degraded past limit_hours (or has no data time)."""
    rows = degraded_sources(feed, critical_kinds)
    if not rows:
        return True, []
    ok, lines = True, []
    for row in rows:
        age = row["age_hours"]
        over = row["critical"] and (age is None or age > limit_hours)
        ok = ok and not over
        age_text = "no data time" if age is None else f"data {age:.1f} h old"
        role = f"critical, limit {limit_hours:g} h" if row["critical"] else "advisory"
        lines.append(f"- {'FAIL' if over else 'warn'} {row['id']} ({row['kind']}): {row['status']}, {age_text} ({role})")
    head = (f"{label}: critical sources degraded past {limit_hours:g} h." if not ok
            else f"{label}: {len(rows)} degraded source(s), none critical past {limit_hours:g} h.")
    return ok, [head, *lines]


def fetch_json(url):
    request = Request(url, headers={"User-Agent": "SkipperCast-freshness-check/1.0", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def fetched(url, fetch):
    try:
        return fetch(url), None
    except Exception as error:  # network, HTTP or JSON failure all mean "not confirmed fresh"
        return None, error


def check(url, now, max_age, label, fetch=fetch_json):
    feed, error = fetched(url, fetch)
    if error is not None:
        return False, f"{label} could not be fetched: {error}"
    return verdict(feed, now, max_age, label)


def run(public, github, now, max_age, fetch=fetch_json, branch="conditions"):
    """Check the public route (decisive) and the GitHub copy (reported). Return (ok, message)."""
    ok, public_message = check(public, now, max_age, f"Public {branch} feed ({public})", fetch)
    github_ok, github_message = check(github, now, max_age, f"GitHub {branch} branch", fetch)
    if not github_ok:
        github_message += " (secondary signal)"
    return ok, public_message + "\n" + github_message


def check_feed(name, public, github, now, fetch=fetch_json, max_age_hours=None, health=None):
    """One feed's age (public route decides) and source health. Return (status bits, message)."""
    config = (health or HEALTH)["feeds"][name]
    max_age = timedelta(hours=config["max_age_hours"] if max_age_hours is None else max_age_hours)
    public_feed, public_error = fetched(public, fetch)
    github_feed, github_error = fetched(github, fetch)
    public_label, github_label = f"Public {name} feed ({public})", f"GitHub {name} branch"
    ok, public_line = (False, f"{public_label} could not be fetched: {public_error}") if public_error is not None \
        else verdict(public_feed, now, max_age, public_label)
    github_ok, github_line = (False, f"{github_label} could not be fetched: {github_error}") if github_error is not None \
        else verdict(github_feed, now, max_age, github_label)
    lines = [public_line, github_line + ("" if github_ok else " (secondary signal)")]
    # Source health is read from what users get; the branch copy stands in only when the public route is unreadable.
    feed = public_feed if isinstance(public_feed, dict) else github_feed if isinstance(github_feed, dict) else None
    sources_ok = True
    if feed is not None:
        label = config["label"] + ("" if feed is public_feed else " (GitHub copy)")
        sources_ok, source_lines = source_verdict(feed, config["critical_degraded_hours"], label, (health or HEALTH)["critical_kinds"])
        lines += source_lines
    return (0 if ok else STALE) | (0 if sources_ok else DEGRADED), "\n".join(lines)


def run_all(base, now, fetch=fetch_json, live_max_age_hours=None, data_max_age_hours=None, live_github=FEED, health=None):
    """Check the live and daily feeds. Return (status bits, message)."""
    health = health or HEALTH
    status, messages = 0, []
    for name, max_age, github in (("conditions", live_max_age_hours, live_github), ("data", data_max_age_hours, None)):
        path = health["feeds"][name]["path"]
        bits, message = check_feed(name, public_url(base, "/feeds/" + path), github or RAW + path, now, fetch, max_age, health)
        status |= bits
        messages.append(message)
    return status, "\n\n".join(messages)


def main(argv=None, fetch=fetch_json, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--public-base", help=f"site serving /feeds/ (default: $FEEDS_PUBLIC_BASE or {DEFAULT_PUBLIC_BASE})")
    parser.add_argument("--url", "--github-url", dest="github_url", default=FEED, help="GitHub conditions branch copy (secondary)")
    parser.add_argument("--max-age-hours", type=float, help="live feed age limit (default: catalog/feed-health.json)")
    parser.add_argument("--data-max-age-hours", type=float, help="daily data feed age limit (default: catalog/feed-health.json)")
    parser.add_argument("--live-only", action="store_true", help="check only the live feed's age (exit 1 when stale)")
    args = parser.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    if args.live_only:
        hours = HEALTH["feeds"]["conditions"]["max_age_hours"] if args.max_age_hours is None else args.max_age_hours
        ok, message = run(public_url(args.public_base), args.github_url, now, timedelta(hours=hours), fetch)
        print(message)
        raise SystemExit(0 if ok else STALE)
    status, message = run_all(args.public_base, now, fetch, live_max_age_hours=args.max_age_hours,
                              data_max_age_hours=args.data_max_age_hours, live_github=args.github_url)
    print(message)
    raise SystemExit(status)


if __name__ == "__main__":
    main()
