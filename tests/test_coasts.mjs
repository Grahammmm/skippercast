import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {coastAt,coastURL,coastForPackage,ensoCurrent,sourceFresh,seasonalMarkup,coastalTargetOptions,localTargetAdvisory} from '../dist/coasts.js';
import {chartLayers} from '../dist/chart-map.js';
const catalog=JSON.parse(fs.readFileSync(new URL('../dist/data/coasts.json',import.meta.url)));
const at=(lat,lon=-123)=>coastAt({latitude:lat,longitude:lon},catalog)?.id;
test('five ocean latitude bands meet without gaps or double membership',()=>{
  assert.equal(at(42,-124.3),'northern');assert.equal(at(40+10/60,-124),'northern');assert.equal(at(40+10/60-.00001,-124),'mendocino');
  assert.equal(at(38+57.5/60,-123.8),'mendocino');assert.equal(at(38+57.5/60-.00001,-123.8),'san-francisco');
  assert.equal(at(37+11/60),'san-francisco');assert.equal(at(37+11/60-.00001),'central');
  assert.equal(at(34+27/60,-120.4),'central');assert.equal(at(34+27/60-.00001,-120.4),'southern');
  assert.equal(at(43),undefined);assert.equal(at(35,-80),undefined);
});
test('southern choices promote local fish without falsely denying lingcod biology',()=>{
  const southern=catalog.regions.find(r=>r.id==='southern');
  assert.equal(southern.targets[0],'kelp-bass');assert.ok(southern.targets.includes('lobster'));
  assert.ok(!southern.targets.includes('dungeness'));assert.ok(!southern.targets.includes('salmon'));
  const reef=southern.target_options.find(t=>t.id==='reef');assert.equal(reef.name,'Rockfish');assert.ok(reef.source_species.includes('lingcod'));
  const north=catalog.regions.find(r=>r.id==='northern');assert.ok(north.targets.includes('pacific-halibut'));assert.ok(!north.targets.includes('lobster'));
});
test('region changes clear stale point, viewport and incompatible target state',()=>{
  const old='https://skippercast.com/?region=morro-bay&coast=central&view=35,-121,10&spot=MB26-001&focus=old&target=dungeness#spot';
  const southern=catalog.regions.find(r=>r.id==='southern');
  const next=coastURL(old,southern,{target:'dungeness'});
  assert.equal(next.search,'?region=southern-california');assert.equal(next.hash,'#map');
  const overview=coastURL(old,catalog.regions[0],{target:'reef'});assert.equal(overview.search,'?coast=northern&target=reef');
  assert.equal(coastForPackage('cambria-san-simeon',catalog).id,'central');
});
test('climate context expires independently of a successful download',()=>{
  const now=Date.parse('2026-09-22T15:00:00Z'),record={status:'ok',data_retrieved_at:'2026-09-22T14:00:00Z',data:{published_date:'2026-09-10'}};
  assert.ok(ensoCurrent(record,catalog,now));assert.ok(!ensoCurrent({...record,data:{published_date:'2026-07-10'}},catalog,now));
  assert.ok(!ensoCurrent({...record,status:'retained'},catalog,now));assert.ok(!sourceFresh({...record,data_retrieved_at:'2026-09-01'},36,now));
  assert.ok(!sourceFresh({...record,data_retrieved_at:'2026-10-01'},36,now));
});
test('no climate advisory becomes a fish-presence claim or a new mapped target',()=>{
  const coast=catalog.regions.find(r=>r.id==='central');const before=coast.targets.slice();
  const html=seasonalMarkup(catalog,coast,{sources:{enso:{status:'ok',data:{status:'El Niño Advisory',published_date:'2026-09-10'}}}});
  assert.ok(html.includes('does not establish fish presence'));assert.deepEqual(coast.targets,before);
  assert.ok(html.includes('Yellowfin'));assert.ok(!coast.targets.includes('yellowfin'));
});
test('a supported seasonal visitor appears only in its own fresh coastal browse list',()=>{
  const coast=catalog.regions.find(r=>r.id==='central'),now=Date.parse('2026-09-22T15:00:00Z');
  const status={completed_at:'2026-09-22T14:00:00Z',regions:{central:{watch:[{target:'yellowfin',status:'recent-located-reports'}]}}};
  assert.ok(coastalTargetOptions(coast,status,now).find(t=>t.id==='yellowfin')?.seasonal);
  assert.ok(!coastalTargetOptions(coast,status,now+40*3600000).some(t=>t.id==='yellowfin'));
  assert.ok(!coastalTargetOptions(catalog.regions[0],status,now).some(t=>t.id==='yellowfin'));
});
test('San Francisco salmon advisory follows the Point Reyes latitude and expires',()=>{
  const coast=catalog.regions.find(r=>r.id==='san-francisco');
  const active=Date.parse('2026-09-23T16:00:00Z');
  assert.match(localTargetAdvisory(coast,'salmon',38.20,active).text,/No opening is established/);
  assert.match(localTargetAdvisory(coast,'salmon',37.98,active).text,/south of CDFW/);
  assert.match(localTargetAdvisory(coast,'salmon',38.20,Date.parse('2026-11-02T00:00:00Z')).text,/has ended/);
  assert.equal(localTargetAdvisory(coast,'reef',38.20,active),null);
});
test('clean chart removes cables, traffic and extra areas; full chart stays optional',()=>{
  assert.equal(chartLayers('fishing'),'0,1,2,6');assert.equal(chartLayers('nautical'),'0,1,2,3,4,5,6,7');
  const html=fs.readFileSync(new URL('../dist/index.html',import.meta.url),'utf8');
  assert.match(html,/id="coast-select"/);assert.ok(!/id="layer-drifts"[^>]*checked/.test(html));
});
