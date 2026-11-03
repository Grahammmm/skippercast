import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {coverageModel, renderMap, renderList} from '../dist/coverage-map.js';

const index = JSON.parse(readFileSync(new URL('../dist/regions/index.json', import.meta.url), 'utf8'));
const region = (id, bounds, extra = {}) => ({id, name: id, status: 'preview', fishing_bounds: bounds, ...extra});
const hrefs = html => [...html.matchAll(/<a href="([^"]+)">/g)].map(m => m[1]);

test('published regions are sorted, mapped within the viewBox, and linked exactly', () => {
  const model = coverageModel(index);
  assert.equal(model.rows.length, 16);
  assert.equal(model.rows.filter(r => r.status === 'active').length, 1);
  assert.equal(model.skipped, 0);
  for (let i = 1; i < model.rows.length; i++) assert.ok(model.rows[i - 1].bounds[3] >= model.rows[i].bounds[3]);
  const svg = renderMap(model, {width: 360});
  const view = svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);
  assert.ok(view);
  const boxes = [...svg.matchAll(/<rect class="cov-(active|preview)" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"/g)];
  assert.equal(boxes.length, 16);
  for (const [, , sx, sy, sw, sh] of boxes) {
    const [x, y, w, h] = [sx, sy, sw, sh].map(Number);
    assert.ok(x >= 0 && y >= 0 && w > 0 && h > 0 && x + w <= +view[1] + 1e-9 && y + h <= +view[2] + 1e-9);
  }
  const expected = model.rows.map(r => `/map?region=${r.id}`);
  assert.deepEqual(hrefs(svg), expected);
  assert.deepEqual(hrefs(renderList(model)), expected);
  assert.match(svg, /35°N/);
  assert.match(svg, />Active<\/text>/);
  assert.match(svg, />Preview<\/text>/);
  assert.match(renderList(model), /Active \(reviewed\)/);
  assert.match(renderList(model), /Preview \(not fully reviewed; see its banner\)/);
});

test('adjoining latitudes are both drawn, inverted and zero bounds are counted', () => {
  const model = coverageModel({regions: [region('one', [-123, 35, -122, 36]), region('two', [-123, 36, -122, 37]),
    region('zero', [-123, 37, -122, 37]), region('backwards', [-122, 36, -123, 37])]});
  assert.equal(model.rows.length, 2);
  assert.equal(model.skipped, 2);
  assert.equal(hrefs(renderMap(model)).length, 2);
  assert.match(renderList(model), /2 regions could not be drawn/);
});

test('malformed rows are skipped without leaking rejected values', () => {
  const bad = [
    region('nan', [-123, NaN, -122, 36]), region('string', [-123, '35', -122, 36]),
    region('short', [-123, 35, -122]), region('retired-id', [-123, 35, -122, 36], {status: 'retired'}),
    region('../x', [-123, 35, -122, 36]), region('<script>', [-123, 35, -122, 36]),
    null, region('missing', undefined), region('infinite', [-123, 35, Infinity, 36]),
  ];
  const model = coverageModel({regions: [region('good', [-123, 35, -122, 36]), ...bad]});
  assert.equal(model.skipped, bad.length);
  assert.equal(model.rows.length, 1);
  const html = renderMap(model) + renderList(model);
  for (const value of ['../x', '<script>', 'retired-id', 'NaN', 'Infinity']) assert.ok(!html.includes(value), value);
  assert.match(html, /9 regions could not be drawn/);
  const allBad = coverageModel({regions: bad});
  assert.equal(renderMap(allBad), '');
  assert.doesNotMatch(renderList(allBad), /No regions are published/);
});

test('unreadable and genuinely empty indexes produce different states', () => {
  for (const input of [null, [], {regions: 5}]) {
    const model = coverageModel(input);
    assert.equal(model.error, 'unreadable');
    assert.equal(renderMap(model), '');
    assert.match(renderList(model), /The region list could not be read. Try again later\./);
  }
  const empty = coverageModel({regions: []});
  assert.equal(renderMap(empty), '');
  assert.match(renderList(empty), /No regions are published yet\./);
});

test('names are escaped in SVG titles and list rows', () => {
  const model = coverageModel({regions: [region('safe', [-123, 35, -122, 36], {name: '<img onerror="x"> & friends'})]});
  for (const html of [renderMap(model), renderList(model)]) {
    assert.ok(!html.includes('<img'));
    assert.match(html, /&lt;img onerror=&quot;x&quot;&gt; &amp; friends/);
  }
  assert.match(renderMap(model), /<title>&lt;img/);
});

test('page uses the public index and handles network and HTTP failures in the containers', async () => {
  const page = readFileSync(new URL('../dist/coverage.html', import.meta.url), 'utf8');
  const status = readFileSync(new URL('../dist/status.html', import.meta.url), 'utf8');
  assert.match(page, /id="coverage-map"/);
  assert.match(page, /id="coverage-list"/);
  // The extensionless /coverage route is not registered (follow-up t_f4e422ca); link and canonical use the .html path.
  assert.match(status, /href="\/coverage\.html">Coverage map/);
  assert.match(page, /<link rel="canonical" href="https:\/\/skippercast\.com\/coverage\.html" \/>/);
  assert.doesNotMatch(page + status, /href="[^"]*\/coverage"/);
  const originalDocument = globalThis.document, originalFetch = globalThis.fetch;
  try {
    for (const [n, fetcher] of [async () => { throw Error('offline'); }, async () => ({ok: false})].entries()) {
      const nodes = {'coverage-map': {innerHTML: 'old'}, 'coverage-list': {innerHTML: 'old'}};
      globalThis.document = {getElementById: id => nodes[id]};
      globalThis.fetch = async (url, options) => { assert.equal(url, '/regions/index.json'); assert.equal(options.cache, 'no-store'); return fetcher(); };
      await import(`../dist/coverage-map.js?failure=${n}`);
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(nodes['coverage-map'].innerHTML, '');
      assert.match(nodes['coverage-list'].innerHTML, /could not be read/);
    }
  } finally {
    globalThis.document = originalDocument;
    globalThis.fetch = originalFetch;
  }
});
