// RF1540-3: a region index of the wrong shape shows the regional-unavailable row without blocking the independent
// sections and without requesting an invented region.
import assert from 'node:assert/strict';
import test from 'node:test';
import {main, renderRows, statusRows} from '../dist/status-page.js';

const NOW = Date.parse('2026-11-01T20:30:00Z');
const stamp = new Date(NOW - 600_000).toISOString();
const UNAVAILABLE = 'Regional buoy feeds';
const regionFeed = {published_at: stamp, sources: {}};
const indexOf = (...ids) => ({regions: ids.map(id => ({id, name: `Name ${id}`}))});

const BAD = {
  'object regions': {regions: {}},
  'string regions': {regions: 'morro-bay'},
  'null member': {regions: [null]},
  'member without id': {regions: [{}]},
  'numeric member': {regions: [7]},
  'array member': {regions: [['morro-bay']]},
  'numeric id': {regions: [{id: 7}]},
  'empty id': {regions: [{id: ''}]},
  'slash id': {regions: [{id: 'a/b'}]},
  'percent id': {regions: [{id: 'a%2fb'}]},
  'underscore id': {regions: [{id: 'a_b'}]},
  'absent regions': {},
  'scalar root': 5,
  'array root': [{id: 'morro-bay'}],
  'valid then invalid': {regions: [{id: 'morro-bay'}, null]},
  'invalid then valid': {regions: [{}, {id: 'morro-bay'}]},
};

const names = rows => rows.map(r => r.name);

for (const [label, index] of Object.entries(BAD)) {
  test(`statusRows: ${label} reads as region list unavailable`, () => {
    const rows = statusRows({conditions: null, data: null, index, regions: {'morro-bay': regionFeed}}, NOW);
    assert.ok(names(rows).includes(UNAVAILABLE), 'unavailable row present');
    assert.ok(!names(rows).some(n => n.startsWith('Buoys:')), 'no partial region rows');
    assert.ok(names(rows).includes('Daily evidence feed'), 'independent rows still produced');
  });
}

test('statusRows: empty and null index keep the unavailable row; valid index keeps order and id fallback', () => {
  for (const index of [{regions: []}, null, undefined]) {
    assert.ok(names(statusRows({index}, NOW)).includes(UNAVAILABLE));
  }
  const rows = statusRows({index: {regions: [{id: 'b-1', name: 'Beta'}, {id: 'a-2'}]}, regions: {'b-1': regionFeed, 'a-2': regionFeed}}, NOW);
  assert.deepEqual(names(rows).filter(n => n.startsWith('Buoys:')), ['Buoys: Beta', 'Buoys: a-2']);
  assert.ok(!names(rows).includes(UNAVAILABLE));
});

/** Runs the real main() against a fake fetch and DOM; resolves to {requests, els}. */
async function runMain(index, {indexFails = false} = {}) {
  const requests = [];
  const els = {};
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.document = {getElementById: id => (els[id] ||= {innerHTML: '', textContent: 'Loading the published feeds…'})};
  globalThis.fetch = async url => {
    requests.push(url);
    if (url === '/regions/index.json') {
      if (indexFails === 'reject') throw new Error('network down');
      if (indexFails === 'http') return {ok: false, json: async () => ({})};
      if (indexFails === 'json') return {ok: true, json: async () => { throw new SyntaxError('bad json'); }};
      return {ok: true, json: async () => index};
    }
    if (/\/regions\/[^/]+\/latest\.json$/.test(url) && url.includes('/feeds/conditions/regions/morro-bay/latest')) return {ok: true, json: async () => regionFeed};
    if (url === '/feeds/conditions/latest.json' || url === '/feeds/data/latest.json') return {ok: true, json: async () => ({published_at: stamp, sources: {}})};
    return {ok: false, json: async () => null};
  };
  try { await main(); } finally {
    globalThis.fetch = saved.fetch;
    if (saved.document === undefined) delete globalThis.document; else globalThis.document = saved.document;
  }
  return {requests, els};
}

const indexDriven = requests => requests.filter(u => /\/feeds\/conditions\/regions\/[^/]+\/latest\.json$/.test(u));

for (const [label, index] of Object.entries(BAD)) {
  test(`main: ${label} renders every section and requests no region`, async () => {
    const {requests, els} = await runMain(index);
    assert.deepEqual(indexDriven(requests), [], 'no index-driven regional request');
    assert.ok(!requests.some(u => u.includes('undefined')), 'no invented region');
    assert.ok(els['status-rows'].innerHTML.includes(UNAVAILABLE), 'unavailable row rendered');
    assert.ok(els['status-rows'].innerHTML.includes('Daily evidence feed'), 'independent rows rendered');
    assert.match(els['status-checked'].textContent, / UTC$/, 'loading text replaced');
    assert.ok(els['status-coverage'].innerHTML.length > 0, 'unwatched-source section rendered');
  });
}

for (const failure of ['reject', 'http', 'json']) {
  test(`main: index ${failure} failure keeps the unavailable row and the other sections`, async () => {
    const {requests, els} = await runMain(null, {indexFails: failure});
    assert.deepEqual(indexDriven(requests), []);
    assert.ok(els['status-rows'].innerHTML.includes(UNAVAILABLE));
    assert.ok(els['status-rows'].innerHTML.includes('Daily evidence feed'));
  });
}

test('main: valid index fetches each encoded latest URL once, in order; a failed region does not hide its neighbour', async () => {
  const {requests, els} = await runMain(indexOf('morro-bay', 'half-moon-bay'));
  assert.deepEqual(indexDriven(requests), ['/feeds/conditions/regions/morro-bay/latest.json', '/feeds/conditions/regions/half-moon-bay/latest.json']);
  const html = els['status-rows'].innerHTML;
  assert.ok(html.includes('Buoys: Name morro-bay') && html.includes('Buoys: Name half-moon-bay'));
  assert.ok(!html.includes(UNAVAILABLE));
});

test('rendered unavailable row never echoes the refused input', () => {
  const html = renderRows(statusRows({index: {regions: [{id: '<script>x</script>'}]}}, NOW));
  assert.ok(!html.includes('<script>x'), 'refused id not echoed');
  assert.ok(html.includes(UNAVAILABLE));
});
