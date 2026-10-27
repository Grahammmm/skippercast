// SP-BAR-EVENTS: offline actual-module tests; also a pre-import guard for the named regressions.
import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import fixture from './fixtures/sp_bar_events/events.json' with {type: 'json'};

const originalGlobals = new Map(['fetch', 'localStorage', 'sessionStorage'].map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
let fetchCalls = 0, storageCalls = 0, assertionChecks = 0;
const originals = new Map();
for (const name of ['equal', 'notEqual', 'deepEqual', 'notDeepEqual', 'ok', 'match', 'doesNotMatch', 'throws', 'doesNotThrow', 'rejects', 'doesNotReject', 'fail']) {
  originals.set(name, assert[name]);
  assert[name] = (...args) => {assertionChecks++; return originals.get(name)(...args);};
}
Object.defineProperty(globalThis, 'fetch', {configurable: true, writable: true, value: async () => {fetchCalls++; throw Error('Offline fetch forbidden');}});
for (const name of ['localStorage', 'sessionStorage']) {
  const values = new Map();
  Object.defineProperty(globalThis, name, {configurable: true, value: {
    getItem: k => {storageCalls++; return values.get(k) ?? null;},
    setItem: (k, v) => {storageCalls++; values.set(k, String(v));},
    removeItem: k => {storageCalls++; values.delete(k);},
    clear: () => {storageCalls++; values.clear();},
    key: i => [...values.keys()][i] ?? null,
    get length() {return values.size;},
  }});
}
const results = [];
after(() => {
  for (const [name, descriptor] of originalGlobals) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor);
    else delete globalThis[name];
  }
  for (const [name, fn] of originals) assert[name] = fn;
});
process.on('exit', () => console.log('SP_BAR_EVENTS_JSON ' + JSON.stringify({results, assertion_checks: assertionChecks, fetch_calls: fetchCalls, storage_calls: storageCalls, runtime: process.version})));

// --import loads only the guards, before any regression module or bound defaults.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const {barTide, barBand, barHours, BAR_CHECK} = await import('../packages/coast/src/bar-conditions.ts');
  const negative = process.argv.includes('--negative');
  const unknown = {stage: null, midEbb: false, fraction: null};
  const ebb = {stage: 'ebb', midEbb: true, fraction: 0.5};
  const flood = {stage: 'flood', midEbb: false, fraction: 0.5};
  const [high, low, high2, low2] = fixture.events;
  const start = Date.parse(high.at), duration = Date.parse(low.at) - start, mid = start + duration / 2;
  const conflicting = [{...high, type: 'L'}, high, {...low, type: 'H'}];
  const reversed = [high, {...high, type: 'L'}, {...low, type: 'H'}];
  const cases = [];
  const add = (id, fn, baseline = false) => {if (!negative || baseline) cases.push({id, fn});};
  add('A4-X-to-H', detail => {
    detail.actual = barTide(mid, [{...high, type: 'X'}, {...low, type: 'H'}]);
    assert.deepEqual(detail.actual, unknown);
  }, true);
  add('A4-permutation-invariance', detail => {
    detail.first = barTide(mid, conflicting); detail.second = barTide(mid, reversed);
    assert.deepEqual(detail.first, detail.second);
  }, true);
  add('control-unknown-permutation', detail => {
    detail.actual = barTide(mid, conflicting);
    assert.deepEqual(detail.actual, unknown);
  }, true);
  add('control-ebb', detail => {
    detail.actual = barTide(mid, [high, low]); assert.deepEqual(detail.actual, ebb);
  }, true);
  add('control-flood', detail => {
    detail.actual = barTide(Date.parse(low.at) + duration / 2, [low, high2]); assert.deepEqual(detail.actual, flood);
  }, true);
  add('null-observation', detail => {
    // Baseline exception is a separate observation, NEVER an intended ambiguity failure.
    try {detail.actual = barTide(mid, [null, high, low]);}
    catch (error) {detail.exception = {name: error.name, message: error.message};}
    assert.ok(detail.exception?.name === 'TypeError' || JSON.stringify(detail.actual) === JSON.stringify(ebb));
  }, true);
  add('A1-malformed-rows', () => {
    const malformed = [null, undefined, false, 3, 'H', [], [high.at, 'H'], {}, {at: high.at}, {at: high.at, type: 'h'}, {at: high.at, type: 'X'}, {at: 'bad', type: 'L'}, {at: 0, type: 'H'}, {at: new Date(high.at), type: 'H'}];
    for (const row of malformed) {
      assert.deepEqual(barTide(mid, [row, low]), unknown);
      assert.deepEqual(barTide(mid, [high, low, row]), ebb);
    }
    assert.deepEqual(barTide(mid, malformed), unknown);
    const sparse = [high, , low];
    assert.deepEqual(barTide(mid, sparse), ebb);
    assert.deepEqual(barTide(mid, [null, high, low]), ebb);
  });
  add('A1-nonfinite-and-missing-boundaries', () => {
    for (const at of [NaN, Infinity, -Infinity]) assert.deepEqual(barTide(at, [high, low]), unknown);
    for (const events of [[], [high], [low]]) assert.deepEqual(barTide(mid, events), unknown);
    assert.deepEqual(barTide(start - 1, [high, low]), unknown);
    assert.deepEqual(barTide(Date.parse(low.at), [high, low]), unknown);
  });
  add('A2-conflict-at-either-chosen-boundary', () => {
    const nextConflict = [high, low, {...low, type: 'H'}, high2];
    for (const rows of [conflicting, reversed, nextConflict, [...nextConflict].reverse()]) assert.deepEqual(barTide(mid, rows), unknown);
    // A wider valid bracket must NOT hide an intervening conflicting group.
    const outer = {...high, at: new Date(start - duration).toISOString(), type: 'L'};
    for (const rows of [[outer, ...conflicting, high2], [outer, ...reversed, high2]]) assert.deepEqual(barTide(mid, rows), unknown);
    assert.deepEqual(barTide(start, conflicting), unknown);
    assert.deepEqual(barTide(start - 1, [outer, ...conflicting]), unknown);
    // Unselected conflicting groups do not invalidate an otherwise genuine bracket.
    assert.deepEqual(barTide(mid, [high, low, high2, {...high2, type: 'L'}]), ebb);
  });
  add('A2-duplicates-same-type-and-input-preservation', () => {
    const rows = [low, high, {...high}, {...low}];
    const saved = structuredClone(rows);
    assert.deepEqual(barTide(mid, rows), ebb);
    assert.deepEqual(rows, saved);
    assert.deepEqual(barTide(mid, [high, {...low, type: 'H'}]), unknown);
    assert.deepEqual(barTide(mid, [{...high, type: 'L'}, low]), unknown);
    assert.deepEqual(barTide(mid, [high, {...high, at: '2026-10-08T17:00:00-07:00', type: 'L'}, low]), unknown);
  });
  add('A3-thresholds-rounding-and-exact-events', () => {
    for (const [fraction, midEbb] of [[0, false], [0.249, false], [0.25, true], [0.5, true], [0.75, true], [0.751, false], [0.999, false]]) {
      assert.deepEqual(barTide(start + duration * fraction, [high, low]), {stage: 'ebb', midEbb, fraction: Number(fraction.toFixed(2))});
    }
    assert.deepEqual(barTide(start + duration / 3, [high, low]), {stage: 'ebb', midEbb: true, fraction: 0.33});
    assert.deepEqual(barTide(Date.parse(low.at), [high, low, high2]), {stage: 'flood', midEbb: false, fraction: 0});
    assert.deepEqual(barTide(Date.parse(high2.at), [low, high2, low2]), {stage: 'ebb', midEbb: false, fraction: 0});
  });
  add('A3-consumer-hazard-and-unknown-never-safe', () => {
    const bad = barTide(mid, reversed);
    const swell = heightFt => ({heightFt, periodS: 10, basis: 'nearshore', longPeriodS: null});
    for (const [height, band] of [[1, 'Unknown'], [2, 'Caution'], [8, 'Hazardous']]) {
      const reading = barBand(bad, swell(height), false);
      assert.equal(reading.band, band); assert.ok(reading.reasons.includes('tide phase unknown'));
      assert.doesNotMatch(reading.reasons.join(' '), /\bsafe\b/i);
    }
    assert.equal(barBand(barTide(mid, [high, low]), swell(4), false).band, 'Hazardous');
    assert.equal(barBand(barTide(mid + duration, [low, high2]), swell(1), false).band, 'No bar flag');
    assert.equal(barBand(bad, {heightFt: null, periodS: null, basis: null, longPeriodS: null}, false).band, 'Unknown');
    const input = {hours: [fixture.hour], site: undefined, entrance: {name: 'synthetic entrance', seawardDeg: 260}};
    const valid = barHours({...input, tideEvents: [high, low]})[0];
    assert.equal(valid.band, 'Hazardous'); assert.equal(valid.windAgainst, true);
    const invalid = barHours({...input, tideEvents: reversed})[0];
    assert.deepEqual(invalid.tide, unknown); assert.equal(invalid.band, 'Caution'); assert.equal(invalid.windAgainst, false);
    assert.match(BAR_CHECK, /rough estimate rather than an official bar report/);
    assert.match(BAR_CHECK, /check the Coast Guard bar status/);
  });
  for (const {id, fn} of cases) test(id, () => {
    const detail = {}, before = assertionChecks;
    try {fn(detail); results.push({id, status: 'PASS', detail, assertion_checks: assertionChecks - before});}
    catch (error) {results.push({id, status: 'FAIL', detail, error: {name: error.name, code: error.code}, assertion_checks: assertionChecks - before}); throw error;}
  });
}
