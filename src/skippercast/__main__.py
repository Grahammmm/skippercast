"""Small, explicit entry points; no command schedules jobs or sends messages."""

import argparse
from datetime import datetime, timedelta
import json
import sys
from zoneinfo import ZoneInfo

from skippercast import __version__


def demo() -> None:
    """Demonstrate alert decisions using invented data, without network access."""
    from skippercast.monitor.lifecycle import action_for, fingerprint

    now = datetime(2030, 6, 10, 6, tzinfo=ZoneInfo("America/Los_Angeles"))
    trip_date = (now.date() + timedelta(days=3)).isoformat()
    assessment = {
        "comfort_score": 9, "fishing_conditions_score": 9,
        "confidence": "Moderate", "verification_complete": True,
        "meets_numeric_targets": True, "hazards": [], "critical_gaps": [],
        "area": "Fictional demonstration area",
        "departure": "06:30", "fishing_start": "07:00",
        "fishing_end": "11:00", "return": "12:00",
    }
    previous = {
        "ever_alerted": True, "qualified_at_last_alert": True,
        "material_fingerprint": fingerprint(assessment),
    }
    incomplete = dict(assessment, critical_gaps=["Return-window evidence unavailable"])
    print(json.dumps({
        "notice": "Synthetic offline demonstration. No forecast was fetched or alert sent.",
        "initial": action_for(trip_date, assessment, {}, now),
        "unchanged": action_for(trip_date, assessment, previous, now),
        "evidence_lost": action_for(trip_date, incomplete, previous, now),
        "day_before": action_for(trip_date, assessment, previous,
                                 now.replace(day=12, hour=18)),
    }, indent=2))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("command", choices=["demo", "collect", "atlas"])
    # Let the selected command own its flags, including --help. Otherwise the
    # root parser consumes subcommand help before it reaches the real parser.
    args = parser.parse_args(argv[:1])
    remaining = argv[1:]
    if args.command == "collect":
        from skippercast.monitor.collector import main as collect
        return collect(remaining)
    if args.command == "atlas":
        from skippercast.atlas.export import main as export
        return export(remaining)
    if remaining:
        parser.error("demo does not accept additional arguments")
    demo()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
