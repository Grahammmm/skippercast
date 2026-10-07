import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {HOUR,directionTo} from '../dist/marine-units.js';
const root=new URL('..',import.meta.url).pathname;
test('eager confidence import cannot capture Morro forecast points before a different region is selected',()=>{
 const child=spawnSync(process.execPath,['--input-type=module','-e',`
  import assert from 'node:assert/strict';
  import {readFileSync} from 'node:fs';
  await import('./web/confidence.ts');
  const {setRegion}=await import('./dist/region.js');
  const region=JSON.parse(readFileSync('regions/monterey-point-sur/region.json','utf8'));setRegion(region);
  const {POINTS,POINT_SIGNATURE,modelURL,MODELS}=await import('./dist/marine-data.js');
  assert.deepEqual(POINTS,region.forecast_points);
  assert.equal(POINT_SIGNATURE,JSON.stringify(region.forecast_points.map(p=>[p.id,p.latitude,p.longitude])));
  for(const model of MODELS){const url=new URL(modelURL(model),'https://s.test');assert.equal(url.searchParams.get('latitude'),region.forecast_points.map(p=>p.latitude).join(','));assert.equal(url.searchParams.get('longitude'),region.forecast_points.map(p=>p.longitude).join(','));}
 `],{cwd:root,encoding:'utf8'});assert.equal(child.status,0,child.stderr);
});
test('pure unit extraction retains exact direction and hour behavior',()=>{
 assert.equal(HOUR,3600);for(const value of [0,90,180,270,360,-30,999])assert.equal(directionTo(value),(value+180)%360);for(const value of [null,undefined,NaN,Infinity,'90'])assert.equal(directionTo(value),null);
});
test('all authored eager index entry static imports exclude regional marine-data',()=>{
 const html=readFileSync(resolve(root,'dist/index.html'),'utf8');
 const entries=[...html.matchAll(/<script\b[^>]*type="module"[^>]*src="([^"]+)"/g)].map(match=>resolve(root,'dist',match[1]));
 assert.ok(entries.length>=5);
 const visit=(path,chain,seen)=>{if(seen.has(path))return;seen.add(path);assert.notEqual(path,resolve(root,'dist/marine-data.js'),chain.join(' → '));const source=readFileSync(path,'utf8');
  for(const match of source.matchAll(/^\s*import\s+(?!type\b)(?:[^;]*?\sfrom\s*)?["']([^"']+)["']/gm)){const id=match[1];if(!id.startsWith('.')||id.includes('?')||! /\.(?:js|ts|tsx)$/.test(id))continue;const next=resolve(dirname(path),id);visit(next,[...chain,id],seen);}
 };
 for(const entry of entries)visit(entry,[entry],new Set());
});
