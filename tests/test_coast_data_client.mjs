// FE-74: the v2 coast data client (web/coast-data.ts) over the existing bridge.
// Fixtures in tests/fixtures/coast/ are synthetic snapshots.
import test, {mock} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {CLOCK_SKEW_MS, OFFLINE_REPORT_LIMIT_MS, SNAPSHOT_LIMIT_MS, admitSnapshot, createCoastData} from '../web/coast-data.ts';
import {overviewReportContext} from '../web/overview-context.ts';
import {managedReportState} from '../packages/coast/src/state/report-context.ts';

const json = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const fixtures = {report: json('./fixtures/coast/report.json'), ocean: json('./fixtures/coast/ocean.json'), history: json('./fixtures/coast/history.json')};
const regions = ['morro-bay', 'cambria-san-simeon', 'monterey-point-sur', 'point-arguello-conception'].map(id => json(`../dist/regions/${id}/region.json`));
const GENERATED = Date.parse(fixtures.report.generatedAt);
const NOW = GENERATED + 3_600_000;
const at = new Date(NOW);

/** The context overviewReportContext builds for a published selection at `point` in `region`. */
function place(region, latitude, longitude, {profile = 'boat', target = 'lingcod', when = at} = {}) {
  const point = {latitude, longitude};
  return overviewReportContext(point, {...point, id: 'synthetic-selection', region}, regions, profile, target, when);
}
const MORRO = () => place('morro-bay', 35.36, -120.94);
const CAMBRIA = () => place('cambria-san-simeon', 35.6, -121.15);
const MONTEREY = () => place('monterey-point-sur', 36.5, -121.95);
const CONCEPTION = () => place('point-arguello-conception', 34.5, -120.5);

/** Replace global fetch (coastFetch calls it) with a recorder; `reply` returns a Response or a promise of one. */
function bridge(reply = path => respond(fixtures[path.split('/').pop()])) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = (path, init) => { calls.push({path, init}); return Promise.resolve(reply(path, init, calls.length)); };
  return {calls, restore: () => { globalThis.fetch = original; }};
}
const respond = (body, headers = {}) => new Response(JSON.stringify(body), {headers: {'Content-Type': 'application/json', ...headers}});
/** A reply that waits until released, and rejects when its request is aborted. */
function deferred() {
  const gates = [];
  const reply = (_path, init) => new Promise((resolve, reject) => {
    gates.push(resolve);
    init.signal.addEventListener('abort', () => reject(init.signal.reason));
  });
  return {reply, gates};
}

function withClock(t, now = NOW) {
  mock.timers.enable({apis: ['setTimeout', 'Date'], now});
  t.after(() => mock.timers.reset());
}

test('Monterey and Point Conception get null and request nothing', async t => {
  withClock(t);
  const net = bridge(); t.after(net.restore);
  const client = createCoastData(); t.after(client.destroy);
  for (const context of [MONTEREY(), CONCEPTION()]) {
    assert.equal(context.regionId, '', 'overviewReportContext withholds the binding');
    assert.equal(client.setPlace(context), null);
    await client.load('report', 'ocean', 'history');
    await client.refresh();
    assert.equal(client.coastReport.value, null);
    assert.equal(client.coastOcean.value, null);
    assert.equal(client.coastHistory.value, null);
    assert.deepEqual(client.coastStatus.value, {report: 'unbound', ocean: 'unbound', history: 'unbound'});
  }
  // A context naming those regions directly, even with Morro's local areas, still has no binding.
  const borrowed = {...MORRO(), point: {latitude: 35.36, longitude: -120.94}};
  for (const regionId of ['monterey-point-sur', 'point-arguello-conception']) assert.equal(client.setPlace({...borrowed, regionId}), null);
  assert.equal(client.coastReport.value, null);
  assert.equal(net.calls.length, 0);
});

test('a bound place loads each snapshot through the bridge with its original clocks', async t => {
  withClock(t);
  const net = bridge(path => respond(fixtures[path.split('/').pop()], path.endsWith('/history') ? {'X-SC-Offline': '2026-10-07T12:00:00.000Z'} : {}));
  t.after(net.restore);
  const client = createCoastData(); t.after(client.destroy);
  assert.deepEqual(client.setPlace(MORRO()), {areaId: 'central', localAreaId: 'estero-bay'});
  assert.deepEqual(client.coastStatus.value, {report: 'idle', ocean: 'idle', history: 'idle'});
  await client.load('report', 'ocean', 'history');
  assert.deepEqual(net.calls.map(c => c.path).sort(), ['/api/coast/history', '/api/coast/ocean', '/api/coast/report']);
  for (const {init} of net.calls) { assert.equal(init.credentials, 'omit'); assert.equal(init.redirect, 'error'); }
  const report = client.coastReport.value;
  assert.deepEqual(report.data, fixtures.report, 'the payload is not rewritten');
  assert.equal(report.generatedAt, fixtures.report.generatedAt);
  assert.equal(report.receivedAt, new Date(NOW).toISOString());
  assert.equal(report.savedAt, null);
  assert.equal(report.expiresAt, new Date(GENERATED + SNAPSHOT_LIMIT_MS.report).toISOString());
  assert.equal(client.coastHistory.value.savedAt, '2026-10-07T12:00:00.000Z');
  assert.equal(client.coastOcean.value.data.currents[0].id, 'hfr-6');
  assert.deepEqual(client.coastStatus.value, {report: 'ready', ocean: 'ready', history: 'ready'});
  // The admitted snapshot is what packages/coast's managed report reads for the same place.
  assert.equal(managedReportState(report.data, MORRO(), new Date(NOW))?.areaId, 'central');

  // Hour, profile and target changes keep the place: no new request.
  assert.deepEqual(client.setPlace(place('morro-bay', 35.36, -120.94, {profile: 'spear', target: 'cabezon', when: new Date(NOW + 7_200_000)})), {areaId: 'central', localAreaId: 'estero-bay'});
  await client.load('report');
  assert.equal(net.calls.length, 3);
  assert.equal(client.coastReport.value, report);

  // Snapshots are county-wide: leaving hides them, returning admits the cached copy without a request.
  client.setPlace(MONTEREY());
  assert.equal(client.coastReport.value, null);
  client.setPlace(CAMBRIA());
  assert.equal(client.coastReport.value, report);
  assert.equal(client.coastBinding.value?.areaId, 'north');
  assert.equal(net.calls.length, 3);
});

test('a response for a superseded place is discarded', async t => {
  withClock(t);
  const gate = deferred();
  const net = bridge(gate.reply); t.after(net.restore);
  const client = createCoastData(); t.after(client.destroy);
  client.setPlace(MORRO());
  const loading = client.load('report');
  assert.equal(client.coastStatus.value.report, 'loading');
  client.setPlace(MONTEREY());
  assert.equal(net.calls[0].init.signal.aborted, true, 'the request is aborted on place change');
  gate.gates[0](respond(fixtures.report));
  await loading;
  assert.equal(client.coastReport.value, null);
  assert.equal(client.coastStatus.value.report, 'unbound');

  // Bound to bound: Morro's request is superseded by Cambria's; only Cambria's response lands.
  client.setPlace(MORRO());
  assert.equal(net.calls.length, 2, 'the wanted product is requested again for the new place');
  client.setPlace(CAMBRIA());
  assert.equal(net.calls[1].init.signal.aborted, true);
  assert.equal(net.calls.length, 3);
  const later = {...fixtures.report, generatedAt: new Date(GENERATED + 600_000).toISOString()};
  gate.gates[1](respond(fixtures.report));
  gate.gates[2](respond(later));
  await client.load('report');
  assert.equal(client.coastReport.value.generatedAt, later.generatedAt);
  assert.equal(client.coastBinding.value.localAreaId, 'san-simeon');
});

test('an expired snapshot yields null and the reason, and expiry never refreshes', async t => {
  // Already past its limit when it arrives.
  withClock(t, GENERATED + SNAPSHOT_LIMIT_MS.report + 1);
  const net = bridge(); t.after(net.restore);
  const stale = createCoastData(); t.after(stale.destroy);
  stale.setPlace(MORRO());
  await stale.load('report');
  assert.equal(stale.coastReport.value, null);
  assert.equal(stale.coastStatus.value.report, 'expired');
  await stale.load('report');
  assert.equal(net.calls.length, 1, 'load() does not retry an expired product');

  // Admitted, then passes its limit while shown.
  mock.timers.setTime(NOW);
  const client = createCoastData(); t.after(client.destroy);
  client.setPlace(MORRO());
  await client.load('report', 'ocean');
  assert.ok(client.coastReport.value);
  const calls = net.calls.length;
  mock.timers.tick(GENERATED + SNAPSHOT_LIMIT_MS.report - NOW);
  assert.equal(client.coastReport.value, null);
  assert.equal(client.coastStatus.value.report, 'expired');
  assert.ok(client.coastOcean.value, 'the ocean snapshot keeps its own, longer limit');
  mock.timers.tick(SNAPSHOT_LIMIT_MS.ocean);
  assert.equal(client.coastOcean.value, null);
  assert.deepEqual(client.coastStatus.value, {report: 'expired', ocean: 'expired', history: 'idle'});
  await client.load('report', 'ocean');
  assert.equal(net.calls.length, calls, 'expiry hides; nothing is requested');

  // An explicit retry requests again.
  mock.timers.setTime(NOW);
  await client.refresh('report');
  assert.equal(net.calls.length, calls + 1);
  assert.equal(client.coastStatus.value.report, 'ready');
});

test('a stalled expiry timer cannot show an expired snapshot', async t => {
  withClock(t);
  const net = bridge(); t.after(net.restore);
  const client = createCoastData(); t.after(client.destroy);
  client.setPlace(MORRO());
  await client.load('report');
  assert.ok(client.coastReport.value);
  // A suspended tab: the clock moves past expiresAt but no timer fires (setTime runs none).
  mock.timers.setTime(GENERATED + SNAPSHOT_LIMIT_MS.report + 60_000);
  assert.deepEqual(client.setPlace(place('morro-bay', 35.36, -120.94, {profile: 'shore', target: 'surfperch'})), {areaId: 'central', localAreaId: 'estero-bay'});
  assert.equal(client.coastReport.value, null);
  assert.equal(client.coastStatus.value.report, 'expired');
  await client.load('report');
  assert.equal(net.calls.length, 1, 'the expired report is hidden, not refreshed');
});

test('a returning tab withholds an expired snapshot on its clock events alone', async t => {
  withClock(t);
  const net = bridge(); t.after(net.restore);
  const page = new EventTarget();
  const client = createCoastData({clockEvents: page}); t.after(client.destroy);
  client.setPlace(MORRO());
  await client.load('report', 'ocean');
  const report = client.coastReport.value;
  assert.ok(report);
  // Suspended: the clock passes expiresAt, no timer fires and nothing calls setPlace or load.
  mock.timers.setTime(GENERATED + SNAPSHOT_LIMIT_MS.report + 60_000);
  assert.equal(client.coastReport.value, report, 'no tick yet');
  page.dispatchEvent(new Event('visibilitychange'));
  assert.equal(client.coastReport.value, null);
  assert.equal(client.coastStatus.value.report, 'expired');
  assert.ok(client.coastOcean.value, 'the ocean snapshot is within its own limit');
  mock.timers.setTime(GENERATED + SNAPSHOT_LIMIT_MS.ocean + 60_000);
  page.dispatchEvent(new Event('focus'));
  assert.equal(client.coastOcean.value, null);
  assert.equal(net.calls.length, 2, 'withholding requests nothing');
  client.destroy();
  mock.timers.setTime(NOW);
  page.dispatchEvent(new Event('focus'));
});

test('a refresh keeps the newer snapshot', async t => {
  withClock(t);
  let reply = () => respond(fixtures.report);
  const net = bridge(() => reply()); t.after(net.restore);
  const client = createCoastData(); t.after(client.destroy);
  client.setPlace(MORRO());
  await client.load('report');
  const fresh = client.coastReport.value;
  // An older saved offline copy arrives after the fresher network read.
  reply = () => respond({...fixtures.report, generatedAt: new Date(GENERATED - 1_800_000).toISOString()}, {'X-SC-Offline': '2026-10-07T13:00:00.000Z'});
  await client.refresh('report');
  assert.equal(client.coastReport.value, fresh);
  assert.equal(client.coastStatus.value.report, 'ready');
  // An expired reply does not hide the unexpired snapshot.
  reply = () => respond({...fixtures.report, generatedAt: new Date(NOW - SNAPSHOT_LIMIT_MS.report - 1).toISOString()});
  await client.refresh('report');
  assert.equal(client.coastReport.value, fresh);
  assert.equal(client.coastStatus.value.report, 'ready');
  // A newer one replaces it.
  const newer = {...fixtures.report, generatedAt: new Date(GENERATED + 1_800_000).toISOString()};
  reply = () => respond(newer);
  await client.refresh('report');
  assert.equal(client.coastReport.value.generatedAt, newer.generatedAt);
  assert.equal(net.calls.length, 4);
});

test('bridge failures and wrong identities are reported without inventing data', async t => {
  withClock(t);
  const replies = [
    () => new Response('{"error":"Coast source unavailable"}', {status: 503}),
    () => respond({...fixtures.report, countyId: 'monterey'}),
    () => respond({...fixtures.report, generatedAt: new Date(NOW + CLOCK_SKEW_MS + 1).toISOString()}),
    () => respond({...fixtures.report, forecasts: null}),
    () => { throw new TypeError('offline'); },
  ];
  const expected = ['error', 'invalid', 'invalid', 'invalid', 'error'];
  let index = 0;
  const net = bridge(() => replies[index]()); t.after(net.restore);
  const client = createCoastData(); t.after(client.destroy);
  client.setPlace(MORRO());
  for (; index < replies.length; index++) {
    await client.refresh('report');
    assert.equal(client.coastReport.value, null);
    assert.equal(client.coastStatus.value.report, expected[index]);
  }
  // A failed retry keeps the earlier unexpired snapshot and reports the failure.
  globalThis.fetch = () => Promise.resolve(respond(fixtures.report));
  await client.refresh('report');
  const shown = client.coastReport.value;
  globalThis.fetch = () => Promise.resolve(new Response('', {status: 503}));
  await client.refresh('report');
  assert.equal(client.coastReport.value, shown);
  assert.equal(client.coastStatus.value.report, 'error');
});

test('admission checks each product shape and clock', () => {
  assert.equal(admitSnapshot('ocean', {...fixtures.ocean, currents: {}}, null, NOW), 'invalid');
  assert.equal(admitSnapshot('history', {...fixtures.history, recentWindowDays: 0}, null, NOW), 'invalid');
  assert.equal(admitSnapshot('history', fixtures.history, 'not a time', NOW).savedAt, null);
  assert.equal(admitSnapshot('history', fixtures.history, null, GENERATED + SNAPSHOT_LIMIT_MS.history), 'expired');
  assert.equal(admitSnapshot('report', fixtures.report, null, GENERATED - CLOCK_SKEW_MS).generatedAt, fixtures.report.generatedAt);
  // A saved offline report copy keeps a day's backstop; a network read of the same age is hidden.
  const tenHours = GENERATED + 10 * 3_600_000;
  assert.equal(admitSnapshot('report', fixtures.report, null, tenHours), 'expired');
  assert.equal(admitSnapshot('report', fixtures.report, '2026-10-07T15:30:00.000Z', tenHours).expiresAt, new Date(GENERATED + OFFLINE_REPORT_LIMIT_MS).toISOString());
  assert.equal(admitSnapshot('report', fixtures.report, '2026-10-07T15:30:00.000Z', GENERATED + OFFLINE_REPORT_LIMIT_MS), 'expired');
  assert.equal(admitSnapshot('ocean', fixtures.ocean, '2026-10-07T15:30:00.000Z', GENERATED + SNAPSHOT_LIMIT_MS.ocean), 'expired');
});

test('destroy aborts requests and drops late responses', async t => {
  withClock(t);
  const gate = deferred();
  const net = bridge(gate.reply); t.after(net.restore);
  const client = createCoastData();
  client.setPlace(MORRO());
  const loading = client.load('history');
  client.destroy();
  assert.equal(net.calls[0].init.signal.aborted, true);
  gate.gates[0](respond(fixtures.history));
  await loading;
  assert.equal(client.coastHistory.value, null);
  assert.equal(client.setPlace(MORRO()), null);
  await client.load('report');
  assert.equal(net.calls.length, 1);
});

test('no new endpoint: the client reads only the existing bridge through coastFetch', () => {
  const source = readFileSync(new URL('../web/coast-data.ts', import.meta.url), 'utf8');
  assert.match(source, /coastFetch\('\/api\/' \+ product/);
  assert.doesNotMatch(source.replace(/coastFetch\(/g, ''), /\bfetch\(/);
  assert.doesNotMatch(source, /['"`]\/(?:api\/coast|coast-data)\//, 'paths go through coastPath, never hard-coded');
});
