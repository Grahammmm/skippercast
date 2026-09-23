import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {sectorAt,sectorsForCoast} from '../dist/coastal-sectors.js';

const packet=JSON.parse(fs.readFileSync(new URL('../dist/data/coastal-sectors.json',import.meta.url)));
test('statewide discovery sectors are complete and cannot be mistaken for mapped grounds',()=>{
  assert.equal(packet.sectors.length,19);
  assert.equal(sectorsForCoast(packet,'northern').length,3);
  assert.equal(packet.sectors.every(s=>s.status==='discovery'),true);
  const north=sectorAt(packet,'northern',{latitude:41.5,longitude:-124.5});
  assert.equal(north.id,'crescent-city-humboldt');
  assert.equal(sectorAt(packet,'northern',{latitude:40.95,longitude:-124.5}).id,'crescent-city-humboldt');
  assert.equal(sectorAt(packet,'northern',{latitude:41.5,longitude:-126}),null);
  assert.equal(sectorAt(packet,'northern',{latitude:NaN,longitude:-124.5}),null);
});
