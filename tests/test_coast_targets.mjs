import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {sharedTargetOptions,nativeOnlyTarget} from '../dist/coast-targets.js';
import {regulationState} from '../web/regs.ts';
const read=id=>JSON.parse(readFileSync(`dist/regions/${id}/region.json`,'utf8'));
const central=read('morro-bay');
test('shared targets preserve every chart option and original native species without duplicates',()=>{
 const options=sharedTargetOptions(central),ids=options.map(t=>t.id);
 for(const original of central.target_options)assert.deepEqual(options.find(t=>t.id===original.id),original);
 for(const id of ['lingcod','rockfish-reef','gopher-rockfish','cabezon-shallow-reef','surfperch'])assert.ok(ids.includes(id));
 assert.equal(new Set(ids).size,ids.length);
 for(const id of ['gopher-rockfish','cabezon-shallow-reef','surfperch'])assert.ok(nativeOnlyTarget(id));
 assert.ok(!nativeOnlyTarget('lingcod'));assert.ok(!nativeOnlyTarget('__proto__'));
});
test('reviewed geography adds no coast targets outside terrain regions',()=>{
 const south=read('southern-california');assert.deepEqual(sharedTargetOptions(south),south.target_options);
});
test('native-only targets cannot inherit generic legal limits',()=>{
 const rules=JSON.parse(readFileSync('dist/'+central.assets.regulations,'utf8'));
 for(const id of ['rockfish-reef','gopher-rockfish','cabezon-shallow-reef','surfperch'])
  assert.equal(regulationState(rules,id,central,Date.parse(rules.reviewed_at)).status,'unknown');
});
