import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {coverageModel, renderMap, renderList} from '../dist/coverage-map.js';

const index = JSON.parse(readFileSync(new URL('../dist/regions/index.json', import.meta.url), 'utf8'));
const region = (id, bounds, extra = {}) => ({id, name: id, status: 'preview', fishing_bounds: bounds, ...extra});
const hrefs = html => [...html.matchAll(/<a href="([^"]+)">/g)].map(m => m[1]);
const bounds = [-123, 35, -122, 36];
const tick = () => new Promise(resolve => setImmediate(resolve));
const json = (body, init) => new Response(JSON.stringify(body), init);
const pointer = id => ({
  region: id, status: 'reviewed', private: false, bounds, minzoom: 13, maxzoom: 13,
  sha256: 'a'.repeat(64), bytes: 4096, digest_root_sha256: 'b'.repeat(64),
  release_sha256: 'c'.repeat(64), envelope_sha256: 'd'.repeat(64),
  sources: [{id: 'fixture-survey', attribution: 'Fictional Survey Institute', label: 'measured',
    vertical_datum: 'NAVD88', survey_dates: ['2025-01-01'], rights_class: 'public', rights: {public_display: 'allowed'}}],
  detail_summary: {mask: 'transparent-nodata', depth_bands: [
    {source_id: 'fixture-survey', min_depth_m: 0, max_depth_m: 20, resolution_m: 2, support_class: 3}]},
  native_support_by_zoom: {13: {tiles: 1, limit_m: 91.44, sources: []}},
});

// Model only the DOM boundary of the page: installing markup creates the row
// labels, and updating their contents leaves each surrounding row intact.
function listHost() {
  let html = '', labels = [];
  return {
    set innerHTML(value) {
      html = value;
      labels = [...html.matchAll(/<span data-depth-region="([^"]+)">([^<]*)<\/span>/g)]
        .map(([, id, initial]) => {
          let contents = initial;
          return {
            dataset: {depthRegion: id},
            set textContent(value) { contents = value; },
            get textContent() { return contents.replace(/<[^>]+>/g, ''); },
            set innerHTML(value) { contents = value; },
            get innerHTML() { return contents; },
          };
        });
    },
    get innerHTML() {
      let i = 0;
      return html.replace(/(<span data-depth-region="[^"]+">)[^<]*/g, (_, open) => open + labels[i++].innerHTML);
    },
    querySelectorAll: selector => selector === '[data-depth-region]' ? labels : [],
    states: () => labels.map(label => [label.dataset.depthRegion, label.textContent]),
  };
}

async function loadPage(mock, name, fetcher, {lang = 'en', heading, list = listHost()} = {}) {
  const nodes = {'coverage-map': {}, 'coverage-list': list};
  const doc = {documentElement: {lang: 'en'}, getElementById: id => nodes[id],
    querySelectorAll: selector => selector === '[data-i18n]' && heading ? [heading] : []};
  const original = {document: globalThis.document, location: globalThis.location};
  globalThis.document = doc;
  globalThis.location = {search: `?lang=${lang}`};
  mock.method(globalThis, 'fetch', fetcher);
  try {
    await import(`../dist/coverage-map.js?${name}`);
    await tick();
    return {doc, svg: nodes['coverage-map'].innerHTML, list};
  } finally {
    for (const [key, value] of Object.entries(original)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

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
  // SC1722-17: the drawing is decorative and holds no links; the list below it is the only navigation.
  assert.deepEqual(hrefs(svg), []);
  assert.doesNotMatch(svg, /<a[\s>]|<button|tabindex|onclick|role="img"|aria-label/);
  assert.match(svg, /^<svg [^>]*aria-hidden="true" focusable="false"/);
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
  assert.equal([...renderMap(model).matchAll(/<rect class="cov-/g)].length, 2);
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
  // The worker serves the page at /coverage (ROUTE-1, server/routes/assets.ts), so its canonical is that path; status navigation still links the .html path.
  assert.match(status, /href="\/coverage\.html">Coverage map/);
  assert.match(page, /<link rel="canonical" href="https:\/\/skippercast\.com\/coverage" \/>/);
  const originalDocument = globalThis.document, originalFetch = globalThis.fetch;
  try {
    for (const [n, fetcher] of [async () => { throw Error('offline'); }, async () => ({ok: false})].entries()) {
      const nodes = {'coverage-map': {innerHTML: 'old'}, 'coverage-list': {innerHTML: 'old'}};
      globalThis.document = {documentElement: {lang: 'en'}, getElementById: id => nodes[id]};
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

// A fallback to English or treating a wrong-region pointer as missing loses the distinction in Spanish.
test('C1: Spanish Coverage distinguishes 404 from unreadable evidence and localizes the Sources link', async ({mock}) => {
  const page = readFileSync(new URL('../dist/coverage.html', import.meta.url), 'utf8');
  const heading = {textContent: 'Coverage', getAttribute: () => page.match(/<h1 data-i18n="([^"]+)"/)?.[1]};
  const {doc, svg, list} = await loadPage(mock, 'spanish', async url => {
    if (url === '/regions/index.json') return json({regions: [
      region('point-reyes', bounds, {name: 'Point Reyes'}), region('missing', bounds), region('wrong', bounds), null]});
    if (url === '/catalog/relief/point-reyes.json') return json(pointer('point-reyes'));
    if (url === '/catalog/relief/missing.json') return new Response(null, {status: 404});
    if (url === '/catalog/relief/wrong.json') return json(pointer('point-reyes'));
  }, {lang: 'es', heading});
  assert.equal(doc.documentElement.lang, 'es');
  assert.equal(heading.textContent, 'Cobertura');
  assert.match(page, /<noscript>.*lang="es"/);
  assert.match(svg, /<title>Point Reyes — Vista previa<\/title>/);
  assert.match(list.innerHTML, /Point Reyes — Vista previa \(revisión incompleta; consulta el aviso\)/);
  assert.match(list.innerHTML, /Regiones que no se pudieron dibujar: 1/);
  assert.match(renderList(coverageModel(null), 'es'), /No se pudo leer la lista de regiones/);
  assert.deepEqual(list.states(), [
    ['point-reyes', 'Mapa de profundidad: disponible — Fuentes'],
    ['missing', 'Mapa de profundidad: aún no disponible'],
    ['wrong', 'No se puede leer'],
  ]);
  assert.deepEqual(hrefs(list.innerHTML), [
    '/map?region=point-reyes', '/sources#region-point-reyes', '/map?region=missing', '/map?region=wrong',
  ]);
});

// Neither HTTP success alone nor a decodable body on HTTP failure proves readiness; only 404 means missing.
test('C1: English Coverage reserves not yet for 404 and links only decoder-ready pointers', async ({mock}) => {
  const cases = {
    ready: () => json(pointer('ready')),
    missing: () => new Response(null, {status: 404}),
    failed: () => json(pointer('failed'), {status: 503}),
    offline: () => { throw new TypeError('offline'); },
    malformed: () => new Response('{bad json'),
    null: () => json(null),
    wrong: () => json(pointer('ready')),
    held: () => json({...pointer('held'), status: 'held', previous: pointer('held')}),
    private: () => json({...pointer('private'), private: true}),
    identity: () => json({...pointer('identity'), digest_root_sha256: 'invalid'}),
    metadata: () => json({...pointer('metadata'), detail_summary: null}),
    resolution: () => json({...pointer('resolution'), native_support_by_zoom: {}}),
  };
  const ids = Object.keys(cases);
  const {list} = await loadPage(mock, 'english-states', async url => {
    if (url === '/regions/index.json') return json({regions: ids.map(id => region(id, bounds))});
    return cases[url.match(/^\/catalog\/relief\/([a-z]+)\.json$/)?.[1]]();
  });
  assert.deepEqual(list.states(), [['ready', 'Depth map: live — Sources'], ['missing', 'Depth map: not yet'],
    ...ids.slice(2).map(id => [id, 'Cannot be read'])]);
  assert.deepEqual(hrefs(list.innerHTML), ['/map?region=ready', '/sources#region-ready', ...ids.slice(1).map(id => `/map?region=${id}`)]);
});

// Hold the first fetch open: a sequential or all-or-nothing implementation stalls the other label.
test('C2: render before parallel GETs and make no additional requests for credits', async ({mock}) => {
  const first = Promise.withResolvers(), list = listHost(), requests = [];
  const {svg} = await loadPage(mock, 'parallel', async (url, options) => {
    requests.push([url, options?.method ?? 'GET', options?.redirect, hrefs(list.innerHTML)]);
    if (url === '/regions/index.json') return json({regions: [
      region('north', bounds), region('south', bounds), region('north', bounds), region('retired', bounds, {status: 'retired'})]});
    if (url === '/catalog/relief/north.json') return first.promise;
    throw new TypeError('offline');
  }, {list});
  const links = ['/map?region=north', '/map?region=south', '/map?region=north'];
  const expected = [
    ['/regions/index.json', 'GET', undefined, []],
    ['/catalog/relief/north.json', 'GET', 'error', links],
    ['/catalog/relief/south.json', 'GET', 'error', links],
  ];
  assert.deepEqual(requests, expected);
  assert.deepEqual(list.states(), [['north', 'Depth map: checking…'], ['south', 'Cannot be read'], ['north', 'Depth map: checking…']]);
  assert.deepEqual(hrefs(svg), []);
  first.resolve(json(pointer('north')));
  await tick();
  assert.deepEqual(requests, expected);
  assert.deepEqual(list.states(), [['north', 'Depth map: live — Sources'], ['south', 'Cannot be read'], ['north', 'Depth map: live — Sources']]);
  assert.deepEqual(hrefs(list.innerHTML), ['/map?region=north', '/sources#region-north', '/map?region=south', '/map?region=north', '/sources#region-north']);
});

// A valid pointer carries attribution; rendering that payload instead of just its state leaks it here.
test('C2: Coverage shows a generic credits link without source names or IDs', async ({mock}) => {
  const {svg, list} = await loadPage(mock, 'no-sources', async url => url === '/regions/index.json'
    ? json({regions: [region('port', bounds)]}) : json(pointer('port')));
  assert.equal(list.innerHTML, '<ul><li><a href="/map?region=port">port — Preview (not fully reviewed; see its banner)</a> — <span data-depth-region="port">Depth map: live — <a href="/sources#region-port">Sources</a></span></li></ul>');
  assert.doesNotMatch(svg, /Fictional Survey Institute|fixture-survey/);
});

test('coverage English map, region links and messages retain their existing copy', () => {
  const models = [coverageModel({regions: [region('port', [-123, 35, -122, 36], {name: 'Port & Bay', status: 'active'}), region('preview', [-123, 36, -122, 37]), null]}), coverageModel(null), coverageModel({regions: []})];
  const html = models.map(m => renderMap(m, {lang: 'en'}) + renderList(m, 'en')).join('\n')
    .replaceAll(/ — <span data-depth-region="[^"]+">Depth map: checking…<\/span>/g, '');
  assert.equal(createHash('sha256').update(html).digest('hex'), 'e12561220690ddb4f77f49598ce2a3a56fddfec2cfac4c83c261e51aad6716c0');
});
