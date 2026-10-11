#!/usr/bin/env python3
"""Fail when a published feed is old or a whole critical kind of its sources has been degraded too long.

The live job publishes every 30 minutes to R2 (what the site serves) and to the
`conditions` branch; the daily job publishes the `data` branch once a day. If
either stops (failing tests, a broken source, an expired or revoked token), the
app keeps serving the last generation and nothing looks wrong. This check turns
that silence into a visible failure and a GitHub issue.

A feed can also look fresh while its sources are not: a source that failed is
published as `retained` (last good data) or `stale`. Each source's status is
read, and every degraded one is reported by name with the age of its data when
the feed was built. A critical kind (buoys including their spectra, alerts,
tides, forecast models; see catalog/feed-health.json) fails the check only when
every source of that kind in one feed is degraded past the feed's limit: one
buoy out while another reports is a partial outage, reported but not failed.
Other kinds only warn.

Besides the top-level live feed (the default region's alias) and the daily
feed, each published region's live feed (`conditions/regions/<id>/latest.json`,
ids from dist/regions/index.json) is checked the same way, per region. A stale
or unreadable feed for a region that is not the default or `active` is a
partial outage too.

The public route (`<FEEDS_PUBLIC_BASE>/feeds/<branch>/latest.json`) is what
users get, so it decides the result. The GitHub branch copy is fetched second
and its age reported as a secondary signal: a fresh branch next to a stale
public route points at R2 publication.

Exit status is a bit mask: 1 when a feed is stale or unreadable, 2 when every
source of a critical kind in a feed is degraded past its limit (3 when both).
A partial outage exits 0; `--report FILE` writes {"stale", "degraded",
"partial"} as JSON so the workflow can keep its issue current.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
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
ROOT = Path(__file__).resolve().parent.parent
HEALTH_FILE = ROOT / "catalog" / "feed-health.json"

# PARTIAL never reaches the exit status: it marks a reported outage that does not fail the run.
STALE, DEGRADED, PARTIAL = 1, 2, 4
FAILING = STALE | DEGRADED


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


def feed_sources(feed):
    """(key, source) pairs of a feed's source objects."""
    sources = feed.get("sources") if isinstance(feed, dict) else None
    if not isinstance(sources, dict):
        return []
    return [(key, source) for key, source in sources.items() if isinstance(source, dict)]


def degraded_sources(feed, critical_kinds=None):
    """Every source whose status is not ok: [{id, status, kind, critical, age_hours}], critical first."""
    critical_kinds = set(HEALTH["critical_kinds"] if critical_kinds is None else critical_kinds)
    rows = []
    for key, source in feed_sources(feed):
        if source.get("status") == "ok":
            continue
        rows.append({"id": source.get("id") or key, "status": source.get("status") or "unknown",
                     "kind": source.get("kind") or "unknown", "critical": source.get("kind") in critical_kinds,
                     "age_hours": data_age_hours(source, feed)})
    return sorted(rows, key=lambda row: (not row["critical"], row["id"]))


def past_limit(row, limit_hours):
    """A critical source degraded past the limit, or with no data time at all."""
    return row["critical"] and (row["age_hours"] is None or row["age_hours"] > limit_hours)


def failing_kinds(feed, limit_hours, critical_kinds=None):
    """Critical kinds whose every source in this feed is degraded past limit_hours, sorted.

    Spectral buoy sources (`buoy-<id>-spectrum`) are kind observation, so one buoy's
    spectrum reporting keeps the observation kind alive.
    """
    over, totals = {}, {}
    for row in degraded_sources(feed, critical_kinds):
        if past_limit(row, limit_hours):
            over[row["kind"]] = over.get(row["kind"], 0) + 1
    for _, source in feed_sources(feed):
        totals[source.get("kind")] = totals.get(source.get("kind"), 0) + 1
    return sorted(kind for kind, count in over.items() if count == totals.get(kind))


def source_verdict(feed, limit_hours, label, critical_kinds=None):
    """Return (status bits, lines) for a feed's sources.

    DEGRADED when every source of a critical kind is degraded past limit_hours (or has no
    data time); PARTIAL when some critical sources are past the limit while others of their
    kind are not; 0 otherwise. Every degraded source is listed either way.
    """
    rows = degraded_sources(feed, critical_kinds)
    if not rows:
        return 0, []
    failing = set(failing_kinds(feed, limit_hours, critical_kinds))
    lines, partial = [], 0
    for row in rows:
        over = past_limit(row, limit_hours)
        partial += over and row["kind"] not in failing
        age = row["age_hours"]
        age_text = "no data time" if age is None else f"data {age:.1f} h old"
        role = f"critical, limit {limit_hours:g} h" if row["critical"] else "advisory"
        mark = "FAIL" if row["kind"] in failing else "over" if over else "warn"
        lines.append(f"- {mark} {row['id']} ({row['kind']}): {row['status']}, {age_text} ({role})")
    if failing:
        head = f"{label}: every {', '.join(sorted(failing))} source degraded past {limit_hours:g} h."
    elif partial:
        head = (f"{label}: {partial} critical source(s) degraded past {limit_hours:g} h while others of "
                "the same kind are not (partial outage; reported, does not fail).")
    else:
        head = f"{label}: {len(rows)} degraded source(s), none critical past {limit_hours:g} h."
    return (DEGRADED if failing else PARTIAL if partial else 0), [head, *lines]


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


def age_limit_hours(feed, config, override=None):
    """The feed's age limit: an explicit override, else its schedule.max_delay_hours, else the catalog default."""
    if override is not None:
        return override
    schedule = feed.get("schedule") if isinstance(feed, dict) else None
    declared = schedule.get("max_delay_hours") if isinstance(schedule, dict) else None
    if isinstance(declared, (int, float)) and not isinstance(declared, bool) and declared > 0:
        return declared
    return config["max_age_hours"]


def check_feed(name, public, github, now, fetch=fetch_json, max_age_hours=None, health=None):
    """One feed's age (public route decides) and source health. Return (status bits, message)."""
    health = health or HEALTH
    config = health["feeds"][name]
    public_feed, public_error = fetched(public, fetch)
    github_feed, github_error = fetched(github, fetch)
    # Source health and the declared schedule are read from what users get; the branch copy
    # stands in only when the public route is unreadable.
    feed = public_feed if isinstance(public_feed, dict) else github_feed if isinstance(github_feed, dict) else None
    max_age = timedelta(hours=age_limit_hours(feed, config, max_age_hours))
    public_label, github_label = f"Public {name} feed ({public})", f"GitHub {name} branch"
    ok, public_line = (False, f"{public_label} could not be fetched: {public_error}") if public_error is not None \
        else verdict(public_feed, now, max_age, public_label)
    github_ok, github_line = (False, f"{github_label} could not be fetched: {github_error}") if github_error is not None \
        else verdict(github_feed, now, max_age, github_label)
    lines = [public_line, github_line + ("" if github_ok else " (secondary signal)")]
    source_bits = 0
    if feed is not None:
        label = config["label"] + ("" if feed is public_feed else " (GitHub copy)")
        source_bits, source_lines = source_verdict(feed, config["critical_degraded_hours"], label, health["critical_kinds"])
        lines += source_lines
    return (0 if ok else STALE) | source_bits, "\n".join(lines)


def published_regions(health=None, root=ROOT):
    """[(region id, critical)] for each region's live feed, from the published region index.

    The default region is left out: the top-level conditions feed is its alias and is checked
    as such. A region is critical (its stale feed fails the run) when its status is active.
    """
    index = json.loads((Path(root) / (health or HEALTH)["regions"]["index"]).read_text())
    default = index.get("default_region")
    return [(row["id"], row.get("status") == "active") for row in index.get("regions", [])
            if isinstance(row, dict) and row.get("id") and row["id"] != default]


def check_region(region, critical, base, now, fetch=fetch_json, health=None):
    """One region's live feed: its age (public route decides) and its sources (GitHub copy when the route fails)."""
    health = health or HEALTH
    config = health["regions"]
    path = config["path"].format(region=region)
    label = f"{config['label']} {region}"
    feed, error = fetched(public_url(base, "/feeds/" + path), fetch)
    if error is None:
        ok, line = verdict(feed, now, timedelta(hours=age_limit_hours(feed, config)), f"Public {label}")
    else:
        ok, line = False, f"Public {label} could not be fetched: {error}"
        feed, _ = fetched(RAW + path, fetch)
        label += " (GitHub copy)"
    if not ok and not critical:
        line += " (not an active region; reported, does not fail)"
    bits, lines = 0 if ok else STALE if critical else PARTIAL, [line]
    if isinstance(feed, dict):
        source_bits, source_lines = source_verdict(feed, config["critical_degraded_hours"], label, health["critical_kinds"])
        bits |= source_bits
        lines += source_lines
    return bits, "\n".join(lines)


def run_all(base, now, fetch=fetch_json, live_max_age_hours=None, data_max_age_hours=None, live_github=FEED,
            health=None, regions=None):
    """Check the live and daily feeds, then each region's live feed. Return (status bits, message)."""
    health = health or HEALTH
    status, messages = 0, []
    for name, max_age, github in (("conditions", live_max_age_hours, live_github), ("data", data_max_age_hours, None)):
        path = health["feeds"][name]["path"]
        bits, message = check_feed(name, public_url(base, "/feeds/" + path), github or RAW + path, now, fetch, max_age, health)
        status |= bits
        messages.append(message)
    region_lines = []
    rows = published_regions(health) if regions is None else regions
    with ThreadPoolExecutor(max_workers=8) as pool:  # about 15 regions; keep the run well inside its timeout
        for bits, message in pool.map(lambda row: check_region(row[0], row[1], base, now, fetch, health), rows):
            status |= bits
            region_lines.append(message)
    if region_lines:
        messages.append("\n".join(region_lines))
    return status, "\n\n".join(messages)


def write_report(path, status):
    """The workflow's view of one run: what failed (stale, degraded) and what was only reported (partial)."""
    Path(path).write_text(json.dumps({"stale": bool(status & STALE), "degraded": bool(status & DEGRADED),
                                      "partial": bool(status & PARTIAL)}) + "\n")


def main(argv=None, fetch=fetch_json, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--public-base", help=f"site serving /feeds/ (default: $FEEDS_PUBLIC_BASE or {DEFAULT_PUBLIC_BASE})")
    parser.add_argument("--url", "--github-url", dest="github_url", default=FEED, help="GitHub conditions branch copy (secondary)")
    parser.add_argument("--max-age-hours", type=float, help="live feed age limit (default: catalog/feed-health.json)")
    parser.add_argument("--data-max-age-hours", type=float,
                        help="daily data feed age limit (default: its schedule.max_delay_hours, else catalog/feed-health.json)")
    parser.add_argument("--live-only", action="store_true", help="check only the live feed's age (exit 1 when stale)")
    parser.add_argument("--report", type=Path, help="write {stale, degraded, partial} as JSON to this file")
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
    if args.report:
        write_report(args.report, status)
    raise SystemExit(status & FAILING)


if __name__ == "__main__":
    main()
