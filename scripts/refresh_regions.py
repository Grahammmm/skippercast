"""One scheduled refresh across all published regions; retain the Morro Bay alias."""
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


def refresh(kind, output, previous_root=None, *, only_region=None, include_drafts=False):
    if include_drafts and (not only_region or not output.resolve().is_relative_to((REPO / 'var').resolve())):
        raise ValueError('Draft rehearsal requires one region and an unpublished var/ output')
    now=datetime.now(timezone.utc)
    summaries=[]
    for path in sorted((REPO/"regions").glob("*/region.json")):
        if only_region and path.parent.name != only_region: continue
        region=load_region(path.parent.name)
        if region["status"]=="draft" and not include_drafts: continue
        ident=region["id"]
        prior_path=previous_root/"regions"/ident/"latest.json" if previous_root else None
        if prior_path and not prior_path.exists() and ident=="morro-bay": prior_path=previous_root/"latest.json"
        prior=read_json(prior_path) if prior_path and prior_path.is_file() else None
        if kind in ('intelligence','habitat'):
            if kind=='intelligence':
                from skippercast.pipeline.intelligence import run
            else:
                from skippercast.pipeline.habitat_dynamics import run
            data=run(ident,output,previous_root,now)
            summaries.append({'region_id':ident,'status':data['health']['status'],'completed_at':data['completed_at'],'issues':data['health']['issues'],'coverage_gaps':data['health'].get('coverage_gaps',[])})
            continue
        data=(daily(now,prior,region_id=ident) if kind=="daily" else live(now,prior,region_id=ident))
        target=output/"regions"/ident
        atomic_json(target/"latest.json",data)
        atomic_json(target/"health.json",{"region_id":ident,"generated_at":data["generated_at"],**data["health"]})
        if kind=="daily":
            rules_health = coverage(data['regulations'], data['sources'], now)
            rules_health['region_id'] = ident
            active = {s for target in region['species'] for s in (['lingcod', 'rockfish'] if target == 'reef' else [target])}
            rules_health['species'] = {k: v for k, v in rules_health['species'].items() if k in active}
            atomic_json(target/'regulations-health.json', rules_health)
            history=target/"history"
            if prior_path and (prior_path.parent/"history").is_dir(): shutil.copytree(prior_path.parent/"history",history,dirs_exist_ok=True)
            atomic_json(history/(now.strftime("%Y-%m-%d")+".json"),data)
            for old in history.glob("*.json"):
                if old.stem<(now-timedelta(days=90)).strftime("%Y-%m-%d"):old.unlink()
        summaries.append({"region_id":ident,"status":data["health"]["status"],"completed_at":data["completed_at"],"issues":data["health"]["issues"]})
    if only_region and not summaries:
        raise ValueError(f"Region {only_region} was not collected; check ID and draft inclusion")
    if kind in ('intelligence','habitat'):
        atomic_json(output/(kind+'-health.json'),{'schema_version':1,'regions':summaries})
        return summaries
    # Compatibility alias only when the Morro Bay region was actually collected.
    if any(row['region_id'] == 'morro-bay' for row in summaries):
        for name in ("latest.json","health.json"):
            shutil.copyfile(output/"regions/morro-bay"/name,output/name)
        if kind=="daily": shutil.copytree(output/"regions/morro-bay/history",output/"history",dirs_exist_ok=True)
    atomic_json(output/"regions/index.json",{"schema_version":1,"completed_at":datetime.now(timezone.utc).isoformat(),"regions":summaries})
    return summaries


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("kind",choices=["daily","live","intelligence","habitat"])
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--previous-root",type=Path)
    p.add_argument("--only-region",help="Collect one region for an isolated rehearsal")
    p.add_argument("--include-drafts",action="store_true",help="Include drafts in the requested local output; do not use for public feed publication")
    a=p.parse_args();print(json.dumps(refresh(a.kind,a.output,a.previous_root,
        only_region=a.only_region,include_drafts=a.include_drafts),indent=2))
