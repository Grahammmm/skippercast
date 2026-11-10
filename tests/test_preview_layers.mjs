// MAPLIVE-1: the private map-style preview layers on the real Chart. Offline: fake engine, fake fetch.
// Gate (owner/admin session only), off by default, lazy (no module and no request until switched on), cleanup.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {signal} from '@preact/signals';

const account = await import('../web/account.ts');
const P = await import('../web/map/preview-layers.ts');
const {rampGradient} = P;

const admin = {state: 'signed-in', name: 'G', advisor: false};
const asSession = (s, isAdmin = s === admin) => { account.session.value = s; account.sessionAdmin.value = isAdmin; };
const fresh = () => { P.previewOn.value = []; P.previewStatus.value = {}; };

function fakeEngine() {
  const calls = [];
  return {calls, setOverlay: (id, overlay) => calls.push([id, overlay ? 'draw' : 'remove']), view: {container: () => ({appendChild() {}})}};
}
const PALETTE = {text: '#eeeeee', bgDeep: '#111111'};
const tick = () => new Promise(r => setTimeout(r, 0));

test('the gate: only the server\'s is_admin answer opens it', () => {
  const body = {signIn: '/#a', signedIn: true};
  assert.equal(account.readAdmin({...body, is_admin: true}), true);
  for (const v of [false, 'true', 1, null, undefined]) assert.equal(account.readAdmin({...body, is_admin: v}), false, String(v));
  assert.equal(account.readAdmin({...body, signedIn: false, is_admin: true}), false, 'signed out is never admin');
  assert.equal(account.readAdmin({...body, is_admin: true}, false), false, 'a failed read is never admin');
  assert.equal(account.readAdmin(null), false);
  assert.equal('is_admin' in account.readSession({...body, is_admin: true}), false, 'the Session itself carries no role');
  for (const s of [{state: 'loading'}, {state: 'offline'}, {state: 'disabled', advisor: false}, {state: 'signed-out', advisor: false}, {state: 'signed-in', name: null, advisor: false}]) {
    assert.equal(P.previewAccess(s, false), false, s.state);
    if (s.state !== 'signed-in') assert.equal(P.previewAccess(s, true), false, `${s.state} stays closed even with a stale flag`);
  }
  assert.equal(P.previewAccess(admin, true), true);
});

test('off by default, and a switch is ignored without the gate', () => {
  fresh(); asSession({state: 'signed-in', name: null, advisor: false}, false);
  assert.deepEqual(P.previewOn.value, []);
  P.togglePreview('sst', true);
  assert.deepEqual(P.previewOn.value, [], 'a non-admin session cannot switch a layer on');
  asSession(admin);
  P.togglePreview('sst', true); P.togglePreview('wind', true); P.togglePreview('sst', true);
  assert.deepEqual(P.previewOn.value, ['wind', 'sst'], 'in layer order, once each');
  P.togglePreview('wind', false);
  assert.deepEqual(P.previewOn.value, ['sst']);
  P.togglePreview('nonsense', true);
  assert.deepEqual(P.previewOn.value, ['sst']);
  fresh(); asSession({state: 'loading'});
});

test('lazy: creating the layer and drawing the first paint loads no layer code and makes no request', async () => {
  fresh(); asSession(admin);
  const loaded = [], fetched = [];
  const loaders = Object.fromEntries(P.PREVIEW_IDS.map(id => [id, async () => { loaded.push(id); return async () => null; }]));
  const layer = P.createPreviewLayers({engine: signal(fakeEngine()), fetchFn: async url => { fetched.push(url); return new Response('{}'); }, loaders, page: () => 'https://x.test/app'});
  await tick();
  assert.deepEqual(loaded, [], 'no loader ran');
  assert.deepEqual(fetched, [], 'no request');
  P.togglePreview('chlorophyll', true);
  await tick();
  assert.deepEqual(loaded, ['chlorophyll'], 'only the layer switched on loads');
  layer.destroy(); fresh(); asSession({state: 'loading'});
});

test('switching off destroys the overlay and aborts a load in flight; a closed gate does the same', async () => {
  fresh(); asSession(admin);
  const log = [];
  let release;
  const loaders = {
    ...Object.fromEntries(P.PREVIEW_IDS.map(id => [id, async () => async () => ({destroy: () => log.push(`destroy ${id}`)})])),
    wind: async () => async ctx => { await new Promise(r => { release = r; }); log.push(`wind aborted=${ctx.signal.aborted}`); return {destroy: () => log.push('destroy wind (late)')}; },
  };
  const layer = P.createPreviewLayers({engine: signal(fakeEngine()), loaders, page: () => 'https://x.test/'});
  P.togglePreview('sst', true); P.togglePreview('wind', true);
  await tick();
  assert.deepEqual(P.previewStatus.value.sst?.state, 'loading');
  P.togglePreview('wind', false);       // while its attach is still waiting
  release(); await tick();
  assert.ok(log.includes('wind aborted=true') && log.includes('destroy wind (late)'), 'a late answer is destroyed, never kept');
  P.togglePreview('sst', false);
  await tick();
  assert.ok(log.includes('destroy sst'));
  assert.equal(P.previewStatus.value.sst, undefined, 'status cleared');
  P.togglePreview('chlorophyll', true);
  await tick();
  asSession({state: 'signed-out', advisor: false});          // the gate closes
  await tick();
  assert.ok(log.includes('destroy chlorophyll'), 'a closed gate removes what is drawn');
  layer.destroy(); fresh(); asSession({state: 'loading'});
});

test('a switched-on layer outside the gate is never started, even if the list is set directly', async () => {
  fresh(); asSession({state: 'signed-in', name: null, advisor: false}, false);
  let started = 0;
  const loaders = Object.fromEntries(P.PREVIEW_IDS.map(id => [id, async () => { started++; return async () => null; }]));
  const layer = P.createPreviewLayers({engine: signal(fakeEngine()), loaders});
  P.previewOn.value = ['sst', 'wind'];
  await tick();
  assert.equal(started, 0);
  layer.destroy(); fresh(); asSession({state: 'loading'});
});

test('each real layer requests only its own private file, and only when attached', async () => {
  const sstDoc = {data_time: new Date(Date.now() - 3600e3).toISOString(), max_age_hours: 48, colours: ['#2b5d9e', '#d33'],
    cells: {type: 'FeatureCollection', features: []}, breaks: {type: 'FeatureCollection', features: []}};
  const chlDoc = {bounds: [-121, 35, -120, 36], sample_at: new Date(Date.now() - 3600e3).toISOString(), max_age_hours: 96, style: {legend: [[0.01, '#112233'], [100, '#ffee00']]}};
  const requests = [];
  const fetchFn = async (url, init) => {
    requests.push(String(url));
    const u = String(url);
    return new Response(u.endsWith('sst-preview.json') ? JSON.stringify(sstDoc) : u.endsWith('chlorophyll.json') ? JSON.stringify(chlDoc) : 'nope', {status: u.includes('maplayer-sst') || u.endsWith('chlorophyll.json') ? 200 : 404});
  };
  for (const id of ['sst', 'chlorophyll', 'seafloor']) {
    const engine = fakeEngine(), reports = [];
    const attach = await P.PREVIEW_LOADERS[id]();
    const before = requests.length;
    const abort = new AbortController();
    const ctx = {engine, fetchFn, now: () => new Date(), palette: () => PALETTE, url: p => new URL(p, 'https://x.test/app').href, signal: abort.signal, report: s => reports.push(s)};
    if (id === 'seafloor') await assert.rejects(attach(ctx), /not found \(HTTP 404\)/, 'a missing archive reads unavailable, nothing drawn');
    else {
      const handle = await attach(ctx);
      assert.deepEqual(engine.calls, [[id === 'sst' ? 'preview-sst-cells' : 'preview-chlorophyll', 'draw']]);
      assert.equal(reports.at(-1).state, 'ready');
      assert.equal(reports.at(-1).dataTime, (id === 'sst' ? sstDoc.data_time : chlDoc.sample_at), 'the data\'s own time, not the load time');
      handle.destroy();
      assert.equal(engine.calls.at(-1)[1], 'remove');
    }
    assert.equal(requests.length - before, 1, `${id}: exactly one request`);
  }
  assert.ok(requests.every(u => u.startsWith('https://x.test/var/')), 'private var/ paths only');
});

test('stale or invalid data is withheld, never drawn', async () => {
  const old = new Date(Date.now() - 200 * 3600e3).toISOString();
  const doc = {data_time: old, max_age_hours: 48, colours: ['#111', '#222'], cells: {type: 'FeatureCollection', features: []}, breaks: {type: 'FeatureCollection', features: []}};
  const engine = fakeEngine(), reports = [];
  const attach = await P.PREVIEW_LOADERS.sst();
  const handle = await attach({engine, fetchFn: async () => new Response(JSON.stringify(doc)), now: () => new Date(), palette: () => PALETTE, url: p => 'https://x.test' + p, signal: new AbortController().signal, report: s => reports.push(s)});
  assert.equal(handle, null);
  assert.deepEqual(engine.calls, []);
  assert.equal(reports.at(-1).state, 'stale');
  const attachBad = await P.PREVIEW_LOADERS.sst();
  await assert.rejects(attachBad({engine, fetchFn: async () => new Response('{"oops":1}'), now: () => new Date(), url: p => 'https://x.test' + p, signal: new AbortController().signal, report() {}}), /not a valid SST/);
});

test('arrowheads point along the flow; the wind adapter forwards the view', async () => {
  const {arrowhead} = await import('../web/map/preview/currents.ts');
  const [tip, a, b] = arrowhead([-121, 35], [-121.1, 35], 0.01);       // flowing east
  assert.deepEqual(tip, [-121, 35]);
  assert.ok(a[0] < tip[0] && b[0] < tip[0], 'barbs sit behind the tip');
  assert.ok(Math.sign(a[1] - 35) !== Math.sign(b[1] - 35), 'one barb each side');
  const {viewAsMap} = await import('../web/map/preview/wind.ts');
  const seen = [], view = {size: () => ({width: 400, height: 300}), project: (x, y) => ({x: x + 1, y: y + 2}), unproject: (x, y) => ({lon: x, lat: y}), busy: () => true,
    on: (type, fn) => { seen.push(type); return () => seen.push('off ' + type); }};
  const map = viewAsMap(view), fn = () => {};
  assert.deepEqual([map.getCanvas().clientWidth, map.getCanvas().clientHeight], [400, 300]);
  assert.deepEqual(map.unproject([3, 4]), {lng: 3, lat: 4});
  map.on('resize', fn); map.off('resize', fn);
  assert.deepEqual(seen, ['resize', 'off resize']);
});

test('first paint carries no layer code: the eager files import only the light registry', () => {
  const core = readFileSync(new URL('../web/map/preview-layers.ts', import.meta.url), 'utf8');
  assert.equal(/^import .*\.\/preview\//m.test(core), false, 'no static import of a layer module');
  assert.equal(/from '[^']*research\/scripts/.test(core), false);
  for (const f of ['../web/app/PreviewLayers.tsx', '../web/app/LayerRail.tsx', '../web/app/Legend.tsx', '../web/app/MapStage.tsx']) {
    const text = readFileSync(new URL(f, import.meta.url), 'utf8');
    assert.equal(/from '\.\.\/map\/preview\/|research\/scripts/.test(text), false, f);
  }
  const build = readFileSync(new URL('../scripts/client-build.mjs', import.meta.url), 'utf8');
  assert.ok(build.includes('PRIVATE_OUTPUT'), 'private pmtiles output still never copied');
});

test('legend ramps accept only plain colours from a data file', () => {
  assert.equal(rampGradient(['#fff', 'rgb(1,2,3)']), 'linear-gradient(to right, #fff, rgb(1,2,3))');
  assert.equal(rampGradient(['#fff', 'red; background:url(x)']), null);
  assert.equal(rampGradient(['#fff']), null);
});

test('the one /api/session read sets the admin flag, and any later non-admin answer clears it', async () => {
  const answer = body => async () => new Response(JSON.stringify(body), {status: 200});
  await account.refreshSession(answer({signIn: '/#a', signedIn: true, is_admin: true, user: {display_name: 'G'}}));
  assert.equal(account.sessionAdmin.value, true);
  assert.equal(P.previewAccess(), true);
  await account.refreshSession(answer({signIn: '/#a', signedIn: true, is_admin: false}));
  assert.equal(account.sessionAdmin.value, false);
  await account.refreshSession(answer({signIn: '/#a', signedIn: true, is_admin: true}));
  await account.refreshSession(async () => { throw new Error('offline'); });
  assert.equal(account.sessionAdmin.value, false, 'offline clears it');
  assert.equal(P.previewAccess(), false);
  asSession({state: 'loading'});
});

test('the chlorophyll ramp ends are the file\'s own scale', async () => {
  const doc = {bounds: [-121, 35, -120, 36], sample_at: new Date(Date.now() - 3600e3).toISOString(), max_age_hours: 96, style: {legend: [[0.05, '#112233'], [0.5, '#336699'], [15, '#ffee00']]}};
  const reports = [];
  const attach = await P.PREVIEW_LOADERS.chlorophyll();
  const handle = await attach({engine: fakeEngine(), fetchFn: async () => new Response(JSON.stringify(doc)), now: () => new Date(), url: p => new URL(p, 'https://x.test/').href, signal: new AbortController().signal, report: s => reports.push(s)});
  assert.deepEqual([reports.at(-1).ramp.low, reports.at(-1).ramp.high], ['0.05 mg/m³', '15+']);
  handle.destroy();
});

test('a source that fails after the layer reported ready reads unavailable and draws nothing', async () => {
  fresh(); asSession(admin);
  const engine = fakeEngine(), failed = signal([]), cleared = [];
  const loaders = Object.fromEntries(P.PREVIEW_IDS.map(id => [id, async () => async ctx => {
    ctx.engine.setOverlay(`preview-${id}`, {}); ctx.report({state: 'ready', text: 'ok'});
    return {destroy() { ctx.engine.setOverlay(`preview-${id}`, null); }};
  }]));
  const layer = P.createPreviewLayers({engine: signal(engine), loaders, failures: {list: failed, clear: l => { cleared.push(l); failed.value = failed.value.filter(x => x !== l); }}});
  P.previewOn.value = ['chlorophyll', 'seafloor'];
  await tick();
  assert.equal(P.previewStatus.value.chlorophyll.state, 'ready');
  failed.value = ['preview-chlorophyll'];
  assert.equal(P.previewStatus.value.chlorophyll.state, 'unavailable');
  assert.equal(P.previewStatus.value.seafloor.state, 'ready', 'only the failing layer changes');
  assert.deepEqual(engine.calls.at(-1), ['preview-chlorophyll', 'remove']);
  assert.deepEqual(cleared.sort(), ['preview-chlorophyll', 'preview-seafloor']);
  P.previewOn.value = ['seafloor']; await tick();
  P.previewOn.value = ['seafloor', 'chlorophyll']; await tick();
  assert.equal(P.previewStatus.value.chlorophyll.state, 'ready', 'switching it off and on tries again');
  layer.destroy(); fresh(); asSession({state: 'loading'});
});

// RF1915-7: failures arrive under the registry owner the real Engine routes them to (the overlay that holds the failed source),
// not under a name derived from the preview id. Real SST attach and real Engine over a fake MapLibre; real currents overlay.
const {createEngine} = await import('../web/map/engine.ts');
const {currentsOverlay, CURRENTS_TINT, CURRENTS_LINES, CURRENTS_HEADS} = await import('../web/map/preview/currents.ts');
const {SST_CELLS, SST_BREAKS, SST_HALO, SST_LINES} = await import('../web/map/preview/sst.ts');

function mapLibrary() {
  const fake = {maps: []};
  class FakeMap {
    constructor(options) {
      this.options = options; this.handlers = {}; this.sources = new Set(); this.layers = new Set(); fake.maps.push(this);
      this.keyboard = {disableRotation() {}}; this.touchZoomRotate = {disableRotation() {}};
    }
    on(type, fn) { (this.handlers[type] ??= []).push(fn); }
    fire(type, event = {}) { for (const fn of this.handlers[type] ?? []) fn(event); }
    getLayer(id) { return this.layers.has(id) ? {} : undefined; }
    getSource(id) { return this.sources.has(id) ? {} : undefined; }
    addSource(id) { this.sources.add(id); }
    addLayer(l) { this.layers.add(l.id); }
    removeLayer(id) { this.layers.delete(id); }
    removeSource(id) { this.sources.delete(id); }
    getCenter() { return {lat: 35, lng: -121}; }
    getZoom() { return 10; }
    remove() {}
  }
  const control = class {};
  fake.module = {lib: {Map: FakeMap, NavigationControl: control, ScaleControl: control, AttributionControl: control, setWorkerUrl() {}, addProtocol() {}},
    workerUrl: '/w.js', Protocol: class { constructor() { this.tile = () => {}; } }};
  return fake;
}

const sstDoc = () => ({data_time: new Date(Date.now() - 3600e3).toISOString(), max_age_hours: 48, colours: ['#2b5d9e', '#d33'],
  cells: {type: 'FeatureCollection', features: []}, breaks: {type: 'FeatureCollection', features: []}});
const currentsLoader = () => async () => async ctx => {
  const overlay = currentsOverlay([{coords: [[-121, 35], [-120.99, 35.01], [-120.98, 35.02]]}], {url: 'data:image/png;base64,AA==', coordinates: [[-121, 36], [-120, 36], [-120, 35], [-121, 35]]}, 0.01);
  ctx.engine.setOverlay(CURRENTS_TINT, overlay);
  ctx.report({state: 'ready', text: 'ok'});
  return {destroy() { ctx.engine.setOverlay(CURRENTS_TINT, null); }};
};

/** A stack as the Chart builds it: real Engine whose onLayerError appends the owner once (web/map/chart.ts markUnavailable). */
function stack(t, {loaders = P.PREVIEW_LOADERS, fetchFn} = {}) {
  const fake = mapLibrary(), failed = signal([]), cleared = [];
  const engine = createEngine(fake.module, {host: {}, style: {version: 8, sources: {}, layers: []}, camera: {latitude: 35, longitude: -121, zoom: 10}, still: true, onMove() {},
    onLayerError: layer => { if (!failed.peek().includes(layer)) failed.value = [...failed.peek(), layer]; }});
  const map = fake.maps[0]; map.fire('style.load');
  const failures = {list: failed, clear: l => { cleared.push(l); failed.value = failed.peek().filter(x => x !== l); }};
  const layer = P.createPreviewLayers({engine: signal(engine), loaders, fetchFn, failures, page: () => 'https://x.test/app', palette: () => PALETTE});
  t.after(() => finish({layer}));    // a failing assertion must still stop the preview's expiry timers
  const sourceError = sourceId => map.fire('error', {sourceId, error: new Error('tile failed')});
  return {map, engine, failed, cleared, layer, sourceError};
}
const sstFetch = () => { const n = {count: 0}; return {n, fetchFn: async () => { n.count++; return new Response(JSON.stringify(sstDoc())); }}; };
const finish = s => { s.layer.destroy(); fresh(); asSession({state: 'loading'}); };

test('sst_break_source_error_removes_entire_preview', async t => {
  t.mock.method(console, 'error', () => {});
  for (const failing of [SST_BREAKS, SST_CELLS]) {
    fresh(); asSession(admin);
    const {fetchFn} = sstFetch(), s = stack(t, {fetchFn});
    P.togglePreview('sst', true); await tick();
    assert.equal(P.previewStatus.value.sst.state, 'ready');
    assert.deepEqual([...s.map.layers].sort(), [SST_CELLS, SST_HALO, SST_LINES].sort(), 'all three layers installed');
    s.sourceError(failing);
    assert.deepEqual(s.failed.value, [SST_CELLS], `${failing}: the Engine routes to the overlay owner`);
    assert.equal(P.previewStatus.value.sst.state, 'unavailable');
    assert.match(P.previewStatus.value.sst.text, /^Unavailable: the map could not load this layer's image or tiles\. Nothing is drawn\.$/);
    assert.deepEqual([[...s.map.layers], [...s.map.sources]], [[], []], 'cells, breaks, halo and line are all removed');
    finish(s);
  }
});

test('currents_any_source_error_uses_tint_owner', async t => {
  t.mock.method(console, 'error', () => {});
  for (const failing of [CURRENTS_TINT, CURRENTS_LINES, CURRENTS_HEADS]) {
    fresh(); asSession(admin);
    const s = stack(t, {loaders: {...P.PREVIEW_LOADERS, currents: currentsLoader()}});
    P.togglePreview('currents', true); await tick();
    assert.equal(P.previewStatus.value.currents.state, 'ready');
    assert.equal(s.map.layers.size, 3);
    s.sourceError(failing);
    assert.deepEqual(s.failed.value, [CURRENTS_TINT], `${failing} routes to the tint owner`);
    assert.equal(P.previewStatus.value.currents.state, 'unavailable');
    assert.deepEqual([[...s.map.layers], [...s.map.sources]], [[], []], 'tint, lines and heads are all removed');
    finish(s);
  }
});

test('retry_clears_exact_owner_only', async t => {
  t.mock.method(console, 'error', () => {});
  fresh(); asSession(admin);
  const {n, fetchFn} = sstFetch(), s = stack(t, {fetchFn});
  P.togglePreview('sst', true); await tick();
  s.failed.value = ['basemap', ...s.failed.value];
  s.sourceError(SST_BREAKS);
  assert.deepEqual(s.failed.value, ['basemap', SST_CELLS]);
  assert.equal(P.previewStatus.value.sst.state, 'unavailable');
  await tick();
  assert.equal(P.previewStatus.value.sst.state, 'unavailable', 'the failure persists until the person retries');
  s.cleared.length = 0;
  P.togglePreview('sst', false); await tick();
  assert.equal(P.previewStatus.value.sst, undefined);
  assert.deepEqual(s.failed.value, ['basemap', SST_CELLS], 'switching off alone clears nothing');
  P.togglePreview('sst', true); await tick();
  assert.deepEqual(s.cleared, [SST_CELLS], 'only the real owner marker is cleared');
  assert.deepEqual(s.failed.value, ['basemap'], 'an unrelated failure is kept');
  assert.equal(n.count, 2, 'one attach per switch-on');
  assert.equal(P.previewStatus.value.sst.state, 'ready', 'ready comes from the loader');
  assert.equal(s.map.layers.size, 3);
  s.sourceError(SST_BREAKS);
  assert.equal(P.previewStatus.value.sst.state, 'unavailable', 'a fresh source error is handled again');
  assert.equal(s.map.layers.size, 0);
  finish(s);
});

test('unrelated_and_unknown_failures_do_not_disable_preview', async t => {
  t.mock.method(console, 'error', () => {});
  fresh(); asSession(admin);
  const {fetchFn} = sstFetch(), s = stack(t, {fetchFn, loaders: {...P.PREVIEW_LOADERS, currents: currentsLoader()}});
  P.previewOn.value = ['currents', 'sst']; await tick();
  assert.equal(P.previewStatus.value.sst.state, 'ready'); assert.equal(P.previewStatus.value.currents.state, 'ready');
  s.failed.value = ['preview-sst', 'preview-currents', 'preview-currents-lines', 'preview-sst-breaks', 'basemap', 'nonsense'];
  assert.equal(P.previewStatus.value.sst.state, 'ready', 'a display-id or secondary-source name is not the owner');
  assert.equal(P.previewStatus.value.currents.state, 'ready');
  assert.equal(s.map.layers.size, 6, 'nothing was removed');
  s.failed.value = [...s.failed.value, SST_CELLS];
  assert.equal(P.previewStatus.value.sst.state, 'unavailable');
  assert.equal(P.previewStatus.value.currents.state, 'ready', 'another preview stays ready');
  assert.deepEqual([...s.map.layers].sort(), [CURRENTS_TINT, CURRENTS_LINES, CURRENTS_HEADS].sort());
  assert.deepEqual(P.PREVIEW_OWNERS.wind, 'preview-wind', 'wind keeps its compatibility marker');
  assert.deepEqual([P.PREVIEW_OWNERS.seafloor, P.PREVIEW_OWNERS.chlorophyll], ['preview-seafloor', 'preview-chlorophyll']);
  finish(s);
});

test('late_attach_failure_and_gate_cleanup_keep_working', async t => {
  fresh(); asSession(admin);
  const log = [], gates = [];
  const loaders = {...Object.fromEntries(P.PREVIEW_IDS.map(id => [id, async () => async () => null])),
    sst: async () => async () => { await new Promise(r => gates.push(r)); return {destroy: () => log.push('destroy sst')}; }};
  const failed = signal([]), engine = signal(fakeEngine());
  const layer = P.createPreviewLayers({engine, loaders, failures: {list: failed, clear: l => { failed.value = failed.value.filter(x => x !== l); }}});
  t.after(() => finish({layer}));
  P.togglePreview('sst', true); await tick();
  failed.value = [P.PREVIEW_OWNERS.sst];                 // the owner fails while the attach is pending
  assert.equal(P.previewStatus.value.sst.state, 'unavailable');
  gates[0](); await tick();
  assert.deepEqual(log, ['destroy sst'], 'the handle that arrives after the failure is destroyed');
  assert.equal(P.previewStatus.value.sst.state, 'unavailable');
  // The gate closing while an attach is pending keeps the late handle too.
  P.togglePreview('sst', false); await tick();
  P.togglePreview('sst', true); await tick();
  assert.equal(P.previewStatus.value.sst.state, 'loading', 'retry cleared the owner marker and loads again');
  asSession({state: 'signed-out', advisor: false}); await tick();
  gates[1](); await tick();
  assert.deepEqual(log, ['destroy sst', 'destroy sst'], 'a late handle after the gate closed is destroyed');
  assert.equal(P.previewStatus.value.sst, undefined);
  // So does replacing the engine.
  asSession(admin); P.togglePreview('sst', false); P.togglePreview('sst', true); await tick();
  engine.value = fakeEngine(); await tick();
  gates[2](); await tick();
  assert.equal(log.filter(x => x === 'destroy sst').length, 3, 'a late handle after an engine replacement is destroyed');
  layer.destroy(); fresh(); asSession({state: 'loading'});
});
