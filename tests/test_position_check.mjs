// SC-GPSOFFLINE-1 (t_a0686aad): the angler's live position against the protected areas, on this device, with no signal.
// Real committed boundary data (dist/data/protected-areas.geojson, Point Buchon SMR) through the real planner screen
// (dist/protected-areas.js) and the planner's own verdict (dist/geo-screen.js screenPlace). The browser Geolocation API is a stand-in that
// counts its calls; the network, the page's storage and every other way out are recorded so a test can fail if a coordinate leaves the device.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {PLANNING_MARGIN_M, pointGeometry, pointInGeometry, screenPlace} from '../dist/geo-screen.js';
import {assetURL} from '../dist/region.js';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {LOW_ACCURACY_M, POSITION_OPTIONS, checkPosition, packState, readPosition, readingFor} from '../web/position-check.ts';
import {STRINGS} from '../web/i18n.ts';

const mpas = JSON.parse(readFileSync(new URL('../dist/data/protected-areas.geojson', import.meta.url), 'utf8'));
const buchon = mpas.features.find(f => f.properties.NAME === 'Point Buchon SMR');
const ring = buchon.geometry.type === 'Polygon' ? buchon.geometry.coordinates[0] : buchon.geometry.coordinates[0][0];
const vertex = ring[Math.floor(ring.length / 3)];
const mLat = 1 / 111320, mLon = 1 / (111320 * Math.cos(vertex[1] * Math.PI / 180));
const at = (metres, bearing) => ({longitude: vertex[0] + Math.sin(bearing) * metres * mLon, latitude: vertex[1] + Math.cos(bearing) * metres * mLat});
const BEARINGS = Array.from({length: 16}, (_, i) => i * Math.PI / 8);
// Boundary data as the screen holds it, to measure the fixtures with the planner's own verdict.
const MEASURE = {status: 'ready', boundaries: mpas.features.map(f => ({name: f.properties.FULLNAME || f.properties.NAME, geometry: f.geometry})), coversGeometry: () => true};
const verdictAt = p => screenPlace(MEASURE, p);
/** A point whose own verdict has the wanted outcome, found by walking `metres` from a vertex of the reserve in every direction. */
function find(metres, ok) { for (const b of BEARINGS) { const p = at(metres, b), v = verdictAt(p); if (ok(v)) return {...p, v}; } throw new Error(`no fixture at ${metres} m`); }
const INSIDE = find(0, v => v.inside), insidePoint = (() => { // a point well inside the reserve: the vertex pulled toward the ring's mean
  const cx = ring.reduce((s, p) => s + p[0], 0) / ring.length, cy = ring.reduce((s, p) => s + p[1], 0) / ring.length;
  for (const k of [0.5, 0.3, 0.7, 0.9]) { const p = {longitude: vertex[0] + (cx - vertex[0]) * k, latitude: vertex[1] + (cy - vertex[1]) * k}; if (pointInGeometry([p.longitude, p.latitude], buchon.geometry)) return p; }
  return {longitude: INSIDE.longitude, latitude: INSIDE.latitude};
})();
const NEAR = find(40, v => !v.inside && v.distanceM > 0 && v.distanceM <= 60);
const NEAR_BY_ACCURACY = find(120, v => !v.inside && v.distanceM > 100 && v.distanceM <= 140);
const OUTSIDE = find(3000, v => !v.inside && v.distanceM > 1500);
const OFF_MAP = {latitude: 36.8, longitude: -123.5}; // west and north of this region's boundary envelope: not covered

const NOW = Date.now(), FRESH = new Date(NOW - 3600000).toISOString(), OLD = new Date(NOW - 5 * 86400000).toISOString();
const fixOf = (p, accuracyM = 8) => ({latitude: p.latitude, longitude: p.longitude, accuracyM});

/** The Geolocation API stand-in: one scripted answer, and a record of how it was used. `watchPosition` must never be touched. */
function geolocation(answer) {
  const calls = {current: [], watch: 0};
  return {calls, getCurrentPosition(ok, fail, options) {
    calls.current.push(options);
    queueMicrotask(() => answer.error ? fail({code: answer.error}) : ok({coords: {latitude: answer.latitude, longitude: answer.longitude, accuracy: answer.accuracy}}));
  }, watchPosition() { calls.watch++; throw new Error('watchPosition: the page must never track'); }, clearWatch() {}};
}
const fixAnswer = (p, accuracy = 8) => ({latitude: p.latitude, longitude: p.longitude, accuracy});

/** Every way a page can send something out, recorded; and the page's storage, which must stay untouched. */
function sandbox({online = true, checkedAt = FRESH} = {}) {
  const saved = {};
  const names = ['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'Image', 'document', 'localStorage', 'sessionStorage', 'indexedDB', 'caches', 'navigator'];
  for (const n of names) saved[n] = Object.getOwnPropertyDescriptor(globalThis, n);
  const sent = [], stored = [];
  const out = (kind, ...a) => { sent.push({kind, text: a.map(x => typeof x === 'string' ? x : x instanceof URL ? x.href : JSON.stringify(x ?? null)).join(' ')}); };
  const set = (name, value) => Object.defineProperty(globalThis, name, {value, configurable: true, writable: true});
  // The legal pack's saved boundary file, as the service worker answers it from the cache; every other address needs a connection.
  set('fetch', async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input?.url ?? String(input);
    out('fetch', url, init?.method ?? 'GET', init?.body ?? '', init?.headers ?? {});
    if (url === assetURL('protected_areas')) return new Response(JSON.stringify({...mpas, checked_at: checkedAt}), {headers: {'content-type': 'application/json'}});
    if (online && url.startsWith('https://services2.arcgis.com/')) return new Response(JSON.stringify(mpas), {headers: {'content-type': 'application/json'}});
    throw new TypeError('Failed to fetch');
  });
  const closed = kind => class { constructor(...a) { out(kind, ...a); throw new Error(`${kind} is not allowed here`); } };
  set('XMLHttpRequest', closed('XMLHttpRequest')); set('WebSocket', closed('WebSocket')); set('EventSource', closed('EventSource')); set('Image', closed('Image'));
  const box = name => ({getItem: () => null, setItem: (...a) => { stored.push([name, ...a]); }, removeItem() {}, clear() {}, key: () => null, length: 0});
  set('localStorage', box('localStorage')); set('sessionStorage', box('sessionStorage'));
  set('indexedDB', {open: (...a) => { stored.push(['indexedDB', ...a]); throw new Error('no indexedDB'); }});
  set('caches', {open: async (...a) => { stored.push(['caches', ...a]); throw new Error('no caches'); }, match: async () => undefined});
  set('document', {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), createElement: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {},
    get cookie() { return ''; }, set cookie(v) { stored.push(['cookie', v]); }});
  set('navigator', {onLine: online, sendBeacon: (...a) => { out('sendBeacon', ...a); return false; }});
  return {sent, stored, restore() { for (const n of names) { if (saved[n]) Object.defineProperty(globalThis, n, saved[n]); else delete globalThis[n]; } }};
}

/** The planner's own loader (web/trip.ts loadProtectedScreen): the real screen over a read through fetch, its live refresh started and not awaited. */
const loadScreen = () => initProtectedAreas(null, () => {}, async path => { const r = await fetch(path); if (!r.ok) throw new Error('read failed'); return r.json(); })
  .then(screen => { void screen.refresh(); return screen; });
const settle = () => new Promise(resolve => setTimeout(resolve, 25));

/** Fails when any recorded request carries the position: the number whole, to three decimals, or percent-encoded, in the address, headers or body. */
function assertNoCoordinates(sent, ...places) {
  const forms = new Set();
  for (const p of places) for (const n of [p.latitude, p.longitude]) { const a = Math.abs(n); forms.add(String(a)); forms.add(a.toFixed(6)); forms.add(a.toFixed(5)); forms.add(a.toFixed(4)); forms.add(a.toFixed(3)); forms.add(String(Math.trunc(a * 1000) / 1000)); }
  for (const r of sent) {
    const text = (() => { try { return decodeURIComponent(r.text); } catch { return r.text; } })();
    for (const f of forms) assert.ok(!text.includes(f) && !r.text.includes(f), `${r.kind} request carries a coordinate (${f}): ${r.text.slice(0, 120)}`);
  }
}

test('inside: the planner screen says so, by name, at 0 m', async () => {
  const box = sandbox();
  try {
    const answer = await checkPosition(loadScreen, geolocation(fixAnswer(insidePoint)));
    assert.equal(answer.located.ok, true);
    assert.equal(answer.reading.kind, 'checked');
    assert.equal(answer.reading.where, 'inside');
    assert.match(answer.reading.name, /Point Buchon/);
    assert.equal(answer.reading.distanceM, 0);
  } finally { box.restore(); }
});

test('the verdict is the planner screen\'s own: same name and distance as screenPlace over the same boundaries', async () => {
  const box = sandbox();
  try {
    for (const p of [NEAR, NEAR_BY_ACCURACY, OUTSIDE]) {
      const {reading} = await checkPosition(loadScreen, geolocation(fixAnswer(p, 5)));
      const direct = verdictAt(p);
      assert.equal(reading.name, direct.name);
      assert.equal(reading.distanceM, direct.distanceM);
    }
  } finally { box.restore(); }
});

test('near: within the planning margin, and the reported accuracy widens the margin', async () => {
  const box = sandbox();
  try {
    assert.ok(NEAR.v.distanceM <= PLANNING_MARGIN_M);
    const near = (await checkPosition(loadScreen, geolocation(fixAnswer(NEAR, 5)))).reading;
    assert.equal(near.where, 'near');
    assert.equal(near.lowAccuracy, false);
    // 100–140 m from a boundary is past the 70 m margin, but ±80 m of accuracy could put the boat across the line.
    assert.ok(NEAR_BY_ACCURACY.v.distanceM > PLANNING_MARGIN_M);
    assert.equal((await checkPosition(loadScreen, geolocation(fixAnswer(NEAR_BY_ACCURACY, 80)))).reading.where, 'near');
    assert.equal((await checkPosition(loadScreen, geolocation(fixAnswer(NEAR_BY_ACCURACY, 5)))).reading.where, 'outside');
  } finally { box.restore(); }
});

test('outside: names the nearest closure and its distance', async () => {
  const box = sandbox();
  try {
    const {reading} = await checkPosition(loadScreen, geolocation(fixAnswer(OUTSIDE)));
    assert.equal(reading.where, 'outside');
    assert.ok(reading.name);
    assert.ok(reading.distanceM > 1500);
  } finally { box.restore(); }
});

test('low accuracy (or none reported) is flagged and the accuracy is kept for display', async () => {
  const box = sandbox();
  try {
    for (const accuracy of [LOW_ACCURACY_M + 1, 250, undefined, NaN]) {
      const {reading} = await checkPosition(loadScreen, geolocation({...fixAnswer(OUTSIDE), accuracy}));
      assert.equal(reading.lowAccuracy, true, String(accuracy));
      assert.equal(reading.fix.accuracyM, Number.isFinite(accuracy) ? accuracy : null);
    }
    assert.equal((await checkPosition(loadScreen, geolocation(fixAnswer(OUTSIDE, LOW_ACCURACY_M)))).reading.lowAccuracy, false);
  } finally { box.restore(); }
});

test('permission denied, no fix, bad data and no API are each said plainly and nothing is judged clear', async () => {
  const box = sandbox();
  try {
    assert.deepEqual((await checkPosition(loadScreen, geolocation({error: 1}))).located, {ok: false, reason: 'denied'});
    assert.deepEqual((await checkPosition(loadScreen, geolocation({error: 2}))).located, {ok: false, reason: 'unavailable'});
    assert.deepEqual((await checkPosition(loadScreen, geolocation({error: 3}))).located, {ok: false, reason: 'unavailable'});
    assert.deepEqual((await checkPosition(loadScreen, geolocation({latitude: NaN, longitude: 1, accuracy: 5}))).located, {ok: false, reason: 'unavailable'});
    assert.deepEqual((await checkPosition(loadScreen, geolocation({latitude: 95, longitude: 1, accuracy: 5}))).located, {ok: false, reason: 'unavailable'});
    assert.deepEqual((await checkPosition(loadScreen, null)).located, {ok: false, reason: 'unsupported'});
    const denied = await checkPosition(loadScreen, geolocation({error: 1}));
    assert.ok(!('reading' in denied), 'a refused position is never screened');
  } finally { box.restore(); }
});

test('no boundary data: not checked, never clear; and a position outside the boundary file\'s area is not checked either', async () => {
  const box = sandbox();
  try {
    const failed = await checkPosition(async () => { throw new Error('no boundaries'); }, geolocation(fixAnswer(OUTSIDE)));
    assert.equal(failed.reading.kind, 'no-boundaries');
    assert.equal((await checkPosition(async () => null, geolocation(fixAnswer(OUTSIDE)))).reading.kind, 'no-boundaries');
    assert.equal((await checkPosition(async () => ({}), geolocation(fixAnswer(OUTSIDE)))).reading.kind, 'no-boundaries');
    assert.equal(readingFor(fixOf(OUTSIDE), {heldBoundaries: () => ({current: true, checked_at: FRESH, features: []})}).kind, 'no-boundaries');
    assert.equal((await checkPosition(loadScreen, geolocation(fixAnswer(OFF_MAP)))).reading.kind, 'not-covered');
  } finally { box.restore(); }
});

test('no pack: the saved-pack state is read from the legal inventory, and unreadable is not claimed either way', () => {
  const pack = (complete, areas = true) => [{meta: {region_id: 'morro-bay', legal: {complete, items: [{id: 'rules', saved: true}, {id: 'areas', saved: areas}]}}}];
  assert.equal(packState(pack(true), 'morro-bay'), 'saved');
  assert.equal(packState(pack(false), 'morro-bay'), 'partial');
  assert.equal(packState(pack(false, false), 'morro-bay'), 'none');
  assert.equal(packState([], 'morro-bay'), 'none');
  assert.equal(packState([{meta: {region_id: 'elsewhere', legal: {complete: true, items: [{id: 'areas', saved: true}]}}}], 'morro-bay'), 'none');
  assert.equal(packState([{meta: {region_id: 'morro-bay'}}], 'morro-bay'), 'none');
  assert.equal(packState(null, 'morro-bay'), 'unknown');
  assert.equal(packState(pack(true), null), 'unknown');
});

test('offline: with no connection the saved boundary file answers, the verdict is still given, and a week-old save is labelled stale', async () => {
  const box = sandbox({online: false, checkedAt: OLD});
  try {
    const inside = await checkPosition(loadScreen, geolocation(fixAnswer(insidePoint)));
    await settle();
    assert.equal(inside.reading.where, 'inside');
    assert.equal(inside.reading.stale, true);
    assert.equal(inside.reading.checkedAt, new Date(OLD).toISOString());
    assert.equal((await checkPosition(loadScreen, geolocation(fixAnswer(OUTSIDE)))).reading.where, 'outside');
    // Every address but the saved file failed, and the check did not care.
    assert.ok(box.sent.some(r => r.kind === 'fetch' && r.text.startsWith(assetURL('protected_areas'))));
  } finally { box.restore(); }
  const fresh = sandbox({online: false, checkedAt: FRESH});
  try {
    const reading = (await checkPosition(loadScreen, geolocation(fixAnswer(NEAR)))).reading;
    assert.equal(reading.where, 'near');
    assert.equal(reading.stale, false);
  } finally { fresh.restore(); }
});

test('the position never leaves the device: no request, beacon, socket or storage write carries it (online and offline)', async () => {
  for (const online of [true, false]) {
    for (const [name, point] of [['inside', insidePoint], ['near', NEAR], ['outside', OUTSIDE], ['off-map', OFF_MAP]]) {
      const box = sandbox({online});
      try {
        const geo = geolocation(fixAnswer(point));
        await checkPosition(loadScreen, geo);
        await checkPosition(loadScreen, geo);
        await settle();
        assert.ok(box.sent.length > 0, 'the stand-in saw the boundary reads');
        assertNoCoordinates(box.sent, point);
        assert.deepEqual(box.stored, [], `${name}: nothing written to storage, cookies or caches`);
        assert.equal(geo.calls.watch, 0, 'no tracking');
        assert.equal(geo.calls.current.length, 2, 'one read per check, never a loop');
      } finally { box.restore(); }
    }
  }
});

test('the coordinate guard itself fails when a request carries the position', () => {
  const p = {latitude: 35.263412, longitude: -121.116788};
  assert.throws(() => assertNoCoordinates([{kind: 'fetch', text: 'https://x.test/api?lat=35.263412&lon=-121.116788'}], p), /carries a coordinate/);
  assert.throws(() => assertNoCoordinates([{kind: 'fetch', text: 'https://x.test/api?ll=35.263%2C-121.116'}], p), /carries a coordinate/);
  assert.throws(() => assertNoCoordinates([{kind: 'sendBeacon', text: 'https://x.test/b {"at":[-121.116788,35.263412]}'}], p), /carries a coordinate/);
  assert.throws(() => assertNoCoordinates([{kind: 'fetch', text: 'https://x.test/a POST {"latitude":35.2634}'}], p), /carries a coordinate/);
  assert.doesNotThrow(() => assertNoCoordinates([{kind: 'fetch', text: 'https://services2.arcgis.com/q?geometry=-121.9,34.95,-120.55,35.85'}], p));
});

test('one fresh read per tap with the Geolocation API only: high accuracy, no cached fix, a time limit, no watching', async () => {
  const geo = geolocation(fixAnswer(OUTSIDE));
  await readPosition(geo);
  assert.deepEqual(geo.calls.current, [POSITION_OPTIONS]);
  assert.equal(POSITION_OPTIONS.enableHighAccuracy, true);
  assert.equal(POSITION_OPTIONS.maximumAge, 0);
  assert.ok(POSITION_OPTIONS.timeout > 0 && POSITION_OPTIONS.timeout <= 30000);
  assert.equal(geo.calls.watch, 0);
});

test('every position-check string has English and Spanish text', () => {
  const ids = Object.keys(STRINGS).filter(id => id.startsWith('trip.pos.'));
  assert.ok(ids.length >= 25);
  for (const id of ids) { assert.ok(STRINGS[id].en?.length > 0, id); assert.ok(STRINGS[id].es?.length > 0, id); }
});

// ---- the words on screen -------------------------------------------------------------------------------------------------------------------------
const out = join(await mkdtemp(join(tmpdir(), 'position-view-')), 'view.mjs');
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {PositionView, distanceText, OFFICIAL_RULES_URL} from './web/app/PositionView.tsx';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const view = await import(pathToFileURL(out).href);
const html = (state, pack = 'saved', lang = 'en') => view.render(view.h(view.PositionView, {state, pack, onCheck() {}, lang}));
const text = markup => markup.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/\s+/g, ' ');
const done = result => ({phase: 'done', result});
const checked = (where, extra = {}) => done({located: {ok: true, fix: fixOf(OUTSIDE, 8)}, reading: {kind: 'checked', fix: fixOf(OUTSIDE, 8), where, name: 'Point Buchon State Marine Reserve', distanceM: 1234.5,
  lowAccuracy: false, stale: false, missing: [], clock: 'ok', checkedAt: FRESH, ...extra}});

test('the screen says inside / near / outside <area name>, the distance, the accuracy and the official-rules link', () => {
  const inside = text(html(checked('inside', {distanceM: 0})));
  assert.match(inside, /You are inside Point Buchon State Marine Reserve/);
  assert.match(inside, /Distance to the boundary: 0 m/);
  const near = text(html(checked('near', {distanceM: 42})));
  assert.match(near, /You are near Point Buchon State Marine Reserve/);
  assert.match(near, /Nearest closure: 42 m \(138 ft\) away/);
  const outside = text(html(checked('outside')));
  assert.match(outside, /You are outside Point Buchon State Marine Reserve/);
  assert.match(outside, /Nearest closure: 0\.7 nmi \(1\.2 km\) away/);
  for (const s of [inside, near, outside]) {
    assert.match(s, /Position accuracy: ±8 m \(26 ft\)/);
    assert.match(s, /Official CDFW rules govern/);
    assert.match(s, /Check the official rules/);
    assert.match(s, /within 70 m \(230 ft\) of a boundary plus your position accuracy/);
  }
  assert.ok(html(checked('outside')).includes(`href="${view.OFFICIAL_RULES_URL}"`));
  assert.match(html(checked('inside', {distanceM: 0})), /data-where="inside"/);
});

test('far from every closure, low accuracy, stale boundaries: each is said plainly', () => {
  assert.match(text(html(checked('outside', {name: null, distanceM: null}))), /You are outside every closed area we checked.*more than 10\.8 nmi \(20\.0 km\) away/);
  const low = text(html(checked('outside', {lowAccuracy: true, fix: fixOf(OUTSIDE, 250)})));
  assert.match(low, /Low accuracy/);
  const unknownAccuracy = text(html(done({located: {ok: true, fix: fixOf(OUTSIDE, null)}, reading: {kind: 'checked', fix: fixOf(OUTSIDE, null), where: 'outside', name: 'X', distanceM: 900, lowAccuracy: true, stale: false, missing: [], clock: 'ok', checkedAt: FRESH}})));
  assert.match(unknownAccuracy, /Position accuracy: not reported by this device/);
  const shown = text(html(done({located: {ok: true, fix: fixOf(OUTSIDE, 250)}, reading: {kind: 'checked', fix: fixOf(OUTSIDE, 250), where: 'outside', name: 'X', distanceM: 900, lowAccuracy: true, stale: false, missing: [], clock: 'ok', checkedAt: FRESH}})));
  assert.match(shown, /Position accuracy: ±250 m \(820 ft\)/);
  assert.match(shown, /Low accuracy\. Your real position may be well away/);
  assert.match(text(html(checked('outside', {stale: true, clock: 'old', checkedAt: OLD}))), new RegExp(`last checked ${OLD.slice(0, 10)}, more than 36 hours ago`));
  assert.match(text(html(checked('outside'))), new RegExp(`Boundaries last checked ${FRESH.slice(0, 10)}`));
});

test('permission denied, no fix, no API, no boundaries, outside coverage and no pack: plain words, no verdict', () => {
  const refused = reason => text(html(done({located: {ok: false, reason}})));
  assert.match(refused('denied'), /Location permission is blocked for this site/);
  assert.match(refused('unavailable'), /No position fix/);
  assert.match(refused('unsupported'), /This browser cannot read a position/);
  for (const s of [refused('denied'), refused('unavailable'), refused('unsupported')]) { assert.match(s, /Your position was not checked/); assert.ok(!/You are (inside|near|outside)/.test(s)); assert.match(s, /Check the official rules/); }
  const unchecked = kind => text(html(done({located: {ok: true, fix: fixOf(OUTSIDE)}, reading: {kind, fix: fixOf(OUTSIDE)}})));
  assert.match(unchecked('no-boundaries'), /not available on this device right now.*not clear of closures/);
  assert.match(unchecked('not-covered'), /outside the area these boundary files cover.*not clear of closures/);
  for (const s of [unchecked('no-boundaries'), unchecked('not-covered')]) assert.ok(!/You are (inside|near|outside)/.test(s));
  assert.match(text(html({phase: 'idle'}, 'none')), /No legal files are saved on this device for this region, so this will not work without signal/);
  assert.ok(!/No legal files are saved/.test(text(html({phase: 'idle'}, 'saved'))));
  assert.ok(!/No legal files are saved/.test(text(html({phase: 'idle'}, 'unknown'))));
});

test('opt-in only: nothing is read until the button is pressed, and the button says so', () => {
  const idle = html({phase: 'idle'});
  assert.match(text(idle), /Check my position/);
  assert.match(text(idle), /Reads your position once, only when you tap, and only on this device\. It is not sent anywhere and not saved\. NOT FOR NAVIGATION\./);
  assert.ok(!/You are (inside|near|outside)/.test(text(idle)));
  assert.match(html({phase: 'reading'}), /disabled/);
  assert.match(text(html({phase: 'reading'})), /Reading your position/);
  assert.match(text(html(checked('outside'))), /Check again/);
});

test('Spanish', () => {
  const es = text(html(checked('near', {distanceM: 42}), 'saved', 'es'));
  assert.match(es, /Estás cerca de Point Buchon State Marine Reserve/);
  assert.match(es, /Consulta las reglas oficiales/);
  assert.match(es, /Rigen las reglas oficiales del CDFW/);
});

test('no background tracking or notification code in the check', () => {
  for (const file of ['../web/position-check.ts', '../web/app/PositionView.tsx', '../web/app/PositionCheck.tsx']) {
    const source = readFileSync(new URL(file, import.meta.url), 'utf8').replace(/\/\/.*$/gm, '');
    assert.ok(!/watchPosition|Notification|serviceWorker|setInterval|localStorage|sessionStorage|indexedDB|caches\.|sendBeacon|XMLHttpRequest|\bfetch\(|WebSocket/.test(source), file);
  }
});
