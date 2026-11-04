import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {profileTripDefaults, tripDefaults} from '../web/alerts.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const dir = await mkdtemp(join(tmpdir(), 'trip-profile-'));
const out = join(dir, 'form.mjs');
// Expose the real signed-in component only in this test bundle, not the app API.
await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
  export {SignedIn} from './web/app/TripAlerts.tsx';
  export {profile} from './web/state.ts';
  export {savedLimits, limitsFor, resetLimits} from './web/limits.ts';
  export {defaultLimits} from './packages/coast/src/limits.ts';
  export {tripDefaults, tripBoat, tripBody, alertDate} from './web/alerts.ts';
  export {PROFILE_TABLE} from './web/profile.ts';
  export {h, options} from 'preact';
  export {render} from 'preact-render-to-string';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
  jsx: 'automatic', jsxImportSource: 'preact', plugins: [{name: 'signed-in', setup(b) {
    b.onLoad({filter: /\/TripAlerts\.tsx$/}, async ({path}) => ({
      contents: await readFile(path, 'utf8') + '\nexport {SignedIn};', loader: 'tsx',
    }));
  }}],
});
const ui = await import(pathToFileURL(out).href);
test.after(() => rm(dir, {recursive: true, force: true}));
const custom = {factors: {wind: .8, sea: .7, custom: true, chopPeriod: 4.2}, saved: {boat: {name: 'Fixture'}}};
const reference = {factors: {wind: 1, sea: 1, custom: false}, saved: null};
function open(p, boat = custom) {
  ui.profile.value = p;
  let form;
  const previous = ui.options.vnode;
  ui.options.vnode = vnode => {
    previous?.(vnode);
    if (vnode.type === 'form' && vnode.props.id === 'save-alert') form = vnode;
  };
  try {
    const html = ui.render(ui.h(ui.SignedIn, {session: {}, region: {id: 'fixture', timezone: 'UTC', species: ['reef'], forecast_points: []}, boat, target: null}));
    const values = Object.fromEntries([...html.matchAll(/name="(wind_limit|gust_limit|sea_limit)"[^>]*value="([^"]+)"/g)].map(m => [m[1], Number(m[2])]));
    const note = html.match(/id="trip-boat-note">([^<]+)</)?.[1];
    return {values, note, form};
  } finally { ui.options.vnode = previous; }
}
const fields = ({wind, gust, sea}) => ({wind_limit: wind, gust_limit: gust, sea_limit: sea});

test('each non-boat form uses its own default or saved limits, including saved kayak 6/9/1.5', () => {
  ui.savedLimits.value = {};
  for (const p of ['kayak', 'shore', 'spear']) {
    assert.deepEqual(ui.limitsFor(p), ui.defaultLimits(p));
    assert.deepEqual(open(p).values, fields(profileTripDefaults(ui.defaultLimits(p))), p);
    ui.savedLimits.value = {[p]: {...ui.defaultLimits(p), wind: 6, gust: 9, seas: 1.5}};
    assert.deepEqual(open(p).values, {wind_limit: 6, gust_limit: 9, sea_limit: 1.5}, p);
    ui.savedLimits.value = {};
  }
});

const REFERENCE_NOTE = 'Limits start from the reference 23 ft boat. Set your boat to tailor them.';
const OWN_WITH_BOAT = 'Limits start from your Boat limits, without boat-factor scaling; alerts judge wind chop for your saved boat too.';
const OWN_NO_BOAT = 'Limits start from your Boat limits, without boat-factor scaling; alerts judge wind, gusts and offshore seas only.';
const unnamed = {factors: {wind: 1.3, sea: 1.4, custom: true}, saved: {boat: {}}};

test('boat without own Boat limits keeps byte-identical factor defaults and both original notes', () => {
  const own = ui.defaultLimits('boat');
  for (const [label, saved] of [
    ['empty map', {}],
    ['only another profile saved', {kayak: {...ui.defaultLimits('kayak'), wind: 6, gust: 9, seas: 1.5}}],
    ['reset after saving', (() => { ui.savedLimits.value = {boat: {...own, wind: 5, gust: 7, seas: 1}}; ui.resetLimits('boat'); return ui.savedLimits.value; })()],
  ]) {
    ui.savedLimits.value = saved;
    for (const boat of [reference, custom, unnamed])
      assert.equal(JSON.stringify(open('boat', boat).values), JSON.stringify(fields(tripDefaults(boat.factors))), `${label} ${JSON.stringify(boat.factors)}`);
    assert.equal(open('boat', reference).note, REFERENCE_NOTE, label);
    assert.equal(open('boat').note, 'Limits start from your saved boat (Fixture); alerts judge wind chop for it too.', label);
    assert.equal(open('boat', unnamed).note, 'Limits start from your saved boat; alerts judge wind chop for it too.', label);
  }
});

test('own Boat limits start the form as saved, unscaled by any boat, with the Boat-limits note', () => {
  ui.savedLimits.value = {boat: {...ui.defaultLimits('boat'), wind: 6, gust: 11, seas: 2.5}};
  const want = {wind_limit: 6, gust_limit: 11, sea_limit: 2.5};
  for (const boat of [reference, custom, unnamed, {factors: {wind: 0.5, sea: 0.5, custom: true}, saved: {boat: {name: 'Small'}}}, {factors: {wind: 2, sea: 2, custom: true}, saved: {boat: {name: 'Large'}}}])
    assert.deepEqual(open('boat', boat).values, want, JSON.stringify(boat.factors));
  assert.equal(open('boat', reference).note, OWN_NO_BOAT);
  assert.equal(open('boat', custom).note, OWN_WITH_BOAT);
  assert.equal(open('boat', unnamed).note, OWN_WITH_BOAT);
  assert.doesNotMatch(open('boat', custom).note, /Fixture/);
});

test('own Boat limits are clamped and stepped to the server ranges without mutating the saved entry', () => {
  for (const [saved, expected] of [
    [{wind: 45, gust: 2, seas: .2}, {wind_limit: 30, gust_limit: 30, sea_limit: .5}],
    [{wind: 6.4, gust: 9.6, seas: 1.3}, {wind_limit: 6, gust_limit: 10, sea_limit: 1.5}],
    [{wind: -5, gust: 100, seas: 99}, {wind_limit: 1, gust_limit: 40, sea_limit: 10}],
    [{wind: NaN, gust: 9, seas: Infinity}, {wind_limit: tripDefaults().wind, gust_limit: 9, sea_limit: tripDefaults().sea}],
  ]) {
    const entry = Object.freeze({...ui.defaultLimits('boat'), ...saved});
    ui.savedLimits.value = {boat: entry};
    assert.deepEqual(open('boat', custom).values, expected, JSON.stringify(saved));
    assert.equal(ui.savedLimits.value.boat, entry);
  }
});

test('own limits saved for another profile do not trigger the Boat-limits note or values', () => {
  ui.savedLimits.value = {kayak: {...ui.defaultLimits('kayak'), wind: 6, gust: 9, seas: 1.5}, shore: {...ui.defaultLimits('shore'), wind: 7, gust: 10, seas: 2}};
  assert.deepEqual(open('boat', custom).values, fields(tripDefaults(custom.factors)));
  assert.equal(open('boat', custom).note, 'Limits start from your saved boat (Fixture); alerts judge wind chop for it too.');
  assert.deepEqual(open('kayak').values, {wind_limit: 6, gust_limit: 9, sea_limit: 1.5});
});

test('reopening reads the current Boat limits: new, then reset, then a profile switch', () => {
  ui.savedLimits.value = {};
  assert.equal(open('boat').note, 'Limits start from your saved boat (Fixture); alerts judge wind chop for it too.');
  ui.savedLimits.value = {boat: {...ui.defaultLimits('boat'), wind: 5, gust: 7, seas: 1}};
  assert.deepEqual(open('boat').values, {wind_limit: 5, gust_limit: 7, sea_limit: 1});
  assert.equal(open('boat').note, OWN_WITH_BOAT);
  assert.equal(open('shore').note, `Limits start from your ${ui.PROFILE_TABLE.shore.label} limits; alerts still judge wind, gusts and offshore seas only, not surf at your launch or beach.`);
  ui.resetLimits('boat');
  assert.deepEqual(open('boat').values, fields(tripDefaults(custom.factors)));
  assert.equal(open('boat').note, 'Limits start from your saved boat (Fixture); alerts judge wind chop for it too.');
});

test('clamps both ends, rounds steps, and never sets gust below wind', () => {
  for (const [input, expected] of [
    [{wind: 45, gust: 2, seas: .2}, {wind: 30, gust: 30, sea: .5}],
    [{wind: 6.4, gust: 9.6, seas: 1.3}, {wind: 6, gust: 10, sea: 1.5}],
    [{wind: -5, gust: 100, seas: 99}, {wind: 1, gust: 40, sea: 10}],
  ]) assert.deepEqual(profileTripDefaults(input), expected);
});

test('non-finite or missing fields fall back independently, without mutating inputs', () => {
  for (const [field, output] of [['wind', 'wind'], ['gust', 'gust'], ['seas', 'sea']]) {
    for (const bad of [NaN, Infinity, -Infinity, undefined]) {
      const input = {wind: 6, gust: 9, seas: 1.5, [field]: bad};
      const expected = {wind: 6, gust: 9, sea: 1.5, [output]: tripDefaults()[output]};
      assert.deepEqual(profileTripDefaults(Object.freeze(input)), expected);
    }
  }
  assert.deepEqual(profileTripDefaults({}), tripDefaults());
});

test('profile notes name the mode and preserve the offshore-only caveat; reopen reads the new profile', () => {
  ui.savedLimits.value = {};
  open('boat');
  for (const p of ['kayak', 'shore', 'spear', 'kayak']) {
    const got = open(p);
    assert.equal(got.note, `Limits start from your ${ui.PROFILE_TABLE[p].label} limits; alerts still judge wind, gusts and offshore seas only, not surf at your launch or beach.`);
    assert.doesNotMatch(got.note, /23 ft/);
    assert.deepEqual(got.values, fields(profileTripDefaults(ui.limitsFor(p))));
  }
});

test('actual submit passes tripBody no saved boat for any non-boat, even with a custom boat', async () => {
  const oldFetch = globalThis.fetch, oldData = globalThis.FormData;
  const requests = [];
  globalThis.fetch = async (url, init) => { requests.push({url, ...init}); return Response.json({trips: [], events: []}); };
  try {
    for (const p of ['kayak', 'shore', 'spear', 'boat']) {
      const {form, values} = open(p);
      const data = {date: ui.alertDate('UTC'), point: 'central', start_hour: 7, end_hour: 13, ...values};
      globalThis.FormData = class { get(k) { return data[k]; } };
      await form.props.onSubmit({preventDefault() {}, currentTarget: {}});
      await new Promise(resolve => setImmediate(resolve));
      const posted = JSON.parse(requests.findLast(r => r.method === 'POST').body);
      assert.deepEqual(posted, ui.tripBody(data, 'fixture', 'reef', p === 'boat' ? ui.tripBoat(custom.factors, custom.saved.boat) : null));
      assert.equal(Object.hasOwn(posted, 'boat'), p === 'boat');
    }
  } finally { globalThis.fetch = oldFetch; globalThis.FormData = oldData; }
});

test('boat submit posts the edited limits, not the defaults, with only the existing boat fields', async () => {
  ui.savedLimits.value = {boat: {...ui.defaultLimits('boat'), wind: 6, gust: 11, seas: 2.5}, kayak: {...ui.defaultLimits('kayak'), wind: 4, gust: 5, seas: 1}};
  const oldFetch = globalThis.fetch, oldData = globalThis.FormData;
  const requests = [];
  globalThis.fetch = async (url, init) => { requests.push({url, ...init}); return Response.json({trips: [], events: []}); };
  try {
    for (const boat of [custom, reference]) {
      const {form, values} = open('boat', boat);
      assert.deepEqual(values, {wind_limit: 6, gust_limit: 11, sea_limit: 2.5});
      const edited = {date: ui.alertDate('UTC'), point: 'central', start_hour: 8, end_hour: 12, wind_limit: 9, gust_limit: 14, sea_limit: 3.5};
      globalThis.FormData = class { get(k) { return edited[k]; } };
      await form.props.onSubmit({preventDefault() {}, currentTarget: {}});
      await new Promise(resolve => setImmediate(resolve));
      const posted = JSON.parse(requests.findLast(r => r.method === 'POST').body);
      assert.deepEqual(posted, ui.tripBody(edited, 'fixture', 'reef', ui.tripBoat(boat.factors, boat.saved?.boat)));
      assert.equal(posted.wind_limit, 9);
      assert.equal(Object.hasOwn(posted, 'boat'), boat === custom);
      assert.doesNotMatch(JSON.stringify(posted), /kayak|seas|profile|limits"/);
    }
  } finally { globalThis.fetch = oldFetch; globalThis.FormData = oldData; ui.savedLimits.value = {}; }
});
