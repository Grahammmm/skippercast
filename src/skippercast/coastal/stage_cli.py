"""Trusted neutral stage CLI for cached native coastal processing.

Discovery is an explicitly local, frozen catalog lane. It never reports absence
outside the supplied complete offline catalog; network missions remain separate.
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import resource
import time

from .handoff.common import confined, digest, load, ref, resolve, write, validate_native_source
from .handoff import mapping_input
from . import mapping

SUCCESSOR = dict(discover='acquire', acquire='qualify', qualify='map', map='render')


def _next(stage, artifact, job):
    plans = job['params'].get('stage_params',{})
    if not isinstance(plans,dict) or any(k not in (*SUCCESSOR,'render') for k in plans):
        raise ValueError('known downstream stage parameters required')
    for name, params in plans.items():
        allowed = {'imagery','alignment','review','rights'} if name == 'render' else set()
        if not isinstance(params,dict) or set(params)-allowed:
            raise ValueError('downstream stage parameter fields refused')
    params = dict(stage_params=plans,**plans.get(stage,{})) if plans else {}
    return dict(stage=stage, input_manifest=artifact, params=params, budget=job['budget'])


def execute(job, output, *, now):
    if job.get('sourcefree_contract'):
        from .coordinator.source_free import execute as sourcefree_execute
        return sourcefree_execute(job,output,now=now)
    root = Path(job['root']).resolve()
    out = confined(root, Path(output).relative_to(root) if Path(output).is_absolute() else output, existing=False)
    out.mkdir(parents=True, exist_ok=True)
    if digest(job['params']) != job['params_sha']:
        raise ValueError('job parameter hash mismatch')
    if job['input_manifest']['sha256'] != job['input_manifest_sha']:
        raise ValueError('job input hash mismatch')
    manifest = load(root, job['input_manifest'])
    stage = job['stage']
    minimum_valid_until = now + timedelta(seconds=float(job['budget']['wall_s']))
    synthetic = job['segment'].get('synthetic') is True
    if manifest.get('synthetic') is not synthetic:
        raise ValueError('synthetic source/job identity mismatch')
    base = dict(schema='coastal-stage-result-v1', stage=stage, job_id=job['job_id'],
                segment_id=job['segment']['segment_id'], lease_token=job['lease_token'],
                code_sha=job['code_sha'], deps_sha=job['deps_sha'],
                input_manifest_sha=job['input_manifest_sha'], params_sha=job['params_sha'],
                artifacts=[], usage=dict(requests=0,bytes_in=0,model_calls=[]),
                provenance=dict(libs=mapping_input.libraries(),synthetic=synthetic))
    if now.timestamp() >= float(job['deadline_utc']):
        return dict(base,state='held',holds=['budget_exhausted'])
    relative = out.relative_to(root).as_posix()
    if stage == 'discover':
        if manifest.get('schema') != 'coastal-local-discovery-plan-v1':
            return dict(base,state='held',holds=['bounded_catalog_adapter_unavailable'])
        import rasterio
        from rasterio.warp import transform_bounds
        from shapely.geometry import box
        leads = []
        for candidate in manifest.get('candidates',[]):
            path = validate_native_source(root,candidate['source'])
            with rasterio.open(path) as ds:
                if not ds.crs:
                    continue
                geographic = transform_bounds(ds.crs,'OGC:CRS84',*ds.bounds,densify_pts=21)
                if box(*geographic).intersection(box(*job['segment']['bbox_crs84'])).area > 0:
                    leads.append(candidate)
        receipt = dict(schema='coastal-local-discovery-v1',synthetic=synthetic,segment_id=base['segment_id'],
                       leads=leads,catalog_scope='explicit_local_frozen_candidates',
                       complete_within_supplied_catalog=True,unexamined_external_catalogs=True)
        write(out/'discovery.json',receipt)
        artifact = ref(root,out/'discovery.json',receipt['schema'])
        base['artifacts'].append(artifact)
        if not leads:
            return dict(base,state='held',holds=['no_local_leads_external_catalogs_unexamined'])
        next_manifest = dict(leads[0],schema='coastal-native-job-v1',synthetic=synthetic,segment_id=base['segment_id'])
        write(out/'native-job.json',next_manifest)
        native_ref = ref(root,out/'native-job.json',next_manifest['schema'])
        base['artifacts'].append(native_ref)
        return dict(base,state='done',holds=[],next_job=_next('acquire',native_ref,job))
    if stage in ('acquire','qualify') and manifest.get('segment_id') != base['segment_id']:
        raise ValueError('job/native-input geographic identity mismatch')
    if stage == 'acquire':
        if manifest.get('schema') != 'coastal-native-job-v1':
            raise ValueError('acquisition native input contract mismatch')
        source = resolve(root,manifest['source'])
        if source.stat().st_size > int(job['budget'].get('bytes',2*1024**3)):
            return dict(base,state='held',holds=['budget_exhausted'])
        facts, holds, *_ = mapping_input.observe(root,manifest['source'],window=manifest['window'],
            vertical=manifest['vertical'],source_row=manifest.get('source_row'),
            metadata_sha256=manifest.get('metadata_sha256'))
        receipt = dict(schema='coastal-cached-observation-v1',synthetic=synthetic,source=manifest['source'],
                       facts_digest=digest(facts),facts=facts,holds=holds,acquisition='verified_existing_cache',
                       requests=0,transferred_bytes=0)
        write(out/'observation.json',receipt)
        write(out/'native-job.json',manifest)
        artifact = ref(root,out/'native-job.json',manifest['schema'])
        base['artifacts'].extend([ref(root,out/'observation.json',receipt['schema']),artifact])
        return dict(base,state='held' if holds else 'done',holds=holds,
                    **({} if holds else dict(next_job=_next('qualify',artifact,job))))
    if stage == 'qualify':
        if manifest.get('schema') != 'coastal-native-job-v1':
            raise ValueError('qualification native input contract mismatch')
        produced = mapping_input.produce(root,manifest['source'],segment_id=base['segment_id'],
            window=manifest['window'],vertical=manifest['vertical'],rights=manifest['rights'],
            output_dir=relative,segment=job['segment'],review=manifest.get('review'),synthetic=synthetic,
            source_row=manifest.get('source_row'),metadata_sha256=manifest.get('metadata_sha256'))
        checked = mapping_input.verify(root,produced,now=now,minimum_valid_until=minimum_valid_until)
        artifact = ref(root,out/'mapping-input.json',mapping_input.SCHEMA)
        base['artifacts'].append(artifact)
        return dict(base,state='done' if checked['ready'] else 'held',holds=checked['holds'],
                    **(dict(next_job=_next('map',artifact,job)) if checked['ready'] else {}))
    if stage == 'map':
        if manifest.get('segment_id') != base['segment_id'] or manifest.get('segment') != job['segment']:
            raise ValueError('job/mapping-input geographic identity mismatch')
        result = mapping.run(root,manifest,output_dir=relative,now=now,minimum_valid_until=minimum_valid_until)
        if result['state'] != 'done':
            return dict(base,state='held',holds=result['holds'])
        artifact = ref(root,out/'run.json',mapping.SCHEMA)
        base['artifacts'].extend([artifact,*result['outputs'].values()])
        return dict(base,state='done',holds=[],next_job=_next('render',artifact,job))
    if stage == 'render':
        if manifest.get("schema") == "coastal-terrain-only-input-v1":
            from .render import terrain_only
            terrain_root = Path(job["params"]["terrain_root"]).resolve()
            if not root.is_relative_to(terrain_root) or not out.resolve().is_relative_to(root):
                raise ValueError("terrain-only queue/output root confinement")
            if terrain_only.context(manifest) != job["params"]["terrain_context_digest"]:
                raise ValueError("terrain-only context binding mismatch")
            checked = terrain_only.verify(terrain_root, manifest, now=now)
            produced = terrain_only.preview(terrain_root, checked, output_dir=(out/"preview").relative_to(terrain_root),
                now=now, style=job["params"].get("terrain_style"))
            path = out/"terrain-only-result.json"
            write(path, produced)
            owned = []
            for artifact in produced["artifacts"]:
                absolute = resolve(terrain_root, artifact)
                if not absolute.is_relative_to(root):
                    raise ValueError("terrain-only artifact outside queue root")
                owned.append(ref(root, absolute, artifact["contract"]))
            base.update(state="done", holds=[], artifact=ref(root,path,terrain_only.RESULT),
                artifacts=owned, terrain_only_context_digest=terrain_only.context(checked),
                terrain_only_input_root=str(terrain_root))
            base["usage"]["bytes"] = sum(a["bytes"] for a in owned)
            return base
        if manifest.get('schema') not in (mapping.SCHEMA,'render-handoff-v2.1'):
            raise ValueError('render input contract unsupported')
        if manifest.get('segment_id') != base['segment_id'] or manifest.get('segment') != job['segment']:
            raise ValueError('job/render-input geographic identity mismatch')
        from .handoff import render
        from .render.preview import preview
        if manifest.get('schema') == mapping.SCHEMA:
            produced = render.produce(root,manifest,output_dir=relative,now=now,
                imagery=job['params'].get('imagery'),alignment=job['params'].get('alignment'),
                review=job['params'].get('review'),rights=job['params'].get('rights'),
                minimum_valid_until=minimum_valid_until)
        else:
            produced = manifest
        checked = render.verify(root,produced,now=now,minimum_valid_until=minimum_valid_until)
        artifact = ref(root,out/'render-handoff.json',render.SCHEMA) if manifest.get('schema') == mapping.SCHEMA else job['input_manifest']
        base['artifacts'].append(artifact)
        if not checked['ready']:
            return dict(base,state='held',holds=checked['holds'])
        result = preview(root,produced,output_dir=relative+'/preview',now=now,
                         minimum_valid_until=minimum_valid_until)
        if result.get('state') != 'done':
            state = result.get('state')
            if state not in ('held','failed_retryable','failed_terminal','cancelled'):
                raise ValueError('preview returned unknown state')
            return dict(base,state=state,holds=result.get('holds') or ['preview_not_done'])
        if not result.get('artifacts'):
            raise ValueError('completed preview missing artifacts')
        for artifact in result['artifacts']:
            resolve(root,artifact)
        return dict(base,state='done',holds=[],artifacts=base['artifacts']+result['artifacts'])
    raise ValueError('unknown stage')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    run = sub.add_parser('run')
    run.add_argument('--job',type=Path,required=True)
    run.add_argument('--out',type=Path,required=True)
    args = parser.parse_args(argv)
    job = json.loads(args.job.read_text())
    root = Path(job['root']).resolve()
    args.out = confined(root, args.out.relative_to(root) if args.out.is_absolute() else args.out, existing=False)
    args.out.mkdir(parents=True,exist_ok=True)
    start, cpu = time.monotonic(), time.process_time()
    now = datetime.now(timezone.utc)
    try:
        result = execute(job,args.out,now=now)
    except (ValueError,KeyError,TypeError,OSError) as error:
        result = dict(schema='coastal-stage-result-v1',
            **{k:job[k] for k in ('job_id','stage','lease_token','code_sha','deps_sha','input_manifest_sha','params_sha')},
            segment_id=job['segment']['segment_id'],state='failed_terminal',
            holds=['invalid_stage_input:'+type(error).__name__+':'+str(error)],artifacts=[],
            usage=dict(requests=0,bytes_in=0,model_calls=[]),
            provenance=dict(libs=mapping_input.libraries(),synthetic=job['segment'].get('synthetic') is True))
    result['usage'].update(wall_s=time.monotonic()-start,cpu_s=time.process_time()-cpu,
        max_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if job.get('managed_output_grant') is not None:
        from .output_writer import ManagedOutputs
        grant=job['managed_output_grant']
        owner=ManagedOutputs(grant['output_root'],grant,digest(grant))
        owner.write_json(args.out/'result.json',result,role='mapping',max_bytes=65536,
            intent=digest(['coastal-stage-result',job['job_id'],job['lease_token']]))
    else:write(args.out/'result.json',result)
    print(json.dumps(dict(state=result['state'],holds=result['holds'])))
    return {'done':0,'held':3,'failed_retryable':4,'failed_terminal':5,'cancelled':7}[result['state']]


if __name__ == '__main__':
    raise SystemExit(main())
