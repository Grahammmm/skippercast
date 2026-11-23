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
  // Metadata must not let a coarser hit replace a finer hit from the same region.
  const finer = hit('fourth-bay', '2m');
  const [coarser] = tiers[3];
  const expected = {tier: '2m', gridM: null, date: null, text: '2 m', sourcesHref: '/sources#region-fourth-bay'};
  assert.deepEqual(confidenceAt([finer, coarser], 'en'), expected);
  assert.deepEqual(confidenceAt([coarser, finer], 'en'), expected);
});

// Ranking all equal-tier hits by metadata would steal the first region's readout.
test('C1: equal-tier hits from different regions keep the first hit in either order', () => {
  const [first, expected] = tiers[3];
  const second = hit('other-bay', 'estimated');
  assert.deepEqual(confidenceAt([first, second], 'en'), expected);
  assert.deepEqual(confidenceAt([second, first], 'en'), {
    tier: 'estimated', gridM: null, date: null, text: 'estimated', sourcesHref: '/sources#region-other-bay',
  });
});

test('RMSC-151: same-region, same-tier duplicates prefer grid, then date, without merging', () => {
  const duplicate = extra => hit('other-bay', 'estimated', extra);
  const grid = duplicate({grid_m: 4});
  const dated = duplicate({date});
  const gridReadout = {tier: 'estimated', gridM: 4, date: null, text: 'estimated (4 m grid)', sourcesHref: '/sources#region-other-bay'};
  const datedReadout = {tier: 'estimated', gridM: null, date, text: 'estimated', sourcesHref: '/sources#region-other-bay'};
  for (const [why, winner, other, expected] of [
    ['an unconditional first hit can lose a known grid', grid, duplicate(), gridReadout],
    ['a grid-only check can lose a known date', dated, duplicate({grid_m: 0, date: ' '}), datedReadout],
    ['a truthiness check can mistake an infinite grid for known metadata', dated, duplicate({grid_m: Infinity}), datedReadout],
    ['a date-only tie-break or field merge can override the grid hit', grid, dated, gridReadout],
  ]) {
    assert.deepEqual(confidenceAt([other, winner], 'en'), expected, why);
    assert.deepEqual(confidenceAt([winner, other], 'en'), expected, why);
  }
  // Equal metadata quality is not a reason to switch to the last duplicate.
  assert.deepEqual(confidenceAt([grid, duplicate({grid_m: 8})], 'en'), gridReadout);
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
