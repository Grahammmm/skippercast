import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {sectorAt,sectorsForCoast,trustedNoaaLink} from '../dist/coastal-sectors.js';

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
test('survey source links require official HTTPS host and matching survey identity',()=>{
  assert.equal(trustedNoaaLink('https://www.ngdc.noaa.gov/nos/H10001-H12000/H11983.html','H11983','catalog'),true);
  assert.equal(trustedNoaaLink('https://data.ngdc.noaa.gov/nos/H11983/BAG/grid.bag','H11983'),true);
  assert.equal(trustedNoaaLink('javascript:alert(1)','H11983'),false);
  assert.equal(trustedNoaaLink('https://www.ngdc.noaa.gov.evil.example/H11983/BAG/grid.bag','H11983'),false);
  assert.equal(trustedNoaaLink('https://data.ngdc.noaa.gov/nos/H11111/BAG/grid.bag','H11983'),false);
});
