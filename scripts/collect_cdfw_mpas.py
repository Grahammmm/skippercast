#!/usr/bin/env python3
"""Capture complete current CDFW MPA geometry for unpublished source reviews."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from skippercast.pipeline.coastal_watch import CoastalClient, mpa_loader
from skippercast.platform.contracts import atomic_json


def collect(now=None):
    now = now or datetime.now(timezone.utc)
    client = CoastalClient(now)
    data = mpa_loader(client)
    return {
        "status": "ok",
        "checked_at": now.isoformat(),
        "data": data,
        "requests": client.requests,
        "fishing_permission": None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.is_symlink() or args.output.is_dir():
        print("collect_cdfw_mpas: --output must be a file path, not a directory or link", file=sys.stderr)
        return 2
    try:
        result = collect()
    except (ValueError, OSError) as exc:
        reason = (str(exc).splitlines() or [""])[0][:200]
        print(f"collect_cdfw_mpas: capture failed: {type(exc).__name__}: {reason}", file=sys.stderr)
        return 1
    atomic_json(args.output, result)
    print(json.dumps({"cdfw_mpa_features": result["data"]["feature_count"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
