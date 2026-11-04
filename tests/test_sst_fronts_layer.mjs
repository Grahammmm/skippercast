// BF-sst-fronts: web/map/fronts.ts draws the published offshore fronts as edges with a band, says their age in words and
// draws nothing once they are past the feed's limit. The feed here is synthetic, in the publisher's shape
// (src/skippercast/pipeline/sst_fronts.py).
import assert from 'node:assert/strict';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {
  FRONTS_BAND_LAYER, FRONTS_LAYER, MAX_AGE_MS, NONE, ageWords, frontFeatures, frontsMark, frontsOverlay, frontsStatus, readFronts, regionalFronts,
} from '../web/map/fronts.ts';
import {LAYERS, layerEntry} from '../web/map/layers.ts';
import {readPalette} from '../web/map/palette.ts';
import {PROFILE_TABLE, RAIL_IDS} from '../web/profile.ts';

const HOUR = 3_600_000, REGION = 'test-coast', PAGE = 'https://s.test/map';
const NOW = new Date('2026-10-16T12:00:00Z');
const ago = hours => new Date(NOW.getTime() - hours * HOUR).toISOString();
const sentinel = readPalette(name => `token(${name})`);

const front = (observedAt, id = 'f1') => ({id, observed_at: observedAt, strength_c_per_km: 0.2, uncertainty_c: 0.3, band_half_width_km: 1.5,
  geometry: {type: 'LineString', coordinates: [[-121.0, 35.0], [-120.9, 35.1], [-120.8, 35.2]]}});
const doc = (fronts, extra = {}) => ({schema_version: 1, region_id: REGION, layer_id: 'sst-fronts', product: 'NOAA Geo-Polar Blended night SST', credit: 'NOAA CoastWatch',
  max_age_hours: 48, observed_at: fronts[0]?.observed_at ?? null, fronts, ...extra});
const ready = (data, region = REGION) => ({state: 'ready', doc: readFronts(data, region)});
const fetchOf = (status, body) => async () => ({status, ok: status >= 200 && status < 300, json: async () => { if (body instanceof Error) throw body; return body; }});

test('age is given in words, never a bare timestamp', () => {
  assert.equal(ageWords(30_000), 'less than a minute ago');
  assert.equal(ageWords(60_000), '1 minute ago');
  assert.equal(ageWords(6 * HOUR), '6 hours ago');
  assert.equal(ageWords(HOUR), '1 hour ago');
  assert.equal(ageWords(72 * HOUR), '3 days ago');
  const s = frontsStatus(true, ready(doc([front(ago(6))])), NOW);
  assert.equal(s.note, '1 front · observed 6 hours ago');
  assert.match(s.basis, /observed 6 hours ago/);
  assert.doesNotMatch(s.basis + s.note, /\d{4}-\d{2}-\d{2}T/, 'no ISO timestamp is shown');
});

test('the band is a width taken from the front\'s own error, drawn under the line, and nothing is a point', () => {
  const d = frontsStatus(true, ready(doc([front(ago(6))])), NOW).drawn;
  const {features} = frontFeatures(d);
  assert.equal(features.length, 1);
  assert.equal(features[0].geometry.type, 'MultiLineString');
  assert.ok(features[0].properties.px0 > 0, 'the band has a width');
  const wide = frontFeatures({fronts: [{...d.fronts[0], bandHalfWidthKm: 3}]}).features[0].properties.px0;
  assert.ok(Math.abs(wide / features[0].properties.px0 - 2) < 1e-4, 'twice the half-width, twice the band');
  const overlay = frontsOverlay(sentinel);
  assert.ok(isDeepStrictEqual(overlay.layers.map(l => l.id), [FRONTS_BAND_LAYER, FRONTS_LAYER]), 'band under the line');
  assert.ok(overlay.layers.every(l => l.type === 'line'), 'lines only: no circle, symbol or fill');
  assert.ok(features.every(f => !/Point/.test(f.geometry.type)), 'no point geometry');
});

test('the uncertainty band preserves its ground width at non-equatorial latitudes and zooms', () => {
  const f = readFronts(doc([front(ago(6))]), REGION).fronts[0];
  for (const lat of [35, 60, -35]) {
    const lines = [[[-121, lat], [-120.9, lat]]];
    const px0 = frontFeatures({fronts: [{...f, lines}]}).features[0].properties.px0;
    for (const zoom of [0, 8, 12]) {
      // Web Mercator's 512-pixel world shrinks ground metres per pixel by cos(latitude).
      const metresPerPixel = 40075016.686 * Math.cos(lat * Math.PI / 180) / (512 * 2 ** zoom);
      const groundWidthMetres = px0 * 2 ** zoom * metresPerPixel;
      assert.ok(Math.abs(groundWidthMetres - 3000) < 0.01,
        `±1.5 km band spans 3000 ground metres at latitude ${lat}, zoom ${zoom}; got ${groundWidthMetres}`);
    }
  }
});

test('an absent, unreadable or malformed file reads "no current front data" and draws nothing', async () => {
  const opts = (status, body) => ({fetchFn: fetchOf(status, body), page: PAGE});
  assert.equal((await regionalFronts(REGION, opts(404, null))).state, 'none');
  assert.equal((await regionalFronts(REGION, opts(500, null))).state, 'error');
  assert.equal((await regionalFronts(REGION, opts(200, new SyntaxError('bad json')))).state, 'error');
  assert.equal((await regionalFronts(REGION, opts(200, {schema_version: 1}))).state, 'error');
  assert.equal((await regionalFronts(REGION, opts(200, doc([{...front(ago(1)), geometry: {type: 'Point', coordinates: [0, 0]}}])))).state, 'error', 'a point is refused');
  assert.equal((await regionalFronts(REGION, {fetchFn: async () => { throw new TypeError('offline'); }, page: PAGE})).state, 'error');
  assert.equal(readFronts(doc([front(ago(1))]), 'other-region'), null, 'another region\'s file is refused');
  for (const feed of [{state: 'none'}, {state: 'error'}]) {
    const s = frontsStatus(true, feed, NOW);
    assert.equal(s.drawn, null);
    assert.match(s.reason, /^No current front data/);
  }
  assert.equal(NONE, 'no current front data');
  assert.equal(frontsStatus(false, {state: 'none'}, NOW).reason, '', 'off: says nothing');
});

test('a front is withheld past the feed\'s limit and never past 72 hours', () => {
  const at = hours => frontsStatus(true, ready(doc([front(ago(hours))])), NOW);
  assert.ok(at(48).drawn, 'exactly at the limit still draws');
  assert.equal(frontsStatus(true, ready(doc([front(new Date(NOW.getTime() - 48 * HOUR - 1000).toISOString())])), NOW).drawn, null, 'one second past it');
  assert.match(at(60).reason, /No current front data/);
  assert.equal(at(60).drawn, null);
  const lax = frontsStatus(true, ready(doc([front(ago(80))], {max_age_hours: 120})), NOW);
  assert.equal(lax.drawn, null, 'a file cannot widen the 72-hour ceiling');
  assert.equal(MAX_AGE_MS, 72 * HOUR);
  assert.equal(frontsStatus(true, ready(doc([front('not a time')])), NOW).drawn, null, 'no usable observation time');
  assert.equal(frontsStatus(true, ready(doc([front(new Date(NOW.getTime() + HOUR).toISOString())])), NOW).drawn, null, 'an observation in the future');
});

test('a front reads as an edge to search, never a fish or catch location', () => {
  const d = frontsStatus(true, ready(doc([front(ago(6))])), NOW).drawn;
  const mark = frontsMark(d, {lon: -120.9, lat: 35.1}, NOW);
  assert.equal(mark.name, 'Temperature front');
  assert.match(mark.kind, /^Observed 6 hours ago$/);
  assert.match(mark.reading, /uncertain by about ±1\.5 km/);
  assert.equal(frontsMark(d, {lon: -119, lat: 34}, NOW), null, 'away from every front there is no mark');
  assert.match(layerEntry('sst-fronts').basis, /not a fish or catch location/);
  assert.doesNotMatch(mark.reading + mark.source + mark.basis, /hotspot|catch here|fish here/i);
});

test('Temp fronts sits beside Temp contrast, off by default in every profile', () => {
  const e = layerEntry('sst-fronts');
  assert.equal(e.control, 'sst-fronts');
  assert.ok(RAIL_IDS.includes('sst-fronts'));
  assert.ok(RAIL_IDS.includes('sst-contrast'));
  assert.equal(layerEntry('sst-contrast').label, 'Temp contrast');
  assert.ok(LAYERS.some(l => l.id === 'sst-contrast'));
  for (const p of Object.values(PROFILE_TABLE)) assert.ok(!p.defaultLayers.includes('sst-fronts'), `off by default for ${p.id}`);
});
