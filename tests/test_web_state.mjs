// Client store and Preact islands (P4-01b). web/state.ts and web/hour.ts load
// directly (Node type stripping); the .tsx components are bundled with esbuild
// and rendered to strings to pin their markup to the page they replaced.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {hour, hourParam, needsReload, parseHour, readURL, syncFromURL, withParams} from '../web/state.ts';
import {followForecastHour, indexForHour} from '../web/hour.ts';
import {portChoiceURL} from '../dist/home-port.js';
import {parseView, viewParam} from '../dist/location-context.js';

const ROOT = new URL('..', import.meta.url).pathname;

test('the URL is read and written for the store keys only', () => {
  const href = 'https://skippercast.com/?region=morro-bay&view=35.36000,-120.94000,10&target=halibut&hour=2026-09-30T15:00Z&spot=r12&utm_source=x#forecast';
  assert.deepEqual(readURL(href), {region: 'morro-bay', coast: null, view: '35.36000,-120.94000,10', target: 'halibut', hour: '2026-09-30T15:00Z', selection: 'r12',
    profile: null, day: null, layers: null, area: null, base: null});
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

test('map view values round-trip through the store', () => {
  const v = parseView('35.36000,-120.94000,10');
  assert.deepEqual(v, {latitude: 35.36, longitude: -120.94, zoom: 10});
  assert.equal(viewParam(v, v.zoom), '35.36000,-120.94000,10');
  assert.equal(parseView('35.36,-120.94,3'), null, 'zoom out of range');
  assert.equal(parseView(null), null);
});

test('reload sites go through the store; the in-place ones are the ones that are safe', async () => {
  const read = name => readFile(join(ROOT, 'dist', name), 'utf8');
  for (const name of ['home-port.js', 'coasts.js', 'region.js', 'export-ui.js', 'location-context.js']) {
    const source = await read(name);
    assert.match(source, /from '\.\.\/web\/state\.ts'/, name);
    assert.doesNotMatch(source, /location\.(?:assign|replace)\(/, `${name} navigates through web/state.ts`);
  }
  const boot = await read('boot.js');
  assert.ok(boot.indexOf('lockRegion()') < boot.indexOf('initRegion()'), 'the region is locked before region-bound modules load');
  assert.ok(boot.indexOf('startURLSync()') < boot.indexOf('initHomePort'), 'the store reads the URL before the port step');
});

async function components() {
  const dir = await mkdtemp(join(tmpdir(), 'islands-'));
  const out = join(dir, 'islands.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MeteogramCard, METEOGRAM_LEGEND} from './web/components/MeteogramCard.tsx';
      export {OutlookBadge} from './web/components/OutlookBadge.tsx';
      export {FreshnessBanner} from './web/components/FreshnessBanner.tsx';
      export {outlook, INITIAL_OUTLOOK} from './web/views.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent',
    jsx: 'automatic', jsxImportSource: 'preact',
  });
  return import(pathToFileURL(out).href);
}

test('the meteogram card renders the markup index.html used to carry', async () => {
  const {MeteogramCard, render, h} = await components();
  const legend = [['lg-wind', 'Wind kt'], ['lg-gust', 'Gust'], ['lg-sea', 'Seas ft'], ['lg-tide', 'Tide ft'], ['lg-go', 'Score 7+'], ['lg-caution', '4–6.9'],
    ['lg-rough', 'Under 4 or hazard'], ['lg-unknown', 'No score'], ['lg-differ', 'Models differ'], ['lg-hatch', 'Outlook after 72 h']];
  assert.equal(render(h(MeteogramCard)),
    '<summary>Next 7 days <small>Tap or drag to pick an hour</small></summary><div id="meteogram"><p class="meteogram-loading">Loading forecast graph…</p></div>'
    + `<ul class="meteogram-legend">${legend.map(([c, l]) => `<li><i class="${c}"></i>${l}</li>`).join('')}</ul>`);
  const html = await readFile(join(ROOT, 'dist/index.html'), 'utf8');
  assert.match(html, /<details id="meteogram-card" class="meteogram-card" open><\/details>/, 'the slot is empty; the component fills it');
  assert.ok(html.indexOf('src="../web/islands.tsx"') < html.indexOf('src="meteogram-ui.js"'), 'the card renders before meteogram-ui.js looks for #meteogram');
});

test('the outlook badge renders the header label and value, escaped', async () => {
  const {OutlookBadge, INITIAL_OUTLOOK, render, h} = await components();
  assert.equal(render(h(OutlookBadge, {value: INITIAL_OUTLOOK})), '<span>7-day outlook</span><strong>Checking…</strong>');
  assert.equal(render(h(OutlookBadge, {value: {label: 'Tentative conditions', value: 'Thu · 6.9/10'}})), '<span>Tentative conditions</span><strong>Thu · 6.9/10</strong>');
  assert.equal(render(h(OutlookBadge, {value: {label: '<b>', value: 'x'}})), '<span>&lt;b></span><strong>x</strong>');
  const html = await readFile(join(ROOT, 'dist/index.html'), 'utf8');
  assert.match(html, /id="best-day-banner"[\s\S]*?<span>7-day outlook<\/span><strong>Checking…<\/strong>/, 'static fallback matches the initial render');
});

test('the freshness banner says how old saved data is and offers a reload once back online', async () => {
  const {FreshnessBanner, render, h} = await components();
  const now = Date.parse('2026-09-29T12:00:00Z');
  const offline = render(h(FreshnessBanner, {status: {online: false, savedAt: '2026-09-29T10:00:00Z', now}}));
  assert.equal(offline, '<span>Offline — showing data saved 2 h ago</span><a href="#guide" data-offline-guide>Saved regions</a><button type="button" data-offline-reload hidden>Reload</button>');
  const back = render(h(FreshnessBanner, {status: {online: true, savedAt: '2026-09-29T11:00:00Z', now}}));
  assert.match(back, /<span>Connection problem — showing data saved 1 h ago<\/span>/);
  assert.match(back, /<button type="button" data-offline-reload>Reload<\/button>/);
  assert.match(render(h(FreshnessBanner, {status: {online: true, savedAt: null, now}})), /^<span><\/span>/);
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
