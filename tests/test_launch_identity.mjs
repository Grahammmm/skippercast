// RF1350-2: a saved Kayak launch id names one admitted facility. Every admitted point of a repeated id is
// withheld (so the origin cannot change with file order); unique siblings, the harbor fallback and the
// retry/memoization behavior stay. Synthetic fixtures only; the global fetch is blocked.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launchChoice} from '../web/reach.ts';
import {launchOrigin, launchPoints, loadLaunchPoints, parseLaunchPoints, resetLaunchPoints} from '../web/launches.ts';

const PAGE = 'https://example.test/';
const pt = (id, latitude, longitude, extra = {}) => ({id, name: `N-${id}-${latitude}`, latitude, longitude, ...extra});
const file = (points, region = 'r') => ({region_id: region, launch_points: points});
const deepFreeze = o => { if (o && typeof o === 'object' && !Object.isFrozen(o)) { Object.freeze(o); Object.values(o).forEach(deepFreeze); } return o; };
const ids = list => list.map(p => p.id);
const jsonOf = list => JSON.stringify(list);

async function isolated(body) {
  const realFetch = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('global fetch must not be used'); };
  resetLaunchPoints();
  launchChoice.value = {};
  try { await body(); } finally { globalThis.fetch = realFetch; launchChoice.value = {}; resetLaunchPoints(); }
}
const scripted = answers => { const f = async () => answers[f.calls++]; f.calls = 0; return f; };

test('launch_duplicate_id_is_withheld_in_any_order', () => {
  const sib = pt('solo', 36, -121), a = pt('same', 35, -120), b = pt('same', 36.5, -121.5);
  for (const [label, rows] of [
    ['forward', [a, sib, b]], ['reverse', [b, sib, a]],
    ['identical', [pt('same', 35, -120), sib, pt('same', 35, -120)]],
    ['three', [a, b, sib, pt('same', 37, -122)]],
  ]) {
    const input = deepFreeze(JSON.parse(JSON.stringify(file(rows))));
    const out = parseLaunchPoints(input, 'r');
    assert.deepEqual(ids(out), ['solo'], label);
    assert.deepEqual(out[0], {id: 'solo', name: 'N-solo-36', kind: 'launch', latitude: 36, longitude: -121}, label);
    const list = {region: 'r', points: out};
    assert.equal(launchOrigin('r', list, {r: 'same'}), null, `${label}: saved duplicate id resolves to the harbor`);
    assert.deepEqual(launchOrigin('r', list, {r: 'solo'}), {latitude: 36, longitude: -121, name: 'N-solo-36'}, label);
  }
});

test('launch_duplicate_withholding_keeps_input_order_and_all_unique_points', () => {
  const rows = [pt('u1', 1, 1), pt('d', 2, 2), pt('u2', 3, 3, {kind: 'ramp'}), pt('d', 4, 4), pt('u3', 5, 5)];
  const out = parseLaunchPoints(file(rows), 'r');
  assert.deepEqual(ids(out), ['u1', 'u2', 'u3']);
  assert.equal(out[1].kind, 'ramp');
  assert.equal(out[0].kind, 'launch', 'default kind kept');
});

test('launch_invalid_sibling_cannot_poison_unique_id', () => {
  const rows = [
    pt('x', 95, 0), null, pt('x', 10, 10, {region: 'other'}), pt('x', 35, -120), // only the last is admitted
    pt('Case', 1, 1), pt('case', 2, 2),                                          // exact, case-sensitive ids
    pt('__proto__', 3, 3), pt('constructor', 4, 4), pt('toString', 5, 5),
    pt('dupe', 1, 1), pt('dupe', 1, 1, {region: 'r'}),                           // both admitted: withheld
  ];
  const out = parseLaunchPoints(deepFreeze(file(rows)), 'r');
  assert.deepEqual(ids(out), ['x', 'Case', 'case', '__proto__', 'constructor', 'toString']);
  assert.equal(out[0].latitude, 35);
  // An id repeated only through ignored rows is still unique; a repeated __proto__ is withheld like any id.
  assert.deepEqual(ids(parseLaunchPoints(file([pt('__proto__', 1, 1), pt('__proto__', 2, 2), pt('constructor', 3, 3)]), 'r')), ['constructor']);
});

test('launch_duplicate_group_of_only_ambiguous_ids_is_empty_and_envelope_rules_stay', () => {
  assert.deepEqual(parseLaunchPoints(file([pt('a', 1, 1), pt('a', 2, 2)]), 'r'), []);
  assert.deepEqual(parseLaunchPoints(file([pt('a', 1, 1)], 'other'), 'r'), []);
  assert.deepEqual(parseLaunchPoints({region_id: 'r'}, 'r'), []);
  assert.deepEqual(parseLaunchPoints(null, 'r'), []);
});

test('launch_duplicate_load_preserves_harbor_fallback', () => isolated(async () => {
  const body = JSON.stringify(file([pt('same', 35, -120), pt('same', 36, -121)]));
  const f = scripted([new Response(body), new Response(body)]);
  launchChoice.value = {r: 'same'};
  await loadLaunchPoints('r', PAGE, f);
  assert.equal(launchPoints.value.region, 'r');
  assert.deepEqual(launchPoints.value.points, []);
  assert.equal(launchOrigin('r'), null);
  assert.deepEqual(launchChoice.value, {r: 'same'}, 'the saved choice is kept');
  await loadLaunchPoints('r', PAGE, f);
  assert.equal(f.calls, 1, 'memoized, not retried');
}));

test('launch_mixed_load_still_resolves_unique_choice', () => isolated(async () => {
  const f = scripted([new Response(JSON.stringify(file([pt('same', 35, -120), pt('solo', 36, -121), pt('same', 37, -122)])))]);
  await loadLaunchPoints('r', PAGE, f);
  assert.deepEqual(ids(launchPoints.value.points), ['solo']);
  launchChoice.value = {r: 'solo'};
  assert.deepEqual(launchOrigin('r'), {latitude: 36, longitude: -121, name: 'N-solo-36'});
  launchChoice.value = {r: 'same'};
  assert.equal(launchOrigin('r'), null);
  assert.equal(jsonOf(launchPoints.value.points).includes('"same"'), false);
}));

test('launch_duplicate_filter_keeps_transient_retry', () => isolated(async () => {
  const good = new Response(JSON.stringify(file([pt('same', 1, 1), pt('same', 2, 2), pt('solo', 3, 3)])));
  const f = scripted([new Response('', {status: 503}), good]);
  await loadLaunchPoints('r', PAGE, f);
  assert.deepEqual(launchPoints.value.points, []);
  await loadLaunchPoints('r', PAGE, f);
  assert.equal(f.calls, 2, 'a 503 is still asked again');
  assert.deepEqual(ids(launchPoints.value.points), ['solo']);
}));
