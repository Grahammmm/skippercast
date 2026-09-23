import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {strategyMarkup} from '../dist/primary-strategy.js';

const catalog=JSON.parse(readFileSync(new URL('../catalog/primary-strategies.json',import.meta.url)));

test('every strategy renders a practical plan and a rig without executable markup',()=>{
  for(const [id,strategy] of Object.entries(catalog.species)) {
    const html=strategyMarkup(strategy);
    assert.match(html,/Look for/);
    assert.match(html,/Rig to bring/);
    assert.match(html,/On the water/);
    assert.match(html,/When to change/);
    assert.ok(!html.includes('undefined'),id);
  }
  const html=strategyMarkup({priority:'<img src=x onerror=alert(1)>',rig:'Test',find:['a'],steps:['b'],adjust:'c'});
  assert.doesNotMatch(html,/<img/);
  assert.match(html,/&lt;img/);
});

test('combined reef target distinguishes lingcod from rockfish',()=>{
  const html=strategyMarkup(catalog.species.reef);
  assert.match(html,/Lingcod/);
  assert.match(html,/Rockfish/);
  assert.match(html,/descending device/);
});
