import test from 'node:test';
import assert from 'node:assert/strict';
import {ANALYSIS_LAYERS} from '../server/analysis-alerts.ts';
import {dueAnalysisAlerts} from '../server/analysis-alert-policy.ts';

const [sst, chlorophyll] = ANALYSIS_LAYERS;
const now = new Date('2026-11-19T16:00:00Z');
const pacific = () => 'America/Los_Angeles';
const base = Object.freeze({owner: 'owner-A', region: 'bay', layer: sst, sampleAt: '2026-11-19T14:00:00Z'});
const {owner, region, layer} = base;
const receipt = sentAt => ({owner, region, layer, sentAt});
const sentToday = alert => ({alert, reason: 'sent-today'});
const noZone = alert => ({alert, reason: 'no-zone'});

// An invalid clock takes precedence over both zone lookup and delivery history.
test('C1: an invalid clock holds all candidates without consulting zones', () => {
  const other = {...base, region: 'inland'};
  let calls = 0;
  for (const clock of [new Date(NaN), new Proxy(now, {})]) {
    const result = dueAnalysisAlerts([other, base], [receipt(now.toISOString())], clock, () => {
      calls++;
      return null;
    });
    assert.deepEqual(result, {due: [], held: [
      {alert: other, reason: 'bad-clock'}, {alert: base, reason: 'bad-clock'},
    ]});
  }
  assert.equal(calls, 0);
});

// Neither an empty batch nor an empty history defaults to holding good alerts.
test('C2: an empty batch returns empty lists; no sent records leaves an alert due', () => {
  assert.deepEqual(dueAnalysisAlerts([], [receipt(now.toISOString())], now, pacific), {due: [], held: []});
  assert.deepEqual(dueAnalysisAlerts([base], [], now, pacific), {due: [base], held: []});
});

// A UTC-day comparison (or rolling 24-hour window) misses this midnight boundary.
for (const [label, sentAt, onSameDay] of [
  ['one millisecond before local midnight, on the same UTC date', '2026-11-19T07:59:59.999Z', false],
  ['exactly at local midnight, with a colon offset', '2026-11-19T00:00:00-08:00', true],
  ['one millisecond after local midnight, with a compact offset', '2026-11-19T00:00:00.001-0800', true],
  ['with an explicit GMT zone and a trailing comment', 'Thu, 19 Nov 2026 08:00:00 GMT (comment)', true],
  ['a later instant on the same local day', '2026-11-19T20:00:00Z', true],
  ['next local midnight', '2026-11-20T08:00:00Z', false],
]) {
  test(`C2: classifies a receipt ${label}`, () => {
    assert.deepEqual(dueAnalysisAlerts([base], [receipt(sentAt)], now, pacific),
      onSameDay ? {due: [], held: [sentToday(base)]} : {due: [base], held: []});
  });
}

test('C2: a region east of UTC holds across a UTC date boundary', () => {
  const tokyo = () => 'Asia/Tokyo';
  assert.deepEqual(dueAnalysisAlerts([base], [receipt('2026-12-31T15:00:00Z')], new Date('2027-01-01T01:00:00Z'), tokyo),
    {due: [], held: [sentToday(base)]});
});

// Applying now's offset to historic instants gets the midnight boundary wrong on both DST days.
for (const [label, clock, previousDay, localMidnight] of [
  ['spring-forward', '2026-03-09T06:59:59.999Z', '2026-03-08T07:59:59.999Z', '2026-03-08T08:00:00Z'],
  ['fall-back', '2026-11-02T07:59:59.999Z', '2026-11-01T06:59:59.999Z', '2026-11-01T07:00:00Z'],
]) {
  test(`C2: uses actual offsets on the ${label} day`, () => {
    const at = new Date(clock);
    assert.deepEqual(dueAnalysisAlerts([base], [receipt(previousDay)], at, pacific), {due: [base], held: []});
    assert.deepEqual(dueAnalysisAlerts([base], [receipt(localMidnight)], at, pacific), {due: [], held: [sentToday(base)]});
  });
}

test('C2: null and Intl-rejected zones do not fall back to UTC', () => {
  const unknown = {...base, region: 'unknown'};
  const zoneOf = region => region === 'unknown' ? null : 'Ocean/Nowhere';
  assert.deepEqual(dueAnalysisAlerts([unknown, base], [receipt(now.toISOString())], now, zoneOf),
    {due: [], held: [noZone(unknown), noZone(base)]});
});

// Dropping any component of the key over-throttles an unrelated candidate.
test('C2: a sent record only holds its matching owner, region and layer', () => {
  const choices = [{...base, owner: 'owner-B'}, {...base, region: 'inland'}, {...base, layer: chlorophyll}];
  assert.deepEqual(dueAnalysisAlerts([choices[0], base, ...choices.slice(1)], [receipt(now.toISOString())], now, pacific),
    {due: choices, held: [sentToday(base)]});
});

// Date.parse accepts implicit local time; a zone in a comment does not make it explicit.
test('C3: skips unparseable, unzoned and unreadable sent records without losing valid ones', () => {
  const other = {...base, owner: 'owner-B'};
  const valid = receipt(now.toISOString());
  const {proxy, revoke} = Proxy.revocable({}, {});
  revoke();
  const malformed = [
    null, 1, 'receipt', {}, proxy,
    {...valid, owner: 0}, {...valid, region: null}, {...valid, layer: []}, {...valid, sentAt: now.getTime()},
    {...valid, get sentAt() { throw new Error('unreadable'); }},
    receipt('2026-11-19'), receipt('2026-11-19T12:00:00'), receipt('Nov 19 2026 12:00 (comment (nested) UTC)'),
    receipt('not a date UTC'), receipt('2026-11-19T08:00:00+99:00'),
  ];
  assert.deepEqual(dueAnalysisAlerts([base, other], [...malformed, {...valid, owner: other.owner}], now, pacific),
    {due: [base], held: [sentToday(other)]});
});

// Interleaving catches sorting, replacement by a later sample, and repeated zone resolution.
test('C3: keeps first due and preserves order on both sides without modifying inputs', () => {
  const next = Object.freeze({...base, sampleAt: now.toISOString()});
  const alreadySent = Object.freeze({...base, owner: 'owner-B'});
  const secondRegion = Object.freeze({...base, region: 'inland'});
  const secondLayer = Object.freeze({...base, layer: chlorophyll});
  const candidates = Object.freeze([base, alreadySent, secondRegion, next, secondLayer]);
  const sent = Object.freeze([Object.freeze({...receipt(now.toISOString()), owner: alreadySent.owner})]);
  const clock = now.getTime();
  const calls = [];
  const result = dueAnalysisAlerts(candidates, sent, now, region => {
    calls.push(region);
    return 'America/Los_Angeles';
  });
  assert.deepEqual(result, {due: [base, secondRegion, secondLayer], held: [sentToday(alreadySent), sentToday(next)]});
  assert.deepEqual(calls.slice().sort(), ['bay', 'inland']);
  assert.equal(now.getTime(), clock);
});

test('C3: caches an unavailable zone even if the lookup throws or returns null', () => {
  const missing = {...base, region: 'absent'};
  const invalid = {...base, region: 'invalid'};
  const candidates = [base, missing, invalid, missing, base, invalid];
  const calls = [];
  const result = dueAnalysisAlerts(candidates, [receipt(now.toISOString())], now, region => {
    calls.push(region);
    if (region === 'bay') throw new Error('unavailable');
    return region === 'absent' ? null : 'Ocean/Nowhere';
  });
  assert.deepEqual(result, {due: [], held: candidates.map(noZone)});
  assert.deepEqual(calls.slice().sort(), ['absent', 'bay', 'invalid']);
});
