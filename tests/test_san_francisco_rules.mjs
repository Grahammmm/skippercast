import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {getRegion,setRegion} from '../dist/region.js?v=8.11';
import {regulationState,validRegulations} from '../dist/regulations.js';

const region=JSON.parse(readFileSync(new URL('../regions/bodega-point-reyes/region.json',import.meta.url)));
const draft=JSON.parse(readFileSync(new URL('../dist/data/regulations-san-francisco.json',import.meta.url)));
const now=Date.parse('2026-09-24T18:00:00Z');
const location=(latitude,geometry)=>({coverage:'covered',regionId:region.id,
  point:{latitude,longitude:-123.1,geometry},protection:{status:'clear'}});

function sourceMatchedFixture() {
  const data=structuredClone(draft);
  data.reviewed_at=new Date(now-3600000).toISOString();
  data.rules_review_status='reviewed';
  for(const [id,source] of Object.entries(data.sources)) {
    source.approved_content_sha256='a'.repeat(64);
    data.checks[id]={url:source.url,normalization:source.normalization,status:'unchanged',
      source_status:'ok',content_sha256:'a'.repeat(64),data_retrieved_at:new Date(now).toISOString()};
  }
  return data;
}

test('San Francisco salmon opening remains spatially limited even with matching source receipts',()=>{
  const previous=getRegion();
  try {
    setRegion(region);
    const data=sourceMatchedFixture();
    assert.ok(validRegulations(data));
    assert.equal(regulationState(data,'salmon',now).status,'unknown');
    assert.equal(regulationState(data,'salmon',now,null,'rod',null,location(38.15)).status,'closed');
    assert.equal(regulationState(data,'salmon',now,null,'rod',null,location(38.01)).status,'open');
    const crossing={type:'Polygon',coordinates:[[[-123.2,38.02],[-123.0,38.02],[-123.0,38.05],[-123.2,38.05],[-123.2,38.02]]]};
    assert.equal(regulationState(data,'salmon',now,null,'rod',null,location(38.02,crossing)).status,'unknown');
    assert.equal(regulationState(data,'salmon',now,null,'rod',null,location(38.02,{type:'Polygon',coordinates:[]})).status,'unknown');
    data.checks['rules-salmon'].status='changed';
    assert.equal(regulationState(data,'salmon',now,null,'rod',null,location(38.01)).status,'unknown');
    assert.equal(regulationState(data,'lingcod',now,null,'rod',null,location(38.15)).status,'open');
  } finally {setRegion(previous);}
});

test('loss of legal content approval withholds the San Francisco opening',()=>{
  const previous=getRegion();
  try {
    setRegion(region);
    const unreviewed=structuredClone(draft);
    unreviewed.rules_review_status='content-needs-review';
    assert.equal(regulationState(unreviewed,'salmon',now,null,'rod',null,location(38.01)).status,'unknown');
    assert.equal(regulationState(unreviewed,'dungeness',now,null,'trap',null,location(38.15)).status,'unknown');
  } finally {setRegion(previous);}
});
