"""One scheduled refresh across all published regions; retain the Morro Bay alias.

Regions are independent: one region's collector error is recorded in the index
(`status: failed`, `error_class`, `error`) and the others still publish. The
command exits non-zero only when the default/active region fails or more than
half of the regions fail (see `gate`).

With --run-manifest the run is also recorded as a RunManifest
(skippercast.runs) at var/runs/refresh-<kind>/<run_id>.json: per-region status
and source statuses, sha256 of the region configs and previous feeds read and
of the pointer files written, and the exit status. `python -m
skippercast.report` renders it; `scripts/publish_r2.py var/runs runs` uploads it.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from skippercast.platform.contracts import REPO, atomic_json, load_region, read_json
from skippercast.runs import RunManifest
from skippercast.pipeline.collect import collect as daily
from skippercast.pipeline.live import collect as live
from skippercast.pipeline.regulation_review import coverage


ERROR_CHARS = 300
RUNS = REPO/"var/runs"
# Per-region files recorded as run outputs (pointers only: history, tiles and archives are not hashed).
OUTPUTS = {"daily": ("latest.json", "health.json", "regulations-health.json"), "live": ("latest.json", "health.json"),
           "intelligence": ("intelligence.json",), "habitat": ("habitat-dynamics.json", "habitat-health.json")}
PREVIOUS = {"daily": "latest.json", "live": "latest.json", "intelligence": "intelligence.json",
            "habitat": "habitat-dynamics.json"}


def default_region():
    """The app's default region, as published by skippercast.platform.build."""
    return read_json(REPO/"dist/regions/index.json")["default_region"]


def failed_row(ident, error):
    """Index row for a region whose refresh raised; its previous publication stays in place."""
    return {"region_id":ident,"status":"failed","error_class":type(error).__name__,
            "error":str(error)[:ERROR_CHARS],"completed_at":None,"issues":["refresh-failed"]}


def record_region(run, kind, ident, data, output, previous_root, duration_ms):
    """Add one collected region to the run manifest: its sources, status, inputs and outputs."""
    sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
    rows = {sid: row for sid, row in sources.items() if isinstance(row, dict) and isinstance(row.get("status"), str)}
    for sid, row in rows.items():
        requests = row.get("requests") if isinstance(row.get("requests"), list) else []
        last = requests[-1] if requests and isinstance(requests[-1], dict) else {}
        run.source(f"{ident}/{sid}", row["status"], detail=row.get("issue"),
                   http_status=last.get("http_status"))
    health = data.get("health") if isinstance(data.get("health"), dict) else {}
    run.region(ident, health.get("status") or "ok", sources_ok=sum(r["status"] == "ok" for r in rows.values()),
               sources_total=len(rows), duration_ms=duration_ms, issues=health.get("issues"),
               coverage_gaps=health.get("coverage_gaps") or None)
    if previous_root:
        prior = Path(previous_root)/"regions"/ident/PREVIOUS[kind]
        run.add_input(prior, optional=True)
    for name in OUTPUTS[kind]:
        if (output/"regions"/ident/name).is_file():
            run.add_output(output/"regions"/ident/name)


def record_failure(run, ident, error, duration_ms):
    run.region(ident, "failed", error_class=type(error).__name__, error=str(error), duration_ms=duration_ms)


def refresh_region(kind, region, output, previous_root, now, default, manifest=None):
    """Collect and write one region; return its index row. Raises on failure."""
    started=time.monotonic()
    ident=region["id"]
    prior_path=previous_root/"regions"/ident/"latest.json" if previous_root else None
    if prior_path and not prior_path.exists() and ident==default: prior_path=previous_root/"latest.json"
    prior=read_json(prior_path) if prior_path and prior_path.is_file() else None
    if kind in ('intelligence','habitat'):
        if kind=='intelligence':
            from skippercast.pipeline.intelligence import run
        else:
            from skippercast.pipeline.habitat_dynamics import run
        data=run(ident,output,previous_root,now)
        if manifest: record_region(manifest,kind,ident,data,output,previous_root,round((time.monotonic()-started)*1000))
        return {'region_id':ident,'status':data['health']['status'],'completed_at':data['completed_at'],'issues':data['health']['issues'],'coverage_gaps':data['health'].get('coverage_gaps',[]),
                'forecast_coverage':data['health'].get('forecast_coverage') if kind=='intelligence' else None}
    data=(daily(now,prior,region_id=ident) if kind=="daily" else live(now,prior,region_id=ident))
    target=output/"regions"/ident
    if kind=="daily":  # computed before any write, so a failure leaves no partial region
        rules_health = coverage(data['regulations'], data['sources'], now,
                                data['regulations'].get('source_scope_ids'))
        rules_health['region_id'] = ident
        active = {s for target in region['species'] for s in (['lingcod', 'rockfish'] if target == 'reef' else [target])}
        rules_health['species'] = {k: v for k, v in rules_health['species'].items() if k in active}
    atomic_json(target/"latest.json",data,kind=kind+"-feed")  # validated before the region's first write
    atomic_json(target/"health.json",{"region_id":ident,"generated_at":data["generated_at"],**data["health"]})
    if kind=="daily":
        atomic_json(target/'regulations-health.json', rules_health)
        history=target/"history"
        if prior_path and (prior_path.parent/"history").is_dir(): shutil.copytree(prior_path.parent/"history",history,dirs_exist_ok=True)
        atomic_json(history/(now.strftime("%Y-%m-%d")+".json"),data)
        for old in history.glob("*.json"):
            if old.stem<(now-timedelta(days=90)).strftime("%Y-%m-%d"):old.unlink()
    if manifest: record_region(manifest,kind,ident,data,output,previous_root,round((time.monotonic()-started)*1000))
    return {"region_id":ident,"status":data["health"]["status"],"completed_at":data["completed_at"],"issues":data["health"]["issues"]}


def critical_regions(only_region=None):
    """Regions whose failure fails the job: the one asked for, else the default and active ones."""
    if only_region: return {only_region}
    active={p.parent.name for p in (REPO/"regions").glob("*/region.json") if read_json(p).get("status")=="active"}
    return {default_region()}|active


def gate(summaries, critical):
    """None when the run may pass, else why it must fail."""
    failed=[row["region_id"] for row in summaries if row["status"]=="failed"]
    if set(failed)&set(critical):
        return "default/active region failed: "+", ".join(sorted(set(failed)&set(critical)))
    if summaries and len(failed)*2>len(summaries):
        return f"{len(failed)} of {len(summaries)} regions failed"
    return None


def refresh(kind, output, previous_root=None, *, only_region=None, include_drafts=False, run=None):
    """Refresh every published region (or one); record each in `run` (a RunManifest) when given."""
    if include_drafts and (not only_region or not output.resolve().is_relative_to((REPO / 'var').resolve())):
        raise ValueError('Draft rehearsal requires one region and an unpublished var/ output')
    now=datetime.now(timezone.utc)
    summaries=[]
    default=default_region()
    for path in sorted((REPO/"regions").glob("*/region.json")):
        if only_region and path.parent.name != only_region: continue
        ident=path.parent.name
        started=time.monotonic()
        try:
            region=load_region(ident)
            if region["status"]=="draft" and not include_drafts: continue
            if run: run.add_input(path)
            summaries.append(refresh_region(kind,region,output,previous_root,now,default,run))
        except Exception as error:  # job boundary: one region's failure must not block the others
            summaries.append(failed_row(ident,error))
            if run: record_failure(run,ident,error,round((time.monotonic()-started)*1000))
            print(f"::error title=Region {ident} failed::{type(error).__name__}: {str(error)[:300]}",file=sys.stderr)
    if only_region and not summaries:
        raise ValueError(f"Region {only_region} was not collected; check ID and draft inclusion")
    if kind in ('intelligence','habitat'):
        atomic_json(output/(kind+'-health.json'),{'schema_version':1,'regions':summaries})
        if run: run.add_output(output/(kind+'-health.json'))
        return summaries
    # Compatibility alias only when the default (Morro Bay) region was actually collected.
    if any(row['region_id'] == default and row['status'] != 'failed' for row in summaries):
        for name in ("latest.json","health.json"):
            shutil.copyfile(output/"regions"/default/name,output/name)
        if kind=="daily": shutil.copytree(output/"regions"/default/"history",output/"history",dirs_exist_ok=True)
    atomic_json(output/"regions/index.json",{"schema_version":1,"completed_at":datetime.now(timezone.utc).isoformat(),"regions":summaries},kind="regions-index")
    if run: run.add_output(output/"regions/index.json")
    return summaries


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("kind",choices=["daily","live","intelligence","habitat"])
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--previous-root",type=Path)
    p.add_argument("--only-region",help="Collect one region for an isolated rehearsal")
    p.add_argument("--include-drafts",action="store_true",help="Include drafts in the requested local output; do not use for public feed publication")
    p.add_argument("--run-manifest",nargs="?",const=RUNS,type=Path,metavar="DIR",
                   help="Write a run manifest to DIR/refresh-<kind>/<run_id>.json (DIR defaults to var/runs)")
    a=p.parse_args(argv)
    run=RunManifest.start("refresh-"+a.kind) if a.run_manifest else None
    try:
        summaries=refresh(a.kind,a.output,a.previous_root,only_region=a.only_region,include_drafts=a.include_drafts,run=run)
    except Exception as error:
        if run: write_manifest(run,a.run_manifest,1,error=error)
        raise
    print(json.dumps(summaries,indent=2))
    reason=gate(summaries,critical_regions(a.only_region))
    if reason:
        print(f"::error title=Regional {a.kind} refresh failed::{reason}",file=sys.stderr)
    if run:
        if reason: run.error={"class":"RegionGate","message":reason[:ERROR_CHARS]}
        write_manifest(run,a.run_manifest,1 if reason else 0)
    return 1 if reason else 0


def manifest_path(run, directory):
    """DIR/<job>/<run_id>[-<attempt>].json, mirroring the R2 key runs/<job>/<run_id>.json."""
    return Path(directory)/run.r2_key().removeprefix("runs/")


def write_manifest(run, directory, exit_code, *, error=None):
    """Finish and write the manifest. Observability must never change the job's outcome, so a write error only warns."""
    try:
        run.finish(exit_code, error=error)
        path=manifest_path(run,directory)
        run.write(path)
        print(f"Run manifest: {path}",file=sys.stderr)
        return path
    except Exception as problem:  # noqa: BLE001 - the feed result stands either way
        print(f"::warning title=Run manifest not written::{type(problem).__name__}: {str(problem)[:300]}",file=sys.stderr)
        return None


if __name__=="__main__":
    sys.exit(main())
