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
    const ctx = {engine, fetchFn, now: () => new Date(), url: p => new URL(p, 'https://x.test/app').href, signal: abort.signal, report: s => reports.push(s)};
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
  const handle = await attach({engine, fetchFn: async () => new Response(JSON.stringify(doc)), now: () => new Date(), url: p => 'https://x.test' + p, signal: new AbortController().signal, report: s => reports.push(s)});
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
