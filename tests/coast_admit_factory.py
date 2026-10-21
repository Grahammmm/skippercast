"""Synthetic B1b inputs; SC-3 catalog factory, no downloads or live files."""
import importlib.util
import os
from pathlib import Path
import shlex
from string import Template
import subprocess
import sys

from tests import _coastal_catalog_fixture as fx
from tests.coast_contract_factory import load_helper

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT/'skills/coast-segment-admit/scripts'
refs = load_helper('coast_refs')
load_helper('coast_sample')
load_helper('validate_coast_receipt')


def helper(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS/(name+'.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = helper('admit_common')
stager = helper('stage_cache')
planner = helper('make_plan')
writer = helper('write_admission')

COMMANDS = (
    '"$SC_PY" skills/coast-segment-admit/scripts/stage_cache.py --roots "$ROOTS" --campaign "$C/campaign.json" --selection "$SELECTION" --raw-receipt "$RAW_RECEIPT" --out "$CACHE_STAGE_RECEIPT"',
    '"$SC_PY" skills/coast-segment-admit/scripts/make_plan.py --root "$C" --campaign "$C/campaign.json" --catalog "$D/run/catalog.json" --selection "$SELECTION" --cache-receipt "$CACHE_STAGE_RECEIPT" --out-dir "$P"',
    'PYTHONPATH=src "$SC_PY" -m skippercast.coastal.coordinator.catalog_bridge dry-run --root "$C" --catalog "$D/run/catalog.json" --plan "$P/plan.json" --out "$P/dry"',
    '"$SC_PY" skills/coast-segment-admit/scripts/write_admission.py --roots "$ROOTS" --campaign "$C/campaign.json" --plan-dir "$P" --selection "$SELECTION" --cache-receipt "$CACHE_STAGE_RECEIPT" --ledger-snapshot "$LEDGER_SNAPSHOT" --out "$P/admission.json"',
)


def world(tmp, *, raster=False, centres=None):
    queue, raw = tmp/'queue', tmp/'raw'
    queue.mkdir()
    raw.mkdir()
    d = queue/'discovery/d01'
    (d/'run').mkdir(parents=True)
    (queue/'plans').mkdir()
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    header = dict(created_utc='2026-10-21T00:00:00Z',author_profile='synthetic-author',author_model='synthetic-model',
                  card_id='t_82a3ef2b',code_commit=head,skill_commit=head)
    rows, windows = [], []
    if centres is None:
        centres = [(-55000,-425000)]
        if raster:
            from pyproj import Transformer
            centres = [Transformer.from_crs('OGC:CRS84','EPSG:3310',always_xy=True).transform(-120.595,34.455)]
    for i,(cx,cy) in enumerate(centres):
        path = raw/f'input{i}.tif'
        transform = [1.0,0.0,float(cx-2),0.0,-1.0,float(cy+2)]
        if raster:
            import numpy as np
            import rasterio
            from affine import Affine
            with rasterio.open(path,'w',driver='GTiff',width=4,height=4,count=1,dtype='float32',crs='EPSG:3310',transform=Affine(*transform)) as ds:
                ds.write(np.full((4,4),-10,dtype='float32'),1)
        else:
            path.write_bytes(b'II*\x00Synthetic staging bytes, not a complete raster.\n')
        ref = common.file_ref(path,'raw:campaign',raw)
        source_id = f'ncei:input{i}.tif'
        rows.append(fx.candidate(f'input{i}.tif',size=ref['bytes'],source_hash=ref['sha256']))
        definition = dict(source_sha256=ref['sha256'],raster_crs='EPSG:3310',affine_transform=transform,
                          width=4,height=4,tile_width=4,tile_height=4,tiling_version='single-selected-v1',pixel_window=[0,0,4,4])
        windows.append(dict(source_id=source_id,input=ref,raw_provenance=[ref],retained_inputs=[],pixel_window=[0,0,4,4],
                            grid_definition=definition,reader='native-raster-v1',vertical=None,
                            rights=dict(private_use=True,evidence=[]),rights_summary='synthetic private-use fixture',datum='unknown'))
    campaign = dict(schema='coast-campaign-v1',**header,campaign_segment_id='synthetic-campaign',
                    bbox_crs84=[-120.65,34.40,-120.50,34.60],lane='offline-synthetic',source_inventory=[w['source_id'] for w in windows],
                    intended_windows=[common.window_key(w['source_id'],refs.object_digest(w['grid_definition']),0) for w in windows])
    def put(path,value):
        path.write_bytes(refs.canonical(value))
        return common.file_ref(path,'queue:synthetic-campaign',queue)
    put(queue/'campaign.json',campaign)
    catalog = fx.frozen_catalog(rows)
    fx.write_catalog(d/'run/catalog.json',catalog)
    catalog_ref = common.file_ref(d/'run/catalog.json','queue:synthetic-campaign',queue)

    (d/'run/metadata.xml').write_bytes(b'<synthetic>SC-3 fixture, no live discovery</synthetic>\n')
    metadata = common.file_ref(d/'run/metadata.xml','queue:synthetic-campaign',queue)
    discovery_ref = put(d/'run/evidence.json',dict(schema='coast-discovery-evidence-v1',**header,catalog=catalog_ref,evidence=[metadata]))
    owner = common.owner_id(*centres[0])
    usage = dict(requests=0,bytes=0,wall_s=0)
    limits = dict(requests=0,bytes=10_000_000,wall_s=3600)
    snapshot = dict(schema='coast-budget-snapshot-v1',campaign_sha256=refs.sha256(refs.canonical(campaign)),
                    coordinator_segment_id=owner,attested_by='synthetic fixture only',
                    campaign_usage_before=usage,segment_usage_before=usage,campaign_limits=limits,segment_limits=limits)
    snapshot_ref = put(queue/'budget-snapshot.json',snapshot)
    selection = dict(schema='coast-selection-v1',**{k:header[k] for k in common.HEADER},campaign_sha256=refs.sha256(refs.canonical(campaign)),
                     allowed_root_ids=['queue:synthetic-campaign','raw:campaign'],catalog=catalog_ref,discovery=discovery_ref,
                     ledger_snapshot=snapshot_ref,max_total_bytes=10_000_000,budget=dict(fx.BUDGET),windows=windows,
                     preconditions=dict(exclusive_writer=True,attested_by='synthetic fixture, no live authority'))
    put(queue/'selection.json',selection)
    raw_receipt = dict(schema='coast-raw-selection-v1',campaign_sha256=selection['campaign_sha256'],
                       sources=[{k:w[k] for k in ('source_id','input','raw_provenance','retained_inputs')} for w in windows])
    put(queue/'raw-receipt.json',raw_receipt)
    roots = tmp/'roots.json'
    roots.write_bytes(refs.canonical({'queue:synthetic-campaign':str(queue),'raw:campaign':str(raw)}))
    env = dict(SC_PY=sys.executable,C=str(queue),D=str(d),P=str(queue/'plans/p01'),ROOTS=str(roots),
               SELECTION=str(queue/'selection.json'),RAW_RECEIPT=str(queue/'raw-receipt.json'),
               CACHE_STAGE_RECEIPT=str(queue/'cache-stage.json'),LEDGER_SNAPSHOT=str(queue/'budget-snapshot.json'))
    return dict(queue=queue,raw=raw,campaign=campaign,selection=selection,env=env,put=put)


def stage(w):
    e = w['env']
    return stager.stage_cache(roots=Path(e['ROOTS']),campaign=w['queue']/'campaign.json',
                              selection=Path(e['SELECTION']),raw_receipt=Path(e['RAW_RECEIPT']),out=Path(e['CACHE_STAGE_RECEIPT']))


def command(w,index):
    argv = shlex.split(Template(COMMANDS[index]).substitute(w['env']))
    env = dict(os.environ,PYTHONPATH='src')
    if argv[0] == 'PYTHONPATH=src':
        argv = argv[1:]
    return subprocess.run(argv,cwd=ROOT,env=env,text=True,capture_output=True,timeout=45)


def smoke(w):
    for i in range(4):
        result = command(w,i)
        assert result.returncode == 0, (i,result.stdout,result.stderr)
    return refs.loads((Path(w['env']['P'])/'admission.json').read_bytes())
