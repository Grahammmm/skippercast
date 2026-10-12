"""Explicit closed-producer adoption; never a native phase or source authority."""
import hashlib, json, math, sqlite3
from pathlib import Path
from .stages import digest
from .authenticated import metadata_document, IDENTITY_FIELDS, bounded_control_bytes
from ..handoff.common import load, resolve, epoch
from ..authenticated_v1.profiles import grant_identity
CONTRACT = 'coastal-saved-area-continuation-v1'
ADOPTION = 'coastal-saved-area-adoption-v1'
SCHEMA = "CREATE TABLE IF NOT EXISTS saved_area_adoptions(grant_sha TEXT PRIMARY KEY, adoption_sha TEXT NOT NULL, record_json TEXT NOT NULL)"

def continuation_grant(grant):
    if grant.get('saved_area_continuation_contract') != CONTRACT:
        raise ValueError('explicit saved-area continuation contract required')
    if (grant.get('window_count') != 4 or grant.get('window_side') != 128
        or grant.get('source_reuse_contract') is not None
        or grant.get('larger_runtime_contract') != 'coastal-managed-eight-copy-four128-v1'
        or type(grant['source']['bytes']) is not int or grant['source']['bytes'] != 36757568
        or grant.get('source_volume_cap_bytes') != 220545408
        or grant.get('prior_effective_bytes') != 895006524
        or grant.get('cumulative_limit_bytes') != 1115551932):
        raise ValueError('exact adopted-A six-admission nonrefundable authority required')
    return grant

def _review(review, result_ref, facts, now, horizon, historical=False):
    if (review.get('schema') != 'coastal-derived-window-review-v1'
        or review.get('independent') is not True or not review.get('reviewer_id')
        or review.get('decision') != 'accept' or review.get('quality_accepted') is not True
        or review.get('holds_added') != [] or review.get('qualified_result') != result_ref
        or review.get('facts_digest') != digest(dict(qualified_result=result_ref,facts_digest=facts['facts_digest']))
        or review.get('native_facts_digest') != facts['facts_digest']
        or review.get('window') != facts['window'] or review.get('vertical') != facts['normalized_vertical']):
        raise ValueError('independent exact saved producer scientific acceptance required')
    checked,valid=epoch(review['checked_at']),epoch(review['valid_until'])
    if not math.isfinite(checked) or not math.isfinite(valid) or checked>=valid:
        raise ValueError('scientific acceptance clock invalid')
    if historical and not now<=checked<=horizon<valid:
        raise ValueError('historical acceptance must follow committed producer and cover original horizon')
    if not historical and not checked<=now<=horizon<valid:
        raise ValueError('fresh saved science review must cover new horizon')

def validate_adoption(root, descriptor, new_grant, *, now, horizon):
    """No writes, Store/Budget creation, native source opening, or clock reset."""
    continuation_grant(new_grant)
    if type(now) not in (int,float) or type(horizon) not in (int,float) or not math.isfinite(now+horizon) or not now<=horizon<=now+3600:
        raise ValueError('finite prospective adoption horizon required')
    doc=metadata_document(root,descriptor,ADOPTION)
    origin=Path(doc['origin_root'])
    if str(origin)!=str(origin.absolute()) or origin.resolve(strict=True)!=origin or origin==Path(root).absolute():
        raise ValueError('exact disjoint canonical original root required')
    for ancestor in (origin,*origin.parents):
        if ancestor.is_symlink():raise ValueError('original root alias forbidden')
    target=Path(new_grant['output_root']).absolute()
    if origin.is_relative_to(target) or target.is_relative_to(origin):
        raise ValueError('original and execution output domains must be disjoint')
    old=metadata_document(origin,doc['original_grant'],'coastal-authenticated-policy-v1')
    if (old.get('saved_area_continuation_contract') is not None or old.get('execution_authorized') is not True
        or old['source']!=new_grant['source'] or old['window_set']!=new_grant['window_set']
        or old['source_root']!=new_grant['source_root'] or old['source_relative_path']!=new_grant['source_relative_path']
        or old['output_root']==new_grant['output_root']):
        raise ValueError('original approved source/scope and new output separation required')
    stop=load(origin.parent,doc['origin_stop'],contract='coastal-four128-stop-proof-v1')
    if (stop.get('descendants_empty') is not True or stop.get('stop_exit_code')!=0 or stop.get('query_exit_code')!=0
        or stop.get('properties',{}).get('ActiveState')!='inactive' or stop.get('properties',{}).get('ControlGroup')!=''):
        raise ValueError('original stopped empty mission proof required')
    result=load(origin,doc['qualified_result'],contract='coastal-authenticated-stage-result-v1')
    from .source_free import require_closed_database
    db=resolve(origin,doc['origin_database'],contract='coastal-saved-origin-sqlite-v1',cap=1048576)
    if db!=origin/'var/coastal/authenticated.sqlite':raise ValueError('exact original authenticated database required')
    require_closed_database(db)
    connection=sqlite3.connect('file:'+str(db)+'?mode=ro&immutable=1',uri=True)
    connection.row_factory=sqlite3.Row
    try:
        job=connection.execute('SELECT * FROM jobs WHERE job_id=?',(result['job_id'],)).fetchone()
        if not job or job['state']!='done' or job['stage']!='qualify' or job['result_sha']!=doc['qualified_result']['sha256']:
            raise ValueError('original committed qualified producer required')
        completed=list(connection.execute("SELECT utc,detail_json FROM events WHERE job_id=? AND kind='authenticated_finished'",(job['job_id'],)))
        if len(completed)!=1 or json.loads(completed[0]['detail_json']).get('state')!='done' or json.loads(completed[0]['detail_json']).get('result_sha')!=job['result_sha']:
            raise ValueError('exact original committed completion event required')
        completed_utc=completed[0]['utc']
        record=json.loads(job['record_json'])
        if (record.get('root')!=str(origin) or record.get('source_domain_grant')!=grant_identity(old)
            or record.get('code_sha')!=old['code_sha'] or record.get('deps_sha')!=old['deps_sha']
            or any(result.get(k)!=record.get(k) for k in IDENTITY_FIELDS)
            or result.get('state')!='done' or result.get('rc')!=0 or result.get('holds')!=[]
            or result.get('policy_holds')!=[] or result.get('accepted') is not False or result.get('qualification') is not False):
            raise ValueError('original producer execution identity differs')
        rows=[dict(r) for r in connection.execute('SELECT * FROM authenticated_artifacts WHERE job_id=? ORDER BY path',(job['job_id'],))]
        bypath={r['path']:r for r in rows}
        for artifact in result['artifacts']:
            row=bypath.get(artifact['path'])
            if (not row or any(row[k]!=artifact[k] for k in ('sha256','bytes','contract'))
                or row['lease_token']!=result['lease_token'] or row['committed_result_sha']!=job['result_sha']):
                raise ValueError('original registered artifact membership differs')
        phases=list(connection.execute('SELECT p.window_key,p.stage,j.job_id,j.state,j.record_json FROM authenticated_window_phases p JOIN jobs j USING(job_id)'))
        if len(phases)!=2 or {r['stage'] for r in phases}!={'acquire','qualify'} or any(r['state']!='done' or r['window_key']!=digest(new_grant['window_set'][0]) or json.loads(r['record_json']).get('source_domain_grant')!=grant_identity(old) for r in phases) or next(r['job_id'] for r in phases if r['stage']=='qualify')!=result['job_id']:
            raise ValueError('only two completed original A native phases may be adopted')
        all_jobs=list(connection.execute('SELECT job_id,state FROM jobs'))
        if len(all_jobs)!=2 or {r['job_id'] for r in all_jobs}!={r['job_id'] for r in phases} or any(r['state']!='done' for r in all_jobs):
            raise ValueError('original unresolved or foreign producer forbidden')
        missions=[dict(r) for r in connection.execute('SELECT * FROM authenticated_missions')]
        if len(missions)!=1 or missions[0]['limits_sha']!=digest(grant_identity(old)) or missions[0]['source_sha']!=old['source']['sha256']:
            raise ValueError('original immutable mission/source/domain required')
        if connection.execute('SELECT 1 FROM leases').fetchone():raise ValueError('original active lease forbidden')
        charges=list(connection.execute('SELECT job_id,bytes FROM charges'))
        if len(charges)!=2 or any(r['bytes']!=old['source']['bytes'] for r in charges) or {r['job_id'] for r in charges}!={r['job_id'] for r in phases}:
            raise ValueError('original two source charges must remain committed')
    finally:connection.close()
    budget_path=resolve(origin,doc['original_budget'],contract='coastal-budget-v1',cap=65536)
    budget=json.loads(budget_path.read_bytes())
    expected_budget=db.parent/('budget-'+digest([db.name,missions[0]['region']])+'.json')
    reservations=list(budget.get('reservations',{}).values())
    if (budget_path!=expected_budget or budget.get('schema')!='coastal-budget-v1'
        or budget.get('clock_uncertain') is not False
        or budget['started_monotonic']!=missions[0]['started_monotonic'] or budget['boot_id']!=missions[0]['boot_id']
        or budget['charged']!={'bytes':73515136,'requests':0,'tokens':0}
        or budget.get('reserved')!={'bytes':73515136,'requests':0,'tokens':0}
        or budget.get('limits')!=dict(attempts_per_candidate=1,bytes=294060544,requests=0,reserve_s=60,stagnation_s=None,tokens=0,wall_s=3600)
        or len(reservations)!=2 or {r['candidate'] for r in reservations}!={r['job_id'] for r in phases}
        or any(r.get('state')!='settled' or r.get('charged',{}).get('bytes')!=36757568 or r.get('execution',{}).get('state')!='completed' for r in reservations)):
        raise ValueError('original source ledger/clock/settled charges must remain nonrefundable')
    carry=metadata_document(origin,doc['original_carry'],'coastal-authenticated-carry-v1')
    if (carry.get('prior_effective_bytes'),carry.get('cumulative_limit_bytes'))!=(821491388,1115551932):
        raise ValueError('original carried authority changed')
    for reservation in reservations:
        execution=reservation['execution'];intent=Path(execution['intent_path'])
        intent.relative_to(origin/'var/coastal/jobs')
        raw_intent=bounded_control_bytes(intent,65536)
        proof=json.loads(raw_intent)
        if (hashlib.sha256(raw_intent).hexdigest()!=execution['intent_sha256'] or proof.get('state')!='finished' or proof.get('processes_stopped') is not True or proof.get('rc')!=0):
            raise ValueError('original unresolved source intent forbids adoption')
    observation=load(origin,result['observation'],contract='coastal-authenticated-observation-v1')
    verification=load(origin,result['verification'],contract='coastal-authenticated-verification-v1')
    facts=observation['native_facts']
    if (observation['facts_digest']!=digest(facts) or verification['facts']!=facts
        or verification['facts_digest']!=observation['facts_digest']
        or observation['window']!=new_grant['window_set'][0] or observation['source']!=new_grant['source']):
        raise ValueError('exact saved A full verified source/window facts required')
    from .. import vertical as vertical_contract
    raw=vertical_contract.require_resolved(observation['declared_vertical'],facts['observed_vertical'])
    if (raw['sign']!='positive_up' or raw['units']!='m' or raw['datum']!='MLLW' or raw['datum_realization']!='unknown'
        or raw['scale_offset_applied'] is not False or raw['scale']!=1 or raw['offset']!=0):
        raise ValueError('original raw MLLW positive-up metre lineage required')
    vertical=vertical_contract.normalized(raw)
    observation=dict(observation,normalized_vertical=vertical)
    if (vertical.get('datum')!='MLLW' or vertical.get('datum_realization')!='unknown'
        or vertical.get('sign')!='positive_down' or vertical.get('units')!='m' or vertical.get('conflicts')!=[]
        or vertical.get('lineage',{}).get('datum_transform') is not False):
        raise ValueError('saved normalized MLLW lineage cannot change')
    from pyproj import CRS
    h=facts['header'];c=CRS.from_user_input(h['horizontal_crs']);c=c.source_crs if c.is_bound else c
    if (h['shape']!=[10495,10034] or h['window']!=new_grant['window_set'][0]
        or h['transform']!=[2.0,0.0,728871.0,0.0,-2.0,3819179.0]
        or h['resolution_m']!=[2.0,2.0] or not c.equals(CRS.from_epsg(26910))
        or facts['valid_count']!=16384 or facts['valid_fraction']!=1):
        raise ValueError('original native grid CRS/affine/full-support scope differs')
    for role in ('policy_evaluation','verified_policy'):
        policy=load(origin,result[role],contract='coastal-fixed-patch-policy-evaluation-v1')
        if policy.get('paired_eligibility_quality_pass') is not True or policy.get('holds')!=[] or policy.get('facts_digest')!=observation['facts_digest']:
            raise ValueError('original strict scientific policy acceptance changed')
    from .ordered_trial import validate_scope_review
    validate_scope_review(root,new_grant,now=now,horizon=max(horizon,now+0.000001))
    historical=metadata_document(origin,doc['original_review'],'coastal-derived-window-review-v1')
    _review(historical,doc['qualified_result'],observation,completed_utc,missions[0]['deadline_utc'],historical=True)
    fresh=metadata_document(root,doc['fresh_review'],'coastal-derived-window-review-v1')
    _review(fresh,doc['qualified_result'],observation,now,horizon)
    if doc.get('window')!=observation['window'] or doc.get('source')!=new_grant['source']:
        raise ValueError('adoption selected scope/source changed')
    return dict(schema=ADOPTION,adoption=descriptor,origin_root=str(origin),origin_database=doc['origin_database'],
        original_grant=doc['original_grant'],original_grant_identity=grant_identity(old),
        qualified_result=doc['qualified_result'],original_review=doc['original_review'],fresh_review=doc['fresh_review'],
        window=observation['window'],source=observation['source'],facts_digest=observation['facts_digest'],
        original_job=record,original_mission=missions[0],original_budget=doc['original_budget'],original_carry=doc['original_carry'],original_stop=doc['origin_stop'],registered_artifacts=rows,execution_grant_sha=digest(new_grant),fresh_review_root=str(Path(root).absolute()),
        source_volume_bytes=0,previous_source_bytes=2*old['source']['bytes'],native_phases_created=0,
        internal_diagnostic=True,publication_prohibited=True,habitat='unassessed')

def adopt_saved_area(store, descriptor, new_grant, *, now, horizon):
    if store.policy.get('authenticated')!=new_grant:raise ValueError('new Store exact continuation grant required')
    proof=validate_adoption(store.root,descriptor,new_grant,now=now,horizon=horizon)
    with store.transaction():
        store.db.execute(SCHEMA)
        previous=store.db.execute('SELECT adoption_sha,record_json FROM saved_area_adoptions WHERE grant_sha=?',(digest(new_grant),)).fetchone()
        if previous:
            if previous['adoption_sha']!=descriptor['sha256'] or json.loads(previous['record_json'])!=proof:
                raise ValueError('adoption immutable registration changed')
        else:
            if store.db.execute('SELECT 1 FROM jobs').fetchone():raise ValueError('adoption must precede new native phases')
            store.db.execute('INSERT INTO saved_area_adoptions VALUES(?,?,?)',(digest(new_grant),descriptor['sha256'],json.dumps(proof,sort_keys=True)))
            store.event(None,'saved_area_adopted',dict(adoption=descriptor,source_volume_bytes=0))
    return proof

def registered_acceptance(store,grant,*,now,horizon):
    descriptor=grant["saved_area_adoption"]
    proof=validate_adoption(store.root,descriptor,grant,now=now,horizon=horizon)
    exists=store.db.execute("SELECT 1 FROM sqlite_master WHERE name='saved_area_adoptions'").fetchone()
    row=store.db.execute("SELECT adoption_sha,record_json FROM saved_area_adoptions WHERE grant_sha=?",(digest(grant),)).fetchone() if exists else None
    if not row or row["adoption_sha"]!=descriptor["sha256"] or json.loads(row["record_json"])!=proof:
        raise ValueError("exact registered adopted producer required")
    return proof

def acceptance(store, preparation):
    grant=metadata_document(store.root,preparation['grant'],'coastal-authenticated-policy-v1')
    descriptor=preparation['saved_area_adoption']
    proof=validate_adoption(store.root,descriptor,grant,now=store.clock(),horizon=preparation['deadline_epoch'])
    exists=store.db.execute("SELECT 1 FROM sqlite_master WHERE name='saved_area_adoptions'").fetchone()
    row=store.db.execute('SELECT adoption_sha,record_json FROM saved_area_adoptions WHERE grant_sha=?',(digest(grant),)).fetchone() if exists else None
    if not row or row['adoption_sha']!=descriptor['sha256'] or json.loads(row['record_json'])!=proof:
        raise ValueError('exact registered adopted producer required')
    return proof
