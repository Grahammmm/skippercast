import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {attachBottomRelief} from '../web/map/bottom-relief.ts';

// Reuse the existing one-tile PMTiles directory. Retag it as PNG for the
// transport test; PMTiles returns opaque bytes, not decoded images.
const bytes = readFileSync(new URL('./fixtures/basemap/tiny.pmtiles', import.meta.url));
bytes[99] = 2;
const payloadOffset = Number(bytes.readBigUInt64LE(56));
const sha = body => createHash('sha256').update(body).digest('hex');
const hash = sha(bytes);
const chunkPath = '10/2_6.json';
const chunk = JSON.stringify([[168, 404, sha(bytes.subarray(payloadOffset))]]);
const digestRoot = JSON.stringify({chunks: {[chunkPath]: sha(chunk)}});
const digestRootHash = sha(digestRoot);
const id = 'synthetic-survey';
const pointer = region => ({region, status: 'reviewed', private: false, sha256: hash, bytes: bytes.length,
  minzoom: 10, maxzoom: 10, bounds: [-121, 35, -120, 36], release_sha256: 'b'.repeat(64),
  envelope_sha256: 'c'.repeat(64), digest_root_sha256: digestRootHash,
  sources: [{id, rights_class: 'public', rights: {public_display: 'allowed'}, attribution: 'Synthetic survey',
    label: 'estimated', vertical_datum: 'synthetic', survey_dates: ['2025-01-01']}],
  detail_summary: {mask: 'transparent-nodata', depth_bands: [{source_id: id, resolution_m: 10, min_depth_m: 0, max_depth_m: 90}]},
  native_support_by_zoom: {10: {tiles: 1, limit_m: 91.44, sources: []}}});
const tick = () => new Promise(resolve => setImmediate(resolve));

function chart(t, surveyView, surveys = new Map()) {
  const root = {dataset: {}};
  const old = Object.fromEntries(['document', 'getComputedStyle', 'MutationObserver'].map(k => [k, globalThis[k]]));
  let themeChanged;
  const canvas = {scale() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
    getImageData(_x, _y, width, height) { return {width, height}; }};
  Object.assign(globalThis, {
    document: {documentElement: root,
      createElement: tag => tag === 'canvas' ? {getContext: () => canvas} : {append() {}, setAttribute() {}}},
    getComputedStyle: () => ({getPropertyValue: key => key.endsWith('opacity') ? '1' : `${root.dataset.theme ?? 'dark'}:${key}`}),
    MutationObserver: class { constructor(cb) { themeChanged = cb; } observe() {} disconnect() { themeChanged = null; } },
  });
  const errors = [], fetches = [], handles = [], readies = [], looks = [];
  const seafloor = signal(false), field = signal(false);
  let overlay, before, protocol, breakRange = false;
  const engine = {
    view: {on: () => () => {}},
    setOverlay(owner, next, anchor) { assert.equal(owner, 'bottom-relief'); overlay = next; before = anchor; },
    setRasterOpacity(id, opacity) { assert.equal(id, overlay.layers[0].id); overlay.layers[0].paint['raster-opacity'] = opacity; },
  };
  const library = {addProtocol(_, action) { protocol = action; }};
  const start = (region, reply = pointer(region)) => {
    const handle = attachBottomRelief({engine, region, library, surveyView, page: 'https://chart.test/map',
      seafloorOn: () => seafloor.value, fieldOn: () => field.value, unavailable: e => errors.push(e.message),
      ready: look => { readies.push(region); looks.push(look); },
      async fetchFn(raw, init) {
        const url = new URL(raw);
        fetches.push([url.pathname, init]);
        const digestPath = `/feeds/tiles/relief/${region}/${hash}.digests/${digestRootHash}/`;
        if (url.pathname === digestPath + 'root.json') return new Response(digestRoot);
        if (url.pathname === digestPath + chunkPath) return new Response(chunk);
        if (url.pathname === `/catalog/relief/${region}.json`) { const body = await reply; return body instanceof Response ? body : Response.json(body); }
        if (url.pathname.includes('/survey/')) return surveys.get(url.pathname)?.() ?? new Response('not a bound response');
        if (breakRange) return new Response(bytes); // full response must never be mistaken for a range
        const [, start, end] = /^bytes=(\d+)-(\d+)$/.exec(init.headers.Range).map(Number);
        return new Response(bytes.subarray(start, end + 1), {status: 206,
          headers: {'Content-Range': `bytes ${start}-${end}/${bytes.length}`}});
      }});
    handles.push(handle);
    return handle;
  };
  t.after(() => { handles.reverse().forEach(h => h.destroy()); Object.assign(globalThis, old); });
  const tile = (url, x = 168) => Promise.resolve().then(() => protocol({url: url.replace('{z}/{x}/{y}', `10/${x}/404`)}, new AbortController()));
  return {start, tile, errors, fetches, readies, looks, seafloor, field, breakRange: () => { breakRange = true; },
    theme(value) { root.dataset.theme = value; themeChanged?.(); },
    get overlay() { return overlay; }, get before() { return before; },
    get template() { return Object.values(overlay.sources)[0].tiles[0]; }};
}

test('region switches retire the old reader; a late or held pointer cannot add a source', async t => {
  const c = chart(t);
  const north = c.start('north');
  await tick();
  const northTiles = c.template;
  assert.deepEqual(c.fetches.map(([url]) => url), ['/catalog/relief/north.json']);
  assert.deepEqual(Buffer.from((await c.tile(northTiles)).data), bytes.subarray(payloadOffset));
  await assert.rejects(c.tile(northTiles, 169), {status: 404}, 'an absent tile permits overzoom without retiring the region');
  assert.ok(c.overlay);
  north.destroy();
  assert.equal(c.overlay, null);
  const count = c.fetches.length;
  await assert.rejects(c.tile(northTiles), {status: 404});
  assert.equal(c.fetches.length, count);
  let release;
  const stale = c.start('north', new Promise(resolve => { release = resolve; }));
  stale.destroy();
  c.start('south');
  await tick();
  const southTiles = c.template;
  release(pointer('north'));
  await tick();
  assert.equal(c.template, southTiles);
  assert.notEqual(northTiles, southTiles);
  await c.tile(southTiles);
  assert.ok(c.fetches.at(-1)[0].startsWith('/feeds/tiles/relief/south/'));
  assert.deepEqual(c.errors, []);
});

test('held inputs do not fetch archive bytes; a failed range unloads the raster and land stack', async t => {
  const c = chart(t);
  c.start('held', {...pointer('held'), status: 'held'});
  await tick();
  assert.equal(c.overlay, undefined);
  assert.equal(c.fetches.length, 1);
  c.start('north');
  await tick();
  const active = c.template;
  await c.tile(active);
  c.breakRange();
  await assert.rejects(c.tile(active), /did not return the requested range/);
  assert.equal(c.overlay, null);
  assert.deepEqual(c.errors, ['Relief unavailable: unreviewed', 'Relief server did not return the requested range']);
  await assert.rejects(c.tile(active), {status: 404});
});

test('land, parks and coast cover the raster; theme and field paints preserve the source', async t => {
  const c = chart(t);
  c.seafloor.value = true;
  c.theme('light'); // late attachment must already use the changed theme
  c.start('north');
  await tick();
  const [raster, earth, parks, coast] = c.overlay.layers;
  assert.equal(c.before, 'boundaries'); // above the water fill, under labels and contours
  assert.equal(raster.type, 'raster');
  assert.equal(raster.paint['raster-resampling'], 'linear');
  assert.equal(raster.paint['raster-brightness-min'], 0.30);
  assert.equal(raster.paint['raster-brightness-max'], 1);
  assert.equal(earth.paint['fill-color'], 'light:--map-land');
  assert.equal(parks.paint['fill-color'], 'light:--map-park');
  assert.equal(coast.paint['line-color'], 'light:--map-coast');
  await c.tile(c.template);
  const source = raster.source, count = c.fetches.length;
  c.theme('dark');
  c.field.value = true;
  assert.equal(c.overlay.layers[0].source, source);
  assert.equal(c.overlay.layers[0].paint['raster-brightness-max'], 0.75);
  assert.equal(c.overlay.layers[0].paint['raster-brightness-min'], 0);
  assert.equal(c.overlay.layers[0].paint['raster-saturation'], -0.8);
  // MSK-2 (kit overlays.base_desaturation_when_field_on; this replaces the old literal raster-opacity 0.6): a field never
  // fades the relief, it desaturates it, and Seafloor type's stronger dimming wins while both are on. Believable bugs:
  // the old fade kept, the field rule overriding Seafloor type, or the desaturation staying after the field goes.
  assert.equal(c.overlay.layers[0].paint['raster-opacity'], 1);
  c.seafloor.value = false;
  assert.equal(c.overlay.layers[0].paint['raster-saturation'], -0.4);
  assert.equal(c.overlay.layers[0].paint['raster-opacity'], 1);
  assert.equal(c.overlay.layers[0].paint['raster-brightness-max'], 1);
  c.field.value = false;
  assert.equal(c.overlay.layers[0].paint['raster-saturation'], 0);
  assert.equal(c.fetches.length, count);
});

// Contract: DATA-LIVE-9 / E2E-16. The overlay is public: attach takes no admin input, and a region draws relief only when
// its pointer resolves ready. Believable bugs: drawing or probing the archive without a pointer; a refusal drawn anyway;
// source or attribution text leaking onto the map through the raster source.
test('a region without a ready pointer draws nothing and requests no archive or tile', async t => {
  const c = chart(t);
  c.start('no-pointer', new Response('', {status: 404}));
  c.start('unreviewed', {...pointer('unreviewed'), status: 'held'});
  c.start('private', {...pointer('private'), private: true});
  c.start('mbari', {...pointer('mbari'), sources: [{...pointer('x').sources[0], id: 'mbari-survey'}]});
  await tick();
  assert.equal(c.overlay, undefined);
  assert.deepEqual(c.readies, []);
  assert.deepEqual(c.fetches.map(([url]) => url).sort(), ['/catalog/relief/mbari.json', '/catalog/relief/no-pointer.json',
    '/catalog/relief/private.json', '/catalog/relief/unreviewed.json']);
});

test('a CSUMB-lineage pointer under the G 2026-11-18 basis draws once, with no source or attribution text on the map', async t => {
  const c = chart(t);
  const p = pointer('csumb-region');
  p.sources = [{...p.sources[0], id: 'csumb-ventresca-cc2', provider: 'CSUMB SFML', attribution: 'CSUMB Seafloor Mapping Lab',
    publication_allowed: false, review_status: 'restricted', rights: {public_display: 'allowed', license: 'unresolved'}}];
  p.detail_summary.depth_bands[0].source_id = 'csumb-ventresca-cc2';
  c.start('csumb-region', p);
  await tick();
  assert.deepEqual(c.readies, ['csumb-region']);
  assert.ok(c.overlay);
  c.theme('light'); c.field.value = true; // a repaint is not a second announcement
  assert.deepEqual(c.readies, ['csumb-region']);
  const drawn = JSON.stringify(c.overlay);
  assert.equal(Object.values(c.overlay.sources)[0].attribution, undefined);
  assert.doesNotMatch(drawn, /csumb|sfml|mbari|attribution|synthetic survey|license|licence/i);
  assert.deepEqual(c.errors, []);
});

// MSK-2 contract (STYLE-PIPELINE-DESIGN rev 2 § 6): `ready` hands the legend the look the drawn tiles were baked with. A
// malformed `style` member still draws the reviewed tiles but reports an unknown look (null), never the default look.
// Believable bugs: the legend reading the default style instead of the pointer, or a bad member refusing the relief.
test('ready reports the pointer look: legacy without style, the baked digest with one, null when malformed', async t => {
  const c = chart(t), style = {baked: 'd'.repeat(64), contours: 'e'.repeat(64), habitat: null, built_with: 'nearshore-v1.0.0'};
  c.start('legacy');
  await tick();
  c.start('styled', {...pointer('styled'), style});
  await tick();
  c.start('malformed', {...pointer('malformed'), style: {...style, baked: 'not-a-digest'}});
  await tick();
  assert.deepEqual(c.readies, ['legacy', 'styled', 'malformed']);
  assert.deepEqual(c.looks, ['deep-fixed-v1', 'd'.repeat(64), null]);
  assert.deepEqual(c.errors, []);
});

// Never fetch optional detail until requested. Bad delivery must remove only the
// survey control, not the underlying relief or the region's ability to read tiles.
test('reviewed survey opt-in is lazy and a bad delivery preserves relief', async t => {
  let view;
  const c = chart(t, next => { view = next; });
  const p = pointer('north');
  p.survey_detail = {wire: {bytes: 15, sha256: 'a'.repeat(64)}, decoded: {bytes: 27, sha256: 'd'.repeat(64)}};
  c.start('north', p);
  await tick();
  assert.deepEqual(c.fetches.map(([url]) => url), ['/catalog/relief/north.json']);
  assert.ok(view, 'missing opt-in');
  const template = c.template;
  view.toggle(); view.toggle();
  await tick();
  assert.equal(view, null);
  assert.deepEqual(c.fetches.map(([url]) => url), ['/catalog/relief/north.json',
    `/feeds/tiles/relief/north/${p.envelope_sha256}/survey/${p.survey_detail.wire.sha256}.geojson.br`]);
  assert.equal(c.template, template);
  assert.deepEqual(Buffer.from((await c.tile(template)).data), bytes.subarray(payloadOffset));
  assert.deepEqual(c.errors, []);
});

// M32 contract: with Layers closed the Chart shows where there is no reviewed survey. A pointer may bind, next to the
// survey detail, a small companion holding only the detail's tier-none areas; it loads at start (never the multi-MB
// detail) and draws only the existing hatch. Believable bugs: eagerly fetching the full detail; drawing the companion's
// outline/labels or a measured tint; trusting a companion that carries any other tier, fails its digest, or is bound
// without the reviewed detail it was derived from; losing the hatch when the opt-in detail is refused.
test('a bound no-survey companion draws only the hatch at start and never fetches the detail early', async t => {
  const square = [[[-121, 35], [-120, 35], [-120, 36], [-121, 35]]];
  const doc = (features, region = 'north') => Buffer.from(JSON.stringify({type: 'FeatureCollection', region, navigation: 'NOT FOR NAVIGATION',
    features: features.map(properties => ({type: 'Feature', properties, geometry: {type: 'Polygon', coordinates: square}}))}));
  const none = {tier: 'none', sources: []};
  const estimated = {tier: 'estimated', sources: [id], source: 'Synthetic survey', grid_m: 10};
  const surveys = new Map(), detail = {wire: {bytes: 15, sha256: 'a'.repeat(64)}, decoded: {bytes: 27, sha256: 'd'.repeat(64)}};
  const bound = (region, body, pins = {wire: {bytes: 40, sha256: sha(`wire:${body}`)}, decoded: {bytes: body.length, sha256: sha(body)}}) => {
    surveys.set(`/feeds/tiles/relief/${region}/${'c'.repeat(64)}/survey/${pins.wire.sha256}.geojson.br`,
      () => new Response(body, {headers: {'Content-Encoding': 'br', 'Content-Length': String(pins.wire.bytes)}}));
    return {...pointer(region), survey_detail: detail, survey_gap: pins};
  };
  let view;
  const c = chart(t, next => { view = next; }, surveys);
  const layerIds = () => c.overlay.layers.map(l => l.id.replace(/^bottom-relief-\d+/, ''));
  const gapBody = doc([none]), p = bound('north', gapBody);
  c.start('north', p);
  await tick(); await tick(); await tick();
  assert.deepEqual(c.fetches.map(([url]) => url), ['/catalog/relief/north.json',
    `/feeds/tiles/relief/north/${'c'.repeat(64)}/survey/${p.survey_gap.wire.sha256}.geojson.br`]);
  assert.deepEqual(layerIds(), ['', '-survey-hatch', '-earth', '-parks', '-coast']);
  const [, data] = Object.entries(c.overlay.sources).find(([key]) => key.endsWith('-survey'));
  assert.deepEqual(data.data.features.map(f => f.properties.tier), ['none']);
  assert.equal(typeof c.overlay.themePatterns, 'function');
  assert.equal(c.overlay.inspect, undefined, 'the companion alone never answers a tap');
  // Opting in still fetches the detail lazily; a refused detail removes the control but keeps the default cue.
  view.toggle();
  await tick(); await tick(); await tick();
  assert.equal(c.fetches.at(-1)[0], `/feeds/tiles/relief/north/${'c'.repeat(64)}/survey/${detail.wire.sha256}.geojson.br`);
  assert.equal(view, null);
  assert.deepEqual(layerIds(), ['', '-survey-hatch', '-earth', '-parks', '-coast']);

  // Refusals: any other tier, a digest mismatch, a companion without its detail binding, an oversized pin.
  const refusals = {
    mixed: bound('mixed', doc([none, estimated], 'mixed')),
    digest: bound('digest', doc([none], 'digest'), {wire: {bytes: 40, sha256: 'e'.repeat(64)}, decoded: {bytes: doc([none], 'digest').length, sha256: 'f'.repeat(64)}}),
    orphan: (({survey_detail: _, ...rest}) => rest)(bound('orphan', gapBody)),
    oversized: bound('oversized', gapBody, {wire: {bytes: 256 * 1024 + 1, sha256: sha('big')}, decoded: {bytes: gapBody.length, sha256: sha(gapBody)}}),
  };
  for (const [region, body] of Object.entries(refusals)) {
    c.start(region, body);
    await tick(); await tick(); await tick();
    assert.ok(!layerIds().includes('-survey-hatch'), `${region}: no hatch`);
    assert.ok(!Object.keys(c.overlay.sources).some(key => key.endsWith('-survey')), `${region}: no survey source`);
  }
  assert.ok(!c.fetches.some(([url]) => url.startsWith('/feeds/tiles/relief/orphan/') || url.startsWith('/feeds/tiles/relief/oversized/')),
    'an unbound or oversized companion is never requested');
  assert.deepEqual(c.errors, []);
});
