"""``python -m skippercast.fleet.ais port-coverage --region CA``: a counts-only Markdown block for the fleet-ais run
summary. Per region port it lists the distinct MMSIs and the MMSI-days heard inside the port geofence over the last
``WINDOW_DAYS`` days (the processor's ``match_presence`` table), and names the ports never heard.

The processor's ``state.sqlite`` is opened read-only and is never created or written. No MMSI, position or vessel name
is ever printed.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .match import WINDOW_DAYS, _day
from .process import DAY

HEADING = "### AIS coverage by port"


def port_coverage(db_path: Path, ports, since_day: str, *, until_day: str | None = None) -> dict | None:
    """Days are inclusive local ISO days; ``until_day=None`` keeps the lower-bound-only count.
    ``{"ports": {id: {"mmsis", "mmsi_days"}}, "never_heard": [ids]}``; ``None`` without state or presence table."""
    path = Path(db_path)
    if not path.is_file():
        return None
    try:  # as_uri() percent-encodes '?', '#' and '%', so the path is the exact file and mode=ro always applies
        db = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        upper, args = ("", (since_day,)) if until_day is None else (" AND day <= ?", (since_day, until_day))
        rows = db.execute("SELECT port_id, COUNT(DISTINCT mmsi), COUNT(*) FROM match_presence WHERE day >= ?"
                          f"{upper} GROUP BY port_id", args).fetchall()
    except sqlite3.Error:
        return None
    finally:
        db.close()
    heard = {port_id: {"mmsis": mmsis, "mmsi_days": days} for port_id, mmsis, days in rows}
    result = {p.id: heard.get(p.id, {"mmsis": 0, "mmsi_days": 0}) for p in ports}
    return {"ports": result, "never_heard": sorted(i for i, c in result.items() if c["mmsi_days"] == 0)}


def render(result: dict | None, ports=(), window_days: int = WINDOW_DAYS) -> str:
    if result is None:
        return f"{HEADING}\n\nNo processor state yet: coverage unknown.\n"
    names = {p.id: p.name for p in ports}
    table = sorted(((names.get(i, i), c) for i, c in result["ports"].items()),
                   key=lambda row: (-row[1]["mmsi_days"], row[0]))
    lines = [f"{HEADING} (last {window_days} days, counts only)", "", "| Port | Distinct MMSIs | MMSI-days |",
             "| --- | ---: | ---: |"]
    lines += [f"| {name} | {c['mmsis']} | {c['mmsi_days']} |" for name, c in table]
    never = sorted(names.get(i, i) for i in result["never_heard"])
    lines += ["", f"Never heard (0 MMSI-days): {', '.join(never)}" if never else "Every port heard."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais port-coverage",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--region", required=True)
    parser.add_argument("--now", help="ISO time to count back from (test seam; default: now)")
    args = parser.parse_args(argv)
    from ..config import FleetConfigError, load_region
    from .store import ais_root
    try:
        region = load_region(args.region)
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now_ms, zone = int(now.timestamp() * 1000), ZoneInfo(region.timezone)
        since_day, until_day = _day(now_ms - WINDOW_DAYS * DAY, zone), _day(now_ms, zone)
        root = ais_root(region.id)
    except (FleetConfigError, ValueError) as error:
        print(f"fleet ais port-coverage: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(render(port_coverage(root / "state.sqlite", region.ports, since_day, until_day=until_day),
                           region.ports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
