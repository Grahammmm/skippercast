import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {getRegion,setRegion} from '../dist/region.js?v=8.12';
import {regulationState,validRegulations} from '../dist/regulations.js';

const region=JSON.parse(readFileSync(new URL('../regions/fort-bragg-point-arena/region.json',import.meta.url)));
const reviewed=JSON.parse(readFileSync(new URL('../dist/data/regulations-mendocino.json',import.meta.url)));
const now=Date.parse('2026-09-24T18:00:00Z');

function matchedFixture(){
  const data=structuredClone(reviewed);
  data.reviewed_at=new Date(now-3600000).toISOString();
  data.rules_review_status='reviewed';
  for(const [id,source] of Object.entries(data.sources)){
    source.approved_content_sha256='a'.repeat(64);
    data.checks[id]={url:source.url,normalization:source.normalization,status:'unchanged',
      source_status:'ok',content_sha256:'a'.repeat(64),data_retrieved_at:new Date(now).toISOString()};
  }
  return data;
}

test('Mendocino 2026 seasons and regional limits stay distinct from Northern and San Francisco',()=>{
  const previous=getRegion();
  try{
    setRegion(region);
    const data=matchedFixture();
    assert.ok(validRegulations(data));
    assert.equal(regulationState(data,'reef',now,'2026-09-24').status,'open');
    assert.match(data.species.rockfish.details[0],/2 vermilion\/sunset/);
    assert.equal(regulationState(data,'salmon',now,'2026-09-24').status,'closed');
    assert.equal(regulationState(data,'dungeness',now,'2026-09-24').status,'closed');
    assert.equal(regulationState(data,'dungeness',now,'2026-11-08').status,'scheduled');
    assert.equal(regulationState(data,'pacific-halibut',now,'2026-11-16').status,'closed');
    assert.equal(regulationState(data,'halibut',now,'2026-09-24').status,'open');
    assert.match(data.species.halibut.details.join(' '),/south of Point Arena/);
    data.checks['rules-mendocino'].status='changed';
    assert.equal(regulationState(data,'reef',now,'2026-09-24').status,'unknown');
  }finally{setRegion(previous);}
});

test('loss of Mendocino legal approval withholds an opening',()=>{
  const previous=getRegion();
  try{
    setRegion(region);
    const unreviewed=structuredClone(reviewed);
    unreviewed.rules_review_status='content-needs-review';
    assert.equal(regulationState(unreviewed,'reef',now,'2026-09-24').status,'unknown');
  }finally{setRegion(previous);}
});
