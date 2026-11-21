import test from 'node:test';
import assert from 'node:assert/strict';
import {headingRating, headingRose, rateComfort} from '../web/score.ts';

const hour = Object.freeze({
  wind: 8, gust: 11, wind_from: 240, sea: 5, sea_period: 11, chop: 1.4, chop_period: 7,
  swell: 4, swell_period: 11, swell_from: 0, secondary: 0, secondary_from: null,
  other_wind: 8, other_gust: 11, other_sea: 5.5,
});

test('heading sectors include their lower bound and are symmetric around the swell bearing', () => {
  // Both sides of each cutoff catch shifted bounds, reversed bearings, and swapped factors.
  for (const [angle, sector, factor] of [
    [0, 'head', 1.25],
    [44.75, 'head', 1.25], [45, 'bow', 1.1], [45.25, 'bow', 1.1],
    [79.75, 'bow', 1.1], [80, 'beam', 1.1], [80.25, 'beam', 1.1],
    [109.75, 'beam', 1.1], [110, 'stern', 0.9], [110.25, 'stern', 0.9],
    [149.75, 'stern', 0.9], [150, 'following', 0.85], [150.25, 'following', 0.85],
    [180, 'following', 0.85],
  ]) {
    for (const course of [angle, 360 - angle]) {
      const r = headingRating(hour, course);
      assert.deepEqual([r.course, r.relative, r.sector, r.factor], [course, angle, sector, factor]);
    }
  }
  for (const [course, swell_from, relative] of [[350, 10, 20], [10, 350, 20], [0, 360, 0]]) {
    assert.equal(headingRating({...hour, swell_from}, course).relative, relative);
  }
});

test('heading scales seas or chop, never wind, gust, crossing or short-chop charges', () => {
  const scores = (h, courses) => courses.map(course => headingRating(h, course).score);
  // Seas dominate (+0.576 overlapped wind charge); the long period adds no roll.
  assert.deepEqual(scores(hour, [0, 90, 180]), [5.9, 6.3, 7]);
  // Wind dominates; chop is the wave burden, and crossing + short chop remain a flat 1.5.
  const choppy = {...hour, wind: 15, gust: 19, sea: 2, other_sea: 2, chop: 2.4, chop_period: 5, secondary: 1.5};
  assert.deepEqual(scores({...choppy, secondary_from: 90}, [0, 180]), [3.9, 4.2]);
  assert.deepEqual(scores(choppy, [0, 180]), [4.6, 4.9]); // no secondary bearing, no crossing charge
  const windOnly = {...hour, sea: 1, other_sea: 1, chop: 0.2};
  assert.deepEqual(scores(windOnly, [0, 45, 90, 135, 180]), [8.7, 8.7, 8.7, 8.7, 8.7]);
});

test('head comfort does not exceed beam comfort when beam roll is charged', () => {
  const boat = {sea: 1.5, wind: 1, chopPeriod: 5};
  const h = {...hour, wind: 2, other_wind: 2, gust: 3, other_gust: 3, sea: 2.9, other_sea: 3, chop: 0.2, swell: 1, swell_period: 7.5};
  const [head, beam, following] = [0, 90, 180].map(course => headingRating(h, course, boat).score);
  assert.ok(head <= beam, `head ${head} exceeds beam ${beam}`);
  assert.ok(beam <= following, `beam ${beam} exceeds following ${following}`);
  assert.equal(beam, 9.1); // Preserve the specified full beam-roll charge.
  // Different wind overlap, wave heights, and limited inputs keep the same uncalibrated ordering.
  for (const sea of [3, 4, 7]) for (const wind of [2, 12, 20]) for (const chop of [0.2, 3]) {
    for (const other_wind of [wind, null]) {
      const sample = {...h, sea, other_sea: sea, wind, other_wind, gust: wind + 1, other_gust: wind + 1, chop};
      const scores = [0, 90, 180].map(course => headingRating(sample, course, boat).score);
      assert.ok(scores[0] <= scores[1] && scores[1] <= scores[2], `unordered scores ${scores}`);
    }
  }
  assert.equal(headingRating(h, 0, boat, {head: 1}).score, 10); // Offsets remain independent.
});

test('beam roll is a flat charge only at sufficient combined seas and short enough swell period', () => {
  const boat = {sea: 1.5, wind: 1, chopPeriod: 5};
  const beam = {...hour, wind: 2, other_wind: 2, gust: 3, other_gust: 3, sea: 2.9, other_sea: 3, chop: 0.2, swell: 1, swell_period: 7.5};
  // Both bounds are inclusive and boat-scaled. The secondary model supplies the qualifying sea height.
  for (const [course, changes, score] of [
    [79.75, {}, 9.6], [80, {}, 9.1], [109.75, {}, 9.1], [110, {}, 9.7],
    [90, {other_sea: 2.99}, 9.6], [90, {swell_period: 7.51}, 9.6],
    [90, {swell_period: null}, 9.6],
  ]) {
    assert.equal(headingRating({...beam, ...changes}, course, boat).score, score);
  }
});

test('missing swell bearing falls back to the ordinary rating, not assumed head seas or calibrated comfort', () => {
  const boat = {sea: 1.5, wind: 1.2, chopPeriod: 5};
  for (const swell_from of [null, undefined, NaN, Infinity]) {
    const h = {...hour, wind_from: 0, swell_from}; // wind direction is not a substitute
    const score = rateComfort(h, boat).score;
    assert.equal(score, 6.9); // normal capped score, not the uncapped value
    for (const course of [0, 90, 180]) {
      assert.deepEqual(headingRating(h, course, boat, {head: -2}), {
        course, relative: null, sector: null, score, factor: 1, limited: true,
      });
    }
  }
  assert.deepEqual(headingRating({...hour, wind_from: null}, 0), headingRating(hour, 0));
});

test('heading can use partial data but cannot bypass the limited cap or invent a score without seas', () => {
  // Wind/chop gaps must not erase a known relative swell angle or turn a partial rating into a full one.
  const partial = {...hour, other_wind: null, chop: null};
  assert.deepEqual(headingRating(partial, 180), {
    course: 180, relative: 180, sector: 'following', score: 6.9, factor: 0.85, limited: true,
  });
  assert.deepEqual(headingRating({...partial, sea: null, other_sea: null}, 180), {
    course: 180, relative: 180, sector: 'following', score: null, factor: 0.85, limited: true,
  });
});

test('rose rates eight true courses in order and forwards boat factors and group offsets', () => {
  const boat = {sea: 1.1, wind: 1.2, chopPeriod: 5};
  const offset = {head: -1, beam: 0.5, following: -0.25};
  const rose = headingRose(hour, boat, offset);
  const courses = [0, 45, 90, 135, 180, 225, 270, 315];
  assert.deepEqual(rose.map(r => r.course), courses);
  assert.deepEqual(rose.map(r => r.sector), ['head', 'bow', 'beam', 'stern', 'following', 'stern', 'beam', 'bow']);
  // Wave cost is 2.45 before scaling, with about 0.36 of overlapped wind cost.
  assert.deepEqual(rose.map(r => r.score), [5.6, 5.9, 7.4, 7.2, 7.3, 7.2, 7.4, 5.9]);
  assert.equal(headingRating(hour, 180, boat, {following: 5}).score, 10);
  assert.equal(headingRating(hour, 0, boat, {head: -8}).score, 0);
});
