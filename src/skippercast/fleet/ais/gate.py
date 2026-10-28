"""``python -m skippercast.fleet.ais watch-check --region <id>``: the watched gate over the stored rows.

Reads every ``fleet_ais_watch`` row of the region with ``GET /api/fleet/jobs/watch``
(``match.read_watch_rows``, fleet-job OIDC inside Actions) and applies
``match.gate_problem``: a ``watched`` row needs a method in ``STRONG_METHODS``
and confidence of at least 0.85 (design.md section 11, #468 D18). Prints counts
by status and method, and failures by method, as one JSON line; never an MMSI or
a vessel. Exit 0 when every row passes, 1 when any fails, 2 on an error.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from typing import Iterable, Mapping

from .match import gate_problem, read_watch_rows

__all__ = ["check_rows", "main"]


def check_rows(rows: Iterable[Mapping]) -> dict:
    """Counts by status and method, and the gate failures by method."""
    counts: dict[str, Counter] = {}
    failures: Counter = Counter()
    for row in rows:
        method = str(row.get("match_method"))
        counts.setdefault(str(row.get("status")), Counter())[method] += 1
        if gate_problem(row) is not None:
            failures[method] += 1
    return {"counts": {status: dict(sorted(c.items())) for status, c in sorted(counts.items())},
            "failures": dict(sorted(failures.items())), "failed": sum(failures.values())}


def main(argv=None, *, worker=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais watch-check",
                                     description="Exit non-zero when a watched row fails the strong-evidence gate.")
    parser.add_argument("--region", required=True)
    args = parser.parse_args(argv)
    from ..config import FleetConfigError, load_region
    from ..sinks import worker_base
    from .process import Worker, WorkerError
    try:
        region = load_region(args.region)
        result = check_rows(read_watch_rows(worker or Worker(worker_base()), region.id))
    except (FleetConfigError, WorkerError, ValueError, KeyError) as error:
        print(f"fleet ais watch-check: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"region": region.id, **result}, sort_keys=True))
    return 1 if result["failed"] else 0
