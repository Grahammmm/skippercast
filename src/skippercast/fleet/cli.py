"""``python -m skippercast.fleet <step> --region CA [--sink staging|worker] [--run-id ID]``.

Each pipeline step (design sections 4 and 9) runs inside a run directory under
``$SKIPPERCAST_FLEET_VAR`` with a sink opened for it, records its status and
counts in ``state.json``, writes one ``fleet_runs`` row through the sink
(``run.record``, id ``<run_id>:<step>``) and updates ``report.json``. ``run``
chains ``discover -> resolve -> enrich-code -> ingest -> refresh`` (``--steps``
picks a subset, in that order) in one run and stops at the first failed step;
a discovery binding that failed makes the run ``partial``. ``plan-agent
[--mode full|refresh]`` writes the OSINT agent's batch manifests
(``fleet.agent``); ``ingest --profiles DIR`` ingests the agent's profiles
instead of the run's discovery output, and a refused profile makes the step
``partial``. ``validate-profile`` checks OSINT profiles
(``fleet.profile``), ``coverage-status`` the regions' charter identity
coverage (``fleet.coverage``) and ``report`` writes the fleet report
(``fleet.report``).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

from .. import validate
from . import agent, coverage, enrich, profile, refresh
from . import report as fleet_report
from .adapters import RunContext
from .config import FleetConfigError, load_region
from .ingest import discover, ingest, resolve_step
from .net import FleetSession
from .runs import Run, now
from .sinks import SinkError, open_sink

PIPELINE = ("discover", "resolve", "enrich-code", "ingest", "refresh")


STEPS: dict[str, Callable[..., dict]] = {
    "discover": discover, "resolve": resolve_step, "enrich-code": enrich.enrich_code, "plan-agent": agent.plan_agent,
    "ingest": ingest, "refresh": refresh.refresh,
}


def _record(sink, step: str, started: str, status: str, counts: Mapping[str, Any], error: str | None) -> None:
    sink.apply([{"op": "run.record", "step": step, "sink": sink.name, "started_at": started, "finished_at": now(),
                 "status": status, "counts_json": dict(counts), "error": error[:2000] if error else None}])


def execute(run: Run, ctx: RunContext, sink, steps, options: Mapping[str, Mapping[str, Any]] | None = None) -> dict:
    """Run ``steps`` in order in one run; ``options[step]`` are keyword arguments for that step (tests pass fakes)."""
    report: dict[str, Any] = dict(json.loads((run.dir / "report.json").read_text()) if (run.dir / "report.json").exists() else {})
    report.setdefault("steps", {})
    for step in steps:
        run.step_started(step, sink.name)
        started, skips = now(), len(getattr(ctx.net, "skips", ()))
        try:
            counts = STEPS[step](ctx, sink, **(options or {}).get(step, {}))
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            run.step_finished(step, {}, message)
            report["steps"][step] = {"status": "failed", "error": message[:2000]}
            run.write_report({**report, "status": "failed"})
            try:
                _record(sink, step, started, "failed", {}, message)
            except Exception:  # the failure itself is what matters; the run log write is best effort
                pass
            raise
        counts = {**counts, "skips": len(getattr(ctx.net, "skips", ())) - skips}
        status = "partial" if counts.get("failed") else "ok"
        run.step_finished(step, counts)
        _record(sink, step, started, status, counts, None)
        report["steps"][step] = {"status": status, "counts": counts}
    report["status"] = "partial" if any(s.get("status") == "partial" for s in report["steps"].values()) else "ok"
    run.write_report(report)
    return report


def run_step(step: str, region_id: str, sink_kind: str = "staging", run_id: str | None = None,
             steps: tuple[str, ...] | None = None, options: Mapping[str, Mapping[str, Any]] | None = None,
             **sink_options) -> Run:
    region = load_region(region_id)
    run = Run(region.id, run_id)
    sink = open_sink(sink_kind, region, run, **sink_options)
    net = FleetSession.for_region(region, cache=run.http_cache)
    ctx = RunContext(region=region, net=net, run_dir=run.dir, clock=now)
    try:
        execute(run, ctx, sink, (steps or PIPELINE) if step == "run" else (step,), options)
    finally:
        sink.close()
    return run


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "validate-profile":
        return profile.main(argv[1:])
    if argv and argv[0] == "coverage-status":
        return coverage.main(argv[1:])
    if argv and argv[0] == "report":
        return fleet_report.main(argv[1:])
    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet", description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=[*STEPS, "run", "validate-profile", "coverage-status", "report"])
    parser.add_argument("--region", required=True, help="fleet region id, e.g. CA")
    parser.add_argument("--sink", choices=["staging", "worker"], default="staging")
    parser.add_argument("--run-id", help="resume this run (default: a new run)")
    parser.add_argument("--steps", help=f"run only: a comma-separated subset of {','.join(PIPELINE)}")
    parser.add_argument("--mode", choices=agent.MODES, help="plan-agent only: which vessels to select (default full)")
    parser.add_argument("--profiles", type=Path, help="ingest only: ingest the OSINT profiles in this directory")
    args = parser.parse_args(argv)
    if args.mode and args.step != "plan-agent":
        parser.error("--mode is a plan-agent option")
    if args.profiles and args.step != "ingest":
        parser.error("--profiles is an ingest option")
    options = {"plan-agent": {"mode": args.mode}} if args.mode else {}
    if args.profiles:
        options["ingest"] = {"profiles": args.profiles}
    steps = tuple(s for s in PIPELINE if s in (args.steps or "").split(",")) if args.steps else None
    if args.steps and (not steps or set(args.steps.split(",")) - set(PIPELINE)):
        parser.error(f"--steps takes a comma-separated subset of {','.join(PIPELINE)}")
    try:
        run = run_step(args.step, args.region, args.sink, args.run_id, steps, options)
    except (FleetConfigError, SinkError, ValueError, OSError, validate.MissingDependency) as error:
        print(f"fleet {args.step}: {error}", file=sys.stderr)
        return 2
    report = json.loads((run.dir / "report.json").read_text(encoding="utf-8"))
    print(json.dumps({"run_id": run.id, "dir": str(run.dir), "status": report["status"], "steps": report["steps"]},
                     sort_keys=True))
    return 0
