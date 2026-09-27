#!/usr/bin/env python3
"""Capture complete current CDFW MPA geometry for unpublished source reviews."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from skippercast.pipeline.coastal_watch import CoastalClient, mpa_loader
from skippercast.platform.contracts import atomic_json


def collect():
    client = CoastalClient(datetime.now(timezone.utc))
    data = mpa_loader(client)
    return {
        "status": "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "requests": client.requests,
        "fishing_permission": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect()
    atomic_json(args.output, result)
    print(json.dumps({"cdfw_mpa_features": result["data"]["feature_count"]}))


if __name__ == "__main__":
    main()
