import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const root = '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">';
const marker = label => Object.freeze({name: `SECRET-NAME-${label}-7f3`, note: `SECRET-NOTE-${label}-7f3`});
const point = (label, lat, lon) => Object.freeze({...marker(label), lat, lon});
const xmlPoint = (tag, {name, note, lat, lon}) =>
  `<${tag} lat="${lat}" lon="${lon}"><name>${name}</name><desc>${note}</desc></${tag}>`;

const good = point('GOOD', 0.007301, -0.007302);
const badSave = point('SAVE-REJECTED', 0.007361, -0.007362);
const refused = point('SCREEN-REFUSED', 0.007305, -0.007306);
const malformed = point('MALFORMED', 0.007307, -0.007308);
const mixed = point('MIXED', 0.007309, -0.007310);
const route = point('ROUTE', 0.007311, -0.007312);
const track = point('TRACK', 0.007313, -0.007314);
const saveError = 'SECRET-SAVE-ERROR-7f3';
const fixtures = [
  {
    label: 'good',
    xml: `${root}${[good, badSave, refused].map(w => xmlPoint('wpt', w)).join('')}</gpx>`,
    parsed: {ok: true, waypoints: [good, badSave, refused], rejected: [], ignoredTrackPoints: 0},
    screened: {ok: true, clear: [good, badSave], refused: [{waypoint: refused, reason: 'inside'}]},
    saved: {saved: 1, failed: [{index: 1, name: badSave.name, error: saveError}]},
  },
  {
    label: 'malformed',
    xml: `${root}${xmlPoint('wpt', malformed)}`, // Complete point, missing root close: no partial output.
    parsed: {ok: false, error: {code: 'invalid-xml', message: 'The GPX file is not well-formed XML.'}},
    screened: {ok: true, clear: [], refused: []},
    saved: {saved: 0, failed: []},
  },
  {
    label: 'route and track',
    xml: `${root}${xmlPoint('wpt', mixed)}<rte>${xmlPoint('rtept', route)}</rte>`
      + `<trk><trkseg>${xmlPoint('trkpt', track)}</trkseg></trk></gpx>`,
    parsed: {ok: true, waypoints: [mixed], rejected: [
      {index: 2, element: 'rtept', name: route.name, reason: 'route-point-not-imported'},
    ], ignoredTrackPoints: 1},
    screened: {ok: true, clear: [mixed], refused: []},
    saved: {saved: 1, failed: []},
  },
];

// Don't touch real storage (including Node's lazy storage getter). Record both
// the Storage methods and direct property access/assignment on the replacement.
function recordingStorage(record) {
  return new Proxy({}, {
    get(_, key) {
      if (['getItem', 'setItem', 'removeItem', 'clear', 'key'].includes(key)) {
        return (...args) => record(key, ...args);
      }
      record('get', key);
    },
    set(_, key, value) { record('set', key, value); return true; },
    defineProperty(_, key, descriptor) { record('define', key, descriptor); return true; },
    deleteProperty(_, key) { record('delete', key); return true; },
  });
}

// A trace added to any stage (including the parse-error or save-rejection path)
// must fail even if every returned value and save attempt is still correct.
test('C1: synthetic GPX stays off output channels, including on rejected saves', async t => {
  const channels = ['log', 'info', 'warn', 'error', 'debug'].map(key => [`console.${key}`, console, key]);
  channels.push(['fetch', globalThis, 'fetch']);
  const navigator = globalThis.navigator;
  if (typeof navigator?.sendBeacon === 'function') channels.push(['sendBeacon', navigator, 'sendBeacon']);
  channels.push(['localStorage', globalThis, 'localStorage', recordingStorage],
    ['sessionStorage', globalThis, 'sessionStorage', recordingStorage]);
  const bindings = [...channels.map(([, target, key]) => [target, key]),
    [globalThis, 'console'], [globalThis, 'navigator']];
  const snapshot = () => bindings.map(([target, key]) => Object.getOwnPropertyDescriptor(target, key));
  const before = snapshot();
  const beaconBefore = navigator?.sendBeacon;

  try {
    const calls = channels.map(() => []);
    for (const [i, [, target, key, wrap]] of channels.entries()) {
      const record = (...args) => { calls[i].push(args); };
      Object.defineProperty(target, key, {configurable: true, value: wrap ? wrap(record) : record});
    }
    const {readGpxWaypoints} = await import('../web/gpx-waypoints.ts');
    const {screenGpxCandidates} = await import('../web/gpx-import-screen.ts');
    const {planGpxImport, saveSequentially} = await import('../web/gpx-import-plan.ts');
    for (const fixture of fixtures) {
      const {label} = fixture;
      const parsed = readGpxWaypoints(fixture.xml);
      assert.deepEqual(parsed, fixture.parsed, label);
      const screenCalls = [];
      const screened = screenGpxCandidates(parsed.ok ? parsed.waypoints : [], {
        checkedAt: 1000,
        verdict(...args) {
          screenCalls.push(args);
          return {inside: args[0].latitude === refused.lat};
        },
        refused: verdict => verdict.inside,
      }, 1000);
      assert.deepEqual(screened, fixture.screened, label);
      assert.deepEqual(screenCalls, (fixture.parsed.waypoints ?? []).map(({lat, lon}) =>
        [{latitude: lat, longitude: lon}]), label);
      const plan = planGpxImport([], screened.clear);
      assert.deepEqual(plan, {save: fixture.screened.clear, duplicates: [], invalid: []}, label);
      const saveCalls = [];
      const saved = await saveSequentially(plan.save, async (...args) => {
        saveCalls.push(args);
        if (args[0].name === badSave.name) throw new Error(saveError);
      });
      assert.deepEqual(saved, fixture.saved, label);
      assert.deepEqual(saveCalls, fixture.screened.clear.map(w => [w]), label);
      for (const [i, [channel]] of channels.entries()) assert.deepEqual(calls[i], [], `${label}: ${channel}`);
    }
  } finally {
    for (const [i, [, target, key]] of channels.entries()) {
      if (before[i]) Object.defineProperty(target, key, before[i]);
      else delete target[key];
    }
    // Installing an own shim over an absent/inherited property must not leave it behind.
    await t.test('C3: restores the original globals and property descriptors', () => {
      const after = snapshot();
      assert.deepEqual(after, before);
      for (const [i, descriptor] of after.entries()) assert.equal(descriptor?.value, before[i]?.value);
      assert.equal(navigator?.sendBeacon, beaconBefore);
    });
  }
});

// Catch a forbidden API or dependency even on a path the fixtures don't take.
test('C2: GPX import sources have no output APIs or outside imports', () => {
  const banned = ['console.', 'fetch(', 'sendBeacon', 'localStorage', 'sessionStorage', 'indexedDB',
    'analytics', 'telemetry', 'XMLHttpRequest', 'WebSocket'];
  const gap = String.raw`(?:\s|/\*[\s\S]*?\*/|//[^\r\n]*)*`;
  const imports = new RegExp(String.raw`\b(?:from|import)${gap}(['"])([^'"\r\n]+)\1`, 'g');
  const loaders = new RegExp(String.raw`\b(?:import|require)${gap}\(`, 'g');
  for (const file of ['gpx-waypoints.ts', 'gpx-import-screen.ts', 'gpx-import-plan.ts']) {
    const source = readFileSync(new URL(`../web/${file}`, import.meta.url), 'utf8');
    const outside = [...source.matchAll(imports)].map(match => match[2])
      .filter(path => !/^\.\/gpx-[\w-]+\.ts$/.test(path));
    // The pure modules use declarative imports; non-declarative loading is not allowed.
    assert.deepEqual({
      tokens: banned.filter(token => source.includes(token)),
      outside,
      loaders: source.match(loaders) ?? [],
    }, {tokens: [], outside: [], loaders: []}, file);
  }
});
