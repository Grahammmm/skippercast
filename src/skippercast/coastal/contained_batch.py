"""Source-free contained, nonadjacent native window mapping. No source resolver."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from . import derived_batch as derived, vertical
from .handoff.common import confined, digest, load, ref, write, validate_derived_geotiff

BATCH = 'coastal-contained-derived-batch-v1'
LIMITATION = 'Private contained-window diagnostic; gaps are unobserved, no shared field or seam continuity claim.'


def _acceptance(item, refs):
    import rasterio
    original_crs=item['crs'].to_string()
    stored_crs=rasterio.crs.CRS.from_user_input(item['crs'].to_wkt()).to_string()
    limitations=item['facts']['support']['limitations']+[LIMITATION]
    if stored_crs!=original_crs:
        limitations.append('Stored-raster CRS spelling is canonical; the original qualified CRS and any BoundCRS operation remain bound in upstream evidence. No coordinate transformation was applied.')
    return dict(schema='coastal-terrain-only-input-v1',creator_id='coastal-contained-derived-batch',
        segment_id=item['result']['segment_id'],**refs,uncertainty_kind='producer_uncertainty_m',
        vertical=item['vertical'],crs=stored_crs,affine=list(item['transform']),
        provenance=dict(source_sha256s=[item['result']['source']['sha256']],
                        upstream_receipt_sha256=item['result_ref']['sha256']),
        support_kind=item['facts']['support']['support_kind'],
        limitations=limitations,
        synthetic=item['packet']['synthetic'],source_accessed=False,imagery_used=False,
        internal_diagnostic=True,publication_prohibited=True,website='held',habitat='unassessed')


def _prepare(root, packets, side, now, horizon, *, declared_window_count=None):
    from affine import Affine
    from pyproj import CRS
    from shapely.geometry import box
    import numpy as np
    from .authenticated_v1.profiles import CONTAINED
    if (type(side)!=int or not 1<=side<=128 or not isinstance(packets,list)
            or not 1<=len(packets)<=4):
        raise ValueError('one to four common-side bounded windows required')
    count=len(packets) if declared_window_count is None else declared_window_count
    if type(count) is not int or not len(packets)<=count<=4:
        raise ValueError("explicit original contained count required")
    items=[]; infos=[]
    for packet in packets:
        if packet.get('schema')=='coastal-derived-window-hold-v1':
            info=derived.read_held(root,packet,side=side);item=None
            facts=info['facts'];obs=info['observation']
            info.update(crs=CRS.from_user_input(facts['header']['horizontal_crs']),
                        synthetic=obs['synthetic'])
        else:
            item=derived.read_window(root,packet,side=side,now=now,minimum_valid_until=horizon)
            facts=item['facts']
            obs=load(root,item['result']['observation'],contract='coastal-authenticated-observation-v1')
            info=dict(source=item['result']['source'],segment_id=item['result']['segment_id'],
                native_window=facts['header']['window'],transform=item['transform'],crs=item['crs'],
                synthetic=item['packet']['synthetic'])
            data=derived.arrays(root,item['result']['arrays'],side=side)
            pair=(~data['elevation_mask'] & ~data['uncertainty_mask']
                  & np.isfinite(data['raw_elevation_data']) & np.isfinite(data['raw_uncertainty_data']))
            if (not item['valid'].all() or int(facts['valid_count'])!=side*side
                    or np.any(item['depth']<0) or np.any(item['depth']>91.44)
                    or np.any(item['uncertainty']<=0) or np.any(item['uncertainty']>1)):
                raise ValueError('contained strict all-pairs depth and uncertainty science gate required')
            if not np.array_equal(pair,item['valid']):
                raise ValueError('exact native finite-pair support required')
        if (obs.get('execution_profile')!=CONTAINED or obs.get('window_side')!=side
                or obs.get('window_count')!=count):
            raise ValueError('contained qualification profile/configuration binding required')
        tr=info['transform'];crs=info['crs'];win=info['native_window']
        if (tr.a!=2 or tr.e!=-2 or tr.b or tr.d or not crs.is_projected
                or any(a.unit_conversion_factor!=1 for a in crs.axis_info[:2])
                or len(win)!=4 or any(type(v)!=int or v<0 for v in win)
                or win[2:]!=[side,side]):
            raise ValueError('registered native metric two metre square required')
        info['box']=box(tr.c,tr.f-2*side,tr.c+2*side,tr.f)
        items.append(item);infos.append(info)
    identity=lambda x:(x['source'],x['segment_id'],x['crs'].to_wkt(),x['synthetic'],
                        x['transform'].c-2*x['native_window'][0],
                        x['transform'].f+2*x['native_window'][1])
    if any(identity(i)!=identity(infos[0]) for i in infos):
        raise ValueError('one source, segment, grid and synthetic identity required')
    windows=[i['native_window'] for i in infos]
    if windows!=sorted(windows,key=lambda w:(-w[1],w[0])):
        raise ValueError('deterministic south-first then eastward window ordering required')
    for i,a in enumerate(infos):
        if any(a['box'].intersection(b['box']).area>0 for b in infos[i+1:]):
            raise ValueError('distinct nonoverlapping window footprints required')
    accepted=[i for i in items if i is not None]
    if accepted and any(digest(i['vertical'])!=digest(accepted[0]['vertical']) for i in accepted):
        raise ValueError('one normalized vertical lineage required')
    return items,infos


def _claims(root, items, infos, side, baselines, binding):
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union, transform as project
    from pyproj import Transformer
    from .handoff.mapping_input import _support
    import numpy as np
    if not isinstance(baselines,list):raise ValueError('explicit retained baseline references required')
    crs=infos[0]['crs'];geometries=[];rows=[];depths=[]
    for index,(item,info) in enumerate(zip(items,infos)):
        if item is None:
            rows.append(dict(id='ABCD'[index],state='held',native_window=info['native_window'],
                held_result=info['held_result'],holds=info['holds'],valid_cells=0,
                measurement_credited=False,selected_area_m2=side*side*4))
        else:
            support=_support(item['valid'],item['transform'],crs)
            if digest(support['geometry'])!=digest(item['facts']['support']['geometry']):
                raise ValueError('native support geometry differs from derived pairs')
            geometries.append(shape(support['geometry']))
            depths.append(item['depth'][item['valid']])
            rows.append(dict(id='ABCD'[index],state='accepted_private_mapping',
                native_window=info['native_window'],valid_cells=int(item['valid'].sum()),
                selected_area_m2=side*side*4,nominal_valid_area_m2=int(item['valid'].sum())*4,
                nominal_unsupported_area_m2=(side*side-int(item['valid'].sum()))*4,
                upstream_result=item['result_ref'],scientific_review=item['packet']['scientific_review']))
    union=unary_union(geometries);selected=unary_union([i['box'] for i in infos])
    prior=[]
    for descriptor in baselines:
        doc=load(root,descriptor,contract='coastal-retained-support-v1')
        if doc.get('schema')!='coastal-retained-support-v1':raise ValueError('retained support baseline schema required')
        prior.append(project(Transformer.from_crs(doc['crs'],crs,always_xy=True).transform,shape(doc['geometry'])))
    prior=unary_union(prior);net=union.difference(prior)
    equal=Transformer.from_crs(crs,'EPSG:3310',always_xy=True).transform
    values=np.concatenate(depths) if depths else np.array([])
    return dict(schema=BATCH,binding=binding,source_accessed=False,publication_prohibited=True,
        synthetic=infos[0]['synthetic'],
        state='mapped_pending_render_reviews' if depths else 'all_windows_held',
        windows=rows,support=dict(crs=crs.to_string(),geometry=mapping(union),
            selected_geometry=mapping(selected),selected_area_m2=selected.area,
            nominal_valid_area_m2=union.area,selected_unobserved_area_m2=selected.difference(union).area,
            selected_gap_geometry=mapping(selected.difference(union)),
            bounding_box_area_m2=selected.envelope.area,
            bounding_box_unobserved_area_m2=selected.envelope.difference(union).area,
            bounding_box_gap_geometry=mapping(selected.envelope.difference(union)),
            overlap_removed_m2=sum(g.area for g in geometries)-union.area,
            nominal_net_new_area_m2=net.area,equal_area_valid_m2=project(equal,union).area,
            equal_area_net_new_m2=project(equal,net).area,baseline_refs=baselines),
        render=dict(core_packets=len(depths),scientific_reviews_required=True,
            shared_range_m=[float(values.min()),float(values.max())] if values.size else None,
            range_mode='locked',view='Measured',subdivisions=1,shared_context_cells=0,
            context_source=None,seam_lighting_continuity_accepted=False,production_loader_ready=False))


def _verify(root,receipt,expected,items):
    import numpy as np
    import rasterio
    if digest({k:receipt[k] for k in expected})!=digest(expected):
        raise ValueError('completed contained semantic claims changed')
    accepted=[i for i in items if i is not None]
    if len(receipt['acceptances'])!=len(accepted):raise ValueError('completed acceptance count changed')
    artifacts=[]
    for desc,item in zip(receipt['acceptances'],accepted):
        doc=load(root,desc,contract='coastal-terrain-only-input-v1');artifacts.append(desc)
        refs={role:doc[role] for role in ('terrain','mask','uncertainty')}
        if digest(doc)!=digest(_acceptance(item,refs)):raise ValueError('completed acceptance claims changed')
        for role,values,contract in (
            ('terrain',item['depth'],'coastal-normalized-terrain-v1'),
            ('mask',item['valid'],'coastal-native-support-v2'),
            ('uncertainty',item['uncertainty'],'coastal-derived-uncertainty-m-v1')):
            desc=refs[role];artifacts.append(desc)
            with rasterio.open(validate_derived_geotiff(root,desc,contract=contract)) as ds:
                actual=ds.read(1,masked=True)
                if (ds.shape!=values.shape or ds.transform!=item['transform'] or ds.crs!=item['crs']
                        or ds.count!=1 or ds.dtypes!=(('uint8' if role=='mask' else 'float32'),)):
                    raise ValueError('completed raster registration changed')
                if role=='mask':
                    valid=(ds.nodata is None and not np.ma.getmaskarray(actual).any()
                           and np.array_equal(np.asarray(actual),values.astype('uint8')))
                else:
                    valid=(np.array_equal(~np.ma.getmaskarray(actual),item['valid'])
                           and np.array_equal(actual.compressed(),values[item['valid']].astype('float32'))
                           and ds.units==('m',) and ds.scales==(1.0,) and ds.offsets==(0.0,))
                if not valid:raise ValueError('completed raster values/support changed')
                if role=='terrain':
                    tags=ds.tags()
                    if (ds.descriptions!=('depth_m_positive_down',) or tags.get('publication_prohibited')!='true'
                            or tags.get('vertical_sign')!='positive_down' or tags.get('scale_offset_applied')!='true'
                            or tags.get('datum_realization')!=item['vertical']['datum_realization']):
                        raise ValueError('completed terrain physical semantics changed')
                    if digest(vertical.normalized_from_raster(ds,source_sha256=desc['sha256'])['lineage'])!=digest(item['vertical']['lineage']):
                        raise ValueError('completed vertical lineage changed')
    if sorted(digest(a) for a in artifacts)!=sorted(digest(a) for a in receipt['artifacts']):
        raise ValueError('completed artifact set changed')


def assemble(root,packets,*,side,output_dir,now,baselines,minimum_valid_until=None):
    """Finite 1..4 windows; all-held is truthful zero mapping, never an invented raster."""
    items,infos=_prepare(root,packets,side,now,minimum_valid_until)
    binding=digest(dict(packets=packets,side=side,baselines=baselines,
        implementations={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (Path(__file__),Path(derived.__file__))}))
    expected=_claims(root,items,infos,side,baselines,binding)
    out=confined(root,output_dir,existing=False);retention=None
    if (Path(root)/'retention.json').exists():
        from .retention import Retention
        retention=Retention(root,json.loads((Path(root)/'retention.json').read_text())['plan_digest'])
        if out.parent==Path(root).resolve():raise ValueError('exclusive mapping parent required')
        retention.reserve('mapping',binding,out.parent.relative_to(Path(root).resolve()).as_posix(),role='mapping')
        retention.audit()
    if out.exists():
        receipt=load(root,ref(root,out/'batch.json',BATCH),contract=BATCH)
        marker=load(root,ref(root,out/'complete.json','coastal-contained-derived-completion-v1'))
        if marker!=dict(schema='coastal-contained-derived-completion-v1',receipt=ref(root,out/'batch.json',BATCH)):
            raise ValueError('completed contained identity changed')
        _verify(root,receipt,expected,items)
        if retention:retention.settle('mapping',completed=True)
        return receipt
    out.parent.mkdir(parents=True,exist_ok=True)
    if list(out.parent.glob('.'+out.name+'.mapping-*')):
        raise ValueError('interrupted mapping evidence preserved; use a new owned directory after investigation')
    stage=Path(tempfile.mkdtemp(prefix='.'+out.name+'.mapping-',dir=out.parent))
    write(stage/'ownership.json',dict(binding=binding))
    receipt=dict(expected,acceptances=[],artifacts=[])
    for index,item in enumerate(items):
        if item is None:continue
        refs=derived._write_rasters(root,stage/str(index),item)
        prefix=stage.relative_to(Path(root).resolve()).as_posix()+'/'
        target=out.relative_to(Path(root).resolve()).as_posix()+'/'
        for desc in refs.values():desc['path']=target+desc['path'][len(prefix):]
        acceptance=_acceptance(item,refs)
        path=stage/str(index)/'acceptance-pending-review.json';write(path,acceptance)
        desc=ref(root,path,'coastal-terrain-only-input-v1');desc['path']=target+desc['path'][len(prefix):]
        receipt['acceptances'].append(desc);receipt['artifacts'].extend([*refs.values(),desc])
    if len(json.dumps(receipt).encode())>2_000_000:raise ValueError('contained metadata 2MB cap exceeded')
    write(stage/'batch.json',receipt)
    desc=ref(root,stage/'batch.json',BATCH);desc['path']=(out/'batch.json').relative_to(Path(root).resolve()).as_posix()
    write(stage/'complete.json',dict(schema='coastal-contained-derived-completion-v1',receipt=desc))
    if sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())>derived.MAX_OUTPUT:
        raise ValueError('contained mapping 8MiB ceiling exceeded; evidence preserved')
    for p in stage.rglob('*'):
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    if retention:retention.audit()
    from .render.preview import publish_staging
    publish_staging(stage,out)
    if retention:retention.settle('mapping',completed=True)
    return receipt
