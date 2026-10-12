import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {tripGPX} from '../dist/gpx.js';
import {regulationState} from '../web/regs.ts';
const read=p=>JSON.parse(readFileSync(new URL(p,import.meta.url)));
const morro=read('../dist/regions/morro-bay/region.json');
const now=Date.parse('2026-09-22T04:00:00Z');

test('trip export deduplicates points and shared geometry',()=>{
  const atlas=read('../dist/data/atlas.json'),ids=atlas.targets.slice(0,3).map(t=>t.id);
  const output=tripGPX(atlas,[...ids,ids[0]]);assert.equal((output.match(/<wpt /g)||[]).length,3);
  const names=[...output.matchAll(/<trk><name>([^<]+)/g)].map(m=>m[1]);assert.equal(new Set(names).size,names.length);
  assert.match(output,/<cmt>SC26-/);assert.doesNotMatch(output,/<rte>/);
});
test('trip-date rules use the selected season while source freshness stays tied to now',()=>{
  const r=read('../dist/data/regulations.json');r.reviewed_at=new Date(now-3600000).toISOString();
  for(const id of Object.keys(r.sources)){r.sources[id].approved_content_sha256='a'.repeat(64);r.checks[id]={url:r.sources[id].url,normalization:r.sources[id].normalization,status:'unchanged',source_status:'ok',content_sha256:'a'.repeat(64),data_retrieved_at:new Date(now-3600000).toISOString()};}
  r.species.dungeness.windows=[{start:'2026-10-01',end:'2026-11-30'}];
  assert.equal(regulationState(r,'dungeness',morro,now,'2026-10-15').status,'open');
  assert.equal(regulationState(r,'dungeness',morro,now,'2026-09-22').status,'closed');
  assert.equal(regulationState(r,'dungeness',morro,now+40*3600000,'2026-10-15').status,'unknown');
});



