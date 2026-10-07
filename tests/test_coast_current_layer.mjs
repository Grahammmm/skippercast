import test from 'node:test';
import assert from 'node:assert/strict';
import {selectedCurrent,isCurrentLayer} from '../packages/coast/src/state/current-layer.ts';
const now=new Date('2026-10-07T12:00Z'),iso=hours=>new Date(now.getTime()+hours*3600000).toISOString();
const forecast={surfaceOnly:true,id:'wcofs',kind:'forecast',label:'Original forecast',fetchedAt:iso(0),issuedAt:iso(-3),nativeResolutionKm:4,frames:[0,3,6].map(hour=>({validAt:iso(hour),cells:[{lat:35.4,lon:-120.9,uMs:1,vMs:0,speedKnots:1.94,towardDeg:90}]}))};
const observed={...forecast,id:'hfr-1',kind:'observation',label:'Original radar',issuedAt:null,nativeResolutionKm:1,frames:[{validAt:iso(-1),cells:forecast.frames[0].cells}]};
test('exact source identity retains original frame and metadata without provider substitution',()=>{
 assert.equal(selectedCurrent([forecast,observed],'wcofs',now,now).field,forecast);assert.equal(selectedCurrent([forecast,observed],'hfr-1',now,now).frame,observed.frames[0]);
 assert.equal(selectedCurrent([forecast,observed],'hfr-6',now,now),null);assert.equal(selectedCurrent([forecast,forecast],'wcofs',now,now),null);assert.equal(selectedCurrent([forecast],'off',now,now),null);
 for(const value of ['constructor','toString','__proto__','',null]){assert.equal(isCurrentLayer(value),false);assert.equal(selectedCurrent([forecast],value,now,now),null);}
});
test('selected source clocks retain forecast horizon, observed-time limits and invalid-hour gaps',()=>{
 assert.equal(selectedCurrent([forecast],'wcofs',new Date(iso(-1)),now),null);assert.equal(selectedCurrent([forecast],'wcofs',new Date(iso(7)),now),null);
 assert.equal(selectedCurrent([observed],'hfr-1',new Date(iso(1)),now),null);assert.equal(selectedCurrent([forecast],'wcofs',new Date(NaN),now),null);
 assert.equal(selectedCurrent([{...forecast,fetchedAt:iso(-7)}],'wcofs',now,now),null);assert.equal(selectedCurrent([{...forecast,fetchedAt:iso(1)}],'wcofs',now,now),null);assert.equal(selectedCurrent([{...forecast,issuedAt:iso(-37)}],'wcofs',now,now),null);
 assert.equal(selectedCurrent([{...observed,frames:[{...observed.frames[0],validAt:iso(-7)}]}],'hfr-1',now,now),null);
 assert.equal(selectedCurrent([forecast],'wcofs',new Date(iso(1)),now).frame,forecast.frames[0],'legitimate native three-hour sampling remains unchanged');
});

test('selected-field validation fails closed for malformed fields, frames and cells',()=>{
 for(const malformed of [null,{}, {...forecast,frames:null}, {...forecast,frames:[null]}, {...forecast,frames:[forecast.frames[0],forecast.frames[0]]}, {...forecast,frames:[{...forecast.frames[0],cells:[null]}]}, {...forecast,frames:[{...forecast.frames[0],cells:[{lat:35,lon:-121,uMs:NaN,vMs:0,speedKnots:1,towardDeg:90}]}]}])assert.equal(selectedCurrent([malformed],'wcofs',now,now),null);
 assert.equal(selectedCurrent([null,forecast],'wcofs',now,now).field,forecast,'unrelated malformed product cannot replace exact selected provider');
 assert.equal(selectedCurrent([forecast],'wcofs',now,now).expiresAt,now.getTime()+6*3600000);
 assert.equal(selectedCurrent([observed],'hfr-1',now,now).expiresAt,now.getTime()+5*3600000);
 assert.equal(selectedCurrent([{...forecast,issuedAt:iso(-35)}],'wcofs',now,now).expiresAt,now.getTime()+3600000);
});

test('surface-only declaration and observed metadata clocks are required for displayed source admission',()=>{
 for(const surfaceOnly of [undefined,false,'true'])assert.equal(selectedCurrent([{...forecast,surfaceOnly}],'wcofs',now,now),null);
 for(const clocks of [{sampleAt:iso(1)},{issuedAt:iso(1)},{issuedAt:'invalid'},{sampleAt:'invalid'}])assert.equal(selectedCurrent([{...observed,...clocks}],'hfr-1',now,now),null);
 assert.equal(selectedCurrent([{...observed,sampleAt:iso(-1),issuedAt:iso(-2)}],'hfr-1',now,now).field.sampleAt,iso(-1));
 assert.equal(selectedCurrent([forecast],'wcofs',new Date(iso(3)),now).frame,forecast.frames[1],'legitimate forecast future valid times remain admitted');
});
