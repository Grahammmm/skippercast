"""Versioned worker scientific tests; authority/envelope mocks are explicit, never CLI approvals."""
import contextlib,copy,hashlib,json,os,subprocess,sys,tempfile,types,time
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
from shapely.geometry import box,mapping
from skippercast.coastal.authenticated_v1 import authority,snapshot,planner,observer,worker
from skippercast.coastal.handoff import common,mapping_input
from skippercast.seafloor.adapters import regular_bag_window
from rasterio.windows import Window
from tests.gis.authenticated_fixture import make_bag,run_unguarded_poison_control
from tests._support import ROOT,FIXTURES,FakeClock
from tests._coastal_operations import export_package

CACHE_PARTS=('var','seafloor','cache')
@pytest.fixture
def fixture():
    # Create only under this owned worktree and reject real cache Python entry paths.
    import builtins,io
    with contextlib.ExitStack() as guards:
        for module,names in ((os,('open','stat','lstat')),(builtins,('open',)),(io,('open',))):
            for name in names:
                original=getattr(module,name)
                def denied(path,*args,_original=original,**kwargs):
                    if isinstance(path,(str,bytes,os.PathLike)) and any(tuple(Path(os.fsdecode(path)).parts[i:i+3])==CACHE_PARTS for i in range(len(Path(os.fsdecode(path)).parts)-2)):
                        raise AssertionError('real native cache probe forbidden')
                    return _original(path,*args,**kwargs)
                guards.enter_context(patch.object(module,name,denied))
        with tempfile.TemporaryDirectory(prefix='synthetic-auth-worker-',dir=FIXTURES) as directory:
            root=Path(directory);bag,row,xmlsha,size=make_bag(root)
            source=dict(path=bag.name,sha256=row['sha256'],bytes=size,contract='coastal-native-source-v1')
            spec=dict(schema=planner.SPEC,source_sha256=source['sha256'],window_shape=[16,16],halo=0,minimum_margin_m=.1,
                center_native=[432016.,3701984.],safety_bbox_native=[431984.,3701952.,432048.,3702016.],
                historical_support=dict(crs='EPSG:26911',geometry=mapping(box(431900,3701900,432100,3702100))),
                legacy_bounds=dict(crs='EPSG:26911',bbox=[431900,3701900,432100,3702100]),
                segment=dict(crs='EPSG:26911',bbox=[431900,3701900,432100,3702100]))
            # Only lower-level scientific tests mock the external live authority validator.
            job=dict(root=str(root),source_root=str(root),source_relative_path=source['path'],job_id='TEST_ONLY',lease_token='TEST_ONLY_TOKEN')
            packet=dict(source=source,source_root=str(root),source_relative_path=source['path'])
            fake=types.ModuleType('skippercast.coastal.coordinator.authenticated')
            fake.authorize_worker=lambda *a,**kw:copy.deepcopy(packet)
            guards.enter_context(patch.dict(sys.modules,{'skippercast.coastal.coordinator.authenticated':fake}))
            _,grant=authority.bind_reserved_source(job,'TEST_ONLY_REQUEST','TEST_ONLY_OUTPUT')
            import resource
            saved_fsize=resource.getrlimit(resource.RLIMIT_FSIZE)
            try:yield root,bag,row,xmlsha,source,spec,grant
            finally:
                grant.close()
                resource.setrlimit(resource.RLIMIT_FSIZE,saved_fsize)
def capture(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    return snapshot.authenticate(root,source['path'],source['sha256'],source['bytes'],authority=grant)
def test_exact_reserved_authority_required_before_any_source_open(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    for supplied in (None,object(),copy.copy(grant)):
        with patch.object(os,'open',side_effect=AssertionError('no source/FS open allowed')):
            with pytest.raises(ValueError):
                with snapshot.authenticate(root,source['path'],source['sha256'],source['bytes'],authority=supplied):pass
    for args in ((str(root.parent),'x',source['sha256'],source['bytes']),
                 (str(root),'different.bag',source['sha256'],source['bytes']),
                 (str(root),source['path'],'0'*64,source['bytes']),
                 (str(root),source['path'],source['sha256'],source['bytes']+1)):
        with patch.object(os,'open',side_effect=AssertionError('no source/FS open allowed')),pytest.raises(ValueError):
            with snapshot.authenticate(*args,authority=grant):pass
def test_header_planner_same_view_exact_fixed16x16(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    with capture(fixture) as view:
        header=planner.read_header(view,source,row,xmlsha)
        plan=planner.plan_header(header,spec)
        assert plan['window']==[0,0,16,16] and plan['halo']==0
        assert not plan['accepted'] and not plan['relocation_allowed']
        assert plan['header_sha256']==common.digest(header)
        assert view.provenance['total_full_hash_passes']==2
        receipt=view.finalize()
        with pytest.raises(ValueError):receipt.payload()
    assert receipt.payload()['capability_closed']
def test_fixed_geometry_holes_margin_invalidgrid_no_relocation(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    with capture(fixture) as view:
        header=planner.read_header(view,source,row,xmlsha)
        bad=copy.deepcopy(spec);bad['safety_bbox_native']=[432000,3701968,432032,3702000]
        with pytest.raises(ValueError):planner.plan_header(header,bad)
        bad=copy.deepcopy(spec);bad['historical_support']['geometry']=mapping(box(431900,3701900,432100,3702100).difference(box(432010,3701980,432011,3701981)))
        with pytest.raises(ValueError):planner.plan_header(header,bad)
        bad=copy.deepcopy(spec);bad['center_native']=[0,0]
        with pytest.raises(ValueError):planner.plan_header(header,bad)
        bad=copy.deepcopy(header);bad['transform'][1]=.001
        with pytest.raises(ValueError):planner.plan_header(bad,spec)
        bad=copy.deepcopy(header);bad['shape']=[8,8]
        with pytest.raises(ValueError):planner.plan_header(bad,spec)
def test_frozen_native_science_arrays_masks_quality_and_metadata_parity(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    baseline=regular_bag_window.read_original_regular_bag_window(bag,row,Window(0,0,16,16),expected_metadata_sha256=xmlsha)
    from skippercast.coastal.authenticated_v1.adapter_bag import read_snapshot_window
    with capture(fixture) as view:
        actual=read_snapshot_window(view,row,Window(0,0,16,16),expected_metadata_sha256=xmlsha)
        for name in ('elevation_m','depth_m_positive_down','product_uncertainty_m','source_pair_valid','qualifies_25_300ft_uncertainty_0_1m'):
            np.testing.assert_array_equal(getattr(actual,name),getattr(baseline,name))
        assert actual.source_pair_valid[1,1] and not actual.qualifies_25_300ft_uncertainty_0_1m[1,1]
        for name in ('horizontal_crs','source_crs_wkt','transform','vertical_datum','metadata_sha256','cell_id_prefix'):
            assert getattr(actual,name)==getattr(baseline,name)
def test_same_return_supplement_depth_is_unchanged_float64(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    from skippercast.coastal.authenticated_v1.supplement import summarize
    with capture(fixture) as view:
        header=planner.read_header(view,source,row,xmlsha);captured=[]
        observed=observer.observe_snapshot(view,root,source,window=[0,0,16,16],vertical=header['vertical'],source_row=row,metadata_sha256=xmlsha,collector=captured.append)
        assert len(captured)==1 and captured[0]['depth'].dtype==np.dtype('float64')
        np.testing.assert_array_equal(captured[0]['depth'],observed[6])
        supplement=summarize(captured[0],common.digest(observed[0]))
        c=supplement['counts'];assert c['returned_paired_cells']==256
        assert c['invalid']+c['valid_but_out_of_range']+c['eligible']==256
        assert supplement['uncertainty']['nonpositive']>0
        assert not supplement['accepted'] and not supplement['qualification']
def test_mutation_body_failure_no_finalized_proof(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    receipt=None
    with pytest.raises(RuntimeError):
        with capture(fixture) as view:receipt=view.finalize();raise RuntimeError('synthetic operation failed')
    with pytest.raises(ValueError):receipt.payload()
    with pytest.raises(ValueError):
        with capture(fixture) as view:
            with bag.open('r+b') as out:out.write(b'X')
            receipt=view.finalize()
def test_unique_observation_schema_cannot_use_ordinary_mapping_verifier():
    assert observer.SCHEMA=='coastal-authenticated-observation-v1'
    assert observer.SCHEMA!=mapping_input.SCHEMA
def test_actual_isolated_bootstrap_rejects_root_import_shadow_before_source(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    evil=root/'skippercast';evil.mkdir()
    (evil/'__init__.py').write_text("raise RuntimeError('ROOT_IMPORT_SHADOW_EXECUTED')")
    env=dict(os.environ,PYTHONPATH=str(root),PYTHONDONTWRITEBYTECODE='1')
    # The bootstrap's source guard refuses a package tree holding bytecode, and this
    # test process has already imported (and may have cached) skippercast, so run
    # the bootstrap from a byte-identical source-only export (tests/_coastal_operations).
    export=export_package(root/'source-only-export')
    bootstrap=export/'skippercast/coastal/authenticated_v1/bootstrap.py'
    assert bootstrap.read_bytes()==Path(worker.__file__).with_name('bootstrap.py').read_bytes()
    result=subprocess.run([sys.executable,'-I',str(bootstrap),'--request',str(root/'wrong.json'),'--output',str(root/'out')],cwd=root,env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==4 and 'ROOT_IMPORT_SHADOW_EXECUTED' not in result.stderr
    assert 'authenticated worker refused' in result.stderr and not result.stdout
def test_hard_envelope_missing_refuses_without_native_or_lease_calls(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    jobdir=root/'var/coastal/jobs/TEST_ONLY/TEST_ONLY_TOKEN';jobdir.mkdir(parents=True)
    request=jobdir/'job.json';common.write(request,dict(execution_contract='coastal-authenticated-job-v1',stage='acquire'))
    with patch.object(worker,'runtime_limits',side_effect=ValueError('hardcaps unavailable')),patch.object(worker,'bind_reserved_source',side_effect=AssertionError('no source authority after resource fail')):
        assert worker.main(['--request',str(request),'--output',str(jobdir/'output')])==4
    assert not (jobdir/'output').exists()
def test_closed_or_forged_source_grant_rejects(fixture):
    root,bag,row,xmlsha,source,spec,grant=fixture
    grant.close()
    with pytest.raises(ValueError):
        with capture(fixture):pass
    with pytest.raises(ValueError):authority.SourceAuthority(object(),{}, {},'x','y')

def clock_job(now=100.,mono=1000.,stage='acquire',unit_offset=0):
    unit=now+unit_offset;um=mono+unit_offset
    return dict(stage=stage,mission_start_utc=now,mission_start_monotonic=mono,
        overall_deadline_utc=now+600,overall_deadline_monotonic=mono+600,
        phase_unit_start_utc=unit,phase_unit_start_monotonic=um,
        phase_deadline_utc=min(unit+180,now+600),phase_deadline_monotonic=min(um+180,mono+600),
        deadline_utc=min(unit+120,now+540),deadline_monotonic=min(um+120,mono+540))
def test_immutable_monotonic_unit_mission_clock_no_reset_or_utc_rollback():
    job=clock_job()
    assert worker.validate_clock(job,utc_now=110,monotonic_now=1010)==220
    for now,mono in ((90,1010),(110,990),(221,1121),(110,1015)):
        with pytest.raises(ValueError):worker.validate_clock(job,utc_now=now,monotonic_now=mono)
    for key,value in (('overall_deadline_monotonic',2000),('deadline_utc',999),('phase_deadline_monotonic',float('inf'))):
        bad=dict(job);bad[key]=value
        with pytest.raises(ValueError):worker.validate_clock(bad,utc_now=110,monotonic_now=1010)
    job=clock_job(stage='qualify',unit_offset=420)
    assert worker.validate_clock(job,utc_now=525,monotonic_now=1425)==640
    with pytest.raises(ValueError):worker.validate_clock(clock_job(stage='qualify',unit_offset=421),utc_now=525,monotonic_now=1425)

def test_policy_has_no_legacy_depth_floor_and_rejects_sparse_quality_or_units():
    from skippercast.coastal.authenticated_v1.policy import evaluate,POLICY_SHA,require_quality_review
    d=dict(facts_digest='f'*64,diagnostics_digest='d'*64,
        counts={key:256 for key in ('returned_paired_cells','paired_mask_valid','paired_raw_finite','source_pair_valid','normalized_finite','eligible')},
        uncertainty=dict(units='m',count=256,minimum=.01,maximum=1,nonpositive=0,above_1m=0))
    facts=dict(header=dict(driver='BAG',scales=[1.,1.],offsets=[0.,0.],units=[None,None]))
    assert evaluate(d,facts)['paired_eligibility_quality_pass']
    for field,value in (('source_pair_valid',255),('normalized_finite',255),('eligible',255)):
        changed=copy.deepcopy(d);changed['counts'][field]=value
        assert evaluate(changed,facts)['holds']
    for field,value in (('minimum',0),('minimum',-1),('maximum',1.01),('count',255)):
        changed=copy.deepcopy(d);changed['uncertainty'][field]=value
        assert 'bounded_patch_uncertainty_quality_failed' in evaluate(changed,facts)['holds']
    for key,value in (('scales',[1,2]),('offsets',[0,1]),('units',[None,'ft']),('scales',[])):
        changed=copy.deepcopy(facts);changed['header'][key]=value
        assert 'bounded_patch_uncertainty_units_unresolved' in evaluate(d,changed)['holds']
    review=dict(quality_accepted=True,policy_sha256=POLICY_SHA,trial_policy_sha256='t'*64,
        facts_digest='f'*64,diagnostics_digest='d'*64,plan_sha256='p'*64)
    require_quality_review(review,facts_digest='f'*64,diagnostics_digest='d'*64,plan_sha256='p'*64,trial_policy_sha256='t'*64)
    for field in review:
        bad=copy.deepcopy(review);bad[field]=False if field=='quality_accepted' else 'different'
        with pytest.raises(ValueError):
            require_quality_review(bad,facts_digest='f'*64,diagnostics_digest='d'*64,plan_sha256='p'*64,trial_policy_sha256='t'*64)

def test_truly_disjoint_native_and_artifact_roots_preserve_logical_ref(fixture):
    source_root,bag,row,xmlsha,original,spec,original_grant=fixture
    with tempfile.TemporaryDirectory(prefix='synthetic-auth-artifacts-',dir=FIXTURES) as directory:
        artifact_root=Path(directory)
        assert artifact_root.parent==source_root.parent and artifact_root!=source_root
        logical=dict(original,path='retained-logical-cache/source.bag')
        job=dict(root=str(artifact_root),source_root=str(source_root),source_relative_path=bag.name,
                 job_id='TEST_ONLY_DISJOINT',lease_token='TEST_ONLY_TOKEN')
        packet=dict(source=logical,source_root=str(source_root),source_relative_path=bag.name)
        fake=types.ModuleType('skippercast.coastal.coordinator.authenticated')
        fake.authorize_worker=lambda *a,**kw:copy.deepcopy(packet)
        with patch.dict(sys.modules,{'skippercast.coastal.coordinator.authenticated':fake}):
            _,grant=authority.bind_reserved_source(job,'TEST_ONLY_REQUEST','TEST_ONLY_OUTPUT')
            try:
                with snapshot.authenticate(source_root,bag.name,logical['sha256'],logical['bytes'],authority=grant) as view:
                    header=planner.read_header(view,logical,row,xmlsha)
                    actual=observer.observe_snapshot(view,artifact_root,logical,window=[0,0,16,16],
                        vertical=header['vertical'],source_row=row,metadata_sha256=xmlsha)
                    assert actual[0]['source']==logical
                    assert view.provenance['origin']['root']==str(source_root)
                    assert view.provenance['logical_source']==logical
                    view.finalize()
                assert list(artifact_root.iterdir())==[]
                for root,leaf in ((artifact_root,bag.name),(source_root,'../'+bag.name)):
                    with patch.object(os,'open',side_effect=AssertionError('wrong native domain must refuse before open')):
                        with pytest.raises(ValueError):
                            with snapshot.authenticate(root,leaf,logical['sha256'],logical['bytes'],authority=grant):pass
            finally:grant.close()

def test_two_phase_worker_native_flow_with_explicit_mocked_fence_and_envelope(fixture,capsys):
    """Only external lease authority/hard envelope are mocked; all synthetic native reads are actual."""
    from skippercast.coastal.authenticated_v1.policy import POLICY_SHA
    from shapely.ops import transform as project
    from pyproj import Transformer
    import h5py
    native_root,bag,row,xmlsha,original,spec,old_grant=fixture
    # Regenerate a complete-policy source using only owned synthetic HDF datasets.
    with h5py.File(bag,'r+') as source:
        source['BAG_root/elevation'][:]=-20.
        source['BAG_root/uncertainty'][:]=.25
    content=bag.read_bytes();sha=hashlib.sha256(content).hexdigest()
    row=dict(row,sha256=sha);logical=dict(original,path='logical-origin/source.bag',sha256=sha,bytes=len(content))
    spec=copy.deepcopy(spec);spec['source_sha256']=sha
    with tempfile.TemporaryDirectory(prefix='synthetic-worker-artifacts-',dir=FIXTURES) as directory:
        root=Path(directory);metadata=root/'metadata';metadata.mkdir()
        footprint=planner.rectangle([432000,3701968,432032,3702000],'EPSG:26911','EPSG:3310')
        x,y=footprint.centroid.x,footprint.centroid.y;x0,y0=int(x//5000)*5000,int(y//5000)*5000
        sid=f'seg:3310:{x0}:{y0}:5000'
        segment=dict(schema='coastal-segment-v1',segment_id=sid,region='TEST_ONLY_SYNTHETIC',crs='EPSG:3310',bbox=[x0,y0,x0+5000,y0+5000])
        common.write(metadata/'segment.json',segment);segment_ref=common.ref(root,metadata/'segment.json','coastal-segment-v1')
        spec['segment']=dict(crs=segment['crs'],bbox=segment['bbox'],segment_id=sid)
        common.write(metadata/'rights.json',dict(schema='coastal-rights-evidence-v1',synthetic=True,accepted_real_rights=False))
        rights=dict(private_use=True,evidence=[common.ref(root,metadata/'rights.json','coastal-rights-evidence-v1')])
        common.write(metadata/'policy.json',dict(schema='coastal-bounded-patch-quality-policy-v1',synthetic=True,accepted_real_source=False))
        policy_ref=common.ref(root,metadata/'policy.json','coastal-bounded-patch-quality-policy-v1')
        packet=dict(schema='coastal-authenticated-input-v1',source=logical,source_row=row,source_root=str(native_root),source_relative_path=bag.name,
                    metadata_sha256=xmlsha,fixed_center_plan=spec,vertical=None,segment_id=sid,segment=segment_ref,rights=rights,
                    synthetic=True,policy_sha256=POLICY_SHA,trial_policy_evidence=policy_ref,trial_policy_sha256=policy_ref['sha256'])
        # No real Store/Budget authorization is claimed by this primitive flow test.
        fake=types.ModuleType('skippercast.coastal.coordinator.authenticated')
        fake.authorize_worker=lambda *a,**kw:copy.deepcopy(packet)
        mocked_envelope=dict(test_only=True,hard_resource_enforcement=False,authority='EXPLICIT_UNIT_MOCK')
        clock=FakeClock();start=clock.timestamp();mono=1000.
        counts=dict(hdf=0,gdal=0,band_reads=0,band_cell_visits=0)
        original_hdf=snapshot.SealedSnapshot._open_hdf_unchecked
        original_raster=snapshot.SealedSnapshot.open_raster
        @contextlib.contextmanager
        def counted_hdf(self):
            counts['hdf']+=1
            with original_hdf(self) as native:yield native
        @contextlib.contextmanager
        def counted_raster(self,*args,**kwargs):
            counts['gdal']+=1
            with original_raster(self,*args,**kwargs) as native:
                class CountedDataset:
                    def __getattr__(self,name):return getattr(native,name)
                    def read(self,*args,**kwargs):
                        values=native.read(*args,**kwargs)
                        counts['band_reads']+=1
                        counts['band_cell_visits']+=values.size
                        return values
                yield CountedDataset()
        with patch.dict(sys.modules,{'skippercast.coastal.coordinator.authenticated':fake}),patch.object(worker,'runtime_limits',return_value=mocked_envelope),patch.object(worker,'time',types.SimpleNamespace(time=clock.timestamp,monotonic=lambda:mono)),patch.object(snapshot.SealedSnapshot,'_open_hdf_unchecked',counted_hdf),patch.object(snapshot.SealedSnapshot,'open_raster',counted_raster):
            def job_for(stage,token):
                job=clock_job(start,mono,stage)
                job.update(root=str(root),source_root=str(native_root),source_relative_path=bag.name,job_id='TEST_ONLY_'+stage,
                    lease_token=token,stage=stage,segment_id=sid,code_sha='c'*64,deps_sha='d'*64,params_sha='p'*64,
                    input_manifest_sha='i'*64,execution_contract='coastal-authenticated-job-v1')
                jobdir=root/'var/coastal/jobs'/job['job_id']/token;jobdir.mkdir(parents=True)
                path=jobdir/'job.json';common.write(path,job)
                return path,jobdir/'output'
            request,out=job_for('acquire','TEST_ONLY_LEASE1')
            assert worker.run(request,out)==0
            envelope=json.loads(capsys.readouterr().out)
            acquire=json.loads((out/'result.json').read_text());observation=json.loads((root/acquire['observation']['path']).read_text())
            assert not acquire['accepted'] and not acquire['qualification']
            assert observation['schema']==observer.SCHEMA and observation['policy_ready']
            assert envelope['result_sha256']==hashlib.sha256((out/'result.json').read_bytes()).hexdigest()
            phase1_counts=copy.deepcopy(counts)
            firstproof=json.loads((root/acquire['finalized_authentication']['path']).read_text())
            assert firstproof['capability_closed'] and firstproof['snapshot']['logical_source']==logical
            plan=json.loads((root/acquire['plan']['path']).read_text())
            diagnostics=json.loads((root/acquire['diagnostics']['path']).read_text())
            review=dict(schema='coastal-private-input-review-v2',independent=True,reviewer_id='TEST_ONLY_INDEPENDENT',
                 checked_at=start-1,valid_until=start+1000,decision='accept',holds_added=[],facts_digest=observation['facts_digest'],
                 quality_accepted=True,policy_sha256=POLICY_SHA,trial_policy_sha256=policy_ref['sha256'],
                 diagnostics_digest=diagnostics['diagnostics_digest'],plan_sha256=observation['plan']['sha256'],
                 synthetic_only=True,accepted_real_source=False)
            common.write(metadata/'review.json',review)
            packet.update(registered_observation=observation,registered_plan=plan,registered_diagnostics=diagnostics,registered_review=review,
                          review=common.ref(root,metadata/'review.json','coastal-private-input-review-v2'))
            request,out=job_for('qualify','TEST_ONLY_LEASE2')
            assert worker.run(request,out)==0
            envelope=json.loads(capsys.readouterr().out)
            qualify=json.loads((out/'result.json').read_text())
            assert not qualify['accepted'] and not qualify['qualification']
            assert qualify['producer_facts_digest']==qualify['verified_facts_digest']==acquire['facts_digest']
            assert qualify['provenance']['scientific_observations']==2
            secondproof=json.loads((root/qualify['finalized_authentication']['path']).read_text())
            assert secondproof['snapshot']['generation']!=firstproof['snapshot']['generation']
            assert secondproof['snapshot']['total_full_hash_passes']==2
            assert envelope['artifacts_digest']==common.digest(qualify['artifacts'])
            producer=json.loads((root/qualify['diagnostics']['path']).read_text())
            verifier=json.loads((root/qualify['verified_diagnostics']['path']).read_text())
            assert producer['diagnostics_digest']==verifier['diagnostics_digest']==diagnostics['diagnostics_digest']
            for artifact in qualify['artifacts']:assert common.resolve(root,artifact).is_relative_to(out)
            assert phase1_counts==dict(hdf=6,gdal=3,band_reads=2,band_cell_visits=512)
            assert counts==dict(hdf=15,gdal=7,band_reads=6,band_cell_visits=1536)
            assert acquire['provenance']['logical_pair_visits']+qualify['provenance']['logical_pair_visits']==768
            assert firstproof['snapshot']['source_full_hash_passes']==secondproof['snapshot']['source_full_hash_passes']==1
            assert firstproof['snapshot']['sealed_snapshot_full_hash_passes']==secondproof['snapshot']['sealed_snapshot_full_hash_passes']==1

def test_actual_fixed_worker_resource_failure_is_bounded_before_authority(fixture):
    """Actual subprocess caps refusal, without any mocked resource gate or source access."""
    root,bag,row,xmlsha,source,spec,grant=fixture
    jobdir=root/'var/coastal/jobs/TEST_ONLY_CAPS/TEST_ONLY_TOKEN';jobdir.mkdir(parents=True)
    request=jobdir/'job.json'
    common.write(request,dict(execution_contract='coastal-authenticated-job-v1',stage='acquire'))
    # Source-only export: the bootstrap guard refuses this process's cached bytecode.
    bootstrap=export_package(root/'source-only-export')/'skippercast/coastal/authenticated_v1/bootstrap.py'
    result=subprocess.run([sys.executable,'-I',str(bootstrap),'--request',str(request),'--output',str(jobdir/'output')],
                          cwd=root,capture_output=True,text=True,timeout=10)
    assert result.returncode==4 and 'authenticated worker refused' in result.stderr and not result.stdout
    assert not (jobdir/'output').exists()

def test_actual_zero_depth_patch_passes_trial_policy_without_legacy25ft_floor(fixture):
    import h5py
    from skippercast.coastal.authenticated_v1.policy import evaluate
    from skippercast.coastal.authenticated_v1.supplement import summarize
    root,bag,row,xmlsha,old_source,spec,old_grant=fixture
    with h5py.File(bag,'r+') as file:
        file['BAG_root/elevation'][:]=0.
        file['BAG_root/uncertainty'][:]=.25
    content=bag.read_bytes();source=dict(old_source,sha256=hashlib.sha256(content).hexdigest(),bytes=len(content))
    row=dict(row,sha256=source['sha256'])
    job=dict(root=str(root),source_root=str(root),source_relative_path=bag.name,job_id='TEST_ONLY_ZERO',lease_token='TEST_ONLY')
    packet=dict(source=source,source_root=str(root),source_relative_path=bag.name)
    fake=types.ModuleType('skippercast.coastal.coordinator.authenticated');fake.authorize_worker=lambda *a,**kw:copy.deepcopy(packet)
    with patch.dict(sys.modules,{'skippercast.coastal.coordinator.authenticated':fake}):
        _,grant=authority.bind_reserved_source(job,'TEST_ONLY_REQUEST','TEST_ONLY_OUTPUT')
        try:
            with snapshot.authenticate(root,bag.name,source['sha256'],source['bytes'],authority=grant) as view:
                header=planner.read_header(view,source,row,xmlsha);arrays=[]
                observed=observer.observe_snapshot(view,root,source,window=[0,0,16,16],vertical=header['vertical'],source_row=row,metadata_sha256=xmlsha,collector=arrays.append)
                d=summarize(arrays[0],common.digest(observed[0]))
                assert d['counts']['eligible']==256 and np.count_nonzero(arrays[0]['legacy_25_300ft_uncertainty_0_1m'])==0
                assert evaluate(d,observed[0])['paired_eligibility_quality_pass']
                assert np.isfinite(arrays[0]['depth']).all() and (arrays[0]['depth']==0).all()
        finally:grant.close()


@pytest.mark.parametrize("poison", ["valid-pyc", "empty-cache", "pyo", "source-symlink"])
def test_actual_preimport_guard_rejects_project_compiled_or_linked_tree(fixture, poison):
    """An actual isolated process must reject before executing a forged project."""
    import importlib.util, marshal, struct
    root = fixture[0] / ("compiled-guard-" + poison)
    package = root / "src/skippercast"
    coastal = package / "coastal"
    lane = coastal / "authenticated_v1"
    lane.mkdir(parents=True)
    marker = root / "FORGED_PROJECT_EXECUTED"
    initial = package / "__init__.py"
    initial.write_text("# innocuous source\\n")
    for directory in (coastal, lane):
        (directory / "__init__.py").write_text("")
    (lane / "worker.py").write_text("def main(): return 0\\n")
    source_root = Path(worker.__file__).parent.parent
    (coastal / "_source_bootstrap.py").write_bytes((source_root / "_source_bootstrap.py").read_bytes())
    bootstrap = lane / "bootstrap.py"
    bootstrap.write_bytes(Path(worker.__file__).with_name("bootstrap.py").read_bytes())
    cache = package / "__pycache__"
    if poison in ("valid-pyc", "empty-cache"):
        cache.mkdir()
    if poison == "valid-pyc":
        metadata = initial.stat()
        forged = compile("from pathlib import Path; Path(" + repr(str(marker)) + ").write_text('EXECUTED')", str(initial), "exec")
        bytecode = importlib.util.MAGIC_NUMBER + struct.pack("<III", 0, int(metadata.st_mtime), metadata.st_size) + marshal.dumps(forged)
        Path(importlib.util.cache_from_source(str(initial))).write_bytes(bytecode)
        # Demonstrate timestamp/size-valid poisoned bytecode really executes
        # under unguarded isolated -B: disabling writes does not disable reads.
        control = run_unguarded_poison_control(package.parent,root)
        assert control.returncode == 0 and marker.exists()
        marker.unlink()
    elif poison == "pyo":
        (coastal / "forged.pyo").write_bytes(b"TEST_ONLY")
    elif poison == "source-symlink":
        (coastal / "linked.py").symlink_to(initial)
    result = subprocess.run([sys.executable, "-I", str(bootstrap), "--request", str(root / "wrong.json"),
        "--output", str(root / "out")], cwd=root, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "compiled bytecode" in result.stderr
    assert not marker.exists() and not (root / "out").exists()


def test_actual_source_sized_memfd_then_artifact_rlimit_under_bounded_subprocess(fixture):
    """Five-MiB synthetic bytes, real RLIMIT_FSIZE; no BAG/native parsing or real lease claim."""
    root=fixture[0]/"rlimit-capture";root.mkdir()
    script=root/"test_only_rlimit.py"
    script.write_text("""
import copy,errno,hashlib,json,os,resource,signal,sys,types
from pathlib import Path
sys.dont_write_bytecode=True
from skippercast.coastal.authenticated_v1 import authority,snapshot,worker
root=Path(sys.argv[1])
source=root/'synthetic-large.bag'
data=b'TEST_ONLY_SYNTHETIC'*(5*1024*1024//19+1)
data=data[:5*1024*1024]
source.write_bytes(data)
identity=dict(path=source.name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
job=dict(root=str(root),source_root=str(root),source_relative_path=source.name)
packet=dict(source=identity,source_root=str(root),source_relative_path=source.name)
fake=types.ModuleType('skippercast.coastal.coordinator.authenticated')
fake.authorize_worker=lambda *a,**kw:copy.deepcopy(packet)
sys.modules[fake.__name__]=fake
_,grant=authority.bind_reserved_source(job,'TEST_ONLY_MOCK_REQUEST','TEST_ONLY_MOCK_OUTPUT')
signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE,(worker.MAX_OUTPUT,len(data)))
try:
    with snapshot.authenticate(root,source.name,identity['sha256'],len(data),authority=grant):pass
except OSError as exc:
    assert exc.errno==errno.EFBIG
else:raise AssertionError('4MiB initial limit incorrectly allowed5MiB memfd')
resource.setrlimit(resource.RLIMIT_FSIZE,(len(data),len(data)))
with snapshot.authenticate(root,source.name,identity['sha256'],len(data),authority=grant) as view:
    assert view.provenance['sealed_snapshot_sha256']==identity['sha256']
    assert worker.limit_artifact_file_size()==worker.MAX_OUTPUT
    assert resource.getrlimit(resource.RLIMIT_FSIZE)==(worker.MAX_OUTPUT,len(data))
    fd=os.open(root/'oversize-output.bin',os.O_WRONLY|os.O_CREAT,0o600)
    try:
        try:os.pwrite(fd,b'X',worker.MAX_OUTPUT)
        except OSError as exc:assert exc.errno==errno.EFBIG
        else:raise AssertionError('output per-file limit not enforced')
    finally:os.close(fd)
grant.close()
print(json.dumps(dict(test_only=True,original_stream_hash_passes=1,sealed_snapshot_hash_passes=1,source_bytes=len(data),artifact_soft_limit=worker.MAX_OUTPUT)))
""")
    result=subprocess.run([sys.executable,str(script),str(root)],cwd=root,
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",PYTHONPATH=str(Path(worker.__file__).parents[3])),
        capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['test_only'] and report['source_bytes']==5*1024*1024
