import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveReportBinding} from '../packages/coast/src/state/report-binding.ts';

const good={id:'estero-bay',bounds:[-121,35,-120,36]};
const ctx=(localAreas,extra={})=>({regionId:'morro-bay',point:{latitude:35.5,longitude:-120.5},localAreas,profile:'fishing',target:'t',at:new Date('2026-01-01T00:00:00Z'),...extra});
const expected={areaId:'central',localAreaId:'estero-bay'};

test('report_binding_skips_malformed_siblings',()=>{
  const bad=[null,undefined,true,7,'x',[],[1,2],{id:'cayucos'},{id:'cayucos',bounds:null},{id:'cayucos',bounds:'-121,35,-120,36'},{id:'cayucos',bounds:{length:4}},{id:7,bounds:[-121,35,-120,36]},{bounds:[-121,35,-120,36]}];
  for(const b of bad){
    assert.deepEqual(resolveReportBinding(ctx([b,good])),expected);
    assert.deepEqual(resolveReportBinding(ctx([good,b])),expected);
    assert.equal(resolveReportBinding(ctx([b])),null);
  }
});

test('report_binding_nonarray_collection_is_unbound',()=>{
  for(const v of [null,undefined,{},{filter:()=>[good]},'abc',5,[]])assert.equal(resolveReportBinding(ctx(v)),null);
});

test('report_binding_explicit_bad_area_never_falls_back',()=>{
  const other={id:'cayucos',bounds:[-121,35,-120,36]};
  assert.equal(resolveReportBinding(ctx([{id:'estero-bay'},other],{localId:'estero-bay'})),null);
  assert.equal(resolveReportBinding(ctx([null,other],{localId:'nowhere'})),null);
  assert.deepEqual(resolveReportBinding(ctx([{id:'estero-bay'},other],{localId:'cayucos'})),{areaId:'central',localAreaId:'cayucos'});
});

test('report_binding_valid_selection_and_purity',()=>{
  const big={id:'avila',bounds:[-122,34,-119,37]};
  const tie={id:'buchon',bounds:[-121,35,-120,36]};
  const areas=Object.freeze([big,good,tie].map(a=>Object.freeze({...a,bounds:Object.freeze([...a.bounds])})));
  assert.deepEqual(resolveReportBinding(ctx(areas)),{areaId:'central',localAreaId:'buchon'});
  assert.deepEqual(resolveReportBinding(ctx(areas,{localId:'avila'})),{areaId:'south',localAreaId:'avila'});
  assert.deepEqual(resolveReportBinding(ctx([{id:'estero-bay',bounds:[-120.5,35,-120,36]}])),expected);
  assert.equal(resolveReportBinding(ctx([{id:'estero-bay',bounds:[-121,35,-120,NaN]}])),null);
  assert.equal(resolveReportBinding(ctx([{id:'estero-bay',bounds:[-121,35,-120.6,36]}])),null);
});
