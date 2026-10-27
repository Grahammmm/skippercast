// SP-MAP-NOW: synthetic producer-shaped fixtures, no acquisition or real storage.
// Shared by discovery, focused acceptance, and unchanged-module negative control.
import assert from 'node:assert/strict';
import test, {after} from 'node:test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {resolve, dirname} from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const option = name => process.argv.find(arg => arg.startsWith(`--${name}=`))?.slice(name.length + 3);
const baseline = option('baseline-root');
const moduleRoot = baseline ? resolve(baseline) : root;
const negative = !!baseline;
const descriptors = new Map(['fetch', 'localStorage', 'sessionStorage'].map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
let fetchCalls = 0;
const memoryStorage = () => {
  const values = new Map();
  return {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key), clear: () => values.clear()};
};
// Install BEFORE dynamic import, including any defaults captured by dependencies.
Object.defineProperty(globalThis, 'fetch', {configurable: true, writable: true, value: async () => {fetchCalls++; throw new Error('SP-MAP-NOW offline fetch refused');}});
Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: memoryStorage()});
Object.defineProperty(globalThis, 'sessionStorage', {configurable: true, value: memoryStorage()});
const outcomes = [];
let checks = 0;
const check = (actual, expected, message) => {checks++; assert.strictEqual(actual, expected, message);};
const deep = (actual, expected, message) => {checks++; assert.deepStrictEqual(actual, expected, message);};
function restore() {
  for (const [key, desc] of descriptors) {
    if (desc) Object.defineProperty(globalThis, key, desc);
    else delete globalThis[key];
  }
}
let sources, wrappers;
try {
  sources = await import(pathToFileURL(resolve(moduleRoot, 'packages/coast/src/map-sources.ts')).href);
  wrappers = await import(pathToFileURL(resolve(moduleRoot, 'web/map/frames.ts')).href);
} catch (error) {restore(); throw error;}
const {cloudSource, selectCurrentFrame, mapSourceHosts, naipSource} = sources;
const {currentFrame, cloudTiles} = wrappers;
const H = 3600000, MIN = 60000;
const T = Date.parse('2026-10-02T03:00:00Z');
const NOW = new Date(T);
const iso = ms => new Date(ms).toISOString();
const cell = {lat: 35.35, lon: -120.95, uMs: 0, vMs: 0.51, speedKnots: 1, towardDeg: 0};
const frame = ms => ({validAt: iso(ms), cells: [{...cell}]});
function forecast(patch = {}) {
  return {id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS', url: 'https://example.test/synthetic-current',
    fetchedAt: iso(T - H), issuedAt: iso(T - 24 * H), sampleAt: null, nativeResolutionKm: 4, sampleStride: 1,
    horizontalDatum: 'NAD83', surfaceOnly: true, frames: [frame(T), frame(T + 3 * H)],
    attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Synthetic surface-only fixture.', ...patch};
}
function observation(patch = {}) {
  return forecast({id: 'hfr-1', kind: 'observation', label: 'HF radar', issuedAt: null, sampleAt: iso(T - H),
    nativeResolutionKm: 1, frames: [frame(T - H), frame(T)], ...patch});
}
function cloud(at = iso(T - 7 * MIN)) {
  return {id: 'goes-longwave', kind: 'observation', observedAt: at, fetchedAt: iso(T - 5 * MIN), availableTimes: [at],
    layer: 'goes_longwave_imagery', url: 'https://example.test/synthetic-cloud', attribution: 'NOAA / NESDIS · GOES',
    license: 'public-domain-us-gov', limitations: 'Synthetic observations only.'};
}
function caseTest(name, fn) {
  test(name, () => {
    try {fn(); outcomes.push({name, status: 'PASS'});}
    catch (error) {outcomes.push({name, status: 'UNEXPECTED_FAILURE', error: String(error)}); throw error;}
  });
}
function refuses(name, call, intended = false) {
  test(name, () => {
    try {
      // A throw is a setup/behavior failure, NEVER the NaN-comparison negative.
      const result = call();
      checks++;
      try {assert.strictEqual(result, null, name);}
      catch (error) {
        if (negative && intended && result !== null && typeof result === 'object' && error.code === 'ERR_ASSERTION') {
          outcomes.push({name, status: 'INTENDED_NEGATIVE_FAILURE', reason: 'returned non-null', actual: result, assertion: error.message});
          return;
        }
        throw error;
      }
      if (negative && intended) throw new Error('baseline unexpectedly passed the invalid-clock refusal assertion');
      outcomes.push({name, status: 'PASS'});
    } catch (error) {outcomes.push({name, status: 'UNEXPECTED_FAILURE', error: String(error)}); throw error;}
  });
}
const badDates = [
  ['label', () => new Date('invalid decision clock')], ['NaN', () => new Date(NaN)],
  ['Infinity', () => new Date(Infinity)], ['finite-positive-out-of-range', () => new Date(8640000000000001)],
  ['finite-negative-out-of-range', () => new Date(-8640000000000001)],
];
function invalidCases(label, make, intended) {
  refuses(`${label}/cloud`, () => cloudSource(cloud(), make()), intended);
  refuses(`${label}/forecast`, () => selectCurrentFrame(forecast(), NOW, make()), intended);
  refuses(`${label}/observation`, () => selectCurrentFrame(observation(), NOW, make()));
  refuses(`${label}/cloudTiles`, () => {const c = cloud(); return cloudTiles(c, c.observedAt, make());}, intended);
  refuses(`${label}/currentFrame-forecast`, () => currentFrame(forecast(), NOW, make()), intended);
  refuses(`${label}/currentFrame-observation`, () => currentFrame(observation(), NOW, make()));
}
for (const [label, make] of badDates) invalidCases(`invalid-date/${label}`, make, true);
// Negative specifically proves the NaN comparison defect, not baseline TypeErrors.
if (!negative) for (const [label, value] of [['null', null], ['number', T], ['string', iso(T)], ['getTime-object', {getTime: () => T}]]) {
  invalidCases(`non-date/${label}`, () => value, false);
}
caseTest('preserved/ordinary-valid-and-expired-controls', () => {
  const f = forecast(), o = observation(), c = cloud();
  check(selectCurrentFrame(f, NOW, NOW), f.frames[0]);
  check(currentFrame(f, NOW, NOW), f.frames[0]);
  check(selectCurrentFrame(o, NOW, NOW), o.frames[1]);
  check(cloudSource(c, NOW)?.tileSize, 512);
  check(cloudTiles(c, c.observedAt, NOW)?.tileSize, 512);
  const expired = new Date(T + 48 * H);
  check(selectCurrentFrame(f, NOW, expired), null);
  check(selectCurrentFrame(o, NOW, expired), null);
  check(currentFrame(f, NOW, expired), null);
  check(cloudSource(c, expired), null);
  check(cloudTiles(c, c.observedAt, expired), null);
});
for (const [label, age, expected] of [['old-equality', 90 * MIN, true], ['old-plus-1ms', 90 * MIN + 1, false],
  ['ahead-equality', -5 * MIN, true], ['ahead-plus-1ms', -5 * MIN - 1, false]]) {
  caseTest(`cloud-boundary/${label}`, () => {
    const c = cloud(iso(T - age));
    check(cloudSource(c, NOW) !== null, expected);
    check(cloudTiles(c, c.observedAt, NOW) !== null, expected);
  });
}
for (const kind of ['forecast', 'observation']) {
  for (const [label, age, expected] of [['old-equality', 6 * H, true], ['old-plus-1ms', 6 * H + 1, false],
    ['ahead-equality', -5 * MIN, true], ['ahead-plus-1ms', -5 * MIN - 1, false]]) {
    caseTest(`fetched-boundary/${kind}/${label}`, () => {
      const f = (kind === 'forecast' ? forecast : observation)({fetchedAt: iso(T - age)});
      check(selectCurrentFrame(f, NOW, NOW), expected ? f.frames[kind === 'forecast' ? 0 : 1] : null);
      check(currentFrame(f, NOW, NOW), expected ? f.frames[kind === 'forecast' ? 0 : 1] : null);
    });
  }
}
for (const [label, age, expected] of [['old-equality', 36 * H, true], ['old-plus-1ms', 36 * H + 1, false],
  ['ahead-equality', -5 * MIN, true], ['ahead-plus-1ms', -5 * MIN - 1, false]]) {
  caseTest(`issued-boundary/${label}`, () => {
    const f = forecast({issuedAt: iso(T - age)});
    check(selectCurrentFrame(f, NOW, NOW), expected ? f.frames[0] : null);
    check(currentFrame(f, NOW, NOW), expected ? f.frames[0] : null);
  });
}
for (const [label, selected, index] of [['90min-equality', T + 90 * MIN, 0], ['90min-plus-1ms', T + 90 * MIN + 1, null],
  ['before-first', T - 1, null], ['after-last', T + 6 * H + 1, null]]) {
  caseTest(`nearest/${label}`, () => {
    const f = forecast({frames: [frame(T), frame(T + 6 * H)]});
    check(selectCurrentFrame(f, new Date(selected), NOW), index === null ? null : f.frames[index]);
    check(currentFrame(f, new Date(selected), NOW), index === null ? null : f.frames[index]);
  });
}
caseTest('nearest/tie-order-native-identity-and-empty', () => {
  const f = forecast();
  check(selectCurrentFrame(f, new Date(T + 90 * MIN), NOW), f.frames[0]);
  check(selectCurrentFrame(f, iso(T + 90 * MIN), NOW), f.frames[0]);
  check(currentFrame(f, new Date(T + 90 * MIN), NOW), f.frames[0]);
  f.frames[0].cells = [];
  check(selectCurrentFrame(f, NOW, NOW), null);
});
caseTest('observation/historical-future-and-reverse-order', () => {
  const o = observation();
  check(selectCurrentFrame(o, new Date(T - 30 * MIN), NOW), o.frames[0]);
  check(currentFrame(o, new Date(T - 30 * MIN), NOW), o.frames[0]);
  check(selectCurrentFrame(o, new Date(T + 5 * MIN), NOW), o.frames[1]);
  check(selectCurrentFrame(o, new Date(T + 5 * MIN + 1), NOW), null);
  check(selectCurrentFrame(o, new Date(T - H - 1), NOW), null);
  const duplicate = frame(T);
  o.frames.push(duplicate);
  check(selectCurrentFrame(o, NOW, NOW), duplicate, 'existing reverse-order observation tie behavior');
});
for (const [label, age, good] of [['6h-equality', 6 * H, true], ['6h-plus-1ms', 6 * H + 1, false]]) {
  caseTest(`observation/frame-age/${label}`, () => {
    const o = observation({frames: [frame(T - age)]});
    check(selectCurrentFrame(o, NOW, NOW), good ? o.frames[0] : null);
    check(currentFrame(o, NOW, NOW), good ? o.frames[0] : null);
  });
  caseTest(`observation/selected-frame-gap/${label}`, () => {
    const o = observation({frames: [frame(T)]});
    const clock = new Date(T + age);
    o.fetchedAt = iso(clock.getTime());
    check(selectCurrentFrame(o, clock, clock), good ? o.frames[0] : null);
  });
}
caseTest('preserved/encoding-fixed-hosts-and-input-immutability', () => {
  const at = '2026-10-02T03:00:00+00:00', c = cloud(at), f = forecast(), o = observation();
  const before = structuredClone([c, f, o]);
  const source = cloudSource(c, NOW);
  check(source.tiles[0].split('&time=')[1], encodeURIComponent(at));
  check(new URL(source.tiles[0]).origin, 'https://nowcoast.noaa.gov');
  deep(mapSourceHosts, ['https://imagery.nationalmap.gov', 'https://nowcoast.noaa.gov']);
  check(new URL(naipSource().tiles[0]).origin, 'https://imagery.nationalmap.gov');
  check(cloudTiles(c, at, NOW).tiles[0], source.tiles[0]);
  check(cloudSource({...c, availableTimes: []}, NOW), null);
  selectCurrentFrame(f, NOW, NOW); selectCurrentFrame(o, NOW, NOW);
  currentFrame(f, NOW, NOW); currentFrame(o, NOW, NOW);
  deep([c, f, o], before);
});
caseTest('defaults/omitted-and-undefined-remain-current-real-clock', () => {
  // No replacement global Date: exercise the original bound default arguments.
  const t = Date.now(), c = cloud(iso(t - MIN));
  const f = forecast({fetchedAt: iso(t - MIN), issuedAt: iso(t - H), frames: [frame(t)]});
  const o = observation({fetchedAt: iso(t - MIN), sampleAt: iso(t - MIN), frames: [frame(t - MIN)]});
  check(cloudSource(c)?.tileSize, 512);
  check(cloudSource(c, undefined)?.tileSize, 512);
  check(selectCurrentFrame(f, new Date(t)), f.frames[0]);
  check(selectCurrentFrame(f, new Date(t), undefined), f.frames[0]);
  check(selectCurrentFrame(o, new Date(t)), o.frames[0]);
  check(selectCurrentFrame(o, new Date(t), undefined), o.frames[0]);
});
caseTest('preserved/offline-fetch-sentinel', () => check(fetchCalls, 0));
after(() => {
  restore();
  const counts = {test_cases: outcomes.length, assertion_checks: checks,
    intended_negative_failures: outcomes.filter(x => x.status === 'INTENDED_NEGATIVE_FAILURE').length,
    unexpected_failures: outcomes.filter(x => x.status === 'UNEXPECTED_FAILURE').length, skips: 0};
  console.log('SP_MAP_NOW_RESULT ' + JSON.stringify({schema_version: 1, negative, counts, fetch_calls: fetchCalls, outcomes}));
});
