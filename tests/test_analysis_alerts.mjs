import test from 'node:test';
import assert from 'node:assert/strict';
import {ANALYSIS_LAYERS, analysisAlertCandidates} from '../server/analysis-alerts.ts';

const sst = 'sst-analysis';
const chl = 'chlorophyll-observation';
const wave = 'wave-forecast';
const morning = '2026-11-19T08:00:00Z';
const noon = '2026-11-19T04:00:00-08:00';
const evening = '2026-11-19T20:00:00Z';
const sub = {owner: 'owner-A', region: 'bay', layers: [sst]};
const row = sampleAt => ({bay: {[sst]: sampleAt}});
const alert = (owner, region, layer, sampleAt) => ({owner, region, layer, sampleAt});
const bayAlert = sampleAt => alert('owner-A', 'bay', sst, sampleAt);

// A catalog or forecast layer must not slip into the public allowlist.
test('C1: exports exactly the two analysis layer IDs', () => {
  assert.deepEqual(ANALYSIS_LAYERS, ['sst-analysis', 'chlorophyll-observation']);
});

// Bad rows must not throw, get coerced, or poison good rows in the same call.
test('C2: malformed subscriptions and samples are isolated', () => {
  const broken = {region: 'bay', layers: [sst], get owner() { throw new Error('unreadable'); }};
  const current = {...row(morning), bad: {[sst]: 42}, unreadable: {
    get [sst]() { throw new Error('unreadable'); },
    [chl]: evening,
  }};
  const previous = {badPrior: null, badRow: [], badValue: {[sst]: null}};
  assert.deepEqual(analysisAlertCandidates({subscriptions: [
    null, broken, {...sub, owner: 2}, {...sub, region: []}, {...sub, layers: sst},
    {...sub, region: 'bad'}, {...sub, region: 'badPrior'}, {...sub, region: 'badRow'},
    {...sub, region: 'badValue'}, {...sub, region: 'unreadable', layers: [sst, chl]},
    {...sub, layers: [null, sst]},
  ], previous, current: {...current, badPrior: row(morning).bay, badRow: row(morning).bay, badValue: row(morning).bay}}), [
    bayAlert(morning), alert('owner-A', 'unreadable', chl, evening),
  ]);
});

test('C2: missing collections and empty subscriptions yield no candidates', () => {
  const {proxy, revoke} = Proxy.revocable([], {});
  revoke();
  for (const input of [null, {}, {subscriptions: proxy}, {subscriptions: [sub], previous: {}},
    {subscriptions: [sub], current: row(morning)}, {subscriptions: [], previous: {}, current: row(morning)}]) {
    assert.deepEqual(analysisAlertCandidates(input), []);
  }
  assert.deepEqual(analysisAlertCandidates({subscriptions: [sub], previous: {bay: proxy}, current: row(morning)}), []);
});

// Replays, out-of-order arrivals, and equal offsets must all suppress a candidate.
test('C3: compares instants, not timestamp spellings or calendar dates', () => {
  for (const [previous, current, expected] of [
    [{}, row(morning), [bayAlert(morning)]],
    [{bay: {[chl]: morning}}, row(morning), [bayAlert(morning)]],
    [row(morning), row(morning), []],
    [row(evening), row(noon), []],
    [row('2026-11-19T12:00:00Z'), row(noon), []],
    [row(morning), row(noon), [bayAlert(noon)]],
    [row(noon), row(evening), [bayAlert(evening)]],
    [row('2026-11-19T12:00:00.0001Z'), row('2026-11-19T12:00:00.0002Z'), [bayAlert('2026-11-19T12:00:00.0002Z')]],
    [row('2026-11-19T12:00:00.0002Z'), row('2026-11-19T12:00:00.00020Z'), []],
  ]) {
    assert.deepEqual(analysisAlertCandidates({subscriptions: [sub], previous, current}), expected);
  }
});

// Seeing an analysis in another region or in an unrequested layer is not enough.
test('C3: requires both the region sample and a subscribed analysis layer', () => {
  const current = {bay: {[sst]: morning, [chl]: noon, [wave]: evening}};
  assert.deepEqual(analysisAlertCandidates({subscriptions: [
    {...sub, layers: [sst, wave]}, {...sub, region: 'other'},
  ], previous: {}, current}), [bayAlert(morning)]);
  assert.deepEqual(analysisAlertCandidates({subscriptions: [sub], previous: {}, current: {bay: {[chl]: noon}}}), []);
});

// Date.parse alone accepts date-only, local, legacy and rolled-over dates.
test('C3: rejects malformed current and previous instants independently', () => {
  for (const invalid of ['not a date', '2026-11-19', '2026-11-19T08:00:00', 'Nov 19 2026 UTC',
    '2026-02-29T08:00:00Z', '2026-11-19T08:00:00+25:00', '2026-11-19T24:00:00.01Z',
    '2026-11-19T08:00.1Z', `${morning}\n`]) {
    assert.deepEqual(analysisAlertCandidates({subscriptions: [sub], previous: {}, current: row(invalid)}), [], invalid);
    assert.deepEqual(analysisAlertCandidates({subscriptions: [sub], previous: row(invalid), current: row(evening)}), [], invalid);
  }
});

// Locale sorting, owner-only de-duplication and delimiter-based keys can drop or reorder rows.
test('C4: coalesces exact triples and orders them by plain string order', () => {
  const subscriptions = [
    {owner: 'a', region: 'Z', layers: [sst]},
    {owner: 'A', region: 'a', layers: [sst]},
    {owner: 'A', region: 'Z', layers: [sst, chl, sst]},
    {owner: 'A', region: 'Z', layers: [chl]},
    {owner: 'A', region: 'Z', layers: [sst, chl, sst]},
    {owner: 'A|B', region: 'C', layers: [sst]},
    {owner: 'A', region: 'B|C', layers: [sst]},
  ];
  const current = {Z: {[sst]: morning, [chl]: evening}, a: {[sst]: noon}, C: {[sst]: noon}, 'B|C': {[sst]: noon}};
  assert.deepEqual(analysisAlertCandidates({subscriptions, previous: {}, current}), [
    alert('A', 'B|C', sst, noon), alert('A', 'Z', chl, evening), alert('A', 'Z', sst, morning),
    alert('A', 'a', sst, noon), alert('A|B', 'C', sst, noon), alert('a', 'Z', sst, morning),
  ]);
});
