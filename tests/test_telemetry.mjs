// Client telemetry (P4-11): POST /api/telemetry through worker.fetch
// (validation, unknown fields, size cap, origin, rate limit, Analytics Engine
// or no-op) and the browser module web/telemetry.ts (batching, dedupe, caps,
// Do Not Track and Global Privacy Control).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {parseBatch, scrub, MAX_BODY, MAX_EVENTS} = await import('../server/telemetry.ts');
const client = await import('../web/telemetry.ts');

const ORIGIN = 'https://skippercast.com';
function sink() { const points = []; return {points, ANALYTICS: {writeDataPoint: p => points.push(structuredClone(p))}}; }
const of = (points, kind) => points.filter(p => p.indexes[0] === kind);
function post(body, {origin = ORIGIN, headers = {}} = {}) {
  return new Request(ORIGIN + '/api/telemetry', {method: 'POST', headers: {'Content-Type': 'text/plain;charset=UTF-8', ...(origin ? {Origin: origin} : {}), ...headers},
    body: typeof body === 'string' ? body : JSON.stringify(body)});
}
const funnel = (name, region) => ({type: 'funnel', name, ...(region ? {region} : {})});
const good = {build: '0123456789', events: [funnel('port_selected', 'morro-bay'), funnel('map_viewed', 'morro-bay'),
  {type: 'error', kind: 'error', message: 'TypeError: x is undefined at https://skippercast.com/assets/app.js?region=morro-bay&who=alice@example.com', source: 'https://skippercast.com/assets/index.0123456789.js?v=1#frag', line: 12, column: 7, request_id: 'abcdefgh12345678'}]};

test('a valid batch answers 204 and writes one client point per event, with nothing personal', async () => {
  const {points, ANALYTICS} = sink();
  const response = await worker.fetch(post(good), {ANALYTICS});
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(await response.text(), '');
  assert.deepEqual(of(points, 'client_event').map(p => [p.blobs, p.doubles]), [
    [['client_event', 'port_selected', 'morro-bay', '0123456789'], [1]],
    [['client_event', 'map_viewed', 'morro-bay', '0123456789'], [1]]]);
  const [error] = of(points, 'client_error');
  assert.deepEqual(error.blobs.slice(0, 5), ['client_error', 'error', 'TypeError: x is undefined at https://skippercast.com/assets/app.js', 'index.0123456789.js', '0123456789']);
  assert.match(error.blobs[5], /^[0-9a-f]{16}$/, 'the request id is hashed like request points');
  assert.notEqual(error.blobs[5], 'abcdefgh12345678');
  assert.deepEqual(error.doubles, [12, 7]);
  const [request] = of(points, 'request');
  assert.deepEqual(request.blobs.slice(1, 3), ['/api/telemetry', 'POST']);
  assert.doesNotMatch(JSON.stringify(points), /alice|example\.com|region=|v=1|frag/);
});

test('without Analytics Engine the route validates and answers 204, writing nothing', async () => {
  assert.equal((await worker.fetch(post(good), {})).status, 204);
  assert.equal((await worker.fetch(post({...good, extra: 1}), {})).status, 400, 'validation does not depend on the binding');
});

test('unknown fields, event names, types and bad values are rejected, not ignored', async () => {
  const bad = [
    {...good, user: 'alice'},
    {...good, events: [{...funnel('map_viewed'), url: 'https://skippercast.com/?region=morro-bay'}]},
    {...good, events: [{...good.events[2], stack: 'at x'}]},
    {...good, events: [funnel('clicked_ad')]},
    {...good, events: [{type: 'pageview'}]},
    {...good, events: [{...good.events[2], kind: 'warning'}]},
    {...good, events: [{...good.events[2], line: -1}]},
    {...good, events: [{...good.events[2], line: 1.5}]},
    {...good, events: [{...good.events[2], request_id: 'bad id'}]},
    {...good, events: [{...good.events[2], message: 'x'.repeat(513)}]},
    {...good, events: []},
    {...good, events: Array(MAX_EVENTS + 1).fill(funnel('map_viewed'))},
    {...good, build: 'not-a-build'},
    {events: good.events},
    [good],
    '{"build":',
  ];
  for (const body of bad) {
    const {points, ANALYTICS} = sink();
    const response = await worker.fetch(post(body), {ANALYTICS});
    assert.equal(response.status, 400, JSON.stringify(body).slice(0, 120));
    assert.equal(of(points, 'client_event').length + of(points, 'client_error').length, 0);
  }
  const {error} = await (await worker.fetch(post({...good, user: 'alice'}), {})).json();
  assert.equal(error, 'invalid telemetry');
});

test('bodies over 4 KiB are refused, by header or by stream', async () => {
  const big = {build: 'dev', events: [{type: 'error', kind: 'error', message: 'x'.repeat(500)}]};
  while (JSON.stringify(big).length <= MAX_BODY) big.events.push({...big.events[0]});
  big.events = big.events.slice(0, MAX_EVENTS);
  assert.ok(JSON.stringify(big).length > MAX_BODY);
  const response = await worker.fetch(post(big), {});
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error, 'body too large');
  // A streamed body with no Content-Length is cut off at the cap too.
  const stream = new ReadableStream({start(c) { c.enqueue(new TextEncoder().encode(JSON.stringify(big))); c.close(); }});
  const streamed = new Request(ORIGIN + '/api/telemetry', {method: 'POST', headers: {Origin: ORIGIN}, body: stream, duplex: 'half'});
  assert.equal((await worker.fetch(streamed, {})).status, 400);
});

test('only allowed origins may post, and PUBLIC_LIMITER applies', async () => {
  assert.equal((await worker.fetch(post(good, {origin: null}), {})).status, 400);
  assert.equal((await worker.fetch(post(good, {origin: 'https://evil.example'}), {})).status, 400);
  assert.equal((await worker.fetch(post(good, {origin: 'http://localhost:8787'}), {EXTRA_ORIGINS: 'http://localhost:8787'})).status, 204);
  const keys = [];
  const PUBLIC_LIMITER = {limit: async ({key}) => { keys.push(key); return {success: false}; }};
  const limited = await worker.fetch(post(good, {headers: {'cf-connecting-ip': '203.0.113.9'}}), {PUBLIC_LIMITER});
  assert.equal(limited.status, 429);
  assert.deepEqual(keys, ['telemetry:203.0.113.9']);
  assert.notEqual((await worker.fetch(new Request(ORIGIN + '/api/telemetry'), {})).status, 204, 'GET is not the telemetry route');
});

test('unknown regions are recorded as other; messages are scrubbed server-side', () => {
  const batch = parseBatch({build: 'dev', events: [funnel('forecast_viewed', 'atlantis'), funnel('map_viewed')]});
  assert.deepEqual(batch.events.map(e => e.region), ['other', '']);
  assert.equal(scrub('Failed https://a.test/x?token=1 for bob@example.org id 12345678'), 'Failed https://a.test/x for [email] id #');
  assert.ok(scrub('y'.repeat(400)).length <= 96);
});

test('queries after relative paths and coordinate-shaped numbers are removed, on both sides', () => {
  const raw = 'fetch /api/om/v1/forecast?latitude=35.3658&longitude=-120.8512 failed; see api/x#frag and https://s.test/a?b=c at 35.36584,-120.85121';
  const expected = 'fetch /api/om/v1/forecast failed; see api/x and https://s.test/a at [coord],[coord]';
  assert.equal(scrub(raw), expected.slice(0, 96));
  assert.equal(client.cleanMessage(raw), expected);
  for (const text of [scrub(raw), client.cleanMessage(raw)]) assert.doesNotMatch(text, /latitude|35\.36|120\.85|frag|b=c/);
  // Ordinary numbers, versions and file names survive.
  assert.equal(client.cleanMessage('x is 3.5 in index.0123456789.js line 12'), 'x is 3.5 in index.0123456789.js line 12');
  assert.equal(scrub('Failed at 12:30 (v1.2)'), 'Failed at 12:30 (v1.2)');
});

test('at most 10 events a batch, and repeated funnel events in one batch are written once', async () => {
  assert.equal(MAX_EVENTS, client.BATCH_SIZE);
  assert.throws(() => parseBatch({build: 'dev', events: Array.from({length: 11}, (_, i) => funnel('map_viewed', 'r' + i))}));
  const batch = parseBatch({build: 'dev', events: [funnel('map_viewed', 'morro-bay'), funnel('map_viewed', 'morro-bay'), funnel('map_viewed'),
    funnel('forecast_viewed', 'atlantis'), funnel('forecast_viewed', 'narnia'), {type: 'error', kind: 'error', message: 'a'}, {type: 'error', kind: 'error', message: 'a'}]});
  assert.deepEqual(batch.events.map(e => e.type === 'funnel' ? `${e.name}:${e.region}` : e.type),
    ['map_viewed:morro-bay', 'map_viewed:', 'forecast_viewed:other', 'error', 'error'], 'unknown regions collapse to other before the repeat check');
  const {points, ANALYTICS} = sink();
  assert.equal((await worker.fetch(post({build: 'dev', events: Array(5).fill(funnel('spot_saved', 'morro-bay'))}), {ANALYTICS})).status, 204);
  assert.equal(of(points, 'client_event').length, 1);
});

test('the request id is taken only from same-origin responses', () => {
  const response = (url, id = 'req-0123456789') => ({url, headers: {get: name => name === 'X-Request-Id' ? id : null}});
  const site = 'https://skippercast.com';
  assert.equal(client.requestIdFrom(response('https://skippercast.com/api/om/v1/forecast?x=1'), site), 'req-0123456789');
  assert.equal(client.requestIdFrom(response('https://api.weather.gov/points/1,2'), site), null);
  assert.equal(client.requestIdFrom(response('https://skippercast.com.evil.example/'), site), null);
  assert.equal(client.requestIdFrom(response(''), site), null, 'synthetic responses have no URL');
  assert.equal(client.requestIdFrom(response('not a url'), site), null);
});

// Browser module ------------------------------------------------------------

function harness(overrides = {}) {
  const sent = [], timers = [];
  const t = client.createTelemetry({send: body => { sent.push(JSON.parse(body)); return true; }, build: '0123456789', region: () => 'morro-bay',
    schedule: (run, ms) => timers.push({run, ms}), ...overrides});
  return {t, sent, timers};
}

test('Do Not Track and Global Privacy Control opt out', () => {
  assert.equal(client.optedOut({doNotTrack: '1'}), true);
  assert.equal(client.optedOut({doNotTrack: 'yes'}), true);
  assert.equal(client.optedOut({doNotTrack: null}, {doNotTrack: '1'}), true);
  assert.equal(client.optedOut({globalPrivacyControl: true}), true);
  assert.equal(client.optedOut({doNotTrack: '0', globalPrivacyControl: false}), false);
  assert.equal(client.optedOut({}), false);
});

test('events batch until BATCH_SIZE or the flush timer, and each step counts once per page and region', () => {
  const {t, sent, timers} = harness();
  t.track('map_viewed'); t.track('map_viewed'); t.track('forecast_viewed');
  assert.equal(sent.length, 0);
  assert.equal(timers.length, 1, 'one timer per batch');
  assert.equal(timers[0].ms, client.FLUSH_MS);
  timers[0].run();
  assert.deepEqual(sent, [{build: '0123456789', events: [{type: 'funnel', name: 'map_viewed', region: 'morro-bay'}, {type: 'funnel', name: 'forecast_viewed', region: 'morro-bay'}]}]);
  t.track('map_viewed', {region: 'other-port'});
  t.track('port_selected', {region: 'morro-bay', flush: true});
  assert.equal(sent.length, 2, 'flush: true sends at once (the page may navigate away)');
  assert.equal(sent[1].events.length, 2);
  t.track('not_an_event');
  assert.equal(t.pending, 0);
});

test('errors are deduplicated, capped per page, carry the last request id, and fit the server contract', () => {
  const {t, sent} = harness();
  t.noteRequestId('bad id');
  t.noteRequestId('req-0123456789');
  const boom = new Error('boom at https://skippercast.com/?region=morro-bay&token=abc');
  boom.stack = 'Error: boom\n    at run (https://skippercast.com/assets/index.0123456789.js?x=1:10:20)';
  t.error('error', boom); t.error('error', boom);
  t.error('rejection', 'plain reason');
  t.error('error', 'Script error.');
  for (let i = 0; i < 10; i++) t.error('error', new Error('distinct ' + i));
  t.flush();
  const events = sent.flatMap(b => b.events);
  assert.equal(events.length, client.MAX_ERRORS);
  assert.deepEqual(events[0], {type: 'error', kind: 'error', message: 'boom at https://skippercast.com/', source: 'index.0123456789.js', line: 10, column: 20, request_id: 'req-0123456789'});
  assert.deepEqual(events[1], {type: 'error', kind: 'rejection', message: 'plain reason', request_id: 'req-0123456789'});
  for (const batch of sent) assert.doesNotThrow(() => parseBatch(batch), 'the server accepts what the client sends');
});

test('a page sends at most MAX_EVENTS events, each beacon under the size cap', () => {
  const {t, sent} = harness({region: () => ''});
  for (let i = 0; i < 100; i++) t.track('map_viewed', {region: 'r' + i});
  t.flush();
  assert.ok(sent.every(b => b.events.length <= client.BATCH_SIZE));
  for (let i = 0; i < 10; i++) t.error('error', new Error('m'.repeat(300) + i), {source: 'https://x.test/a.js', line: i + 1});
  t.flush();
  const events = sent.flatMap(b => b.events);
  assert.equal(events.length, client.MAX_EVENTS);
  for (const batch of sent) {
    assert.ok(JSON.stringify(batch).length <= client.MAX_BEACON_BYTES);
    assert.ok(batch.events.length <= MAX_EVENTS);
    parseBatch(batch);
  }
});

test('initTelemetry does nothing without a browser, or when the browser opts out', async () => {
  assert.equal(client.initTelemetry(), null, 'no window in Node');
  const saved = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const listeners = [];
  globalThis.window = globalThis;
  const original = {addEventListener: globalThis.addEventListener, document: globalThis.document};
  globalThis.addEventListener = (type) => listeners.push(type);
  globalThis.document = {addEventListener: (type) => listeners.push(type), querySelector: () => null};
  try {
    let beacons = 0;
    for (const nav of [{doNotTrack: '1', sendBeacon: () => { beacons++; return true; }}, {globalPrivacyControl: true, sendBeacon: () => { beacons++; return true; }}]) {
      Object.defineProperty(globalThis, 'navigator', {value: nav, configurable: true});
      assert.equal(client.initTelemetry(), null);
      client.track('map_viewed', {flush: true});
    }
    assert.equal(beacons, 0);
    assert.deepEqual(listeners, [], 'no listeners, no fetch wrapper when opted out');
  } finally {
    delete globalThis.window;
    Object.assign(globalThis, original);
    if (saved) Object.defineProperty(globalThis, 'navigator', saved);
  }
});
