import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {getRegion,setRegion,localContext,pointBundle} from '../dist/region.js';
import {regulationState,validRegulations} from '../web/regs.ts';

const region=JSON.parse(readFileSync(new URL('../regions/bodega-point-reyes/region.json',import.meta.url)));
const draft=JSON.parse(readFileSync(new URL('../dist/data/regulations-san-francisco.json',import.meta.url)));
const now=Date.parse('2026-09-24T18:00:00Z');

test('Point Reyes context uses its own marine zones and tide reference',()=>{
  const previous=getRegion();
  try {
    setRegion(region);
    assert.equal(localContext('bodega-nearshore').marine_zones.coastal,'PZZ540');
    assert.equal(localContext('reyes-nearshore').marine_zones.coastal,'PZZ545');
    assert.equal(localContext('reyes-nearshore').marine_zones.offshore,'PZZ571');
    assert.equal(localContext('reyes-nearshore').stations.tide,'9415020');
    const bundle={contexts:{bodega:{tides:[1],alerts:{coastal:['Bodega']}},reyes:{tides:[2],alerts:{coastal:['Reyes']}}}};
    assert.deepEqual(pointBundle(bundle,'reyes-nearshore').tides,[2]);
    assert.deepEqual(pointBundle(bundle,'bodega-nearshore').alerts,{coastal:['Bodega']});
  } finally {setRegion(previous);}
});

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

// FE-61: v1's fishing-location check went with the v1 shell; with no location the salmon band asks for one.
test('San Francisco salmon opening remains spatially limited even with matching source receipts',()=>{
  const data=sourceMatchedFixture();
  assert.ok(validRegulations(data,region));
  assert.equal(regulationState(data,'salmon',region,now).label,'Choose fishing location');
  assert.equal(regulationState(data,'lingcod',region,now).status,'open');
  data.checks['rules-salmon'].status='changed';
  assert.equal(regulationState(data,'salmon',region,now).status,'unknown');
});

test('loss of legal content approval withholds the San Francisco opening',()=>{
  const unreviewed=structuredClone(draft);
  unreviewed.rules_review_status='content-needs-review';
  assert.equal(regulationState(unreviewed,'salmon',region,now).status,'unknown');
  assert.equal(regulationState(unreviewed,'dungeness',region,now).status,'unknown');
});
