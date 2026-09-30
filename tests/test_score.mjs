// web/score.ts is the one conditions score. The golden fixture was generated from
// dist/morning-outlook.js before the arithmetic moved, so a threshold change
// shows up here as a list of exactly which ratings moved, not as a silent drift.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {THRESHOLDS, hourScores, limitedScores, verdictFor, worseVerdict, controlModeFor, angleBetween} from '../web/score.ts';
import {hourScores as legacyHourScores} from '../dist/morning-outlook.js';
import {verdictFor as legacyVerdict, GO, NO_GO} from '../dist/tomorrow.js';

const golden = JSON.parse(fs.readFileSync(new URL('./fixtures/score-golden.json', import.meta.url), 'utf8'));
const REFERENCE = {sea: 1, wind: 1, chopPeriod: 6};

test('every golden case scores exactly as it did before the module moved', () => {
  const moved = [];
  for (const [i, c] of golden.cases.entries()) {
    const got = hourScores(c.c, c.other, controlModeFor(c.species), c.gust, c.factors);
    if (JSON.stringify(got) !== JSON.stringify(c.expected)) moved.push({case: i, species: c.species, expected: c.expected, got});
  }
  assert.deepEqual(moved, [], `${moved.length} of ${golden.cases.length} golden ratings changed`);
  assert.equal(golden.cases.length, 150);
});

test('the legacy wrapper in morning-outlook.js returns the same numbers', () => {
  for (const c of golden.cases) {
    assert.deepEqual(legacyHourScores(c.c, c.other, c.species, c.gust, c.factors), c.expected);
  }
});

test('the tuned thresholds are the documented ones', () => {
  assert.equal(THRESHOLDS.go, 7);
  assert.equal(THRESHOLDS.noGo, 4);
  assert.equal(GO, THRESHOLDS.go);
  assert.equal(NO_GO, THRESHOLDS.noGo);
  assert.deepEqual([THRESHOLDS.capUncertain, THRESHOLDS.capLimited, THRESHOLDS.capHazard], [7.9, 6.9, 1.9]);
  assert.ok(Object.isFrozen(THRESHOLDS));
});

test('a flat calm scores 10 and a gale scores 0 for the reference boat', () => {
  const calm = {wind: 2, gust: 3, sea: {height: 1, period: 14, from: 290}, chop: {height: 0.1, period: 3, from: 300}, swell: {height: 1, period: 14, from: 290}, secondary: {height: 0, period: null, from: null}};
  assert.deepEqual(hourScores(calm, {wind: 2, sea: {height: 1}}, 'bottom', 3, REFERENCE), {comfort: 10, control: 10, conditions: 10, score_scope: 'comfort-and-control', bite: null, overall: null});
  const gale = {...calm, wind: 35, gust: 45, sea: {height: 12, period: 8, from: 300}, chop: {height: 4, period: 4, from: 300}};
  assert.equal(hourScores(gale, {wind: 35, sea: {height: 12}}, 'bottom', 45, REFERENCE).conditions, 0);
});

test('bottom fishing is more wind-sensitive than the water column; boat-comfort scores comfort only', () => {
  const breezy = {wind: 12, gust: 15, sea: {height: 2, period: 10, from: 300}, chop: {height: 0.6, period: 5, from: 300}, swell: {height: 2, period: 10, from: 300}, secondary: {height: 0, period: null, from: null}};
  const other = {wind: 12, sea: {height: 2}};
  const bottom = hourScores(breezy, other, 'bottom', 15, REFERENCE), column = hourScores(breezy, other, 'water-column', 15, REFERENCE);
  assert.ok(bottom.control < column.control, `bottom ${bottom.control} should be below column ${column.control}`);
  assert.equal(bottom.comfort, column.comfort);
  const comfort = hourScores(breezy, other, 'boat-comfort', 15, REFERENCE);
  assert.equal(comfort.control, null);
  assert.equal(comfort.conditions, comfort.comfort);
  assert.equal(comfort.score_scope, 'boat-comfort');
});

test('a bigger boat scores the same sea higher; a skiff scores it lower', () => {
  const seas = {wind: 10, gust: 13, sea: {height: 4, period: 10, from: 300}, chop: {height: 1, period: 5, from: 300}, swell: {height: 4, period: 10, from: 300}, secondary: {height: 0, period: null, from: null}};
  const other = {wind: 10, sea: {height: 4}};
  const big = hourScores(seas, other, 'bottom', 13, {sea: 1.6, wind: 1.3, chopPeriod: 7}).conditions;
  const ref = hourScores(seas, other, 'bottom', 13, REFERENCE).conditions;
  const skiff = hourScores(seas, other, 'bottom', 13, {sea: 0.7, wind: 0.8, chopPeriod: 5}).conditions;
  assert.ok(big > ref && ref > skiff, `${big} > ${ref} > ${skiff}`);
});

test('crossing secondary swell and short steep chop each cost their flat penalty', () => {
  const base = {wind: 3, gust: 4, sea: {height: 1, period: 12, from: 290}, chop: {height: 0.2, period: 8, from: 290}, swell: {height: 1, period: 12, from: 290}, secondary: {height: 0, period: null, from: null}};
  const other = {wind: 3, sea: {height: 1}};
  const clean = hourScores(base, other, 'bottom', 4, REFERENCE).conditions;
  const crossing = hourScores({...base, secondary: {height: 1.5, period: 10, from: 200}}, other, 'bottom', 4, REFERENCE).conditions;
  assert.equal(+(clean - crossing).toFixed(1), THRESHOLDS.crossingPenalty);
  const aligned = hourScores({...base, secondary: {height: 1.5, period: 10, from: 300}}, other, 'bottom', 4, REFERENCE).conditions;
  assert.equal(aligned, clean, 'a secondary swell from nearly the same direction does not cross');
  const short = hourScores({...base, chop: {height: 0.6, period: 4, from: 290}}, other, 'bottom', 4, REFERENCE).conditions;
  assert.ok(clean - short >= THRESHOLDS.shortChopPenalty);
});

test('missing chop, swell or gust is never treated as zero: the limited estimate is capped at 6.9', () => {
  const limited = limitedScores(3, 1, null, 'bottom', REFERENCE);
  assert.equal(limited.conditions, THRESHOLDS.capLimited);
  assert.equal(limited.comfort, 10, 'the underlying comfort stays uncapped for display');
  const noGust = limitedScores(14, 3, null, 'bottom', REFERENCE), gusty = limitedScores(14, 3, 24, 'bottom', REFERENCE);
  assert.ok(gusty.comfort < noGust.comfort, `a known gust costs points (${gusty.comfort} < ${noGust.comfort}); an unknown one costs nothing`);
  assert.ok(noGust.conditions <= THRESHOLDS.capLimited && gusty.conditions <= THRESHOLDS.capLimited);
});

test('verdicts: go at 7, marginal below, no-go below 4 or under any hazard; windows take the worse hour', () => {
  assert.equal(verdictFor({conditions: 7}), 'go');
  assert.equal(verdictFor({conditions: 6.9}), 'marginal');
  assert.equal(verdictFor({conditions: 3.9}), 'no-go');
  assert.equal(verdictFor({conditions: 9.5, hazard: true}), 'no-go');
  assert.equal(verdictFor({conditions: null}), 'unknown');
  assert.equal(verdictFor(null), 'unknown');
  assert.equal(legacyVerdict({conditions: 7}), 'go');
  assert.equal(worseVerdict('go', 'marginal'), 'marginal');
  assert.equal(worseVerdict('unknown', 'no-go'), 'no-go');
  assert.equal(worseVerdict('go', 'unknown'), 'unknown');
});

test('control mode comes from the region when configured, else from the species', () => {
  assert.equal(controlModeFor('reef'), 'bottom');
  assert.equal(controlModeFor('tuna'), 'water-column');
  assert.equal(controlModeFor('tuna', 'boat-comfort'), 'boat-comfort');
  assert.equal(controlModeFor('reef', 'nonsense'), 'bottom');
  assert.equal(angleBetween(350, 10), 20);
  assert.equal(angleBetween(null, 10), null);
});
