"""Durable source-free mapping bridge for registered retained qualifications.

Native producer identity is imported from a completed authenticated Store through
read-only SQL. Only bounded JSON and qualified NPZ are copied; original source
pointers remain metadata. Mapping jobs use the existing coordinator queue.
"""
from datetime import datetime,timezone,timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import os

from .stages import digest
from ..handoff.common import load,ref,write,confined,resolve
from .. import contained_batch,derived_batch

CONTRACT='coastal-sourcefree-map-job-v1'
INPUT='coastal-sourcefree-map-manifest-v1'
PROOF='coastal-retained-producer-proof-v1'
CORE='coastal-sourcefree-map-core-v1'
IDENTITY_FIELDS=('job_id','stage','segment_id','code_sha','deps_sha','params_sha','input_manifest_sha')
SCHEMA="""
CREATE TABLE IF NOT EXISTS sourcefree_imports(manifest_sha TEXT PRIMARY KEY,record_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retained_producers(proof_sha TEXT PRIMARY KEY,record_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retained_artifacts(path TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,
 proof_sha TEXT NOT NULL REFERENCES retained_producers,PRIMARY KEY(path,sha256,proof_sha));
"""
MAX_TOTAL=16*1024*1024
MAX_MAPPING=4*1024*1024

def policy():
    from importlib.resources import files
    p=json.loads(files('skippercast.coastal.coordinator').joinpath('policy.json').read_text())
    p.update(sourcefree_only=True,max_attempts=2)
    p['storage']['minimum_free_bytes']=1073741824
    p['budgets']=dict(wall_s=3600,bytes=0,requests=0)
    p['storage']['job_output_bytes']=MAX_MAPPING
    return p

def _stamp(now):
    return now if isinstance(now,datetime) else datetime.fromtimestamp(float(now),timezone.utc)

def _copy_refs(root,result_ref,packet):
    result=load(root,result_ref,contract='coastal-authenticated-stage-result-v1')
    obs=load(root,result['observation'],contract='coastal-authenticated-observation-v1')
    refs=[result_ref,packet['scientific_review']]
    refs.extend(result[k] for k in ('observation','verification','arrays','diagnostics',
        'verified_diagnostics','policy_evaluation','verified_policy','plan'))
    refs.extend(obs['native_facts']['rights']['evidence'])
    unique={}
    for d in refs:
        suffix=Path(d['path']).suffix.lower()
        if suffix not in ('.json','.npz') or 'native-source' in d['contract']:
            raise ValueError('only retained qualification JSON/NPZ allowed')
        if d['path'] in unique and unique[d['path']]!=d:raise ValueError('retained path identity collision')
        resolve(root,d,contract=d['contract'],cap=4194304 if suffix=='.npz' else 2097152)
        unique[d['path']]=d
    return result,list(unique.values())

def _managed_metadata_bytes(value,label):
    payload=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
    if len(payload)>32768:raise ValueError('managed '+label+'32KiB bound before import')
    return payload

def require_closed_database(path):
    """Never ignore a WAL or DELETE recovery journal through immutable=1."""
    path=Path(path)
    for suffix in ('-wal','-journal'):
        sidecar=path.with_name(path.name+suffix)
        if sidecar.is_symlink() or (sidecar.exists() and sidecar.stat().st_size):
            raise ValueError('closed checkpointed SQLite required; preserve nonempty '+suffix)
    return path

def import_retained(store,*,source_root,source_db,plan_ref,now,deadline,adoption=None):
    """Validate all producer/science contracts before any copy or SQL effect."""
    now=_stamp(now);deadline=_stamp(deadline)
    if not now<deadline<=now+timedelta(seconds=3600):
        raise ValueError('finite current source-free deadline required')
    source_root=Path(source_root).resolve(strict=True)
    validation_root=source_root
    if adoption is not None:
        from .saved_area import validate_adoption
        grant=store.policy.get("managed_output_grant")
        checked=validate_adoption(adoption["fresh_review_root"],adoption["adoption"],grant,now=now.timestamp(),horizon=deadline.timestamp())
        if checked!=adoption or str(source_root)!=adoption["origin_root"]:
            raise ValueError("exact independently validated mapping adoption required")
        validation_root=store.root
    if source_root==store.root or source_root.is_relative_to(store.root) or store.root.is_relative_to(source_root):
        raise ValueError('retained source and fresh mission domains must be disjoint')
    plan=load(validation_root,plan_ref,contract='coastal-contained-mapping-plan-v1')
    parent=None
    if 'parent_grant' in plan:
        from ..authenticated_v1.profiles import grant_identity,CONTAINED
        parent_doc=load(validation_root,plan['parent_grant'],contract='coastal-authenticated-policy-v1')
        parent=grant_identity(parent_doc)
        if store.managed_outputs is not None and parent_doc!=store.policy.get('managed_output_grant') and adoption is None:
            raise ValueError('managed mapping parent differs from exact released grant')
        if (parent.get('execution_profile')!=CONTAINED or parent.get('window_count')!=4
                or parent.get('window_side')!=plan['side']):
            raise ValueError('exact original four-window contained parent required')
    if adoption is not None and parent!=adoption['original_grant_identity']:
        raise ValueError('adopted mapping original parent differs')
    items,infos=contained_batch._prepare(validation_root,plan['packets'],plan['side'],now,deadline,
        declared_window_count=parent['window_count'] if parent else None)
    if parent and any(i['native_window'] not in parent['window_set'] or i['source']!=parent['source'] for i in infos):
        raise ValueError('accepted subset outside exact original parent')
    if any(item is None for item in items):raise ValueError('completed accepted qualification producers required')
    source_db=Path(source_db).resolve(strict=True);source_db.relative_to(source_root)
    require_closed_database(source_db)
    connection=sqlite3.connect('file:'+str(require_closed_database(source_db))+'?mode=ro&immutable=1',uri=True)
    connection.row_factory=sqlite3.Row
    producers=[];all_refs={}
    try:
        for index,(packet_ref,item) in enumerate(zip(plan['packets'],items)):
            packet=item['packet']
            result,refs=_copy_refs(validation_root,item['result_ref'],packet)
            if isinstance(packet_ref,dict) and {'path','bytes','sha256','contract'}<=set(packet_ref):refs.append(packet_ref)
            job=connection.execute('SELECT * FROM jobs WHERE job_id=?',(result['job_id'],)).fetchone()
            if not job or job['state']!='done' or job['stage']!='qualify' or job['result_sha']!=packet['qualified_result']['sha256']:
                raise ValueError('completed authenticated qualification producer unavailable')
            record=json.loads(job['record_json'])
            if parent and record.get('source_domain_grant')!=parent:
                raise ValueError('original producer differs from pinned parent grant')
            if record.get('execution_contract')!='coastal-authenticated-job-v1':
                raise ValueError('authenticated original producer contract required')
            if any(result.get(k)!=record[k] for k in IDENTITY_FIELDS):
                raise ValueError('original producer execution identity mismatch')
            rows=[dict(r) for r in connection.execute('SELECT * FROM authenticated_artifacts WHERE job_id=? ORDER BY path',(job['job_id'],))]
            by_path={r['path']:r for r in rows}
            for artifact in result['artifacts']:
                registered=by_path.get(artifact['path'])
                if (not registered or any(registered[k]!=artifact[k] for k in ('sha256','bytes','contract'))
                        or registered['committed_result_sha']!=job['result_sha']
                        or registered['lease_token']!=result['lease_token']):
                    raise ValueError('registered native producer artifact identity mismatch')
            if packet['qualified_result']['path']!=('var/coastal/jobs/'+job['job_id'].replace(':','-')+'/'+result['lease_token']+'/output/result.json'):
                raise ValueError('native producer result namespace mismatch')
            proof=dict(schema=PROOF,source_accessed=False,
                retained_qualification_arrays_read=True,original_job=record,
                original_state='done',original_result=packet['qualified_result'],
                original_lease_token=result['lease_token'],registered_artifacts=rows,
                retained_inputs=refs,window=item['facts']['header']['window'],
                producer_source_db=str(source_db),source_db_mode='immutable-read-only',
                copied_original_source=False)
            producers.append(proof)
            for d in refs:
                if d['path'] in all_refs and all_refs[d['path']]!=d:raise ValueError('shared retained input identity differs')
                all_refs[d['path']]=d
    finally:connection.close()
    segment_doc=load(source_root,plan['segment'],contract='coastal-segment-v1') if 'segment' in plan else None
    if segment_doc is None:
        connection=sqlite3.connect('file:'+str(require_closed_database(source_db))+'?mode=ro&immutable=1',uri=True)
        try:segment_doc=json.loads(connection.execute('SELECT record_json FROM segments WHERE segment_id=?',(infos[0]['segment_id'],)).fetchone()[0])
        finally:connection.close()
    if parent:
        all_refs[plan['parent_grant']['path']]=plan['parent_grant']
    for d in plan.get('baselines',[]):
        resolve(source_root,d,contract='coastal-retained-support-v1',cap=2097152)
        if d['path'] in all_refs and all_refs[d['path']]!=d:raise ValueError('baseline path identity collision')
        all_refs[d['path']]=d
    if sum(d['bytes'] for d in all_refs.values())>12*1024*1024:raise ValueError('retained import 12MiB ceiling')
    if store.managed_outputs is not None:
        predicted=[]
        for proof in producers:
            payload=_managed_metadata_bytes(proof,'producer proof')
            path=store.root/'metadata'/('retained-'+proof['original_job']['job_id'].replace(':','-')+'.json')
            predicted.append(dict(path=str(path.relative_to(store.root)),sha256=hashlib.sha256(payload).hexdigest(),bytes=len(payload),contract=PROOF))
        preview=dict(schema=INPUT,source_accessed=False,synthetic=items[0]['packet']['synthetic'],
            segment_id=infos[0]['segment_id'],side=plan['side'],packets=plan['packets'],
            baselines=plan.get('baselines',[]),producer_proofs=predicted,
            imported_artifacts=list(all_refs.values()),deadline_epoch=deadline.timestamp(),
            source_volume_allowance_bytes=0,native_requests_allowance=0)
        if parent:preview.update(parent_grant=plan['parent_grant'],original_window_count=parent['window_count'],parent_window_set=parent['window_set'])
        _managed_metadata_bytes(preview,'sourcefree manifest')

    # Import keys remain original relative descriptors so existing review digests
    # are preserved. Source pointers in metadata are never traversed or copied.
    for descriptor in all_refs.values():
        target=confined(store.root,descriptor['path'],existing=False)
        if target.exists():
            resolve(store.root,descriptor,contract=descriptor['contract'],cap=4194304)
            continue
        original=resolve(source_root,descriptor,contract=descriptor['contract'],cap=4194304)
        if store.managed_outputs is not None:
            store.managed_outputs.write_bytes(store.managed_outputs.relative_path(target),original.read_bytes(),
                role='control',max_bytes=descriptor['bytes'],intent=digest(['retained-import',descriptor]))
            resolve(store.root,descriptor,contract=descriptor['contract'],cap=4194304)
            continue
        target.parent.mkdir(parents=True,exist_ok=True)
        tmp=target.with_name('.'+target.name+'.import-'+os.urandom(8).hex())
        with tmp.open('xb') as output,original.open('rb') as source:
            while chunk:=source.read(65536):output.write(chunk)
            output.flush();os.fsync(output.fileno())
        if hashlib.sha256(tmp.read_bytes()).hexdigest()!=descriptor['sha256']:raise ValueError('retained copy changed')
        os.link(tmp,target);tmp.unlink()
    proofs=[]
    for proof in producers:
        path=store.root/'metadata'/('retained-'+proof['original_job']['job_id'].replace(':','-')+'.json')
        if path.exists():
            if json.loads(path.read_text())!=proof:raise ValueError('retained producer proof cannot change')
        else:store.write_artifact(path,proof,max_bytes=32768 if store.managed_outputs is not None else 131072)
        proofs.append(ref(store.root,path,PROOF))
    manifest=dict(schema=INPUT,source_accessed=False,synthetic=items[0]['packet']['synthetic'],
        segment_id=infos[0]['segment_id'],side=plan['side'],packets=plan['packets'],
        baselines=plan.get('baselines',[]),producer_proofs=proofs,
        imported_artifacts=list(all_refs.values()),deadline_epoch=deadline.timestamp(),
        source_volume_allowance_bytes=0,native_requests_allowance=0)
    if adoption is not None:
        manifest.update(saved_area_adoption=adoption,execution_grant_identity=grant_identity(store.policy['managed_output_grant']))
    if parent:
        manifest.update(parent_grant=plan['parent_grant'],original_window_count=parent['window_count'],parent_window_set=parent['window_set'])
    path=store.root/'metadata'/('sourcefree-map-'+plan_ref['sha256']+'.json' if parent else 'sourcefree-map-manifest.json')
    if path.exists():
        if json.loads(path.read_text())!=manifest:raise ValueError('mission manifest cannot change')
    else:store.write_artifact(path,manifest,max_bytes=32768 if store.managed_outputs is not None else 131072)
    descriptor=ref(store.root,path,INPUT)
    store.add_segment(segment_doc)
    with store.transaction():
        for proof_ref,proof in zip(proofs,producers):
            existing=store.db.execute('SELECT record_json FROM retained_producers WHERE proof_sha=?',(proof_ref['sha256'],)).fetchone()
            if existing and json.loads(existing[0])!=proof:raise ValueError('retained producer SQL identity changed')
            store.db.execute('INSERT OR IGNORE INTO retained_producers VALUES(?,?)',(proof_ref['sha256'],json.dumps(proof,sort_keys=True)))
            for d in proof['retained_inputs']:
                store.db.execute('INSERT OR IGNORE INTO retained_artifacts VALUES(?,?,?,?)',(d['path'],d['sha256'],d['bytes'],proof_ref['sha256']))
        store.db.execute('INSERT OR IGNORE INTO sourcefree_imports VALUES(?,?)',(descriptor['sha256'],json.dumps(manifest,sort_keys=True)))
        store.event(None,'sourcefree_imported',dict(manifest=descriptor,producer_ids=[p['original_job']['job_id'] for p in producers],source_reads=0))
    audit(store)
    return descriptor

def validate_input(store,descriptor,*,now,horizon):
    document=load(store.root,descriptor,contract=INPUT)
    registered=store.db.execute('SELECT record_json FROM sourcefree_imports WHERE manifest_sha=?',(descriptor['sha256'],)).fetchone()
    if (not registered or json.loads(registered[0])!=document or document['source_accessed'] is not False
            or document['source_volume_allowance_bytes']!=0 or document['native_requests_allowance']!=0):
        raise ValueError('exact registered source-free manifest required')
    now=_stamp(now);horizon=_stamp(horizon)
    if horizon.timestamp()>document['deadline_epoch'] or now.timestamp()>=document['deadline_epoch']:
        raise ValueError('source-free immutable deadline insufficient')
    count=None
    if 'parent_grant' in document:
        from ..authenticated_v1.profiles import grant_identity
        parent_doc=load(store.root,document['parent_grant'],contract='coastal-authenticated-policy-v1')
        parent=grant_identity(parent_doc)
        if store.managed_outputs is not None and parent_doc!=store.policy.get('managed_output_grant'):
            adoption=document.get('saved_area_adoption')
            if not adoption:raise ValueError('managed mapping manifest parent changed')
            from .saved_area import validate_adoption
            current=store.policy['managed_output_grant']
            registered_adoption=store.db.execute('SELECT record_json FROM saved_area_adoptions WHERE grant_sha=?',(digest(current),)).fetchone()
            if not registered_adoption or json.loads(registered_adoption[0])!=adoption:
                raise ValueError('exact registered mapping adoption required')
            if (validate_adoption(adoption['fresh_review_root'],adoption['adoption'],current,now=now.timestamp(),horizon=horizon.timestamp())!=adoption
                or document.get('execution_grant_identity')!=grant_identity(current)
                or parent!=adoption['original_grant_identity']):
                raise ValueError('adopted mapping execution/original lineage changed')
        if (parent.get('window_count')!=document.get('original_window_count')
                or parent.get('window_set')!=document.get('parent_window_set') or parent.get('window_count')!=4):
            raise ValueError('original parent subset lineage changed')
        count=parent['window_count']
    items,infos=contained_batch._prepare(store.root,document['packets'],document['side'],now,horizon,
        declared_window_count=count)
    if count and any(i['native_window'] not in parent['window_set'] or i['source']!=parent['source'] for i in infos):
        raise ValueError('registered subset outside original parent')
    if document.get('saved_area_adoption') and (len(items)!=1 or items[0]['result_ref']!=document['saved_area_adoption']['qualified_result']):
        raise ValueError('adopted map exact single original A required')
    for proof_ref,item in zip(document['producer_proofs'],items):
        proof=load(store.root,proof_ref,contract=PROOF)
        stored=store.db.execute('SELECT record_json FROM retained_producers WHERE proof_sha=?',(proof_ref['sha256'],)).fetchone()
        if (not stored or json.loads(stored[0])!=proof or item is None
                or proof['original_result']!=item['result_ref'] or proof['window']!=item['facts']['header']['window']):
            raise ValueError('retained producer/input identity changed')
        for d in proof['retained_inputs']:
            if not store.db.execute('SELECT 1 FROM retained_artifacts WHERE path=? AND sha256=? AND bytes=? AND proof_sha=?',
                    (d['path'],d['sha256'],d['bytes'],proof_ref['sha256'])).fetchone():
                raise ValueError('retained artifact producer membership missing')
            resolve(store.root,d,contract=d['contract'],cap=4194304)
    for d in document['imported_artifacts']:
        resolve(store.root,d,contract=d['contract'],cap=4194304)
    return document,items

def enqueue(store,descriptor,index,*,code_sha,deps_sha):
    if not store.policy.get('sourcefree_only'):raise ValueError('source-free-only mission policy required')
    audit(store)
    document,items=validate_input(store,descriptor,now=store.clock(),horizon=store.clock()+120)
    if type(index)!=int or not 0<=index<len(items):raise ValueError('finite core index required')
    params=dict(sourcefree_contract=CONTRACT,core_index=index,producer_sha=document['producer_proofs'][index]['sha256'])
    with store.transaction():
        job=store._enqueue(document['segment_id'],'map',code_sha=code_sha,deps_sha=deps_sha,
            params=params,input_manifest=descriptor,max_attempts=2,
            budget=dict(wall_s=120,memory_bytes=1073741824,bytes=0,requests=0))
        record=json.loads(store.db.execute('SELECT record_json FROM jobs WHERE job_id=?',(job,)).fetchone()[0])
        record['sourcefree_contract']=CONTRACT
        record['sourcefree_database']=str(store.path)
        if store.managed_outputs is not None:
            record['managed_output_grant']=store.policy['managed_output_grant']
        store.db.execute('UPDATE jobs SET record_json=? WHERE job_id=?',(json.dumps(record,sort_keys=True),job))
        return job

def audit(store):
    imported={(r['path'],r['sha256']) for r in store.db.execute('SELECT DISTINCT path,sha256 FROM retained_artifacts')}
    mapping=total=0
    for directory,dirs,files in os.walk(store.root,followlinks=False):
        for name in [*dirs,*files]:
            p=Path(directory)/name
            if p.is_symlink():raise ValueError('source-free output symlink')
            if p.is_file():
                st=p.stat()
                if st.st_nlink!=1:raise ValueError('source-free output hardlink')
                total+=st.st_size
                relative=p.relative_to(store.root).as_posix()
                if relative.startswith('var/coastal/jobs/') and not any(relative==path for path,_ in imported):mapping+=st.st_size
    if total>MAX_TOTAL or mapping>MAX_MAPPING or total-mapping>12*1024*1024:raise ValueError('source-free 16MiB total/4MiB mapping ceiling exceeded')
    return dict(total_bytes=total,mapping_bytes=mapping,source_accessed=False,physical_io_measured=False)

def _managed_rasters(store,directory,item):
    import numpy as np
    managed=store.managed_outputs
    refs={}
    for role,values,contract,ceiling in (
            ('terrain',item['depth'],'coastal-normalized-terrain-v1',131072),
            ('mask',item['valid'],'coastal-native-support-v2',32768),
            ('uncertainty',item['uncertainty'],'coastal-derived-uncertainty-m-v1',131072)):
        cast=np.asarray(values,dtype='uint8' if role=='mask' else 'float32')
        if role!='mask' and not np.array_equal(cast.astype('float64')[item['valid']],values.astype('float64')[item['valid']]):
            raise ValueError('lossless float32 derived storage required')
        profile=dict(driver='GTiff',width=cast.shape[1],height=cast.shape[0],count=1,
            dtype=cast.dtype.name,crs=item['crs'],transform=item['transform'],compress='DEFLATE',
            nodata=None if role=='mask' else np.nan)
        tags={};description=None
        if role=='terrain':
            description='depth_m_positive_down'
            tags=dict(vertical_contract=json.dumps(item['vertical'],sort_keys=True),
                vertical_sign='positive_down',vertical_datum=item['vertical']['datum'],
                datum_realization=item['vertical']['datum_realization'],scale_offset_applied='true',
                publication_prohibited='true',source_sha256=item['result']['source']['sha256'])
        elif role=='uncertainty':
            description='producer_uncertainty_m'
            tags=dict(uncertainty_kind='producer_uncertainty_m',publication_prohibited='true')
        path=directory/(role+'.tif')
        managed.write_geotiff(path,cast,profile,role='mapping',max_bytes=ceiling,
            intent=digest(['derived-raster',str(path)]),tags=tags,description=description,
            mask=None if role=='mask' else item['valid'],
            unit=None if role=='mask' else 'm')
        refs[role]=ref(store.root,path,contract)
    return refs

def execute(job,output,*,now):
    from .store import Store
    from .loop import implementation_hashes
    root=Path(job['root']).resolve(strict=True)
    # A managed mission cannot be reopened through the unbounded legacy SQLite
    # route merely by dropping the persisted full-grant field.
    managed_parent=next((p for p in (root,*root.parents) if (p/'managed-output.json').is_file()),None)
    if managed_parent is not None and (
            not isinstance(job.get('managed_output_grant'),dict)
            or job['managed_output_grant'].get('output_root')!=str(managed_parent)):
        raise ValueError('managed source-free job grant missing or rebound')
    database_path=Path(job['sourcefree_database'])
    database=confined(root,database_path.relative_to(root) if database_path.is_absolute() else database_path)
    execution_policy=policy()
    if job.get('managed_output_grant') is not None:
        execution_policy['managed_output_grant']=job['managed_output_grant']
    store=Store(database,root=job['root'],policy=execution_policy)
    try:
        if (job.get('sourcefree_contract')!=CONTRACT or job['stage']!='map'
                or job['params']['sourcefree_contract']!=CONTRACT or digest(job['params'])!=job['params_sha']
                or implementation_hashes(store.root)!=(job['code_sha'],job['deps_sha'])):
            raise ValueError('exact source-free executable/parameter contract required')
        persisted=store.db.execute('SELECT record_json FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()
        if not persisted:raise ValueError('registered source-free job required')
        recorded=json.loads(persisted[0])
        if (job['input_manifest']['sha256']!=job['input_manifest_sha']
                or any(job.get(k)!=recorded.get(k) for k in (*IDENTITY_FIELDS,'params','input_manifest','sourcefree_contract','sourcefree_database','managed_output_grant'))):
            raise ValueError('persisted source-free input/job identity mismatch')
        lease=store.db.execute('SELECT token FROM leases WHERE job_id=?',(job['job_id'],)).fetchone()
        if not lease or lease[0]!=job['lease_token']:raise ValueError('source-free lease token mismatch')
        expected=store.root/'var/coastal/jobs'/job['job_id'].replace(':','-')/job['lease_token']/'output'
        output_path=Path(output)
        out=confined(store.root,output_path.relative_to(store.root) if output_path.is_absolute() else output_path,existing=False)
        if out!=expected:raise ValueError('exact source-free owned output directory required')
        document,items=validate_input(store,job['input_manifest'],now=now,horizon=now+timedelta(seconds=job['budget']['wall_s']))
        index=job['params']['core_index'];item=items[index]
        if job['params']['producer_sha']!=document['producer_proofs'][index]['sha256']:
            raise ValueError('selected retained producer changed')
        core=out/'core'
        binding=digest(dict(input=job['input_manifest'],params=job['params'],code_sha=job['code_sha'],deps_sha=job['deps_sha']))
        expected=dict(schema=CORE,binding=binding,source_accessed=False,publication_prohibited=True,
            state='mapped_pending_render_review',synthetic=item['packet']['synthetic'],
            native_window=item['facts']['header']['window'],valid_cells=int(item['valid'].sum()),
            nominal_valid_area_m2=int(item['valid'].sum())*4,
            producer_proof=document['producer_proofs'][index],qualified_result=item['result_ref'])
        if (core/'core.json').exists():
            receipt=load(store.root,ref(store.root,core/'core.json',CORE),contract=CORE)
            contained_batch._verify(store.root,receipt,expected,[item])
        elif core.exists():raise ValueError('interrupted source-free core preserved')
        else:
            refs=(_managed_rasters(store,core,item) if store.managed_outputs is not None
                  else derived_batch._write_rasters(store.root,core,item))
            acceptance=contained_batch._acceptance(item,refs)
            store.write_artifact(core/'acceptance-pending-review.json',acceptance,role='mapping',max_bytes=32768)
            acceptance_ref=ref(store.root,core/'acceptance-pending-review.json','coastal-terrain-only-input-v1')
            receipt=dict(expected,acceptances=[acceptance_ref],artifacts=[acceptance_ref,*refs.values()])
            store.write_artifact(core/'core.json',receipt,role='mapping',max_bytes=16384)
        artifact=ref(store.root,core/'core.json',CORE)
        audit(store)
        return dict(schema='coastal-stage-result-v1',**{k:job[k] for k in IDENTITY_FIELDS},
            lease_token=job['lease_token'],state='done',holds=[],sourcefree_contract=CONTRACT,
            mapped_core=artifact,artifacts=[artifact,*receipt['artifacts']],
            usage=dict(requests=0,bytes=0,bytes_in=0,model_calls=[],
                retained_qualification_arrays_read=True,retained_logical_pair_visits=None,
                physical_io_measured=False,source_volume_accounting_scope='original native source admissions only'),
            provenance=dict(libs={'sourcefree_mapper':'v1'},synthetic=item['packet']['synthetic'],source_accessed=False))
    finally:store.close()

def verify_completion(store,job,token,result):
    if (job.get('sourcefree_contract')!=CONTRACT or result.get('sourcefree_contract')!=CONTRACT
            or result.get('lease_token')!=token or result.get('state')!='done' or result.get('holds')
            or result['provenance'].get('source_accessed') is not False
            or any(result['usage'].get(k,0)!=0 for k in ('bytes','bytes_in','requests'))):
        raise ValueError('source-free result contract or zero source usage required')
    document,items=validate_input(store,job['input_manifest'],now=store.clock(),horizon=store.clock())
    index=job['params']['core_index'];item=items[index]
    prefix='var/coastal/jobs/'+job['job_id'].replace(':','-')+'/'+token+'/output/'
    if any(not a['path'].startswith(prefix) for a in result['artifacts']):raise ValueError('owned per-lease mapping outputs required')
    receipt=load(store.root,result['mapped_core'],contract=CORE)
    expected=dict(schema=CORE,binding=digest(dict(input=job['input_manifest'],params=job['params'],code_sha=job['code_sha'],deps_sha=job['deps_sha'])),
        source_accessed=False,publication_prohibited=True,state='mapped_pending_render_review',
        synthetic=item['packet']['synthetic'],native_window=item['facts']['header']['window'],
        valid_cells=int(item['valid'].sum()),nominal_valid_area_m2=int(item['valid'].sum())*4,
        producer_proof=document['producer_proofs'][index],qualified_result=item['result_ref'])
    contained_batch._verify(store.root,receipt,expected,[item])
    if sorted(digest(a) for a in result['artifacts'])!=sorted(digest(a) for a in [result['mapped_core'],*receipt['artifacts']]):
        raise ValueError('exact source-free output artifact set required')
    audit(store)

def commit(store,job,token,result_ref,result):
    if result_ref['path']!='var/coastal/jobs/'+job['job_id'].replace(':','-')+'/'+token+'/output/result.json':
        raise ValueError('exact source-free result output ownership required')
    verify_completion(store,job,token,result)
    for d in result['artifacts']:
        prior=store.db.execute('SELECT produced_by_job FROM artifacts WHERE sha256=? AND path=?',(d['sha256'],d['path'])).fetchone()
        if prior and prior[0]!=job['job_id']:raise ValueError('output producer ownership collision')
        store.db.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)',(d['sha256'],d['path'],d['bytes'],d['contract'],job['job_id']))
    store.charge(job['job_id'],result['usage'])
    store.db.execute("UPDATE jobs SET state='done',result_sha=?,holds_json='[]' WHERE job_id=?",(result_ref['sha256'],job['job_id']))
    store.db.execute('DELETE FROM leases WHERE job_id=?',(job['job_id'],))
    store.event(job['job_id'],'sourcefree_finished',dict(result=result_ref,source_reads=0,producer_sha=job['params']['producer_sha']))
    segment=json.loads(store.db.execute('SELECT record_json FROM segments WHERE segment_id=?',(job['segment_id'],)).fetchone()[0])
    store._progress(segment['region'],'map',job['segment_id'],digest([job['params']['producer_sha'],result['mapped_core']['sha256']]))
    return True

def recover_completion(store,job_id,recovery_ref):
    """Commit retained completed work only after stopped fenced-lease evidence."""
    from .store import identity_stopped
    receipt=load(store.root,recovery_ref,contract='coastal-sourcefree-recovery-v1')
    with store.transaction():
        row=store.db.execute('SELECT * FROM jobs WHERE job_id=?',(job_id,)).fetchone()
        if not row:raise ValueError('unknown source-free recovery job')
        job=json.loads(row['record_json'])
        result_ref=receipt['result']
        if row['state']=='done' and row['result_sha']==result_ref['sha256']:
            prior=store.db.execute("SELECT detail_json FROM events WHERE job_id=? AND kind='sourcefree_recovered' ORDER BY seq DESC LIMIT 1",(job_id,)).fetchone()
            if prior and json.loads(prior[0])['receipt']==recovery_ref:
                result=load(store.root,result_ref,contract='coastal-stage-result-v1')
                verify_completion(store,job,receipt['lease_token'],result)
                return False
            raise ValueError('completed job requires its exact prior recovery receipt')
        lease=store.db.execute('SELECT * FROM leases WHERE job_id=?',(job_id,)).fetchone()
        if (job.get('sourcefree_contract')!=CONTRACT or row['state']!='failed_uncertain'
                or not lease or receipt.get('job_id')!=job_id or receipt.get('lease_token')!=lease['token']
                or receipt.get('processes_stopped') is not True or not receipt.get('attested_by')):
            raise ValueError('source-free fenced recovery identity required')
        child=json.loads(lease['child_json']) if lease['child_json'] else None
        controller=json.loads(lease['controller_json'])
        if not identity_stopped(controller) or child and not identity_stopped(child):
            raise ValueError('source-free original controller or child live or unverifiable')
        expected='var/coastal/jobs/'+job_id.replace(':','-')+'/'+lease['token']+'/output/result.json'
        if result_ref['path']!=expected:raise ValueError('exact retained completed result path required')
        result=load(store.root,result_ref,contract='coastal-stage-result-v1')
        if any(result.get(k)!=job[k] for k in IDENTITY_FIELDS):
            raise ValueError('recovery original job identity mismatch')
        verify_completion(store,job,lease['token'],result)
        region=store.db.execute('SELECT region FROM segments WHERE segment_id=?',(job['segment_id'],)).fetchone()[0]
        authority=store.budget_for(region)
        intent=store.root/'var/coastal/jobs'/job_id.replace(':','-')/lease['token']/'intent.json'
        if intent.exists():
            runtime_ref=receipt.get('runtime_recovery')
            if not runtime_ref:raise ValueError('bound stopped durable-runner recovery proof required')
            runtime=load(store.root,runtime_ref)
            authority.recover_uncertain(lease['token'],intent=intent,receipt=runtime)
        else:
            raise ValueError('durable runner intent and recovery proof required; external dispatcher recovery unsupported')
        commit(store,job,lease['token'],result_ref,result)
        store.event(job_id,'sourcefree_recovered',dict(receipt=recovery_ref,result=result_ref,
            retained_output_reused=True,source_reads=0))
        return True

def main(argv=None):
    import argparse
    from .store import Store
    from .loop import Coordinator,implementation_hashes
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--database',default='var/coastal/sourcefree.sqlite')
    sub=parser.add_subparsers(dest='command',required=True)
    imp=sub.add_parser('import')
    imp.add_argument('--source-root',required=True);imp.add_argument('--source-db',required=True)
    imp.add_argument('--plan',required=True);imp.add_argument('--deadline-epoch',type=float,required=True)
    enq=sub.add_parser('enqueue');enq.add_argument('--manifest',required=True);enq.add_argument('--index',type=int,required=True)
    run=sub.add_parser('run');run.add_argument('--deadline-epoch',type=float,required=True);run.add_argument('--max-jobs',type=int,default=3)
    recover=sub.add_parser('recover');recover.add_argument('--job-id',required=True);recover.add_argument('--receipt',required=True)
    sub.add_parser('status')
    args=parser.parse_args(argv);root=Path(args.root).resolve(strict=True)
    db=confined(root,args.database,existing=False)
    store=Store(db,root=root,policy=policy())
    try:
        if args.command=='import':
            result=import_retained(store,source_root=args.source_root,source_db=args.source_db,
                plan_ref=ref(args.source_root,args.plan,'coastal-contained-mapping-plan-v1'),
                now=store.clock(),deadline=args.deadline_epoch)
        elif args.command=='enqueue':
            result=store.enqueue_sourcefree(ref(root,args.manifest,INPUT),args.index,
                code_sha=implementation_hashes(root)[0],deps_sha=implementation_hashes(root)[1])
        elif args.command=='run':
            if not 1<=args.max_jobs<=3:raise ValueError('finite three-job dispatch bound')
            result=Coordinator(store).run(until=args.deadline_epoch,max_jobs=args.max_jobs)
        elif args.command=='recover':
            result=recover_completion(store,args.job_id,ref(root,args.receipt,'coastal-sourcefree-recovery-v1'))
        else:
            result=dict(jobs=[dict(r) for r in store.db.execute('SELECT job_id,stage,state,attempts,result_sha FROM jobs ORDER BY created,job_id')],
                        storage=audit(store),source_volume_charged_bytes=sum(r[0] for r in store.db.execute('SELECT bytes FROM charges')))
        print(json.dumps(result,sort_keys=True))
    finally:store.close()

if __name__=='__main__':main()


def import_adopted(store,adoption,*,native_store,now,deadline):
    """Bounded derived-only copy; original producer identity is never rewritten."""
    from .saved_area import validate_adoption,registered_acceptance,SCHEMA as ADOPT_SCHEMA
    current=store.policy['managed_output_grant']
    if registered_acceptance(native_store,current,now=float(now),horizon=float(deadline))!=adoption:
        raise ValueError('mapping requires exact registered native-Store adoption')
    with store.transaction():
        store.db.execute(ADOPT_SCHEMA)
        previous=store.db.execute('SELECT record_json FROM saved_area_adoptions WHERE grant_sha=?',(digest(current),)).fetchone()
        if previous and json.loads(previous[0])!=adoption:raise ValueError('mapping adoption cannot change')
        store.db.execute('INSERT OR IGNORE INTO saved_area_adoptions VALUES(?,?,?)',(digest(current),adoption['adoption']['sha256'],json.dumps(adoption,sort_keys=True)))
    if validate_adoption(adoption['fresh_review_root'],adoption['adoption'],current,now=float(now),horizon=float(deadline))!=adoption:
        raise ValueError('registered adoption must revalidate before imported effects')
    source=Path(adoption['origin_root'])
    oldpacket=dict(schema=derived_batch.INPUT,qualified_result=adoption['qualified_result'],scientific_review=adoption['original_review'])
    result,refs=_copy_refs(source,adoption['qualified_result'],oldpacket)
    original_grant=load(source,adoption['original_grant'],contract='coastal-authenticated-policy-v1')
    original_grant_path=store.root/'metadata/adopted-A-original-grant.json'
    original_bytes=resolve(source,adoption['original_grant'],contract='coastal-authenticated-policy-v1',cap=16384).read_bytes()
    if store.managed_outputs is not None:
        store.managed_outputs.write_bytes(store.managed_outputs.relative_path(original_grant_path),original_bytes,role='control',max_bytes=16384,intent=digest(['adopted-origin-grant',adoption['original_grant']]))
    elif not original_grant_path.exists():
        original_grant_path.parent.mkdir(parents=True,exist_ok=True)
        with original_grant_path.open('xb') as stream:stream.write(original_bytes);stream.flush();os.fsync(stream.fileno())
    elif original_grant_path.read_bytes()!=original_bytes:raise ValueError('adopted original grant bytes changed')
    parent_ref=ref(store.root,original_grant_path,'coastal-authenticated-policy-v1')
    for descriptor in refs:
        original=resolve(source,descriptor,contract=descriptor['contract'],cap=4194304)
        target=confined(store.root,descriptor['path'],existing=False)
        if target.exists():resolve(store.root,descriptor,contract=descriptor['contract'],cap=4194304);continue
        if store.managed_outputs is not None:
            store.managed_outputs.write_bytes(store.managed_outputs.relative_path(target),original.read_bytes(),role='control',max_bytes=descriptor['bytes'],intent=digest(['retained-import',descriptor]))
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as output:output.write(original.read_bytes());output.flush();os.fsync(output.fileno())
    review=load(adoption['fresh_review_root'],adoption['fresh_review'],contract=derived_batch.REVIEW)
    review_path=store.root/'metadata/adopted-A-fresh-review.json'
    review_bytes=resolve(adoption['fresh_review_root'],adoption['fresh_review'],contract=derived_batch.REVIEW,cap=65536).read_bytes()
    if store.managed_outputs is not None:
        store.managed_outputs.write_bytes(store.managed_outputs.relative_path(review_path),review_bytes,role='control',max_bytes=65536,intent=digest(['adopted-fresh-review',adoption['fresh_review']]))
    elif not review_path.exists():
        review_path.parent.mkdir(parents=True,exist_ok=True)
        with review_path.open('xb') as stream:stream.write(review_bytes);stream.flush();os.fsync(stream.fileno())
    elif review_path.read_bytes()!=review_bytes:raise ValueError('adopted fresh review bytes changed')
    packet=dict(schema=derived_batch.INPUT,qualified_result=adoption['qualified_result'],scientific_review=ref(store.root,review_path,derived_batch.REVIEW),
        synthetic=review['synthetic'],source_accessed=False,creator_id='registered-saved-A-adoption')
    packet_path=store.root/'metadata/adopted-A-map-packet.json';store.write_artifact(packet_path,packet,max_bytes=16384)
    plan=dict(schema='coastal-contained-mapping-plan-v1',side=128,packets=[ref(store.root,packet_path,derived_batch.INPUT)],
        parent_grant=parent_ref,baselines=[])
    plan_path=store.root/'metadata/adopted-A-map-plan.json';store.write_artifact(plan_path,plan,max_bytes=32768)
    return import_retained(store,source_root=source,source_db=source/adoption['origin_database']['path'],
        plan_ref=ref(store.root,plan_path,plan['schema']),now=now,deadline=deadline,adoption=adoption)
