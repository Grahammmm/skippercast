"""One scheduled refresh across all published regions; retain the Morro Bay alias.

Regions are independent: one region's collector error is recorded in the index
(`status: failed`, `error_class`, `error`) and the others still publish. The
command exits non-zero only when the default/active region fails or more than
half of the regions fail (see `gate`).
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from skippercast.platform.contracts import REPO, atomic_json, load_region, read_json
from skippercast.pipeline.collect import collect as daily
from skippercast.pipeline.live import collect as live
from skippercast.pipeline.regulation_review import coverage


ERROR_CHARS = 300


def default_region():
    """The app's default region, as published by skippercast.platform.build."""
    return read_json(REPO/"dist/regions/index.json")["default_region"]


def failed_row(ident, error):
    """Index row for a region whose refresh raised; its previous publication stays in place."""
    return {"region_id":ident,"status":"failed","error_class":type(error).__name__,
            "error":str(error)[:ERROR_CHARS],"completed_at":None,"issues":["refresh-failed"]}


def refresh_region(kind, region, output, previous_root, now, default):
    """Collect and write one region; return its index row. Raises on failure."""
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


def refresh(kind, output, previous_root=None, *, only_region=None, include_drafts=False):
    if include_drafts and (not only_region or not output.resolve().is_relative_to((REPO / 'var').resolve())):
        raise ValueError('Draft rehearsal requires one region and an unpublished var/ output')
    now=datetime.now(timezone.utc)
    summaries=[]
    default=default_region()
    for path in sorted((REPO/"regions").glob("*/region.json")):
        if only_region and path.parent.name != only_region: continue
        ident=path.parent.name
        try:
            region=load_region(ident)
            if region["status"]=="draft" and not include_drafts: continue
            summaries.append(refresh_region(kind,region,output,previous_root,now,default))
        except Exception as error:  # job boundary: one region's failure must not block the others
            summaries.append(failed_row(ident,error))
            print(f"::error title=Region {ident} failed::{type(error).__name__}: {str(error)[:300]}",file=sys.stderr)
    if only_region and not summaries:
        raise ValueError(f"Region {only_region} was not collected; check ID and draft inclusion")
    if kind in ('intelligence','habitat'):
        atomic_json(output/(kind+'-health.json'),{'schema_version':1,'regions':summaries})
        return summaries
    # Compatibility alias only when the default (Morro Bay) region was actually collected.
    if any(row['region_id'] == default and row['status'] != 'failed' for row in summaries):
        for name in ("latest.json","health.json"):
            shutil.copyfile(output/"regions"/default/name,output/name)
        if kind=="daily": shutil.copytree(output/"regions"/default/"history",output/"history",dirs_exist_ok=True)
    atomic_json(output/"regions/index.json",{"schema_version":1,"completed_at":datetime.now(timezone.utc).isoformat(),"regions":summaries},kind="regions-index")
    return summaries


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("kind",choices=["daily","live","intelligence","habitat"])
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--previous-root",type=Path)
    p.add_argument("--only-region",help="Collect one region for an isolated rehearsal")
    p.add_argument("--include-drafts",action="store_true",help="Include drafts in the requested local output; do not use for public feed publication")
    a=p.parse_args(argv)
    summaries=refresh(a.kind,a.output,a.previous_root,only_region=a.only_region,include_drafts=a.include_drafts)
    print(json.dumps(summaries,indent=2))
    reason=gate(summaries,critical_regions(a.only_region))
    if reason:
        print(f"::error title=Regional {a.kind} refresh failed::{reason}",file=sys.stderr)
        return 1
    return 0


if __name__=="__main__":
    sys.exit(main())
