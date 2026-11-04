// Client telemetry beacons are budgeted in UTF-8 bytes (RF1110-4): the server
// rejects a body over 4096 bytes, so non-ASCII error text must never push a
// beacon past MAX_BEACON_BYTES, while order, the batch ceiling and queue
// progress stay as before. All fixtures are synthetic; nothing is sent.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {parseBatch, MAX_BODY} = await import('../server/telemetry.ts');
const client = await import('../web/telemetry.ts');

const BUILD = '0123456789';
const bytes = s => new TextEncoder().encode(s).byteLength;
const SOURCE = 'a'.repeat(77) + '.js';
const REQUEST_ID = 'r'.repeat(64);

function harness({send} = {}) {
  const raw = [], timers = [];
  const t = client.createTelemetry({
    send: send ?? (body => { raw.push(body); return true; }),
    build: BUILD, region: () => '', schedule: (run, ms) => timers.push({run, ms}),
  });
  const sent = () => raw.map(body => JSON.parse(body));
  return {t, raw, sent, timers};
}
const errorAt = (t, message, i) => t.error('error', new Error(message), {source: 'https://x.test/' + SOURCE, line: 12345 + i, column: 67890});
const messages = raw => raw.flatMap(body => JSON.parse(body).events.map(e => e.message));
/** The exact event the client queues for errorAt (key order matters for the byte count). */
const errorEvent = (message, i) => ({type: 'error', kind: 'error', message, source: SOURCE, line: 12345 + i, column: 67890, request_id: REQUEST_ID});
const envelope = events => JSON.stringify({build: BUILD, events});
const funnel = region => ({type: 'funnel', name: 'map_viewed', region});

const cjk = (prefix, n) => prefix + '語'.repeat(n - prefix.length);

test('telemetry_utf8_error_batches_fit_and_keep_every_event', () => {
  // The probe from the spec: five 200-character CJK errors with legal metadata (4231 UTF-8 bytes in one body).
  const {t, raw, sent} = harness();
  t.noteRequestId(REQUEST_ID);
  const wanted = [0, 1, 2, 3, 4].map(i => cjk(i + ':', 200));
  wanted.forEach((m, i) => errorAt(t, m, i));
  assert.ok(bytes(envelope(wanted.map(errorEvent))) > MAX_BODY, 'the unsplit body would exceed the server cap');
  t.flush();
  assert.ok(raw.length >= 2, 'the batch was split');
  for (const body of raw) {
    assert.ok(bytes(body) <= client.MAX_BEACON_BYTES, `${bytes(body)} bytes`);
    assert.ok(bytes(body) <= MAX_BODY);
    assert.doesNotThrow(() => parseBatch(JSON.parse(body)), 'the server accepts each beacon');
  }
  assert.deepEqual(messages(raw), wanted, 'every event sent once, in order');
  assert.equal(t.pending, 0);
  assert.deepEqual(sent().flatMap(b => b.events).map(e => e.line), [12345, 12346, 12347, 12348, 12349]);
});

test('telemetry_utf8_error_batches_fit_and_keep_every_event: ASCII, CJK and emoji mixtures', () => {
  const {t, raw} = harness();
  t.noteRequestId(REQUEST_ID);
  const wanted = [cjk('a:', 200), '😀'.repeat(100), 'b'.repeat(200), 'é'.repeat(100) + '語'.repeat(100), '🐟x'.repeat(66)];
  wanted.forEach((m, i) => errorAt(t, m, i));
  for (let i = 0; i < 5; i++) t.track('map_viewed', {region: 'region' + i});
  t.flush();
  for (const body of raw) assert.ok(bytes(body) <= client.MAX_BEACON_BYTES, `${bytes(body)} bytes`);
  const events = raw.flatMap(body => JSON.parse(body).events);
  assert.deepEqual(events.filter(e => e.type === 'error').map(e => e.message), wanted);
  assert.deepEqual(events.filter(e => e.type === 'funnel').map(e => e.region), [0, 1, 2, 3, 4].map(i => 'region' + i));
  assert.equal(events.length, 10, 'nothing dropped or duplicated');
  assert.equal(t.pending, 0);
});

test('telemetry_utf8_exact_boundary_and_one_byte_over', () => {
  // Four fixed CJK errors, then a fifth whose ASCII padding sets the body to exactly the cap, or one byte over.
  const first = [cjk('0:', 200), cjk('1:', 200), cjk('2:', 200), cjk('3:', 120)];
  const fifth = pad => '😀' + 'x'.repeat(pad);
  const bodyBytes = pad => bytes(envelope([...first.map(errorEvent), errorEvent(fifth(pad), 4)]));
  let pad = 0;
  while (bodyBytes(pad) < client.MAX_BEACON_BYTES) pad++;
  assert.equal(bodyBytes(pad), client.MAX_BEACON_BYTES, 'a padding length reaches the cap exactly');
  assert.ok(pad < 197, 'the fifth message stays a legal length');
  assert.ok(bytes(first.join('')) > client.MAX_BEACON_BYTES / 2, 'multi-byte characters dominate the body');

  for (const [label, n] of [['exact cap', pad], ['one byte under', pad - 1]]) {
    const {t, raw} = harness();
    t.noteRequestId(REQUEST_ID);
    [...first, fifth(n)].forEach((m, i) => errorAt(t, m, i));
    t.flush();
    assert.equal(raw.length, 1, label + ' stays together');
    assert.equal(raw[0], envelope([...first, fifth(n)].map(errorEvent)));
    assert.ok(bytes(raw[0]) <= client.MAX_BEACON_BYTES);
  }
  const {t, raw} = harness();
  t.noteRequestId(REQUEST_ID);
  [...first, fifth(pad + 1)].forEach((m, i) => errorAt(t, m, i));
  t.flush();
  assert.equal(bytes(envelope([...first.map(errorEvent), errorEvent(fifth(pad + 1), 4)])), client.MAX_BEACON_BYTES + 1);
  assert.equal(raw.length, 2, 'one byte over splits');
  assert.deepEqual(JSON.parse(raw[0]).events.map(e => e.message), first, 'split at an event boundary');
  assert.deepEqual(JSON.parse(raw[1]).events.map(e => e.message), [fifth(pad + 1)]);
  for (const body of raw) assert.ok(bytes(body) <= client.MAX_BEACON_BYTES);
});

test('telemetry_ascii_payload_and_batch_size_unchanged', () => {
  const small = harness();
  small.t.track('port_selected', {region: 'morro-bay'});
  small.t.error('error', new Error('boom'), {source: 'https://x.test/a.js', line: 3, column: 4});
  small.t.flush();
  assert.deepEqual(small.raw, [JSON.stringify({build: BUILD, events: [
    {type: 'funnel', name: 'port_selected', region: 'morro-bay'},
    {type: 'error', kind: 'error', message: 'boom', source: 'a.js', line: 3, column: 4}]})]);

  // The ten-event ceiling flushes by itself, in order; the rest follows on the timer.
  const {t, sent, timers} = harness();
  for (let i = 0; i < 12; i++) t.track('map_viewed', {region: 'r' + i});
  assert.deepEqual(sent().map(b => b.events.length), [10], 'the tenth event flushes one full batch');
  assert.equal(t.pending, 2);
  const timer = timers.at(-1);
  assert.equal(timer.ms, client.FLUSH_MS, 'a timer waits for the remaining events');
  timer.run();
  assert.deepEqual(sent().map(b => b.events.length), [10, 2]);
  assert.deepEqual(sent().flatMap(b => b.events).map(e => e.region), Array.from({length: 12}, (_, i) => 'r' + i));
  assert.equal(t.pending, 0);

  // flushNow, dedupe and the page cap are untouched.
  const more = harness();
  more.t.track('install', {flush: true});
  more.t.track('install', {flush: true});
  assert.equal(more.raw.length, 1, 'a repeated step is not sent twice');
  for (let i = 0; i < 40; i++) more.t.track('map_viewed', {region: 'q' + i});
  more.t.flush();
  assert.equal(more.sent().flatMap(b => b.events).length, client.MAX_EVENTS);
});

test('telemetry_oversized_singleton_is_dropped_and_later_events_progress', () => {
  // The envelope counts toward the cap: find the longest region that still fits, byte for byte.
  let fits = 1;
  while (bytes(envelope([funnel('r'.repeat(fits + 1))])) <= client.MAX_BEACON_BYTES) fits++;
  assert.equal(bytes(envelope([funnel('r'.repeat(fits))])), client.MAX_BEACON_BYTES);
  const tooBig = 'r'.repeat(fits + 1);
  assert.equal(bytes(envelope([funnel(tooBig)])), client.MAX_BEACON_BYTES + 1);

  const {t, raw, sent} = harness();
  t.track('map_viewed', {region: 'a'});
  t.track('map_viewed', {region: tooBig});
  t.track('map_viewed', {region: 'b'});
  t.track('map_viewed', {region: 'r'.repeat(fits)});
  t.track('map_viewed', {region: 'c'.repeat(2 * client.MAX_BEACON_BYTES)});
  t.track('map_viewed', {region: 'd'});
  t.flush();
  assert.deepEqual(sent().flatMap(b => b.events).map(e => e.region.slice(0, 1)), ['a', 'b', 'r', 'd'], 'oversized events dropped, the rest in order');
  for (const body of raw) assert.ok(bytes(body) <= client.MAX_BEACON_BYTES);
  assert.equal(t.pending, 0);
  assert.equal(raw.filter(body => body.includes(tooBig)).length, 0, 'no oversized beacon was sent');

  // A queue of nothing but oversized events drains without sending or hanging.
  const all = harness();
  all.t.track('map_viewed', {region: 'x'.repeat(5000)});
  all.t.track('map_viewed', {region: 'y'.repeat(5000), flush: true});
  all.t.flush();
  assert.equal(all.raw.length, 0);
  assert.equal(all.t.pending, 0);

  // The dropped event still counts toward the page total: MAX_EVENTS events are accepted, one of them dropped.
  const total = harness();
  total.t.track('map_viewed', {region: 'z'.repeat(5000)});
  for (let i = 0; i < 40; i++) total.t.track('map_viewed', {region: 'k' + i});
  total.t.flush();
  assert.equal(total.sent().flatMap(b => b.events).length, client.MAX_EVENTS - 1);
});

test('telemetry_utf8_send_failure_remains_best_effort', () => {
  for (const [label, fail] of [['false', () => false], ['throw', () => { throw new Error('refused'); }]]) {
    let calls = 0;
    const {t} = harness({send: () => { calls++; return fail(); }});
    t.noteRequestId(REQUEST_ID);
    [0, 1, 2, 3, 4].forEach(i => errorAt(t, cjk(i + ':', 200), i));
    assert.doesNotThrow(() => t.flush(), label);
    assert.ok(calls >= 2, 'each split beacon was tried once');
    const attempts = calls;
    assert.equal(t.pending, 0, 'a failed send leaves nothing queued');
    t.flush();
    assert.equal(calls, attempts, 'no retry and no duplicate');
  }
});
