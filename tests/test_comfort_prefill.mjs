import test from 'node:test';
import assert from 'node:assert/strict';
import {comfortPrefill} from '../web/comfort-prefill.ts';

const empty = {phase: null, heading: null, wind: null, sea: null, period: null};
const plan = {departAt: 10, fishFrom: 20, fishTo: 30};
const bearings = {out: 123, back: 302};
const input = {at: 15, plan, bearings, hour: null};
const outbound = {...empty, phase: 'outbound', heading: 123};

function check(input, expected) {
  const result = comfortPrefill(input);
  assert.deepEqual(result, expected);
  // Match the unchanged feedback route's phase and context checks for every result.
  if (result.phase !== null) assert.ok(['outbound', 'fishing', 'return'].includes(result.phase));
  for (const [key, max] of Object.entries({heading: 360, wind: 200, sea: 100, period: 60})) {
    const value = result[key];
    if (value !== null) assert.ok(Number.isFinite(value) && value >= 0 && value <= max, `${key}: ${value}`);
  }
}

test('C1: missing inputs still return every key with a null value', () => {
  check({at: 15, plan: null, bearings: null, hour: null}, empty);
});

test('C1: a missing plan and one missing reading do not discard the other readings', () => {
  check({at: 15, plan: null, bearings, hour: {wind: null, sea: 4, period: 8}}, {...empty, sea: 4, period: 8});
});

for (const [label, at, phase, heading] of [
  ['before departAt', 9, 'outbound', 123],
  ['at departAt', 10, 'outbound', 123],
  ['just before fishFrom', 19, 'outbound', 123],
  ['at fishFrom', 20, 'fishing', null],
  ['just before fishTo', 29, 'fishing', null],
  ['at fishTo', 30, 'return', 302],
  ['after fishTo', 31, 'return', 302],
]) {
  test(`C2: phase ${label}`, () => check({...input, at}, {...empty, phase, heading}));
}

test('C2: coincident plan times are valid and a zero-length fishing window goes straight to return', () => {
  check({...input, at: 20, plan: {departAt: 20, fishFrom: 20, fishTo: 20}}, {...empty, phase: 'return', heading: 302});
});

for (const [label, overrides] of [
  ['non-finite at', {at: NaN}],
  ['non-finite departAt', {plan: {...plan, departAt: -Infinity}}],
  ['non-finite fishFrom', {plan: {...plan, fishFrom: NaN}}],
  ['non-finite fishTo', {plan: {...plan, fishTo: Infinity}}],
  ['departAt after fishFrom', {plan: {...plan, departAt: 21}}],
  ['fishFrom after fishTo', {plan: {...plan, fishTo: 19}}],
]) {
  test(`C2: ${label} suppresses phase and heading, not the forecast`, () => {
    check({...input, ...overrides, hour: {wind: 12, sea: 4, period: 8}}, {...empty, wind: 12, sea: 4, period: 8});
  });
}

for (const [label, at, courses, phase, heading] of [
  ['wraps a negative outbound bearing', 15, {out: -10, back: 302}, 'outbound', 350],
  ['rounds a return bearing before wrapping', 35, {out: 123, back: 359.6}, 'return', 0],
  ['wraps multiple full turns without needing a return bearing', 15, {out: 720, back: null}, 'outbound', 0],
  ['rounds a bearing away from the wrap point', 35, {out: null, back: 22.6}, 'return', 23],
  ['does not borrow the return bearing if the outbound bearing is null', 15, {out: null, back: 302}, 'outbound', null],
  ['does not borrow the outbound bearing if the return bearing is null', 35, {out: 123, back: null}, 'return', null],
  ['rejects NaN', 15, {out: NaN, back: 302}, 'outbound', null],
  ['rejects infinity', 35, {out: 123, back: Infinity}, 'return', null],
  ['accepts missing bearings without losing the phase', 15, null, 'outbound', null],
  ['uses neither bearing while fishing', 25, bearings, 'fishing', null],
]) {
  test(`C3: ${label}`, () => check({...input, at, bearings: courses}, {...empty, phase, heading}));
}

test('C4: each reading rounds independently to tenths', () => {
  check({...input, hour: {wind: 12.34, sea: 4.56, period: 8.75}}, {...outbound, wind: 12.3, sea: 4.6, period: 8.8});
});

test('C4: all three ranges include their endpoints', () => {
  check({...input, hour: {wind: 0, sea: 0, period: 0}}, {...outbound, wind: 0, sea: 0, period: 0});
  check({...input, hour: {wind: 200, sea: 100, period: 60}}, {...outbound, wind: 200, sea: 100, period: 60});
});

for (const [key, max] of Object.entries({wind: 200, sea: 100, period: 60})) {
  for (const [label, value] of [['just below zero', -0.01], ['just above the maximum', max + 0.01], ['NaN', NaN], ['infinity', Infinity]]) {
    test(`C4: ${key} is null for ${label}, without affecting valid readings`, () => {
      const hour = {wind: 12, sea: 4, period: 8};
      check({...input, hour: {...hour, [key]: value}}, {...outbound, ...hour, [key]: null});
    });
  }
}

test('C4: a missing hour does not erase phase and heading', () => check(input, outbound));
