// Client store (P4-01b). web/state.ts and web/hour.ts load directly (Node type
// stripping). FE-61 deleted the v1 islands these tests also rendered.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {hour, hourParam, needsReload, parseHour, readURL, syncFromURL, withParams} from '../web/state.ts';
import {followForecastHour, indexForHour} from '../web/hour.ts';
import {portChoiceURL} from '../dist/home-port.js';

const ROOT = new URL('..', import.meta.url).pathname;

test('the URL is read and written for the store keys only', () => {
  const href = 'https://skippercast.com/?region=morro-bay&view=35.36000,-120.94000,10&target=halibut&hour=2026-09-30T15:00Z&spot=r12&utm_source=x#forecast';
  assert.deepEqual(readURL(href), {region: 'morro-bay', coast: null, view: '35.36000,-120.94000,10', target: 'halibut', hour: '2026-09-30T15:00Z', selection: 'r12',
    profile: null, day: null, layers: null, area: null, base: null, station: null, metric: null, range: null});
  const next = new URL(withParams(href, {hour: null, target: 'reef', region: undefined}));
  assert.equal(next.searchParams.get('hour'), null);
  assert.equal(next.searchParams.get('target'), 'reef');
  assert.equal(next.searchParams.get('region'), 'morro-bay');
  assert.equal(next.searchParams.get('utm_source'), 'x');
  assert.equal(next.hash, '#forecast');
});

test('a region or coast change reloads only after boot has loaded a region', () => {
  const a = 'https://s.test/?region=morro-bay&view=35,-120,10#map';
  const sameRegion = 'https://s.test/?region=morro-bay&view=35.1,-120.8,10&target=reef#forecast';
  const otherRegion = 'https://s.test/?region=southern-california&view=32.8,-117.4,10#map';
  const coast = 'https://s.test/?coast=central#map';
  assert.equal(needsReload(a, otherRegion, null), false, 'before boot loads a region nothing reloads');
  const lock = {region: 'morro-bay', coast: null};
  assert.equal(needsReload(a, sameRegion, lock), false);
  assert.equal(needsReload(a, otherRegion, lock), true);
  assert.equal(needsReload(a, coast, lock), true);
  assert.equal(needsReload(a, 'https://s.test/sources.html?region=morro-bay', lock), true, 'another page always loads');
});

test('?hour= is a whole UTC hour and maps onto the forecast timeline', () => {
  const t = Date.parse('2026-09-30T15:00:00Z') / 1000;
  assert.equal(hourParam(t + 1799), '2026-09-30T15:00Z');
  assert.equal(parseHour('2026-09-30T15:00Z'), t);
  for (const bad of ['2026-09-30T15:30Z', '2026-09-30', 'tomorrow', '', null]) assert.equal(parseHour(bad), null, String(bad));
  // Selected time t at index 2: the timeline starts two hours earlier.
  assert.equal(indexForHour(t + 3 * 3600, t, 2), 5);
  assert.equal(indexForHour(t - 3 * 3600, t, 2), null, 'before the timeline');
  assert.equal(indexForHour(t + 200 * 3600, t, 2), null, 'after the timeline');
  assert.equal(indexForHour(null, t, 2), null);
});

test('a port in the region already shown keeps the target; another region resets it', () => {
  const href = 'https://s.test/?region=southern-california&view=32.8,-117.4,10&target=yellowtail&hour=2026-09-30T15:00Z#forecast';
  const ventura = {region: 'southern-california', view: [34.2, -119.5, 10]}, morro = {region: 'morro-bay', view: [35.36, -120.94, 10]};
  const same = new URL(portChoiceURL(href, ventura)), other = new URL(portChoiceURL(href, morro));
  assert.equal(same.searchParams.get('target'), 'yellowtail');
  assert.equal(same.searchParams.get('view'), '34.20000,-119.50000,10');
  assert.equal(same.searchParams.get('hour'), '2026-09-30T15:00Z');
  assert.equal(same.hash, '#map');
  assert.equal(other.searchParams.get('target'), null);
  assert.equal(other.searchParams.get('region'), 'morro-bay');
});

test('reload sites go through the store; the in-place ones are the ones that are safe', async () => {
  const read = name => readFile(join(ROOT, 'dist', name), 'utf8');
  for (const name of ['home-port.js', 'coasts.js', 'region.js']) {
    const source = await read(name);
    assert.match(source, /from '\.\.\/web\/state\.ts'/, name);
    assert.doesNotMatch(source, /location\.(?:assign|replace)\(/, `${name} navigates through web/state.ts`);
  }
});

test('the shared clock updates its URL without requiring a forecast bundle',()=>{
 const saved={location:globalThis.location,history:globalThis.history};
 const start=Date.parse('2026-10-06T12:00:00Z')/1000;
 globalThis.location={href:'https://skippercast.com/?region=morro-bay#map'};
 globalThis.history={state:null,replaceState(_state,_title,href){location.href=href;},pushState(_state,_title,href){location.href=href;}};
 const listeners={},input={value:'0',max:'168',dispatchEvent(){}};
 const doc={addEventListener(name,fn){listeners[name]=fn;},getElementById(){return input;}};
 try{syncFromURL();followForecastHour(doc);listeners['skippercast:time']({detail:{epoch:start}});input.value='168';listeners['skippercast:time']({detail:{epoch:start+168*3600}});assert.equal(new URL(location.href).searchParams.get('hour'),'2026-10-13T12:00Z');assert.equal(hour.value,'2026-10-13T12:00Z');}
 finally{Object.assign(globalThis,saved);hour.value=null;}
});
