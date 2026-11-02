import test from 'node:test';
import assert from 'node:assert/strict';
import {viewSteps, createTelemetry} from '../web/telemetry.ts';
import {region} from '../web/state.ts';
globalThis.REGIONS = {'morro-bay': {}, 'half-moon-bay': {}};
globalThis.DEPLOYMENT = {allowed_origins: ['https://skippercast.com']};
const {parseBatch} = await import('../server/telemetry.ts');

const sequence = ['morro-bay', 'morro-bay', 'half-moon-bay', 'morro-bay'];
test('views count once per region in encounter order, independently per page', () => {
  const sent = [], view = viewSteps((...event) => sent.push(event));
  sequence.forEach(view);
  assert.deepEqual(sent, [['map_viewed', 'morro-bay'], ['map_viewed', 'half-moon-bay']]);
  viewSteps((...event) => sent.push(event))('morro-bay');
  assert.equal(sent.length, 3);
});

test('invalid regions never send or consume the ten-region cap', () => {
  const sent = [], view = viewSteps((...event) => sent.push(event));
  ['', null, undefined, 5, 'Morro Bay', '../x', 'x'.repeat(41), 'morro-bay\n', {}, 'a_b'].forEach(view);
  assert.equal(sent.length, 0);
  for (let i = 0; i < 11; i++) { view(`r-${i}`); view(`r-${i}`); }
  assert.deepEqual(sent, Array.from({length: 10}, (_, i) => ['map_viewed', `r-${i}`]));
});

test('map views batch in the existing server contract with no additional fields', () => {
  for (const source of ['', 'txt']) {
    const sent = [];
    const telemetry = createTelemetry({send: body => { sent.push(JSON.parse(body)); return true; },
      build: '0123456789', source: () => source, schedule: () => {}});
    sequence.forEach(viewSteps((name, region) => telemetry.track(name, {region})));
    telemetry.flush();
    assert.deepEqual(sent, [{build: '0123456789', events: ['morro-bay', 'half-moon-bay'].map(region =>
      ({type: 'funnel', name: 'map_viewed', region, ...(source ? {source} : {})}))}]);
    assert.doesNotThrow(() => parseBatch(sent[0]));
  }
});

async function browser(t, nav = {}) {
  const sent = [], listeners = [], timers = [];
  const originals = new Map();
  const globals = {
    window: {}, navigator: {sendBeacon: (...args) => { sent.push(args); return true; }, ...nav},
    document: {querySelector: () => null, addEventListener: type => listeners.push(type)},
    location: {href: 'https://skippercast.com/map?s=txt', origin: 'https://skippercast.com'},
    addEventListener: type => listeners.push(type), setTimeout: run => { timers.push(run); return 1; },
  };
  for (const [key, value] of Object.entries(globals)) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, {value, configurable: true, writable: true});
  }
  const previous = region.peek();
  region.value = 'morro-bay';
  t.after(() => {
    region.value = previous;
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
  });
  const client = await import(`../web/telemetry.ts?view-test=${t.name}`);
  return {client, sent, listeners, timers};
}

for (const nav of [{globalPrivacyControl: true}, {doNotTrack: '1'}, {sendBeacon: undefined}]) {
  test(`views stay inactive with ${JSON.stringify(nav)}`, async t => {
    const {client, sent, listeners, timers} = await browser(t, nav);
    assert.equal(client.initTelemetry({views: true}), null);
    region.value = 'half-moon-bay';
    client.track('map_viewed', {flush: true});
    assert.deepEqual([sent, listeners, timers], [[], [], []]);
  });
}

test('default initialization never queues views on initial or changed region', async t => {
  const {client, sent, timers} = await browser(t);
  const telemetry = client.initTelemetry();
  assert.ok(telemetry);
  region.value = 'half-moon-bay';
  assert.equal(telemetry.pending, 0);
  telemetry.flush();
  assert.deepEqual([sent, timers], [[], []]);
});

test('opt-in follows the signal once per region and repeated initialization is idempotent', async t => {
  const {client, sent} = await browser(t);
  const telemetry = client.initTelemetry({views: true});
  assert.equal(telemetry.pending, 1);
  assert.equal(client.initTelemetry({views: true}), telemetry);
  region.value = 'half-moon-bay';
  region.value = 'morro-bay';
  region.value = '../x';
  telemetry.flush();
  assert.equal(sent.length, 1);
  assert.equal(sent[0][0], '/api/telemetry');
  assert.deepEqual(JSON.parse(sent[0][1]).events, ['morro-bay', 'half-moon-bay'].map(region =>
    ({type: 'funnel', name: 'map_viewed', region, source: 'txt'})));
});
