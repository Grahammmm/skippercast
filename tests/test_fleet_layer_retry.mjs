// SC1737-03: a dropped read (throw or timeout, 429, 5xx) of the charter-grounds, commercial AIS or shore file
// is asked again when the layer is turned on again; a 404 or invalid file is remembered and never re-requested.
// Offline: the committed Morro Bay files stand in for the network.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {NOTES, assetLoader, createCharterGrounds, groundsState} from '../web/map/charter-grounds.ts';
import {AIS_NOTES, aisOn, aisState, createCommercialAis} from '../web/map/commercial-ais.ts';
import {assessScreen, CHECKING} from '../web/map/habitat.ts';
import {markData, markScreen} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';
import {createShore, shoreState, shoreURL} from '../web/map/shore.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url);
const json = path => JSON.parse(readFileSync(new URL(path, ROOT), 'utf8'));
const REGION = json('dist/regions/morro-bay/region.json');
const SNAPSHOT = json(`dist/${REGION.assets.protected_areas}`);
const NOW = Date.parse('2026-10-11T00:00:00Z');
const READY = assessScreen({areas: SNAPSHOT.features, checkedAt: new Date(NOW - 3_600_000).toISOString(), live: false, closures: undefined}, NOW);
const sentinel = readPalette(name => `token(${name})`);
const flush = async () => { for (let i = 0; i < 3; i++) await new Promise(resolve => setImmediate(resolve)); };
const engine = () => signal({setOverlay() {}, setData() {}});

/** A fetch that answers from a script: 'throw', 'timeout', a status number, 'invalid', a {then} gate, or (when out) the committed file. */
function scripted(...answers) {
  const asked = [];
  const fetchFn = async url => {
    const path = new URL(url).pathname.slice(1);
    asked.push(path);
    let a = answers.shift();
    if (a && typeof a.then === 'function') a = await a;
    if (a === 'throw') throw new TypeError('Failed to fetch');
    if (a === 'timeout') throw new DOMException('The operation timed out.', 'TimeoutError');
    if (typeof a === 'number') return {ok: false, status: a, json: async () => ({})};
    return {ok: true, status: 200, json: async () => (a === 'invalid' ? {nothing: true} : json(`dist/${path}`))};
  };
  return {asked, fetchFn};
}
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };
const loader = f => assetLoader(f.fetchFn, () => 'https://s.test/map', d => d?.ok === true);
const okBody = f => ({...f, fetchFn: async (url, init) => { const r = await f.fetchFn(url, init); return r.ok ? {...r, json: async () => ({ok: true})} : r; }});

test('assetLoader: a rejected or timed-out read is asked again and then gives the data', async () => {
  for (const drop of ['throw', 'timeout']) {
    const f = okBody(scripted(drop)), load = loader(f);
    assert.equal(await load('a.json'), null, `${drop}: null`);
    assert.deepEqual(await load('a.json'), {ok: true}, `${drop}: asked again`);
    assert.deepEqual(await load('a.json'), {ok: true}, `${drop}: the data is now remembered`);
    assert.equal(f.asked.length, 2);
  }
});

test('assetLoader: 429 and 5xx are retried; 404, other refusals and an invalid file are not', async () => {
  for (const status of [429, 500, 503, 599]) {
    const f = okBody(scripted(status)), load = loader(f);
    assert.equal(await load('a.json'), null);
    assert.deepEqual(await load('a.json'), {ok: true}, `${status} is asked again`);
    assert.equal(f.asked.length, 2, `${status}: one retry`);
  }
  for (const status of [404, 403, 410, 400, 600]) {
    const f = okBody(scripted(status)), load = loader(f);
    assert.equal(await load('a.json'), null);
    assert.equal(await load('a.json'), null, `${status} stays remembered`);
    assert.equal(f.asked.length, 1, `${status}: no second request`);
  }
  const bad = scripted('invalid'), load = loader(bad);
  assert.equal(await load('a.json'), null);
  assert.equal(await load('a.json'), null);
  assert.equal(bad.asked.length, 1, 'a file that fails `valid` is not re-requested');
  const unparsable = {asked: [], fetchFn: async () => { unparsable.asked.push(1); return {ok: true, status: 200, json: async () => { throw new SyntaxError('bad JSON'); }}; }};
  const loadU = loader(unparsable);
  assert.equal(await loadU('a.json'), null);
  assert.equal(await loadU('a.json'), null);
  assert.equal(unparsable.asked.length, 1, 'invalid JSON is not re-requested');
});

test('assetLoader: concurrent calls share one read; a retry that succeeds is kept; paths are separate', async () => {
  const gate = deferred(), f = okBody(scripted(gate.promise.then(() => 503))), load = loader(f);
  const a = load('a.json'), b = load('a.json');
  assert.equal(a, b, 'one in-flight promise');
  gate.resolve();
  assert.equal(await a, null);
  assert.equal(f.asked.length, 1);
  const c = load('a.json'), d = load('a.json'), other = load('b.json');
  assert.equal(c, d, 'the retry is shared too');
  assert.deepEqual(await c, {ok: true});
  assert.deepEqual(await other, {ok: true});
  assert.deepEqual(await load('a.json'), {ok: true});
  assert.deepEqual(f.asked, ['a.json', 'a.json', 'b.json'], 'the newer entry is kept: no third read of a.json');
});

/** Morro Bay with the Fleet entry on. */
function fleetPage(t) {
  globalThis.location = {href: 'https://s.test/map?region=morro-bay&layers=fleet'};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  markScreen.value = READY;
  markData.value = {region: {...REGION, id: 'morro-bay'}, atlas: null, survey: null, geology: null};
  t.after(() => { markData.value = null; markScreen.value = CHECKING; aisOn.value = false; });
}
const fleet = on => syncFromURL(`https://s.test/map?region=morro-bay&layers=${on ? 'fleet' : 'seafloor'}`);

test('grounds: a dropped read says failed; off then on asks once more and draws the grounds', async t => {
  fleetPage(t);
  const f = scripted('throw');
  const grounds = createCharterGrounds({engine: engine(), fetchFn: f.fetchFn, page: () => location.href, palette: () => sentinel});
  t.after(() => grounds.destroy());
  await flush();
  assert.equal(groundsState.value.note, NOTES.failed);
  assert.equal(groundsState.value.drawn, 0);
  fleet(false); await flush();
  fleet(true); await flush();
  assert.deepEqual(f.asked, [REGION.assets.charters, REGION.assets.charters], 'one new read');
  assert.equal(groundsState.value.drawn, 2);
  assert.equal(groundsState.value.note, '');
  fleet(false); await flush();
  fleet(true); await flush();
  assert.equal(f.asked.length, 2, 'drawn grounds are not asked for again');
});

test('grounds: off and on while a dropped read is still out makes no second read', async t => {
  fleetPage(t);
  const gate = deferred(), f = scripted(gate.promise.then(() => 502));
  const grounds = createCharterGrounds({engine: engine(), fetchFn: f.fetchFn, page: () => location.href, palette: () => sentinel});
  t.after(() => grounds.destroy());
  await flush();
  fleet(false); await flush();
  fleet(true); await flush();
  assert.equal(f.asked.length, 1, 'the in-flight read is shared');
  gate.resolve(); await flush();
  assert.equal(groundsState.value.note, NOTES.failed);
  fleet(false); await flush();
  fleet(true); await flush();
  assert.equal(f.asked.length, 2);
  assert.equal(groundsState.value.drawn, 2);
});

test('grounds: after a 404 or an invalid file, off then on makes no request and the note stays', async t => {
  for (const answer of [404, 'invalid']) {
    fleetPage(t);
    const f = scripted(answer);
    const grounds = createCharterGrounds({engine: engine(), fetchFn: f.fetchFn, page: () => location.href, palette: () => sentinel});
    await flush();
    assert.equal(groundsState.value.note, NOTES.failed, `${answer}: failed`);
    fleet(false); await flush();
    fleet(true); await flush();
    assert.equal(f.asked.length, 1, `${answer}: zero new requests`);
    assert.equal(groundsState.value.note, NOTES.failed, `${answer}: note unchanged`);
    grounds.destroy();
  }
});

test('commercial AIS: a 429 says failed; option off then on asks once more and draws the cells; a 404 is not re-asked', async t => {
  fleetPage(t);
  const f = scripted(429);
  const ais = createCommercialAis({engine: engine(), fetchFn: f.fetchFn, page: () => location.href, palette: () => sentinel});
  t.after(() => ais.destroy());
  aisOn.value = true; await flush();
  assert.equal(aisState.value.note, AIS_NOTES.failed);
  aisOn.value = false; await flush();
  aisOn.value = true; await flush();
  assert.deepEqual(f.asked, [REGION.assets.commercial_ais, REGION.assets.commercial_ais]);
  assert.equal(aisState.value.drawn, 3);
  ais.destroy();
  const gone = scripted(404);
  const again = createCommercialAis({engine: engine(), fetchFn: gone.fetchFn, page: () => location.href, palette: () => sentinel});
  t.after(() => again.destroy());
  await flush();
  assert.equal(aisState.value.note, AIS_NOTES.failed);
  fleet(false); await flush();
  fleet(true); await flush();
  assert.equal(gone.asked.length, 1, 'zero new requests after a 404');
  assert.equal(aisState.value.note, AIS_NOTES.failed);
});

test('shore: a 503 draws nothing; leaving Shore and coming back asks once more and draws the runs; a 404 is not re-asked', async t => {
  const page = p => syncFromURL(`https://s.test/map?region=morro-bay&profile=${p}`);
  globalThis.location = {href: 'https://s.test/map?region=morro-bay&profile=shore'};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  markScreen.value = READY;
  t.after(() => { markScreen.value = CHECKING; });
  const make = f => createShore({engine: engine(), fetchFn: f.fetchFn, page: () => location.href, palette: () => sentinel, now: () => NOW, report: signal(null)});
  const f = scripted(503), shore = make(f);
  await flush();
  assert.equal(shoreState.value.drawn, 0);
  page('boat'); await flush();
  page('shore'); await flush();
  assert.deepEqual(f.asked, [shoreURL('morro-bay'), shoreURL('morro-bay')]);
  assert.ok(shoreState.value.drawn > 0, 'the runs are drawn');
  shore.destroy();
  const gone = scripted(404), again = make(gone);
  t.after(() => again.destroy());
  await flush();
  page('boat'); await flush();
  page('shore'); await flush();
  assert.equal(gone.asked.length, 1, 'zero new requests after a 404');
  assert.equal(shoreState.value.drawn, 0);
});
