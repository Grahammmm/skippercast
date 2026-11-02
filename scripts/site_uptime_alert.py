#!/usr/bin/env python3
"""Tell the team once when the site itself stops answering, then age the alert (BF-uptime-oncall).

feed_stale_alert.py watches the published data; nothing else checked that the Worker answers. Each hourly run (the Live feed
freshness workflow) GETs <base>/api/health, <base>/ and <base>/map: 15 s timeout, one retry of a failed path after 20 s.
A path is up on HTTP 200 (and, for /api/health, a JSON object body). Same issue state model as feed_stale_alert.py, label `site-down`:

  * first down  -> one issue is opened, one line per failing path: the path and its HTTP status or error class.
  * still down  -> one `still: N h` comment per STILL_HOURS since the issue opened, never one per hourly check.
  * up again    -> the issue is closed with how long it was down.
  * probe crash -> not a `site-down` issue: the script exits non-zero and the workflow step fails.

Issue text carries paths, status codes and error class names only: never response bodies, headers, redirect targets or tokens.
A redirect to another host is never followed and counts as down.

Usage: site_uptime_alert.py --base URL --report FILE [--dry-run]
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import socket
import sys
import time
from urllib import error, parse, request

try:
    from scripts import feed_stale_alert as stale
except ImportError:  # run as `python scripts/site_uptime_alert.py`: scripts/ is sys.path[0]
    import feed_stale_alert as stale

LABEL = "site-down"
TITLE = "Site is down"
PATHS = ("/api/health", "/", "/map")
TIMEOUT = 15.0
RETRY_DELAY = 20
STILL_HOURS = stale.STILL_HOURS


class SameHost(request.HTTPRedirectHandler):
    """Follow a redirect only within the same scheme and host; otherwise stop, so urllib raises the 3xx as an HTTPError."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = parse.urlsplit(req.full_url), parse.urlsplit(parse.urljoin(req.full_url, newurl))
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def probe(base, path, timeout=TIMEOUT):
    """None when the path is up, else {path, status|error}. Never keeps a response body or header."""
    try:
        with request.build_opener(SameHost).open(request.Request(base + path), timeout=timeout) as response:
            if response.status != 200:
                return {"path": path, "status": response.status}
            if path == "/api/health":
                try:
                    ok = isinstance(json.loads(response.read(1 << 20)), dict)
                except ValueError:
                    ok = False
                if not ok:
                    return {"path": path, "status": 200, "error": "not JSON"}
            return None
    except error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return {"path": path, "status": exc.code, "error": "redirect"}
        return {"path": path, "status": exc.code}
    except Exception as exc:  # a probe failure is a down site, not a crash
        reason = exc.reason if isinstance(exc, error.URLError) else exc
        if isinstance(reason, socket.gaierror):
            return {"path": path, "error": "dns error"}
        if isinstance(reason, TimeoutError):
            return {"path": path, "error": "timeout"}
        return {"path": path, "error": type(reason).__name__}


def check(base, timeout=TIMEOUT, retry_delay=RETRY_DELAY, sleep=time.sleep):
    """Probe every path; retry the failed ones once after retry_delay. Returns the failures left."""
    failed = [p for p in PATHS if probe(base, p, timeout)]
    if failed:
        sleep(retry_delay)
    return [f for f in (probe(base, p, timeout) for p in failed) if f]


def describe(failure):
    return " ".join(str(failure[k]) for k in ("path", "error", "status") if k in failure)


def plan(failures, issues, now, still_hours=STILL_HOURS):
    """The actions for one pass: [("create", title, body) | ("comment", n, text) | ("close", n, text)]."""
    issues = sorted(issues, key=lambda i: i["createdAt"])
    if not failures:
        actions = []
        for issue in issues:
            minutes = int((now - stale.parse(issue["createdAt"])).total_seconds() // 60)
            actions.append(("close", issue["number"], f"Recovered: the site was down for {minutes // 60} h {minutes % 60} min."))
        return actions
    lines = "\n".join(f"- {describe(f)}" for f in failures)
    if not issues:
        body = (f"The site did not answer on:\n{lines}\n\nThis issue is the alert: it is not repeated every hour. A `still: N h` "
                f"comment follows every {still_hours} h while it stays down, and the issue closes when the site answers again.")
        return [("create", TITLE, body)]
    issue = issues[0]
    opened = (now - stale.parse(issue["createdAt"])).total_seconds() / 3600
    due = math.floor(opened / still_hours) * still_hours
    if due > stale.last_still_hours(issue):
        return [("comment", issue["number"], f"still: {due:d} h - still down:\n{lines}")]
    return []


def apply(actions, runner):
    for action in actions:
        if action[0] == "create":
            runner("issue", "create", "--label", LABEL, "--title", action[1], "--body", action[2])
        elif action[0] == "comment":
            runner("issue", "comment", str(action[1]), "--body", action[2])
        else:
            runner("issue", "close", str(action[1]), "--comment", action[2])


def main(argv=None, runner=stale.gh, now=None, sleep=time.sleep, timeout=TIMEOUT, retry_delay=RETRY_DELAY):
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base", default="")
    parser.add_argument("--report", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    base = args.base.strip().rstrip("/")
    parts = parse.urlsplit(base)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        print("site_uptime_alert: --base must be an http(s) URL", file=sys.stderr)
        return 2
    now = now or datetime.now(timezone.utc)
    failures = check(base, timeout, retry_delay, sleep)
    report = {"down": bool(failures), "failures": failures, "checked_at": now.isoformat()}
    Path(args.report).write_text(json.dumps(report))
    print(f"down: {str(bool(failures)).lower()}")
    for failure in failures:
        print(f"  {describe(failure)}")
    if args.dry_run:
        return 0
    issues = json.loads(runner("issue", "list", "--label", LABEL, "--state", "open", "--limit", "100",
                               "--json", "number,title,createdAt,comments"))
    actions = plan(failures, issues, now)
    for action in actions:
        print(" | ".join(str(part).splitlines()[0] for part in action))
    apply(actions, runner)
    print(f"site_uptime_alert: {len(actions)} action(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
