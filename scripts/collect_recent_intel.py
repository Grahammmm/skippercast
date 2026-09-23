"""Run a pinned last30days engine and publish attributed regional research leads.

This is a discovery feed. Search hits never become catch, habitat, or GPS facts.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "catalog/recent-intel-watchlist.json"
GOOD = {"ok", "no-results"}
PLACE_TERMS = {
    "morro-bay": ("morro bay", "avila", "point buchon", "cayucos", "estero bay"),
    "cambria-san-simeon": ("cambria", "san simeon"),
    "southern-california": ("channel islands", "anacapa", "santa cruz island", "santa rosa island", "san miguel island", "catalina", "san diego", "point loma", "los angeles", "orange county"),
}
FISH_TERMS = ("rockfish", "rock cod", "lingcod", "halibut", "salmon", "tuna", "yellowtail", "seabass", "sea bass", "lobster", "bonito", "bass fishing")


def iso(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def clean_url(value):
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or not p.hostname or p.username or p.password:
            return None
        query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")])
        return urlunsplit(("https", p.netloc.lower(), p.path.rstrip("/") or "/", query, ""))
    except ValueError:
        return None


def normalize(raw, region, query, now, lookback):
    version = str(raw.get("schema_version", ""))
    if version.split(".")[0] != "1" or not isinstance(raw.get("results"), list) or not isinstance(raw.get("source_status"), dict):
        raise ValueError("Unexpected last30days agent JSON contract")
    lower = now - timedelta(days=lookback)
    items = []
    for r in raw["results"]:
        url = clean_url(r.get("url"))
        published = iso(r.get("published_at"))
        if not url or not published or not lower <= published <= now + timedelta(hours=1):
            continue
        title = str(r.get("title") or "").strip()[:220]
        summary = str(r.get("summary") or "").strip()[:220]
        if not title or not summary:
            continue
        text = (title + " " + summary).lower()
        # Real keyless runs can return popular unrelated posts with relevance 0.
        if float(r.get("relevance_score") or 0) < 0.3 or not any(p in text for p in PLACE_TERMS[region]) or not any(f in text for f in FISH_TERMS):
            continue
        source = str(r.get("source") or "unknown")[:40]
        ident = hashlib.sha256(url.encode()).hexdigest()[:20]
        items.append({"id": ident, "region_id": region, "query_id": query,
                      "source": source, "url": url, "published_at": published.isoformat(),
                      "title": title, "summary": summary,
                      "review_status": "candidate", "reported_catch": None,
                      "species": [], "fishing_date": None, "geometry": None,
                      "note": "Search lead only; no catch, species, trip date, or fishing position verified."})
    return items


def gather(config, engine, output, now, previous=None, runner=subprocess.run):
    if config.get("schema_version") != 1 or not 1 <= config.get("lookback_days", 0) <= 90:
        raise ValueError("Invalid watchlist")
    if not engine.is_file():
        raise FileNotFoundError(engine)
    output.mkdir(parents=True, exist_ok=True)
    jobs = []
    seen = set()
    for region in config["regions"]:
        if not (ROOT / "regions" / region["id"] / "region.json").is_file():
            raise ValueError("Unknown region " + region["id"])
        for query in region["queries"]:
            key = region["id"] + "/" + query["id"]
            if key in seen or not query["text"].strip():
                raise ValueError("Duplicate or empty query")
            seen.add(key)
            jobs.append((key, region["id"], query))
    if not 1 <= config.get("jobs_per_day", 0) <= len(jobs):
        raise ValueError("Invalid daily research cadence")
    start = now.date().toordinal() % len(jobs)
    scheduled = [jobs[(start + i) % len(jobs)] for i in range(config["jobs_per_day"])]
    results, checks = {}, {}
    raw_handle = tempfile.TemporaryDirectory(prefix="skippercast-recent-intel-")
    raw_dir = Path(raw_handle.name)
    # The engine is a third-party tool. Do not pass account tokens or browser access.
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "PYTHONPATH")}
    env["FROM_BROWSER"] = "off"
    env["LAST30DAYS_CONFIG_DIR"] = ""  # documented clean/no-config mode
    env["LAST30DAYS_DEFAULT_SEARCH"] = ",".join(config["source_set"])
    for key, region, query in scheduled:
        path = raw_dir / (key.replace("/", "-") + ".json")
        cmd = [sys.executable, str(engine), query["text"],
               "--days=" + str(config["lookback_days"]), "--search=" + ",".join(config["source_set"]),
               "--web-backend=keyless", "--no-browser-cookies", "--emit=json", "--json-profile=agent",
               "--output=" + str(path), "--save-dir=" + str(raw_dir)]
        try:
            completed = runner(cmd, env=env, capture_output=True, text=True, timeout=180)
            if completed.returncode:
                raise RuntimeError("engine exit " + str(completed.returncode))
            raw = json.loads(path.read_text())
            items = normalize(raw, region, query["id"], now, config["lookback_days"])
            status = raw["source_status"]
            if any(v not in GOOD for v in status.values()):
                outcome = "partial"
            elif not status:
                outcome = "failed"
            else:
                outcome = "ok"
            checks[key] = {"status": outcome, "source_status": status, "retrieved_at": now.isoformat(),
                           "result_count": len(items)}
            if outcome in ("ok", "partial"):
                for item in items:
                    results[item["id"]] = item
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            checks[key] = {"status": "failed", "issue": str(exc)[:160], "retrieved_at": now.isoformat(), "result_count": 0}
    raw_handle.cleanup()
    # Retained leads keep their original publication and collection dates, never a fresh status.
    for old in (previous or {}).get("candidates", []):
        published = iso(old.get("published_at"))
        if old.get("id") not in results and published and now - timedelta(days=config["lookback_days"]) <= published <= now:
            results[old["id"]] = {**old, "retained": True}
    candidates = sorted(results.values(), key=lambda x: (x["published_at"], x["id"]), reverse=True)
    usable = sum(c["status"] in ("ok", "partial") for c in checks.values())
    return {"schema_version": 1, "generated_at": now.isoformat(), "upstream": config["upstream"],
            "lookback_days": config["lookback_days"], "checks": checks, "candidates": candidates,
            "health": {"status": "ok" if all(c["status"] == "ok" for c in checks.values()) else "degraded",
                       "jobs_usable": usable, "jobs_total": len(checks), "watchlist_queries": len(jobs)},
            "limitations": ["Candidates are search leads, not verified fishing trips or catch locations.",
                            "Publish date may differ from fishing date. No exact GPS, catch likelihood, or bite score is inferred.",
                            "Source failures and no-results have different meanings; coverage is source-specific."]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--previous", type=Path)
    p.add_argument("--config", type=Path, default=CONFIG)
    args = p.parse_args()
    previous = json.loads(args.previous.read_text()) if args.previous and args.previous.is_file() else None
    now = datetime.now(timezone.utc)
    data = gather(json.loads(args.config.read_text()), args.engine, args.output, now, previous)
    target = args.output / "recent-intel.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n")
    temp.replace(target)
    print(json.dumps(data["health"]))
    if data["health"]["jobs_usable"] == 0:
        raise SystemExit("No recent-intel research job completed; explicit failure snapshot saved")


if __name__ == "__main__":
    main()
