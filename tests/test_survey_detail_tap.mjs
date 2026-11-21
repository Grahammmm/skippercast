import assert from 'node:assert/strict';
import test from 'node:test';
import {prepareCatalogue} from '../web/i18n.ts';
import {confidenceAt} from '../web/map/survey-detail-tap.ts';

const hit = (region, tier, extra = {}) => Object.freeze({region, properties: Object.freeze({tier, ...extra})});
const date = '2024-06-12';
const tiers = [
  [hit('first-bay', '1m-measured', {grid_m: 1, date}),
    {tier: '1m-measured', gridM: 1, date, text: '1 m measured', sourcesHref: '/sources#region-first-bay'}],
  [hit('second-bay', '2m', {grid_m: 2}),
    {tier: '2m', gridM: 2, date: null, text: '2 m', sourcesHref: '/sources#region-second-bay'}],
  [hit('third-bay', '5m', {grid_m: 5}),
    {tier: '5m', gridM: 5, date: null, text: '5 m', sourcesHref: '/sources#region-third-bay'}],
  [hit('fourth-bay', 'estimated', {grid_m: 4, date, grid_tier: '4-16m-compiled'}),
    {tier: 'estimated', gridM: 4, date, text: 'estimated (4 m grid)', sourcesHref: '/sources#region-fourth-bay'}],
  [hit('fifth-bay', 'none'),
    {tier: 'none', gridM: null, date: null, text: 'no survey', sourcesHref: '/sources#region-fifth-bay'}],
];

function* orderedSubsets(remaining, prefix = []) {
  yield prefix;
  for (const index of remaining) {
    yield* orderedSubsets(remaining.filter(other => other !== index), [...prefix, index]);
  }
}

// A last-hit, first-hit, or grid-size sort fails on at least one order. In
// particular the 4 m estimate must lose to the measured 5 m footprint.
test('C1: all ordered subsets of the decoded tiers, including no hits', () => {
  for (const order of orderedSubsets([...tiers.keys()])) {
    const expected = order.length ? tiers[Math.min(...order)][1] : null;
    assert.deepEqual(confidenceAt(Object.freeze(order.map(i => tiers[i][0])), 'en'), expected,
      `hits: ${order.map(i => tiers[i][1].tier).join(', ') || '(empty)'}`);
  }
});

// Equal rank must not splice the later feature's grid, date or region into the first hit.
test('C1: equal-tier overlaps keep the first hit intact in either order', () => {
  const [first, expected] = tiers[3];
  const second = hit('other-bay', 'estimated', {grid_m: 3});
  assert.deepEqual(confidenceAt([first, second], 'en'), expected);
  assert.deepEqual(confidenceAt([second, first], 'en'), {
    tier: 'estimated', gridM: 3, date: null, text: 'estimated (3 m grid)', sourcesHref: '/sources#region-other-bay',
  });
});

// Unrecognized metadata isn't an affirmative survey gap or a winning hit.
test('C1: unknown tiers contribute no readout or rank', () => {
  const unknown = hit('other-bay', '4-16m-compiled', {grid_m: 4});
  assert.equal(confidenceAt([unknown], 'en'), null);
  assert.deepEqual(confidenceAt([unknown, tiers[4][0]], 'en'), tiers[4][1]);
});

// Missing metadata should not print a grid token or invent a survey date.
test('C1: missing or unusable grid and date stay null', () => {
  const expected = {tier: 'estimated', gridM: null, date: null, text: 'estimated', sourcesHref: '/sources#region-other-bay'};
  assert.deepEqual(confidenceAt([hit('other-bay', 'estimated')], 'en'), expected);
  assert.deepEqual(confidenceAt([hit('other-bay', 'estimated', {grid_m: Infinity, date: ' '})], 'en'), expected);
  assert.deepEqual(confidenceAt([hit('fifth-bay', 'none', {grid_m: 5, date})], 'en'), tiers[4][1]);
});

// Copying the raw label/provenance would leak the sentinel and bypass localization.
test('C2: Spanish uses catalogue copy and links to the winning feature’s region', async () => {
  await prepareCatalogue('es');
  const provenance = {label: 'Synthetic Provider survey', source: 'Synthetic Provider', sourceId: 'provider-id'};
  const measured = hit('measured-bay', '1m-measured', {grid_m: 1, ...provenance});
  const estimated = hit('estimated-bay', 'estimated', {grid_m: 8, date, ...provenance});
  const gap = hit('gap-bay', 'none', provenance);
  assert.deepEqual(confidenceAt([gap, estimated, measured], 'es'), {
    tier: '1m-measured', gridM: 1, date: null, text: '1 m medido', sourcesHref: '/sources#region-measured-bay',
  });
  assert.deepEqual(confidenceAt([gap, estimated], 'es'), {
    tier: 'estimated', gridM: 8, date, text: 'estimado (cuadrícula de 8 m)', sourcesHref: '/sources#region-estimated-bay',
  });
  assert.deepEqual(confidenceAt([gap], 'es'), {
    tier: 'none', gridM: null, date: null, text: 'sin levantamiento', sourcesHref: '/sources#region-gap-bay',
  });
});

// Sorting in place or reaching for the page/map at runtime breaks this Node-only readout.
test('C3: readout works in Node with frozen hits and no browser or map', () => {
  const hits = Object.freeze([tiers[4][0], tiers[0][0]]);
  assert.equal(typeof globalThis.document, 'undefined');
  assert.deepEqual(confidenceAt(hits, 'en'), tiers[0][1]);
  assert.deepEqual(hits, [tiers[4][0], tiers[0][0]]);
});
