"""Opt-in governed private terrain batch; never reads original survey sources."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import struct
import time
import zlib
import zipfile

from .. import vertical
from ..handoff.common import digest, ref, epoch as _epoch
from ..output_writer import ManagedOutputs, PRIVATE_RENDER_PROFILE, PRIVATE_RENDER_LIMITS
from . import terrain_only as terrain
from . import terrain_demo as demo

MIB = 1024 * 1024
DATA_LIMIT = 15 * MIB
CONTROL_LIMIT = MIB // 2
RECEIPT_LIMIT = 256 * 1024
HTML_LIMIT = 6 * MIB
FLAGS = dict(source_accessed=False, imagery_used=False, internal_diagnostic=True,
             publication_prohibited=True, website='held', habitat='unassessed')


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _mesh_bytes(mesh):
    import numpy as np
    arrays = {name: mesh[name] for name in ('vertices','faces','grid_pixels','support','depth_m','uncertainty_m')}
    arrays.update(crs=np.asarray(mesh['crs']), crs_wkt=np.asarray(mesh['crs_wkt']),
        affine=np.asarray(mesh['affine']), nodata=np.asarray(mesh['nodata']),
        uncertainty_kind=np.asarray(mesh['uncertainty_kind']),
        vertical_json=np.asarray(json.dumps(mesh['vertical'],sort_keys=True,separators=(',',':'))))
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(arrays):
            buffer=io.BytesIO()
            np.lib.format.write_array(buffer,np.asarray(arrays[name]),allow_pickle=False)
            item=zipfile.ZipInfo(name+'.npy',date_time=(1980,1,1,0,0,0))
            item.external_attr=0o600 << 16
            archive.writestr(item,buffer.getvalue())
    return output.getvalue()


def _png_bytes(rgb):
    height,width,channels=rgb.shape
    if (width,height,channels)!=(terrain.WIDTH,terrain.HEIGHT,3):
        raise ValueError('fixed_preview_size_required')
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    raw=b''.join(b'\0'+row.tobytes() for row in rgb)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))
            +chunk(b'IDAT',zlib.compress(raw,6))+chunk(b'IEND',b''))


def _payload(receipt,mesh):
    import numpy as np
    support,depth,uncertainty=(mesh[k] for k in ('support','depth_m','uncertainty_m'))
    vertices,faces,pixels=(mesh[k] for k in ('vertices','faces','grid_pixels'))
    nullable=lambda array:np.where(np.isfinite(array),array,None).tolist()
    return dict(schema=demo.SCHEMA,vertices=vertices.tolist(),faces=faces.tolist(),
        grid_pixels=pixels.tolist(),support=support.tolist(),depth_m=nullable(depth),
        uncertainty_m=nullable(uncertainty),vertex_uncertainty_m=nullable(uncertainty[support]),
        uncertainty_kind=mesh['uncertainty_kind'],
        center=((vertices.min(axis=0)+vertices.max(axis=0))/2).tolist(),span=np.ptp(vertices,axis=0).tolist(),
        metadata=dict(crs=mesh['crs'],crs_wkt=mesh['crs_wkt'],affine=mesh['affine'],nodata=mesh['nodata'],
            vertical=mesh['vertical'],acceptance=receipt['acceptance'],render_binding=receipt['render_binding'],
            limitations=receipt['limitations'],support_cells=receipt['support_cells'],
            uncertainty_kind=mesh['uncertainty_kind'],
            interpolation='planar_supported_triangle_interpolation_visualization_only',**FLAGS))


def _prepare(source_root,item,now,horizon,shared_range_m):
    if (not isinstance(item,dict) or set(item)-{'id','acceptance','style'}
            or not {'id','acceptance'}<=set(item)):
        raise ValueError('render_input_record_invalid')
    ident=item['id']
    if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',ident):
        raise ValueError('render_input_id_invalid')
    document=terrain.verify(source_root,item['acceptance'],now=now,minimum_valid_until=horizon)
    overrides=dict(item.get('style') or {})
    if ('locked_depth_range_m' in overrides and overrides['locked_depth_range_m']!=list(shared_range_m)):
        raise ValueError('shared_render_range_style_conflict')
    overrides.update(color_range='locked',locked_depth_range_m=list(shared_range_m))
    style=terrain.style_controls(overrides)
    mesh=terrain.build_terrain(source_root,document)
    rendered,pixels=terrain.render_terrain(mesh,None,style)
    mesh_data,png_data=_mesh_bytes(mesh),_png_bytes(pixels)
    if len(mesh_data)>8*MIB or len(png_data)>2*MIB:
        raise ValueError('render_artifact_byte_bound')
    terrain_dir=f'{ident}/terrain';demo_dir=f'{ident}/inspector'
    mesh_path=f'{terrain_dir}/terrain-mesh.npz';png_path=f'{terrain_dir}/preview.png'
    producer_paths=[Path(__file__),Path(terrain.__file__),Path(vertical.__file__),Path(terrain.__file__).with_name('align.py'),
        Path(terrain.__file__).with_name('mesh.py'),Path(terrain.__file__).with_name('preview.py'),
        Path(terrain.__file__).parents[1]/'handoff'/'common.py']
    binding=digest(dict(acceptance=document,style=style,
        code={p.name:ref(p.parent,p.name,'python')['sha256'] for p in producer_paths},
        schemas={name:digest(json.loads(__import__('importlib.resources').resources.files(
            'skippercast.coastal.resources').joinpath(name+'.schema.json').read_text()))
            for name in (terrain.INPUT,terrain.REVIEW,terrain.RESULT)},
        numpy=__import__('numpy').__version__,rasterio=__import__('rasterio').__version__))
    receipt=dict(schema=terrain.RESULT,state='done',render_binding=binding,
        acceptance_context_sha256=terrain.context(document),acceptance=document,**FLAGS,
        synthetic=document['synthetic'],style=style,display_z='negative_depth_m_positive_up',
        crs=mesh['crs'],crs_wkt=mesh['crs_wkt'],affine=mesh['affine'],vertical=mesh['vertical'],
        nodata=mesh['nodata'],support_cells=int(mesh['support'].sum()),vertices=len(mesh['vertices']),
        triangles=len(mesh['faces']),
        interpolation='planar_triangles_between_supported_samples_visualization_only',
        uncertainty_kind=document.get('uncertainty_kind','unavailable'),**rendered,
        artifacts=[dict(path=p,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),contract=c)
            for p,data,c in ((mesh_path,mesh_data,'coastal-terrain-only-mesh-v1'),
                             (png_path,png_data,'coastal-terrain-only-png-v1'))],
        limitations=document['limitations']+[
            'Derived-only diagnostic; no original-source verification performed.',
            'Scientific review is an independent attestation, not cryptographic authority proof.',
            'Fixed orthographic camera; visual triangles are not additional measurements.',
            'Color tails remain orange/pink; contours and mesh depths retain absolute metres.',
            'No datum transform, imagery, habitat assessment or website acceptance.'])
    receipt_data=_json_bytes(receipt)
    if len(receipt_data)>RECEIPT_LIMIT: raise ValueError('render_receipt_byte_bound')
    receipt_ref=dict(path=f'{terrain_dir}/render-receipt.json',bytes=len(receipt_data),
                     sha256=hashlib.sha256(receipt_data).hexdigest(),contract=terrain.RESULT)
    render_complete=_json_bytes(dict(schema='coastal-terrain-only-complete-v1',binding=binding,receipt=receipt_ref))
    inspector_style=demo.style_config(dict(display_mode='Measured',subdivisions=1,strength=.75))
    payload=_payload(receipt,mesh)
    html_data=demo.html(payload,inspector_style)
    if len(html_data)>HTML_LIMIT: raise ValueError('demo_html_byte_bound')
    demo_code=[Path(demo.__file__),Path(demo.__file__).with_name('terrain_demo_core.js'),
        Path(demo.__file__).with_name('terrain_demo_ui.js'),Path(vertical.__file__),
        Path(terrain.__file__).with_name('preview.py')]
    demo_result=dict(schema=demo.SCHEMA,state='done',**FLAGS,render_receipt=receipt_ref,
        payload_sha256=digest(payload),
        html=dict(path='terrain-demo.html',bytes=len(html_data),sha256=hashlib.sha256(html_data).hexdigest()),
        code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in demo_code},
        vertices=len(mesh['vertices']),triangles=len(mesh['faces']),support_cells=int(mesh['support'].sum()),
        range_algorithm=dict(auto='visible_topmost_supported_pixel_centres_2nd_98th_percentiles',
            minimum_span_m=1,hysteresis_fraction=.08,locked='captures_current_range_until_mode_changed',
            manual='explicit_finite_min_less_than_max'),
        display_polish=dict(config=inspector_style,interpolation='bounded_monotone_hermite_display_only',
            backing_canvas=[1600,1000],shading='area_weighted_vertex_normals_barycentric_display_only',
            raw_probe_geometry='unchanged_original_planar_triangles',
            display_geometry='bounded_interpolation_estimate_in_flow_mode',
            palette='six_stop_blue_bathymetry',default_view='north_up_east_right_plan'),
        contour_display=dict(flow_max_faces=131072,flow_max_candidates=262144,flow_max_segments=8192,
            flow_decimation='whole_absolute_levels',max_triangle_level_candidates=8192,
            max_segments=1024,max_drawing_steps=16384,
            decimation='deterministic_even_sampling_of_display_candidates_only'),
        probe='barycentric_original_depth_and_uncertainty_on_topmost_supported_triangle',
        limitations=['Internal diagnostic identity binding; no renewed scientific review or publication acceptance.',
            'Orthographic projection; units and vertical exaggeration are display-only.',
            'Canvas pixel centres determine visible Auto statistics; no new measurement or habitat claim.'])
    demo_receipt=_json_bytes(demo_result)
    if len(demo_receipt)>RECEIPT_LIMIT: raise ValueError('demo_receipt_byte_bound')
    demo_complete=_json_bytes(dict(schema='coastal-terrain-demo-complete-v1',
        receipt=dict(path=f'{demo_dir}/demo-receipt.json',bytes=len(demo_receipt),
            sha256=hashlib.sha256(demo_receipt).hexdigest()),html=demo_result['html']))
    files=[
        (mesh_path,mesh_data,'render','coastal-terrain-only-mesh-v1'),
        (png_path,png_data,'render','coastal-terrain-only-png-v1'),
        (receipt_ref['path'],receipt_data,'control',terrain.RESULT),
        (f'{terrain_dir}/complete.json',render_complete,'control','coastal-terrain-only-complete-v1'),
        (f'{demo_dir}/terrain-demo.html',html_data,'render',demo.SCHEMA),
        (f'{demo_dir}/demo-receipt.json',demo_receipt,'control',demo.SCHEMA),
        (f'{demo_dir}/complete.json',demo_complete,'control','coastal-terrain-demo-complete-v1')]
    if any(len(data)>RECEIPT_LIMIT for path,data,role,contract in files if role=='control'):
        raise ValueError('render_control_file_byte_bound')
    return dict(id=ident,binding=binding,receipt=receipt,demo=demo_result,files=files)


def _forecast_and_write(source_root,render_inputs,*,release,now,horizon,shared_range_m,source_batch_ref=None,input_binding=None):
    if not isinstance(render_inputs,list) or not 1<=len(render_inputs)<=4:
        raise ValueError('render_batch_requires_one_to_four_previews')
    if (not isinstance(shared_range_m,(list,tuple)) or len(shared_range_m)!=2
            or any(type(value) not in (int,float) or not math.isfinite(value) for value in shared_range_m)
            or shared_range_m[0]>shared_range_m[1]):
        raise ValueError('shared_absolute_depth_range_required')
    shared_range_m=list(shared_range_m)
    if shared_range_m[0]==shared_range_m[1]:
        shared_range_m=[shared_range_m[0]-.5,shared_range_m[1]+.5]
    ids=[row.get('id') if isinstance(row,dict) else None for row in render_inputs]
    if len(set(ids))!=len(ids): raise ValueError('render_preview_ids_must_be_unique')
    grant=release['child_grant']
    plan=grant.get('output_retention',{})
    if plan.get('profile')!=PRIVATE_RENDER_PROFILE or plan.get('limits')!=PRIVATE_RENDER_LIMITS:
        raise ValueError('private_render_output_profile_required')
    previews=[_prepare(source_root,row,now,horizon,shared_range_m) for row in render_inputs]
    files=[entry for preview in previews for entry in preview['files']]
    if len({entry[0] for entry in files})!=len(files): raise ValueError('render_output_path_collision')
    output_bytes={path:data for path,data,role,contract in files}
    def descriptor(path,contract=None):
        data=output_bytes[path]
        result=dict(path=path,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        if contract is not None: result['contract']=contract
        return result
    import html
    order={'A':2,'B':3,'C':0,'D':1}
    display=[p for p in previews if p['id'] in order]
    display.sort(key=lambda p:order[p['id']])
    if len(display)!=len(previews): display=previews
    panels=[]
    for preview in display:
        ident=html.escape(preview['id'],quote=True)
        panels.append(f'<article><h2>{ident}</h2><img alt="Internal terrain core {ident}" src="{ident}/terrain/preview.png"><p><a href="{ident}/inspector/terrain-demo.html">Open individual viewport inspector</a></p></article>')
    low,high=shared_range_m
    index=('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<title>Governed internal terrain preview</title><style>body{font:16px system-ui;margin:2rem;background:#eef4f7;color:#152a38}'
        'main{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}img{width:100%;height:auto}'
        'article{background:white;padding:1rem}@media(max-width:700px){main{grid-template-columns:1fr}}</style>'
        '<h1>Internal terrain comparison</h1><p>Shared locked depth range '+str(low)+' to '+str(high)+
        ' metres. Fixed-camera supported triangles. Internal diagnostic; publication prohibited, website held, habitat unassessed.</p>'
        '<main>'+''.join(panels)+'</main></html>\n').encode()
    input_binding=input_binding or digest([source_batch_ref,render_inputs,shared_range_m])
    implementation=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    batch_binding=digest(dict(prerequisite_sha256=digest(source_batch_ref) if source_batch_ref else None,input_binding=input_binding,
        shared_range_m=shared_range_m,core_bindings=[p['binding'] for p in previews],
        implementation_sha256=implementation))
    index_data=index
    output_bytes['index.html']=index_data
    data_bytes=sum(len(data) for path,data,role,contract in files if role=='render')+len(index_data)
    if data_bytes>DATA_LIMIT: raise ValueError('render_batch_data_forecast_exceeded')
    core_control=sum(len(data) for path,data,role,contract in files if role=='control')
    receipt_data_by_path={path:data for path,data,role,contract in files if role=='control'}
    aggregate=dict(schema='coastal-render-batch-v1',binding=batch_binding,
        source_accessed=False,imagery_used=False,internal_diagnostic=True,publication_prohibited=True,
        website='held',habitat='unassessed',synthetic=all(p['receipt']['synthetic'] for p in previews),
        accepted_window_ids=[p['id'] for p in display],shared_range_m=shared_range_m,
        shared_comparison='fixed_camera_png',inspectors_range='individual_viewport_adaptive',
        common_subdivisions=1,display_mode='Measured',seam_mode='linear_core_edge_fallback',
        production_loader_ready=False,browser_qa_verified=False,upstream_derived_batch_sha256=digest(source_batch_ref) if source_batch_ref else None,
        cores=[dict(window_id=p['id'],render_receipt=descriptor(p['id']+'/terrain/render-receipt.json',terrain.RESULT),
            demo_receipt=descriptor(p['id']+'/inspector/demo-receipt.json',demo.SCHEMA),
            terrain_binding=p['binding']) for p in display])
    aggregate_data=_json_bytes(aggregate)
    output_bytes['render-batch.json']=aggregate_data
    index_ref=descriptor('index.html','coastal-render-batch-html-v1')
    aggregate_ref=descriptor('render-batch.json','coastal-render-batch-v1')
    completion_data=_json_bytes(dict(schema='coastal-render-batch-completion-v1',
        binding=batch_binding,receipt=aggregate_ref,html=index_ref,
        core_completions=[descriptor(p['id']+'/terrain/complete.json') for p in display]+
                         [descriptor(p['id']+'/inspector/complete.json') for p in display]))
    output_bytes['complete.json']=completion_data
    completion_ref=descriptor('complete.json','coastal-render-batch-completion-v1')
    pointer_data=_json_bytes(dict(schema='coastal-render-batch-pointer-v1',binding=batch_binding,
        completion=completion_ref,receipt=aggregate_ref,html=index_ref))
    output_bytes['render-batch-pointer.json']=pointer_data
    pointer_ref=descriptor('render-batch-pointer.json','coastal-render-batch-pointer-v1')
    control_bytes=core_control+len(aggregate_data)+len(completion_data)+len(pointer_data)
    if control_bytes>CONTROL_LIMIT: raise ValueError('render_batch_control_forecast_exceeded')
    previews_ref=[]
    for p in display:
        previews_ref.append(dict(id=p['id'],render_binding=p['binding'],
            render_complete=descriptor(p['id']+'/terrain/complete.json'),
            demo_complete=descriptor(p['id']+'/inspector/complete.json')))
    batch=dict(schema='coastal-governed-render-batch-v1',state='done',preview_count=len(previews),
        binding=batch_binding,render_data_bytes=data_bytes,control_payload_bytes=control_bytes,
        batch_completion_bytes=0,ledger_overhead_bytes=512*1024,effective_control_bytes=CONTROL_LIMIT,
        prewrite_enforcement='managed writer API only',disk_quota=False,physical_io_measured=False,
        shared_range_m=shared_range_m,upstream_derived_batch_sha256=digest(source_batch_ref) if source_batch_ref else None,
        aggregate_completion=completion_ref,aggregate_pointer=pointer_ref,
        aggregate_receipt=aggregate_ref,index=index_ref,previews=previews_ref)
    for _ in range(4):
        batch_data=_json_bytes(batch)
        if len(batch_data)>RECEIPT_LIMIT: raise ValueError('render_batch_completion_byte_bound')
        if batch['batch_completion_bytes']==len(batch_data): break
        batch['batch_completion_bytes']=len(batch_data)
    else: raise ValueError('render_batch_forecast_unstable')
    if control_bytes+len(batch_data)>CONTROL_LIMIT: raise ValueError('render_batch_control_forecast_exceeded')
    if time.time()>=_epoch(horizon): raise TimeoutError('render_stage_deadline_exhausted')
    if batch_bytes_conflict(release['output_root']): raise ValueError('managed_render_root_invalid')
    output_root=Path(release['output_root'])
    if not output_root.exists():
        output_root.mkdir(parents=True,exist_ok=False)
        manager=ManagedOutputs.create(output_root,grant,release['grant_digest'])
    else:
        manager=ManagedOutputs(output_root,grant,release['grant_digest'])
    all_files=files+[
        ('index.html',index_data,'render','coastal-render-batch-html-v1'),
        ('render-batch.json',aggregate_data,'control','coastal-render-batch-v1'),
        ('complete.json',completion_data,'control','coastal-render-batch-completion-v1'),
        ('render-batch-pointer.json',pointer_data,'control','coastal-render-batch-pointer-v1'),
        ('batch-complete.json',batch_data,'control','coastal-governed-render-batch-v1')]
    # Reserve every file before writing any mesh, PNG, HTML or receipt bytes.
    for path,data,role,contract in all_files:
        intent='governed-render:'+digest([path,hashlib.sha256(data).hexdigest()])
        manager.reserve_file(path,role=role,max_bytes=len(data),intent=intent)
    def write_one(entry):
        path,data,role,contract=entry
        intent='governed-render:'+digest([path,hashlib.sha256(data).hexdigest()])
        manager.write_bytes(path,data,role=role,max_bytes=len(data),intent=intent)
    for entry in all_files:
        if entry[0].endswith('/complete.json') or entry[0] in ('complete.json','render-batch-pointer.json','batch-complete.json'):
            continue
        write_one(entry)
    for entry in all_files:
        if entry[0].endswith('/complete.json'):
            write_one(entry)
    write_one(next(entry for entry in all_files if entry[0]=='complete.json'))
    write_one(next(entry for entry in all_files if entry[0]=='render-batch-pointer.json'))
    write_one(next(entry for entry in all_files if entry[0]=='batch-complete.json'))
    return dict(batch=batch,previews=[dict(id=p['id'],render=p['receipt'],demo=p['demo']) for p in previews],
                managed_output_audit=manager.audit())





def load_owner_render_plan(context, release, source_root, inputs_path):
    """Require owner-pinned plan, source root and exact prerequisite-manifest bytes."""
    from ..handoff.common import load, resolve
    from ..child_release import _plain
    from ..child_release import _document, _canonical
    owner_ref=context.get('owner_authorization')
    policy_ref=context.get('role_policy')
    native=_canonical(owner_ref['root'])
    if (not isinstance(policy_ref,dict) or policy_ref.get('root')!=str(native)
            or policy_ref.get('path')!='metadata/render-policy.json'
            or release['owner'].get('render_policy')!=_plain(policy_ref)):
        raise ValueError('immutable_owner_render_policy_required')
    policy=_document(policy_ref,native,'coastal-governed-render-policy-v1')
    policy_fields={'schema','mission_id','source_root','inputs_path','preview_ids',
        'shared_range_algorithm','original_source_bytes','downloads','private_only',
        'output_root','code_sha','deps_sha','render_limit_bytes','control_limit_bytes',
        'window_count','window_side','windows'}
    if (set(policy)!=policy_fields or policy.get('mission_id')!=context.get('mission_id')
            or policy.get('output_root')!=release['output_root']
            or policy.get('code_sha')!=context.get('code_sha')
            or policy.get('deps_sha')!=context.get('deps_sha')
            or policy.get('private_only') is not True
            or policy.get('shared_range_algorithm')!='accepted_derived_absolute_range'
            or any(type(policy.get(k)) is not int or policy[k]!=v for k,v in
                dict(original_source_bytes=0,downloads=0,render_limit_bytes=15*MIB,
                    control_limit_bytes=MIB//2,window_count=4,window_side=128).items())):
        raise ValueError('exact_static_private_render_policy_required')
    windows=policy.get('windows')
    if (not isinstance(windows,list) or len(windows)!=len(policy.get('preview_ids',[]))
            or [w.get('id') for w in windows if isinstance(w,dict)]!=policy['preview_ids']):
        raise ValueError('exact_approved_render_windows_required')
    affines=set()
    for window in windows:
        if (set(window)!={'id','crs','affine','shape','footprint_bounds','source_sha256s'}
                or window.get('shape')!=[128,128] or not isinstance(window.get('crs'),str)
                or not isinstance(window.get('affine'),list) or len(window['affine'])!=9
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in window['affine'])
                or not isinstance(window.get('footprint_bounds'),list) or len(window['footprint_bounds'])!=4
                or not isinstance(window.get('source_sha256s'),list) or not window['source_sha256s']
                or any(not re.fullmatch(r'[a-f0-9]{64}',str(v)) for v in window['source_sha256s'])):
            raise ValueError('approved_render_window_geometry_required')
        from affine import Affine
        transform=Affine(*window['affine'][:6])
        corners=[transform*(x,y) for x,y in ((0,0),(128,0),(0,128),(128,128))]
        bounds=[min(p[0] for p in corners),min(p[1] for p in corners),
                max(p[0] for p in corners),max(p[1] for p in corners)]
        if bounds!=window['footprint_bounds'] or tuple(window['affine']) in affines:
            raise ValueError('approved_render_window_footprint_or_duplicate')
        affines.add(tuple(window['affine']))
    plan_ref=context.get('render_plan')
    runtime=_canonical(release['runtime_grant']['output_root'])
    if (not isinstance(plan_ref,dict) or plan_ref.get('root')!=str(runtime)
            or plan_ref.get('path')!='control/render-plan.json'):
        raise ValueError('runtime_bound_render_plan_required')
    plan=_document(plan_ref,runtime,'coastal-governed-render-plan-v1')
    if (plan.get('role_policy')!=policy_ref
            or plan.get('policy_binding')!=dict(descriptor=policy_ref,sha256=digest(policy))
            or plan.get('code_sha')!=context['code_sha'] or plan.get('deps_sha')!=context['deps_sha']
            or plan.get('owner_authorization')!=_plain(owner_ref)
            or plan.get('runtime_grant_sha256')!=digest(release['runtime_grant'])
            or plan.get('mapping_stop')!=_plain(context['mapping_stop'])
            or plan.get('source_root')!=policy['source_root']
            or str(inputs_path)!=policy['inputs_path']
            or plan.get('preview_ids')!=policy['preview_ids']):
        raise ValueError('render_plan_policy_or_runtime_binding_mismatch')
    required={'schema','mission_id','source_root','inputs_descriptor','derived_batch_receipt',
        'derived_batch_completion','preview_ids','shared_range_m','derived_batch_binding',
        'original_source_bytes','downloads','role_policy','policy_binding',
        'owner_authorization','runtime_grant_sha256','mapping_stop','code_sha','deps_sha'}
    if set(plan)!=required or plan.get('schema')!='coastal-governed-render-plan-v1':
        raise ValueError('exact_governed_render_plan_required')
    if (plan.get('mission_id')!=context.get('mission_id')
            or type(plan.get('original_source_bytes')) is not int or plan['original_source_bytes']!=0
            or type(plan.get('downloads')) is not int or plan['downloads']!=0):
        raise ValueError('render_plan_mission_or_source_free_binding_mismatch')
    root=Path(source_root)
    if not root.is_absolute() or root.is_symlink() or str(root)!=plan['source_root'] or root.resolve(strict=True)!=root:
        raise ValueError('render_plan_source_root_mismatch')
    descriptor=plan['inputs_descriptor']
    if (not isinstance(descriptor,dict) or set(descriptor)!={'root','path','bytes','sha256','contract'}
            or descriptor.get('root')!=str(root)
            or descriptor.get('contract')!='coastal-governed-render-input-v1'):
        raise ValueError('render_plan_input_manifest_pin_required')
    target=root/descriptor['path']
    supplied=Path(inputs_path)
    if not supplied.is_absolute() or supplied.is_symlink() or supplied.resolve(strict=True)!=target.resolve(strict=True):
        raise ValueError('render_plan_input_manifest_path_mismatch')
    manifest_path=resolve(root,{k:v for k,v in descriptor.items() if k!='root'},
        contract='coastal-governed-render-input-v1',cap=2*MIB)
    manifest=json.loads(manifest_path.read_bytes())
    if (not isinstance(manifest,dict) or manifest.get('schema')!='coastal-governed-render-input-v1'
            or manifest.get('derived_batch_receipt')!=plan['derived_batch_receipt']
            or manifest.get('derived_batch_completion')!=plan['derived_batch_completion']
            or [row.get('id') for row in manifest.get('accepted_inputs',[]) if isinstance(row,dict)]!=plan['preview_ids']):
        raise ValueError('render_plan_prerequisite_identity_mismatch')
    if (not isinstance(plan['preview_ids'],list) or not 1<=len(plan['preview_ids'])<=4
            or any(not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',value)
                   for value in plan['preview_ids'])
            or len(set(plan['preview_ids']))!=len(plan['preview_ids'])
            or not isinstance(plan['shared_range_m'],list) or len(plan['shared_range_m'])!=2
            or any(type(value) not in (int,float) or not math.isfinite(value)
                   for value in plan['shared_range_m'])
            or plan['shared_range_m'][0]>plan['shared_range_m'][1]
            or not re.fullmatch(r'[a-f0-9]{64}',str(plan['derived_batch_binding']))):
        raise ValueError('render_plan_preview_or_range_bound_invalid')
    plan=dict(plan,approved_windows=windows)
    return plan,manifest


def shared_range_mismatch(batch,plan):
    return batch.get('render',{}).get('shared_range_m')!=plan.get('shared_range_m')

def load_render_prerequisites(source_root,manifest,*,now,horizon,render_plan=None):
    from ..handoff.common import load, resolve
    from .. import derived_batch
    if (not isinstance(manifest,dict) or manifest.get('schema')!='coastal-governed-render-input-v1'
            or set(manifest)!={'schema','derived_batch_receipt','derived_batch_completion','accepted_inputs'}):
        raise ValueError('completed_derived_batch_render_manifest_required')
    receipt_ref=manifest['derived_batch_receipt']
    completion_ref=manifest['derived_batch_completion']
    batch=load(source_root,receipt_ref,contract=derived_batch.BATCH)
    completion=load(source_root,completion_ref,contract='coastal-derived-batch-completion-v1')
    if render_plan is not None and batch.get('binding')!=render_plan.get('derived_batch_binding'):
        raise ValueError('owner_render_plan_derived_batch_binding_mismatch')
    if (completion.get('schema')!='coastal-derived-batch-completion-v1'
            or completion.get('receipt')!=receipt_ref
            or batch.get('schema')!=derived_batch.BATCH
            or batch.get('state')!='mapped_pending_render_reviews'
            or batch.get('source_accessed') is not False
            or batch.get('publication_prohibited') is not True):
        raise ValueError('completed_source_free_derived_batch_required')
    # Rehash all derived outputs referenced by the prerequisite receipt.
    artifacts=batch.get('artifacts')
    if not isinstance(artifacts,list) or not artifacts:
        raise ValueError('derived_batch_artifact_set_required')
    for artifact in artifacts:
        resolve(source_root,artifact,contract=artifact.get('contract'),cap=8*MIB)
    rows=manifest['accepted_inputs']
    if not isinstance(rows,list) or not 1<=len(rows)<=4:
        raise ValueError('one_to_four_reviewed_render_acceptances_required')
    accepted_ids=[row.get('id') if isinstance(row,dict) else None for row in rows]
    accepted_windows=[row['id'] for row in batch['windows'] if row.get('state')=='accepted_private_mapping']
    if (render_plan is not None and (accepted_ids!=render_plan['preview_ids']
            or shared_range_mismatch(batch,render_plan))):
        raise ValueError('owner_render_plan_scope_mismatch')
    if len(set(accepted_ids))!=len(accepted_ids) or set(accepted_ids)!=set(accepted_windows):
        raise ValueError('all_and_only_accepted_derived_windows_required')
    if len(batch['acceptances'])!=len(accepted_windows):
        raise ValueError('derived_acceptance_index_mismatch')
    pending_by_id={}
    for wid,reference in zip(accepted_windows,batch['acceptances']):
        pending_by_id[wid]=load(source_root,reference,contract=terrain.INPUT)
    inputs=[]
    for row in rows:
        if set(row)!={'id','acceptance'}:
            raise ValueError('exact_reviewed_acceptance_reference_required')
        supplied=load(source_root,row['acceptance'],contract=terrain.INPUT)
        pending=pending_by_id[row['id']]
        strip=lambda value:{key:item for key,item in value.items() if key!='scientific_review'}
        if digest(strip(supplied))!=digest(strip(pending)):
            raise ValueError('reviewed_acceptance_differs_from_completed_derived_batch')
        if render_plan is not None:
            window=next(w for w in render_plan['approved_windows'] if w['id']==row['id'])
            if (supplied.get('crs')!=window['crs'] or supplied.get('affine')!=window['affine']
                    or supplied.get('provenance',{}).get('source_sha256s')!=window['source_sha256s']):
                raise ValueError('reviewed_render_window_geography_or_source_mismatch')
            import rasterio
            terrain_path=resolve(source_root,supplied['terrain'],contract='coastal-normalized-terrain-v1',cap=8*MIB)
            with rasterio.open(terrain_path) as dataset:
                if [dataset.height,dataset.width]!=window['shape']:
                    raise ValueError('reviewed_render_window_shape_mismatch')
        terrain.verify(source_root,supplied,now=now,minimum_valid_until=horizon)
        inputs.append(dict(id=row['id'],acceptance=supplied))
    shared_range=batch.get('render',{}).get('shared_range_m')
    if (not isinstance(shared_range,list) or len(shared_range)!=2
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in shared_range)
            or shared_range[0]>shared_range[1]):
        raise ValueError('derived_shared_absolute_range_required')
    return inputs,shared_range,receipt_ref,digest(dict(manifest=manifest,batch_binding=batch.get('binding'),
        input_contexts=[terrain.context(item['acceptance']) for item in inputs],shared_range=shared_range))

def batch_bytes_conflict(root):
    path=Path(root)
    return not path.is_absolute() or '..' in path.parts or path.is_symlink()




def _read_output(root,relative,cap):
    root=Path(root).resolve(strict=True)
    rel=Path(relative)
    if rel.is_absolute() or not rel.parts or '..' in rel.parts:
        raise ValueError('render_output_relative_path_required')
    target=root/rel
    current=root
    for part in rel.parts:
        current=current/part
        if current.is_symlink():
            raise ValueError('render_output_symlink_rejected')
    fd=os.open(target,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        if not __import__('stat').S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>cap:
            raise ValueError('bounded_single_link_render_file_required')
        data=b''
        while len(data)<before.st_size+1:
            piece=os.read(fd,before.st_size+1-len(data))
            if not piece: break
            data+=piece
        after=os.fstat(fd)
        if ((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns,before.st_nlink)
                !=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_nlink)
                or len(data)!=before.st_size):
            raise ValueError('render_output_changed_during_read')
        return data
    finally:
        os.close(fd)


def _bound_descriptor(root,descriptor,cap):
    if (not isinstance(descriptor,dict) or set(descriptor)-{'path','bytes','sha256','contract'}
            or not {'path','bytes','sha256'}<=set(descriptor) or type(descriptor['bytes']) is not int
            or not 0<descriptor['bytes']<=cap or not re.fullmatch(r'[a-f0-9]{64}',str(descriptor['sha256']))):
        raise ValueError('render_output_descriptor_invalid')
    data=_read_output(root,descriptor['path'],cap)
    if len(data)!=descriptor['bytes'] or hashlib.sha256(data).hexdigest()!=descriptor['sha256']:
        raise ValueError('render_output_descriptor_changed')
    return data


def verify_completed_batch(output_root):
    """Read-only browser admission: terminal batch marker binds every child artifact."""
    root=Path(output_root).resolve(strict=True)
    batch_data=_read_output(root,'batch-complete.json',RECEIPT_LIMIT)
    batch=json.loads(batch_data)
    if (batch.get('schema')!='coastal-governed-render-batch-v1' or batch.get('state')!='done'
            or type(batch.get('preview_count')) is not int or not 1<=batch['preview_count']<=4
            or len(batch.get('previews',[]))!=batch['preview_count']
            or batch.get('ledger_overhead_bytes')!=512*1024
            or batch.get('effective_control_bytes')!=CONTROL_LIMIT
            or batch.get('prewrite_enforcement')!='managed writer API only'
            or batch.get('disk_quota') is not False or batch.get('physical_io_measured') is not False):
        raise ValueError('completed_governed_render_batch_required')
    ids=set();data_sum=0;control_sum=0;checked=[];receipt_refs={}
    aggregate_complete_ref=batch.get('aggregate_completion')
    aggregate_pointer_ref=batch.get('aggregate_pointer')
    aggregate_receipt_ref=batch.get('aggregate_receipt')
    index_ref=batch.get('index')
    aggregate_complete_data=_bound_descriptor(root,aggregate_complete_ref,RECEIPT_LIMIT)
    pointer_data=_bound_descriptor(root,aggregate_pointer_ref,RECEIPT_LIMIT)
    aggregate_data=_bound_descriptor(root,aggregate_receipt_ref,RECEIPT_LIMIT)
    if index_ref.get('path')!='index.html':
        raise ValueError('render_batch_index_path_changed')
    index_data=_bound_descriptor(root,index_ref,DATA_LIMIT)
    aggregate_complete=json.loads(aggregate_complete_data)
    pointer=json.loads(pointer_data)
    aggregate=json.loads(aggregate_data)
    batch_binding=batch.get('binding')
    if (aggregate.get('schema')!='coastal-render-batch-v1' or aggregate.get('binding')!=batch_binding
            or any(aggregate.get(k)!=v for k,v in FLAGS.items())
            or aggregate_complete.get('schema')!='coastal-render-batch-completion-v1'
            or aggregate_complete.get('binding')!=batch_binding
            or aggregate_complete.get('receipt')!=aggregate_receipt_ref
            or aggregate_complete.get('html')!=index_ref
            or pointer.get('schema')!='coastal-render-batch-pointer-v1'
            or pointer.get('binding')!=batch_binding
            or pointer.get('completion')!=aggregate_complete_ref
            or pointer.get('receipt')!=aggregate_receipt_ref or pointer.get('html')!=index_ref
            or aggregate.get('shared_range_m')!=batch.get('shared_range_m')):
        raise ValueError('aggregate_render_completion_binding_mismatch')
    data_sum+=len(index_data)
    control_sum+=len(aggregate_complete_data)+len(pointer_data)+len(aggregate_data)
    for row in batch['previews']:
        ident=row.get('id')
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',ident) or ident in ids:
            raise ValueError('render_batch_preview_identity_invalid')
        ids.add(ident)
        binding=row.get('render_binding')
        if not re.fullmatch(r'[a-f0-9]{64}',str(binding)):
            raise ValueError('render_batch_binding_invalid')
        expected_render=f'{ident}/terrain/complete.json'
        expected_demo=f'{ident}/inspector/complete.json'
        for descriptor,expected in ((row.get('render_complete'),expected_render),(row.get('demo_complete'),expected_demo)):
            if descriptor.get('path')!=expected: raise ValueError('render_batch_completion_path_changed')
        render_marker_data=_bound_descriptor(root,row['render_complete'],RECEIPT_LIMIT)
        demo_marker_data=_bound_descriptor(root,row['demo_complete'],RECEIPT_LIMIT)
        render_marker=json.loads(render_marker_data);demo_marker=json.loads(demo_marker_data)
        if (render_marker.get('schema')!='coastal-terrain-only-complete-v1'
                or render_marker.get('binding')!=binding):
            raise ValueError('render_completion_binding_mismatch')
        render_ref=render_marker.get('receipt')
        if render_ref.get('path')!=f'{ident}/terrain/render-receipt.json':
            raise ValueError('render_receipt_path_mismatch')
        render_data=_bound_descriptor(root,render_ref,RECEIPT_LIMIT)
        render_receipt=json.loads(render_data)
        if (render_receipt.get('schema')!=terrain.RESULT or render_receipt.get('state')!='done'
                or render_receipt.get('render_binding')!=binding
                or any(render_receipt.get(k)!=v for k,v in FLAGS.items())):
            raise ValueError('render_receipt_not_accepted')
        artifacts=render_receipt.get('artifacts',[])
        expected={f'{ident}/terrain/terrain-mesh.npz':'coastal-terrain-only-mesh-v1',
                  f'{ident}/terrain/preview.png':'coastal-terrain-only-png-v1'}
        if len(artifacts)!=2 or {a.get('path') for a in artifacts}!=set(expected):
            raise ValueError('render_artifact_set_invalid')
        for artifact in artifacts:
            if artifact.get('contract')!=expected[artifact['path']]:
                raise ValueError('render_artifact_contract_changed')
            _bound_descriptor(root,artifact,8*MIB)
            data_sum+=artifact['bytes']
        demo_ref=demo_marker.get('receipt')
        if (demo_marker.get('schema')!='coastal-terrain-demo-complete-v1'
                or demo_ref.get('path')!=f'{ident}/inspector/demo-receipt.json'):
            raise ValueError('demo_completion_schema_or_receipt_mismatch')
        demo_receipt_data=_bound_descriptor(root,demo_ref,RECEIPT_LIMIT)
        demo_receipt=json.loads(demo_receipt_data)
        if (demo_receipt.get('schema')!=demo.SCHEMA or demo_receipt.get('state')!='done'
                or any(demo_receipt.get(k)!=v for k,v in FLAGS.items())
                or demo_receipt.get('render_receipt')!=render_ref):
            raise ValueError('demo_receipt_not_bound_to_render')
        html_descriptor=demo_marker.get('html')
        if (not isinstance(html_descriptor,dict) or html_descriptor.get('path')!='terrain-demo.html'
                or demo_receipt.get('html')!=html_descriptor):
            raise ValueError('demo_html_descriptor_changed')
        html_path=f'{ident}/inspector/{html_descriptor["path"]}'
        html_ref=dict(html_descriptor,path=html_path)
        _bound_descriptor(root,html_ref,HTML_LIMIT)
        data_sum+=html_descriptor['bytes']
        control_sum+=len(render_marker_data)+len(render_data)+len(demo_marker_data)+len(demo_receipt_data)
        receipt_refs[ident]=(render_ref,dict(demo_ref,contract=demo.SCHEMA))
        checked.append(dict(id=ident,render=render_receipt,demo=demo_receipt))
    if (len(aggregate.get('cores',[]))!=len(checked)
            or aggregate.get('accepted_window_ids')!=[core['id'] for core in checked]):
        raise ValueError('aggregate_core_count_mismatch')
    for aggregate_core,core in zip(aggregate['cores'],checked):
        ident=core['id']
        if (aggregate_core.get('window_id')!=ident
                or aggregate_core.get('terrain_binding')!=core['render']['render_binding']
                or aggregate_core.get('render_receipt')!=receipt_refs[ident][0]
                or aggregate_core.get('demo_receipt')!=receipt_refs[ident][1]):
            raise ValueError('aggregate_core_binding_mismatch')
    if aggregate_complete.get('core_completions')!=[
            row['render_complete'] for row in batch['previews']]+[
            row['demo_complete'] for row in batch['previews']]:
        raise ValueError('aggregate_core_completion_refs_changed')
    control_sum+=len(batch_data)
    if (data_sum!=batch.get('render_data_bytes') or
            control_sum!=batch.get('control_payload_bytes',0)+batch.get('batch_completion_bytes',-1) or
            data_sum>DATA_LIMIT or control_sum>CONTROL_LIMIT):
        raise ValueError('completed_render_batch_byte_forecast_mismatch')
    return dict(batch=batch,previews=checked,verified_render_data_bytes=data_sum,
                verified_control_bytes=control_sum,publication_authorized=False)

def _read_json(path,cap):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>cap: raise ValueError('bounded_regular_json_required')
    value=json.loads(path.read_text())
    if not isinstance(value,dict): raise ValueError('json_object_required')
    return value



def run_governed(context,source_root,inputs_path,*,now,horizon):
    """Validated programmatic entry; all public execution flows through child release."""
    from ..child_release import validate_child_release
    release=validate_child_release(context,'render',now=now,horizon=horizon)
    plan,manifest=load_owner_render_plan(context,release,source_root,inputs_path)
    inputs,shared_range,source_batch_ref,input_binding=load_render_prerequisites(
        source_root,manifest,now=now,horizon=horizon,render_plan=plan)
    if time.time()>=_epoch(horizon): raise TimeoutError('render_stage_deadline_exhausted')
    result=_forecast_and_write(source_root,inputs,release=release,now=now,horizon=horizon,
        shared_range_m=shared_range,source_batch_ref=source_batch_ref,input_binding=input_binding)
    verify_completed_batch(release['output_root'])
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--inputs',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        context=_read_json(args.context,512*1024)
        from ..handoff.common import load
        clock_ref=context.get('stage_clock')
        if not isinstance(clock_ref,dict):
            raise ValueError('pinned_render_stage_clock_required')
        clock=load(Path(clock_ref['root']),{k:v for k,v in clock_ref.items() if k!='root'},
                   contract='coastal-skill-stage-clock-v1')
        now=time.time()
        horizon=min(float(clock['deadline_epoch'])-0.25,now+3600)
        if horizon<=now:
            raise ValueError('render_stage_deadline_exhausted')
        def stop_deadline(_signum,_frame):
            raise TimeoutError('render_stage_deadline_exhausted')
        previous_handler=signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM,stop_deadline)
        signal.setitimer(signal.ITIMER_REAL,max(0.01,horizon-time.time()))
        try:
            result=run_governed(context,args.source_root,args.inputs,now=now,horizon=horizon)
            print(json.dumps(result,sort_keys=True,allow_nan=False)); return 0
        finally:
            signal.setitimer(signal.ITIMER_REAL,0)
            signal.signal(signal.SIGALRM,previous_handler)
    except (ValueError,KeyError,TypeError,OSError,zipfile.BadZipFile,TimeoutError) as error:
        print(json.dumps(dict(schema='coastal-governed-render-batch-v1',state='held',holds=[str(error)],**FLAGS)))
        return 2


if __name__=='__main__':
    raise SystemExit(main())

