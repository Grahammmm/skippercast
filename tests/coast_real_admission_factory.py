"""Offline real producer graph; synthetic cached bytes, no source requests/Store."""
from pathlib import Path

from pyproj import Transformer

from tests import _coastal_catalog_fixture as fx
from tests.coast_contract_factory import load_helper, materialize
from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.coastal.coordinator.segments import from_bbox
from skippercast.coastal.coordinator.stages import digest

refs = load_helper('coast_refs')
sampling = load_helper('coast_sample')


def real_admission(destination):
    instances, bindings = materialize(destination)
    return instances['admission'], bindings


def populate_admission(admission, bindings, destination):
    """Called by the shared fixture factory before any downstream receipt is pinned."""
    queue = Path(bindings['queue:synthetic'])
    admission = admission.copy()
    header = {k: admission[k] for k in ('created_utc','author_profile','author_model','card_id','code_commit','skill_commit')}

    def put(path, value):
        raw = value if isinstance(value, bytes) else refs.canonical(value)
        target = queue / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return dict(root_id='queue:synthetic', path=path, sha256=refs.sha256(raw), bytes=len(raw))

    extent = [-120.60,34.45,-120.59,34.46]
    cx,cy = Transformer.from_crs('OGC:CRS84','EPSG:3310',always_xy=True).transform(-120.595,34.455)
    records = from_bbox(extent, region='synthetic')
    record = next(r for r in records if r['bbox'][0] <= cx < r['bbox'][2] and r['bbox'][1] <= cy < r['bbox'][3])
    segment_ref = put('plans/plan01/segment.json', record)
    source = fx.cache_file(queue, 'cache/source/input.bag', data=b'Synthetic cached BAG placeholder; not a valid raster. No acquire is run.\n')
    source_id = 'ncei:input.bag'
    catalog = fx.frozen_catalog([fx.candidate('input.bag', size=source['bytes'], source_hash=source['sha256'])])
    catalog_path = queue/'discovery/d01/catalog.json'
    catalog_path.parent.mkdir(parents=True,exist_ok=True)
    catalog_sha = fx.write_catalog(catalog_path,catalog)
    catalog_ref = dict(root_id='queue:synthetic',path='discovery/d01/catalog.json',sha256=catalog_sha,bytes=catalog_path.stat().st_size)
    plan = fx.plan(catalog,catalog_sha,[fx.selection(source_id,source)],bbox=record['bbox_crs84'],segment_id=record['segment_id'],synthetic=False)
    plan_ref = put('plans/plan01/plan.json', plan)
    dry_dir = queue/'plans/plan01/dry'
    if dry_dir.exists():  # deterministic regeneration of this factory's own outputs only
        (dry_dir/'bridge-dry-run-receipt.json').unlink()
        dry_dir.rmdir()
    bridge.dry_run(queue,catalog_path,plan,dry_dir,now=1792540800)
    raw = (queue/'plans/plan01/dry/bridge-dry-run-receipt.json').read_bytes()
    dry_ref = dict(root_id='queue:synthetic',path='plans/plan01/dry/bridge-dry-run-receipt.json',sha256=refs.sha256(raw),bytes=len(raw))
    definition = dict(source_sha256=source['sha256'],raster_crs='EPSG:3310',affine_transform=[1,0,cx-2,0,-1,cy+2],
                      width=4,height=4,tile_width=4,tile_height=4,tiling_version='single-selected-v1',pixel_window=[0,0,4,4])
    grid_sha = digest(definition)
    key = sampling.window_key(source_id,grid_sha,0)
    campaign_ref = put('campaign.json',dict(schema='coast-campaign-v1',**header,campaign_segment_id='synthetic',bbox_crs84=extent,
                       lane='offline-synthetic',source_inventory=[source_id],intended_windows=[key]))
    evidence = put('discovery/d01/synthetic-response.xml',b'<metadata synthetic="true">offline fixture; not acquired data</metadata>\n')
    discovery_ref = put('discovery/d01/evidence.json',dict(schema='coast-discovery-evidence-v1',**header,catalog=catalog_ref,evidence=[evidence]))
    footprint = list(Transformer.from_crs('EPSG:3310','OGC:CRS84',always_xy=True).transform_bounds(cx-2,cy-2,cx+2,cy+2,densify_pts=41))
    hot = dict(root_id='queue:synthetic',**{k:source[k] for k in ('path','sha256','bytes')})
    raw_root = Path(destination)/'raw'
    raw_root.mkdir(exist_ok=True)
    (raw_root/'input.bag').write_bytes((queue/source['path']).read_bytes())
    raw_ref = dict(hot,root_id='raw:campaign',path='input.bag')
    bindings['raw:campaign'] = str(raw_root.absolute())
    admission.update(campaign=campaign_ref,plan_file=plan_ref,segment_record=segment_ref,catalog=catalog_ref,discovery=discovery_ref,
        coordinator_segment_id=record['segment_id'],plan_sha256=digest(plan),
        sources=[dict(source_id=source_id,raw_provenance=[raw_ref],retained_inputs=[],hot_cache=[hot],rights='synthetic private use',datum='unknown',reader='native-raster-v1')],
        grids=[dict(source_id=source_id,grid_sha256=grid_sha,definition=definition,cols=1,rows=1,total=1)],
        windows=[dict(window_key=key,window_dir=sampling.window_dir(key),source_id=source_id,grid_sha256=grid_sha,idx=0,
                      pixel_window=[0,0,4,4],owner_segment_id=record['segment_id'],footprint=footprint,overlapping_segment_ids=[record['segment_id']])],
        budgets=dict(requests=0,bytes=plan['max_total_bytes'],wall_s=plan['budget']['wall_s'],cells=bridge.MAX_WINDOW_CELLS),
        dry_run=dry_ref,would_enqueue_count=1,selected_source_ids=[source_id],held_source_ids=[],
        preconditions=dict(exclusive_writer=True,attested_by='synthetic fixture only; no live authorization'),holds=[])
    return admission, bindings
