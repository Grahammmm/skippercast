"""``python -m skippercast.fleet <step> --region CA [--sink staging|worker] [--run-id ID]``.

Each pipeline step (design sections 4 and 9) runs inside a run directory under
``$SKIPPERCAST_FLEET_VAR`` with a sink opened for it, and records its status and
counts in ``state.json``. The steps are registered here and filled in by later
tasks: discover (CF-12 to CF-14), resolve (CF-15), enrich-code (CF-16),
ingest, refresh and run (CF-17), plan-agent (CF-20). ``validate-profile`` checks
OSINT profiles (``fleet.profile``).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Callable

from .. import validate
from . import enrich, profile
from .adapters import RunContext
from .config import FleetConfigError, load_region
from .net import FleetSession
from .runs import Run, now
from .sinks import SinkError, open_sink


def _empty(ctx: RunContext, sink) -> dict:
    """A registered step whose work lands in a later task: it opens the run and sink and does nothing."""
    return {}


STEPS: dict[str, Callable[[RunContext, object], dict]] = {
    name: _empty for name in ("discover", "resolve", "enrich-code", "plan-agent", "ingest", "refresh", "run")
}
STEPS["enrich-code"] = enrich.step


def run_step(step: str, region_id: str, sink_kind: str = "staging", run_id: str | None = None, **sink_options) -> Run:
    region = load_region(region_id)
    run = Run(region.id, run_id)
    sink = open_sink(sink_kind, region, run, **sink_options)
    run.step_started(step, sink.name)
    net = FleetSession.for_region(region, cache=run.http_cache)
    ctx = RunContext(region=region, net=net, run_dir=run.dir, clock=now)
    try:
        counts = STEPS[step](ctx, sink)
    except Exception as error:
        run.step_finished(step, {"skips": len(net.skips)}, f"{type(error).__name__}: {error}")
        raise
    finally:
        sink.close()
    run.step_finished(step, {**counts, "skips": len(net.skips)})
    return run


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "validate-profile":
        return profile.main(argv[1:])
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet", description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=[*STEPS, "validate-profile"])
    parser.add_argument("--region", required=True, help="fleet region id, e.g. CA")
    parser.add_argument("--sink", choices=["staging", "worker"], default="staging")
    parser.add_argument("--run-id", help="resume this run (default: a new run)")
    args = parser.parse_args(argv)
    try:
        run = run_step(args.step, args.region, args.sink, args.run_id)
    except (FleetConfigError, SinkError, ValueError, validate.MissingDependency) as error:
        print(f"fleet {args.step}: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"run_id": run.id, "dir": str(run.dir), "step": run.state["steps"][args.step]}, sort_keys=True))
    return 0
