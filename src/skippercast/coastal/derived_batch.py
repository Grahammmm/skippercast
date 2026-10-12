"""Source-free finite mapping from independently accepted qualification arrays.

This adapter never resolves the original source pointer or re-runs native
qualification. Scientific authority is the separate bound independent review.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile
import os

from .handoff.common import confined, digest, load, ref, resolve, review_holds, write
from . import vertical

INPUT = 'coastal-derived-window-v1'
BATCH = 'coastal-derived-batch-v1'
REVIEW = 'coastal-derived-window-review-v1'
KEYS = {'depth', 'raw_elevation_data', 'raw_uncertainty_data', 'elevation_mask',
        'uncertainty_mask', 'source_pair_valid', 'legacy_25_300ft_uncertainty_0_1m'}
MAX_OUTPUT = 8 * 1024 * 1024


def _derived(root, artifact, contract):
    if (artifact.get('contract') != contract or Path(artifact.get('path', '')).suffix.lower() == '.bag'
            or type(artifact.get('bytes')) is not int or artifact['bytes'] > 4*1024*1024):
        raise ValueError('bounded derived artifact role required')
    return resolve(root, artifact, contract=contract, cap=4*1024*1024)


def arrays(root, artifact, *, side=128):
    """Inspect bounded NPY declarations before loading already-derived arrays."""
    import numpy as np
    path = _derived(root, artifact, 'coastal-authenticated-arrays-v1')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (len(entries) != len(KEYS) or {item.filename for item in entries} != {key+'.npy' for key in KEYS}
                or sum(item.file_size for item in entries) > 4*1024*1024):
            raise ValueError('exact bounded derived array members required')
        for item in entries:
            with archive.open(item) as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1, 0):
                    shape, order, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=4096)
                elif version == (2, 0):
                    shape, order, dtype = np.lib.format.read_array_header_2_0(stream, max_header_size=4096)
                else:
                    raise ValueError('bounded NPY version required')
                if (shape != (side,side) or order or dtype.hasobject or dtype.fields
                        or dtype.kind not in 'fb' or dtype.itemsize > 8
                        or stream.tell()+side*side*dtype.itemsize != item.file_size):
                    raise ValueError('bounded exact128x128 primitive derived arrays required')
    with np.load(path, allow_pickle=False) as saved:
        result = {key: saved[key].copy() for key in KEYS}
    for key in KEYS:
        expected = np.dtype('float64') if key == 'depth' else np.dtype('float32') if key.startswith('raw_') else np.dtype('bool')
        if result[key].dtype != expected:
            raise ValueError('unchanged worker array dtypes required')
    return result


def read_window(root, packet, *, now, minimum_valid_until=None, side=128):
    import numpy as np
    from affine import Affine
    from pyproj import CRS
    from .authenticated_v1.supplement import summarize
    document = load(root, packet, contract=INPUT)
    if document.get('schema') != INPUT or document.get('source_accessed') is not False:
        raise ValueError('source-free derived window required')
    if type(document.get('synthetic')) is not bool:
        raise ValueError('explicit synthetic status required')
    result_ref = document['qualified_result']
    result = load(root, result_ref, contract='coastal-authenticated-stage-result-v1')
    if (result.get('stage') != 'qualify' or result.get('state') != 'done' or result.get('holds')
            or result.get('policy_holds') or result.get('accepted') is not False
            or result.get('qualification') is not False):
        raise ValueError('completed unheld qualification result required')
    facts_digest = result['facts_digest']
    if result.get('producer_facts_digest') != facts_digest or result.get('verified_facts_digest') != facts_digest:
        raise ValueError('producer/verifier factual binding required')
    observation = load(root, result['observation'], contract='coastal-authenticated-observation-v1')
    verification = load(root, result['verification'], contract='coastal-authenticated-verification-v1')
    facts = observation['native_facts']
    if (digest(facts) != facts_digest or observation.get('facts_digest') != facts_digest
            or observation.get('machine_holds') or observation.get('publication_prohibited') is not True
            or verification.get('ready') is not True or verification.get('holds')
            or verification.get('facts_digest') != facts_digest or digest(verification['facts']) != facts_digest
            or result['source'] != observation['source'] or facts['source'] != result['source']
            or result['segment_id'] != observation['segment_id']
            or document['synthetic'] is not observation.get('synthetic')):
        raise ValueError('qualified facts/segment/publication binding required')
    review_digest = digest({'qualified_result': result_ref, 'facts_digest': facts_digest})
    holds = review_holds(root, document.get('scientific_review'), review_digest, now=now,
                         minimum_valid_until=minimum_valid_until, schema=REVIEW)
    review = load(root, document['scientific_review'], contract=REVIEW)
    if (holds or review.get('scope') != 'qualified-array-mapping'
            or review.get('reviewer_id') == document.get('creator_id')
            or review.get('synthetic') is not observation.get('synthetic')):
        raise ValueError('independent bound derived mapping review required')
    if facts.get('rights', {}).get('private_use') is not True or not facts['rights'].get('evidence'):
        raise ValueError('qualified private rights required')
    data = arrays(root, result['arrays'], side=side)
    diagnostics = summarize(data, facts_digest)
    for role in ('diagnostics', 'verified_diagnostics'):
        prior = load(root, result[role], contract='coastal-same-return-pair-diagnostics-v1')
        if diagnostics != prior:
            raise ValueError('exact independently verified array diagnostics required')
    for role in ('policy_evaluation', 'verified_policy'):
        policy = load(root, result[role], contract='coastal-fixed-patch-policy-evaluation-v1')
        if (policy.get('holds') or policy.get('paired_eligibility_quality_pass') is not True
                or policy.get('facts_digest') != facts_digest
                or policy.get('diagnostics_digest') != diagnostics['diagnostics_digest']
                or policy.get('policy_sha256') != result.get('policy_sha256')
                or policy.get('trial_policy_sha256') != result.get('trial_policy_sha256')):
            raise ValueError('qualified science policy binding required')
    valid = data['source_pair_valid']
    if (np.any(valid & (data['elevation_mask'] | data['uncertainty_mask']))
            or not np.array_equal(np.isfinite(data['depth']), valid)
            or np.any(valid & (~np.isfinite(data['raw_elevation_data']) | ~np.isfinite(data['raw_uncertainty_data'])))):
        raise ValueError('exact native paired masks/finite depth required')
    block = vertical.require_resolved(observation['declared_vertical'], facts['observed_vertical'])
    expected_depth = vertical.to_depth(data['raw_elevation_data'], block, valid=valid, nodata=1e6)
    if not np.array_equal(expected_depth, data['depth'], equal_nan=True):
        raise ValueError('same-return normalized depths changed')
    uncertainty = np.where(valid, data['raw_uncertainty_data'], np.nan)
    if np.any(valid & (uncertainty <= 0)):
        raise ValueError('positive producer uncertainty required')
    h = facts['header']
    if h.get('window') != observation['window'] or h['window'][2:] != [side,side]:
        raise ValueError('exact planned window required')
    transform = Affine(*h['transform'])
    crs = CRS.from_user_input(h['horizontal_crs'])
    if (transform.a != 2 or transform.e != -2 or transform.b or transform.d
            or not crs.is_projected or any(axis.unit_conversion_factor != 1 for axis in crs.axis_info[:2])):
        raise ValueError('native registered2m metric north-up grid required')
    for key, values in (
        ('raw_valid_values_sha256', np.where(valid,data['raw_elevation_data'],0).astype('<f8')),
        ('depth_values_sha256', np.where(valid,data['depth'],0).astype('<f4'))):
        if hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest() != facts[key]:
            raise ValueError('array factual hash mismatch')
    if (int(valid.sum()) != facts['valid_count']
            or hashlib.sha256(valid.astype('uint8').tobytes()).hexdigest() != facts['support']['mask_sha256']):
        raise ValueError('array support count/hash mismatch')
    return dict(packet=document, result=result, result_ref=result_ref, facts=facts, depth=data['depth'],
                uncertainty=uncertainty, valid=valid, transform=transform, crs=crs,
                vertical=vertical.normalized(block))


def read_held(root, packet, *, side=128):
    from affine import Affine
    if packet.get('source_accessed') is not False:
        raise ValueError('source-free terminal hold required')
    descriptor=packet['held_result']
    result=load(root,descriptor,contract='coastal-authenticated-stage-result-v1')
    if (result.get('state')!='held' or result.get('stage') not in ('acquire','qualify')
            or not result.get('holds') or result.get('accepted') is not False
            or result.get('qualification') is not False):
        raise ValueError('actual authenticated terminal hold required')
    observation=load(root,result['observation'],contract='coastal-authenticated-observation-v1')
    plan=load(root,result['plan'],contract='coastal-authenticated-window-plan-v1')
    facts=observation['native_facts']
    if (facts.get('source')!=result['source'] or observation.get('source')!=result['source']
            or digest(facts)!=result['facts_digest'] or observation['facts_digest']!=result['facts_digest']
            or observation['window']!=plan['window'] or facts['header']['window']!=plan['window']
            or plan['window'][2:]!=[side,side] or result['segment_id']!=observation['segment_id']):
        raise ValueError('held result source/window facts binding required')
    return dict(source=result['source'],transform=Affine(*facts['header']['transform']),
                segment_id=result['segment_id'],native_window=plan['window'],held_result=descriptor,
                holds=result['holds'],facts=facts,observation=observation)


def held_receipt(index, info):
    return dict(id='ABCD'[index],state='held',holds=info['holds'],native_window=info['native_window'],
                held_result=info['held_result'],source_sha256=info['source']['sha256'],
                valid_cells=0,measurement_credited=False)


def _write_rasters(root, directory, item):
    import numpy as np
    import rasterio
    directory.mkdir(parents=True)
    common = dict(driver='GTiff',width=item['valid'].shape[1],height=item['valid'].shape[0],count=1,crs=item['crs'],
                  transform=item['transform'],compress='DEFLATE')
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        for role, values, contract in (
            ('terrain',item['depth'],'coastal-normalized-terrain-v1'),
            ('mask',item['valid'].astype('uint8'),'coastal-native-support-v2'),
            ('uncertainty',item['uncertainty'],'coastal-derived-uncertainty-m-v1')):
            path = directory/(role+'.tif')
            if role != 'mask':
                cast = values.astype('float32')
                if not np.array_equal(cast.astype('float64')[item['valid']], values.astype('float64')[item['valid']]):
                    raise ValueError('lossless float32 derived storage required')
            with rasterio.open(path,'w',dtype='uint8' if role == 'mask' else 'float32',
                               nodata=None if role == 'mask' else np.nan,**common) as ds:
                ds.write(values.astype('uint8' if role == 'mask' else 'float32'),1)
                if role != 'mask':
                    ds.write_mask(item['valid'].astype('uint8')*255)
                    ds.set_band_unit(1,'m')
                if role == 'terrain':
                    ds.set_band_description(1,'depth_m_positive_down')
                    ds.update_tags(vertical_contract=json.dumps(item['vertical'],sort_keys=True),
                        vertical_sign='positive_down',vertical_datum=item['vertical']['datum'],
                        datum_realization=item['vertical']['datum_realization'],
                        scale_offset_applied='true',publication_prohibited='true',
                        source_sha256=item['result']['source']['sha256'])
                elif role == 'uncertainty':
                    ds.set_band_description(1,'producer_uncertainty_m')
                    ds.update_tags(uncertainty_kind='producer_uncertainty_m',publication_prohibited='true')
    return {role:ref(root,directory/(role+'.tif'),contract) for role,contract in (
        ('terrain','coastal-normalized-terrain-v1'),('mask','coastal-native-support-v2'),
        ('uncertainty','coastal-derived-uncertainty-m-v1'))}


def _verify_completed(root, receipt, items, held_info, register, left, top, baselines):
    import numpy as np
    import rasterio
    from affine import Affine
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import unary_union, transform as project
    from .handoff.mapping_input import _support
    from .handoff.common import validate_derived_geotiff
    accepted = [item for item in items if item is not None]
    expected_field = dict(depth_m=np.full((256,256),np.nan),uncertainty_m=np.full((256,256),np.nan),
                          support=np.zeros((256,256),dtype=bool))
    geometries=[];artifact_refs=[]
    if len(receipt.get('acceptances',[])) != len(accepted) or len(receipt.get('windows',[])) != 4:
        raise ValueError('completed batch terminal window count changed')
    acceptance_index=0
    for index,(item,(col,row)) in enumerate(zip(items,register)):
        if item is None:
            if digest(receipt['windows'][index]) != digest(held_receipt(index,held_info[index])):
                raise ValueError('held batch window promoted')
            continue
        desc=receipt['acceptances'][acceptance_index];acceptance_index+=1
        document=load(root,desc,contract='coastal-terrain-only-input-v1')
        expected_labels=dict(schema='coastal-terrain-only-input-v1',creator_id='coastal-derived-batch',
            segment_id=item['result']['segment_id'],uncertainty_kind='producer_uncertainty_m',
            vertical=item['vertical'],crs=item['crs'].to_string(),affine=list(item['transform']),
            provenance=dict(source_sha256s=[item['result']['source']['sha256']],
                            upstream_receipt_sha256=item['result_ref']['sha256']),
            support_kind=item['facts']['support']['support_kind'],
            limitations=item['facts']['support']['limitations']+[
                'Internal diagnostic; original source access prohibited; core edges use renderer linear fallback until shared-context integration.'],
            synthetic=item['packet']['synthetic'],source_accessed=False,imagery_used=False,
            internal_diagnostic=True,publication_prohibited=True,website='held',habitat='unassessed')
        if set(document) != set(expected_labels)|{'terrain','mask','uncertainty'}:
            raise ValueError('completed batch acceptance fields changed')
        if digest({key:document[key] for key in expected_labels}) != digest(expected_labels):
            raise ValueError('completed batch acceptance claims changed')
        artifact_refs.append(desc)
        for role, values, contract in (
            ('terrain',item['depth'],'coastal-normalized-terrain-v1'),
            ('mask',item['valid'],'coastal-native-support-v2'),
            ('uncertainty',item['uncertainty'],'coastal-derived-uncertainty-m-v1')):
            artifact=document[role];artifact_refs.append(artifact)
            with rasterio.open(validate_derived_geotiff(root,artifact,contract=contract)) as ds:
                actual=ds.read(1,masked=True)
                if (ds.shape!=(128,128) or ds.count!=1 or ds.transform!=item['transform'] or ds.crs!=item['crs']
                    or ds.dtypes!=(('uint8' if role=='mask' else 'float32'),)):
                    raise ValueError('completed derived raster header changed')
                if role=='mask':
                    matches=(ds.nodata is None and not np.ma.getmaskarray(actual).any()
                             and np.array_equal(np.asarray(actual),values.astype('uint8')))
                else:
                    matches=(np.array_equal(~np.ma.getmaskarray(actual),item['valid'])
                             and np.array_equal(actual.compressed(),values[item['valid']].astype('float32')))
                if not matches:
                    raise ValueError('completed derived raster values/support changed')
                if role!='mask' and (ds.units!=('m',) or ds.scales!=(1.0,) or ds.offsets!=(0.0,)):
                    raise ValueError('completed derived raster units/packing changed')
                if role=='terrain':
                    tags=ds.tags()
                    if (ds.descriptions!=('depth_m_positive_down',) or tags.get('publication_prohibited')!='true'
                        or tags.get('vertical_sign')!='positive_down' or tags.get('scale_offset_applied')!='true'
                        or tags.get('vertical_datum')!=item['vertical']['datum']
                        or tags.get('datum_realization')!=item['vertical']['datum_realization']):
                        raise ValueError('completed terrain disclosure/header changed')
                    block=vertical.normalized_from_raster(ds,source_sha256=artifact['sha256'])
                    if digest(block['lineage']) != digest(item['vertical']['lineage']):
                        raise ValueError('completed vertical lineage changed')
        row_receipt=receipt['windows'][index]
        expected_window=dict(id='ABCD'[index],state='accepted_private_mapping',
            native_window=item['facts']['header']['window'],valid_cells=int(item['valid'].sum()),
            nominal_valid_area_m2=int(item['valid'].sum())*4,
            nominal_unsupported_area_m2=(16384-int(item['valid'].sum()))*4,
            upstream_result=item['result_ref'],scientific_review=item['packet']['scientific_review'])
        if digest(row_receipt)!=digest(expected_window):
            raise ValueError('completed batch window claims changed')
        for role,values in (('depth_m',item['depth']),('uncertainty_m',item['uncertainty']),('support',item['valid'])):
            expected_field[role][row:row+128,col:col+128]=values
        geometries.append(shape(_support(item['valid'],item['transform'],item['crs'])['geometry']))
    field_ref=receipt['shared_field'];artifact_refs.append(field_ref)
    field_path=resolve(root,field_ref,contract='coastal-derived-shared-field-v1',cap=4*1024*1024)
    with zipfile.ZipFile(field_path) as archive:
        if ({x.filename for x in archive.infolist()} != {x+'.npy' for x in ('depth_m','uncertainty_m','support','affine','crs')}
                or len(archive.infolist())!=5 or sum(x.file_size for x in archive.infolist())>4*1024*1024):
            raise ValueError('bounded completed shared field required')
        for info in archive.infolist():
            with archive.open(info) as stream:
                version=np.lib.format.read_magic(stream)
                if version!=(1,0):raise ValueError('bounded shared field NPY version required')
                shape_npy,order,dtype=np.lib.format.read_array_header_1_0(stream,max_header_size=4096)
                key=info.filename[:-4]
                expected_shape=() if key=='crs' else (9,) if key=='affine' else (256,256)
                if (shape_npy!=expected_shape or order or dtype.hasobject or dtype.fields
                    or (dtype.kind!='U' if key=='crs' else dtype.kind not in 'fb')
                    or dtype.itemsize>(8192 if key=='crs' else 8)
                    or stream.tell()+int(np.prod(shape_npy))*dtype.itemsize!=info.file_size):
                    raise ValueError('bounded shared field primitive declarations required')
    with np.load(field_path,allow_pickle=False) as field:
        for key,values in expected_field.items():
            if not np.array_equal(field[key],values,equal_nan=True):
                raise ValueError('completed shared field values changed')
        if (not np.array_equal(field['affine'],np.array(list(Affine(2,0,left,0,-2,top))))
                or field['crs'].item()!=accepted[0]['crs'].to_wkt()):
            raise ValueError('completed shared field registration changed')
    if sorted(digest(a) for a in artifact_refs)!=sorted(digest(a) for a in receipt['artifacts']):
        raise ValueError('completed batch artifact set changed')
    union=unary_union(geometries)
    prior=[]
    for baseline in baselines:
        doc=load(root,baseline,contract='coastal-retained-support-v1')
        prior.append(project(Transformer.from_crs(doc['crs'],accepted[0]['crs'],always_xy=True).transform,shape(doc['geometry'])))
    prior_union=unary_union(prior)
    area=Transformer.from_crs(accepted[0]['crs'],'EPSG:3310',always_xy=True).transform
    expected_support=dict(crs=accepted[0]['crs'].to_string(),geometry=union.__geo_interface__,
        envelope_area_m2=262144,nominal_valid_area_m2=union.area,nominal_unsupported_area_m2=262144-union.area,
        overlap_removed_m2=sum(g.area for g in geometries)-union.area,
        nominal_net_new_area_m2=union.difference(prior_union).area,
        equal_area_valid_m2=project(area,union).area,equal_area_net_new_m2=project(area,union.difference(prior_union)).area,
        baseline_refs=baselines)
    if digest(receipt['support'])!=digest(expected_support):
        raise ValueError('completed batch support claims changed')
    expected_render=dict(core_packets=len(accepted),scientific_reviews_required=True,
        shared_context_cells=3,context_source='shared-field.npz',
        shared_range_m=[float(expected_field['depth_m'][expected_field['support']].min()),
                        float(expected_field['depth_m'][expected_field['support']].max())],
        range_mode='locked',common_subdivision_requested=8,seam_mode='linear_core_edge_fallback',
        seam_lighting_continuity_accepted=False,production_loader_ready=False)
    if (digest(receipt['render'])!=digest(expected_render) or receipt.get('source_accessed') is not False
        or receipt.get('synthetic') is not accepted[0]['packet']['synthetic']
        or receipt.get('publication_prohibited') is not True or receipt.get('state')!='mapped_pending_render_reviews'):
        raise ValueError('completed batch readiness claims changed')

def assemble(root, packets, *, output_dir, now, baselines, minimum_valid_until=None):
    """Produce exactly four core packets and one shared field without source reads.

    The renderer can inspect cores immediately after its own bound reviews.
    Shared field supplies three accepted context cells at internal seams;
    the current single-packet renderer still uses linear edge fallback.
    """
    import numpy as np
    from affine import Affine
    from shapely.geometry import shape, mapping as geometry_mapping, box
    from shapely.ops import unary_union, transform as project
    from pyproj import Transformer
    from .render.preview import publish_staging
    if not isinstance(packets,list) or len(packets) != 4 or not isinstance(baselines,list):
        raise ValueError('finite four packets and explicit all-retained-baseline refs required')
    held_info={}
    items=[]
    for index,packet in enumerate(packets):
        if packet.get('schema')=='coastal-derived-window-hold-v1':
            held_info[index]=read_held(root,packet)
            items.append(None)
        else:
            items.append(read_window(root,packet,now=now,minimum_valid_until=minimum_valid_until))
    accepted = [item for item in items if item is not None]
    if not accepted:
        raise ValueError('at least one independently accepted derived window required')
    source = accepted[0]['result']['source']
    register = [(0,128),(128,128),(0,0),(128,0)]  # A,B,C,D: south row first.
    first_index = next(i for i,item in enumerate(items) if item is not None)
    first = items[first_index]
    first_col,first_row = register[first_index]
    left = first['transform'].c - 2*first_col
    top = first['transform'].f + 2*first_row
    identity = lambda item:(item['result']['source'],item['crs'].to_wkt(),item['result']['segment_id'],
                           digest(item['vertical']),item['packet']['synthetic'])
    if any(identity(item) != identity(accepted[0]) for item in accepted):
        raise ValueError('one shared source/grid/vertical/segment/synthetic lineage required')
    for index,(item,(col,row)) in enumerate(zip(items,register)):
        current=held_info[index] if item is None else dict(source=item['result']['source'],
                    segment_id=item['result']['segment_id'],transform=item['transform'])
        if (current['transform']!=Affine(2,0,left+2*col,0,-2,top-2*row)
                or current['source']!=source or current['segment_id']!=accepted[0]['result']['segment_id']):
            raise ValueError('ordered disjoint adjacent A,B,C,D core registration required')
    binding = digest({'packets':packets,'baselines':baselines,
                      'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    out = confined(root,output_dir,existing=False)
    retention=None
    retention_path=Path(root)/'retention.json'
    if retention_path.exists():
        from .retention import Retention
        retention_state=json.loads(retention_path.read_text())
        retention=Retention(root,retention_state['plan_digest'])
        if out.parent == Path(root).resolve():
            raise ValueError('retained mapping requires an exclusive parent for staging and final output')
        retention.reserve('mapping',binding,out.parent.relative_to(Path(root).resolve()).as_posix(),role='mapping')
        retention.audit()
    if out.exists():
        receipt = load(root,ref(root,out/'batch.json',BATCH),contract=BATCH)
        marker = load(root,ref(root,out/'complete.json','coastal-derived-batch-completion-v1'))
        if receipt.get('binding') != binding or marker.get('receipt') != ref(root,out/'batch.json',BATCH):
            raise ValueError('completed batch identity differs')
        _verify_completed(root, receipt, items, held_info, register, left, top, baselines)
        if retention is not None:retention.settle('mapping',completed=True)
        return receipt
    out.parent.mkdir(parents=True,exist_ok=True)
    # Staging and final output share the reserved exclusive parent. Interrupted
    # staging remains counted and is never silently overwritten or refunded.
    stages = list(out.parent.glob('.'+out.name+'.mapping-*'))
    if stages:
        raise ValueError('interrupted batch staging preserved; investigate and use a new owned directory')
    stage = Path(tempfile.mkdtemp(prefix='.'+out.name+'.mapping-',dir=out.parent))
    write(stage/'ownership.json',dict(binding=binding))
    depth = np.full((256,256),np.nan,dtype='float64')
    uncertainty = np.full((256,256),np.nan,dtype='float32')
    valid = np.zeros((256,256),dtype=bool)
    artifacts=[];acceptances=[];geometries=[];window_receipts=[]
    for index,(item,(col,row)) in enumerate(zip(items,register)):
        if item is None:
            window_receipts.append(held_receipt(index,held_info[index]))
            continue
        refs = _write_rasters(root,stage/str(index),item)
        acceptance = dict(schema='coastal-terrain-only-input-v1',creator_id='coastal-derived-batch',
            segment_id=item['result']['segment_id'],**refs,uncertainty_kind='producer_uncertainty_m',
            vertical=item['vertical'],crs=item['crs'].to_string(),affine=list(item['transform']),
            provenance=dict(source_sha256s=[source['sha256']],upstream_receipt_sha256=item['result_ref']['sha256']),
            support_kind=item['facts']['support']['support_kind'],
            limitations=item['facts']['support']['limitations']+[
                'Internal diagnostic; original source access prohibited; core edges use renderer linear fallback until shared-context integration.'],
            synthetic=item['packet']['synthetic'],source_accessed=False,imagery_used=False,
            internal_diagnostic=True,publication_prohibited=True,website='held',habitat='unassessed')
        write(stage/str(index)/'acceptance-pending-review.json',acceptance)
        acceptances.append(ref(root,stage/str(index)/'acceptance-pending-review.json','coastal-terrain-only-input-v1'))
        artifacts.extend([*refs.values(),acceptances[-1]])
        depth[row:row+128,col:col+128]=item['depth']
        uncertainty[row:row+128,col:col+128]=item['uncertainty']
        valid[row:row+128,col:col+128]=item['valid']
        # Recompute geometry from actual accepted masks, not the catalog envelope.
        from .handoff.mapping_input import _support
        support=_support(item['valid'],item['transform'],item['crs'])
        if digest(support['geometry']) != digest(item['facts']['support']['geometry']):
            raise ValueError('qualified valid footprint differs from actual arrays')
        geometries.append(shape(support['geometry']))
        window_receipts.append(dict(id='ABCD'[index],state='accepted_private_mapping',native_window=item['facts']['header']['window'],
            valid_cells=int(item['valid'].sum()),nominal_valid_area_m2=int(item['valid'].sum())*4,
            nominal_unsupported_area_m2=(16384-int(item['valid'].sum()))*4,
            upstream_result=item['result_ref'],scientific_review=item['packet']['scientific_review']))
    global_transform=Affine(2,0,left,0,-2,top)
    np.savez_compressed(stage/'shared-field.npz',depth_m=depth,uncertainty_m=uncertainty,support=valid,
                        affine=np.array(list(global_transform)),crs=np.array(accepted[0]['crs'].to_wkt()))
    field_ref=ref(root,stage/'shared-field.npz','coastal-derived-shared-field-v1')
    artifacts.append(field_ref)
    union=unary_union(geometries)
    prior_geometries=[]
    for baseline in baselines:
        baseline_doc=load(root,baseline,contract='coastal-retained-support-v1')
        if baseline_doc.get('schema') != 'coastal-retained-support-v1':
            raise ValueError('explicit retained support baseline required')
        from_crs=baseline_doc['crs']
        prior_geometries.append(project(Transformer.from_crs(from_crs,accepted[0]['crs'],always_xy=True).transform,
                                       shape(baseline_doc['geometry'])))
    prior=unary_union(prior_geometries)
    to_area=Transformer.from_crs(accepted[0]['crs'],'EPSG:3310',always_xy=True).transform
    nominal_envelope=262144
    native_area=union.area
    receipt=dict(schema=BATCH,binding=binding,source_accessed=False,publication_prohibited=True,
        synthetic=accepted[0]['packet']['synthetic'],state='mapped_pending_render_reviews',
        windows=window_receipts,acceptances=acceptances,shared_field=field_ref,artifacts=artifacts,
        support=dict(crs=accepted[0]['crs'].to_string(),geometry=geometry_mapping(union),
            envelope_area_m2=nominal_envelope,nominal_valid_area_m2=native_area,
            nominal_unsupported_area_m2=nominal_envelope-native_area,
            overlap_removed_m2=sum(g.area for g in geometries)-native_area,
            nominal_net_new_area_m2=union.difference(prior).area,
            equal_area_valid_m2=project(to_area,union).area,
            equal_area_net_new_m2=project(to_area,union.difference(prior)).area,
            baseline_refs=baselines),
        render=dict(core_packets=len(accepted),scientific_reviews_required=True,
            shared_context_cells=3,context_source='shared-field.npz',
            shared_range_m=[float(depth[valid].min()),float(depth[valid].max())],
            range_mode='locked',common_subdivision_requested=8,
            seam_mode='linear_core_edge_fallback',
            seam_lighting_continuity_accepted=False,production_loader_ready=False))
    # Rewrite all staging paths to their final paths before hashing the receipt.
    prefix=stage.relative_to(Path(root).resolve()).as_posix()+'/'
    target=out.relative_to(Path(root).resolve()).as_posix()+'/'
    def final_paths(value):
        if isinstance(value,dict):
            for key,child in value.items():
                if key=='path' and isinstance(child,str) and child.startswith(prefix):
                    value[key]=target+child[len(prefix):]
                else:final_paths(child)
        elif isinstance(value,list):
            for child in value:final_paths(child)
    accepted_index = 0
    for index,item in enumerate(items):
        if item is None:
            continue
        path=stage/str(index)/'acceptance-pending-review.json'
        document=json.loads(path.read_text());final_paths(document);write(path,document)
        updated=ref(root,path,'coastal-terrain-only-input-v1')
        receipt['acceptances'][accepted_index].update(updated)
        accepted_index += 1
        # acceptances and artifacts share descriptor objects.
    final_paths(receipt)
    if len((json.dumps(receipt,sort_keys=True,separators=(',',':'))+'\n').encode())>2_000_000:
        raise ValueError('batch metadata2MB ceiling exceeded; incomplete staging preserved')
    write(stage/'batch.json',receipt)
    receipt_ref=ref(root,stage/'batch.json',BATCH);final_paths(receipt_ref)
    write(stage/'complete.json',dict(schema='coastal-derived-batch-completion-v1',receipt=receipt_ref))
    if sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()) > MAX_OUTPUT:
        raise ValueError('mapping batch aggregate8MiB bound exceeded')
    for p in stage.rglob('*'):
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    fd=os.open(stage,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    publish_staging(stage,out)
    if retention is not None:
        retention.settle('mapping',completed=True)
    return receipt


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--plan', required=True, help='root-relative finite derived batch JSON')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--now', required=True, help='aware observation/review-check time')
    parser.add_argument('--minimum-valid-until')
    args = parser.parse_args(argv)
    plan = load(args.root, ref(args.root, args.plan, 'coastal-derived-batch-plan-v1'))
    if plan.get('schema') != 'coastal-derived-batch-plan-v1':
        raise ValueError('versioned finite derived batch plan required')
    result = assemble(args.root, plan['packets'], output_dir=args.output_dir, now=args.now,
                      baselines=plan['baselines'], minimum_valid_until=args.minimum_valid_until)
    print(json.dumps({'schema': BATCH, 'state': result['state'], 'binding': result['binding'],
                      'source_accessed': False}, sort_keys=True))


if __name__ == '__main__':
    main()
