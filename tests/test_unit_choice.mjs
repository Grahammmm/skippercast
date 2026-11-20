import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname, KEY = 'skippercast-units-v1';
async function load(raw = null, blocked = false) {
  const saved = new Map([[KEY, raw]]), before = globalThis.localStorage;
  globalThis.localStorage = {getItem: key => { if (blocked) throw Error('blocked'); return saved.get(key) ?? null; },
    setItem: (key, value) => { if (blocked) throw Error('blocked'); saved.set(key, value); }};
  try {
    const out = join(await mkdtemp(join(tmpdir(), 'unit-choice-')), 'test.mjs');
    await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {units, setUnits} from './web/unit-choice.ts';
      export {fToC} from './web/units.ts';
      export {Tiles, tileProps, emptyTiles} from './web/brief/Tiles.tsx';
      export {UnitChoice} from './web/app/UnitChoice.tsx';
      export {hourlyCells, overLimits} from './web/hourly-table.ts';
      export {language} from './web/i18n.ts';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
    jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
    return {m: await import(pathToFileURL(out).href), saved, restore: () => { globalThis.localStorage = before; }};
  } catch (error) { globalThis.localStorage = before; throw error; }
}
const water = (value = 59, state = 'fresh') => Object.freeze({id: 'water', label: 'Water', value, unit: '°F',
  detail: 'buoy 46042', source: 'NDBC 46042', sourceUrl: null, state, ageMs: 60000, limitMs: 3600000});

test('water_tile_celsius: all layouts convert only at render; stale readings keep their state', async () => {
  const {m, restore} = await load();
  try {
    m.setUnits({temp: 'C'});
    for (const state of ['fresh', 'stale']) for (const [compact, dense] of [[false, false], [true, false], [false, true]]) {
      const tile = water(59, state), p = m.tileProps(tile, compact, dense);
      assert.equal(p.reading, '15'); assert.equal(p.unit, '°C'); assert.equal(p.stale, state === 'stale');
      assert.equal(tile.value, 59); assert.equal(tile.unit, '°F');
    }
    assert.equal(m.fToC(32), 0); assert.equal(m.fToC(212), 100);
    assert.equal(m.tileProps({...water(), id: 'wind', unit: 'kt'}).reading, '59');
  } finally { restore(); }
});
test('units_default_fahrenheit and remembered choice, duplicate selection and switching back', async () => {
  const {m, saved, restore} = await load();
  try {
    assert.equal(m.units.value.temp, 'F'); assert.equal(m.tileProps(water(59.9)).reading, '59.9');
    assert.equal(m.tileProps(water()).unit, '°F');
    m.setUnits({temp: 'C'}); m.setUnits({temp: 'C'}); assert.equal(saved.get(KEY), '{"temp":"C","wind":"kt","height":"ft"}');
    const reloaded = await load(saved.get(KEY));
    try { assert.equal(reloaded.m.units.value.temp, 'C'); } finally { reloaded.restore(); }
    m.setUnits({temp: 'F'}); assert.equal(m.tileProps(water()).reading, '59');
  } finally { restore(); }
});
test('units_bad_storage and denied storage default without throwing; invalid choices cannot replace a valid one', async () => {
  for (const raw of ['{x', '{"temp":"K"}', 'null', '[]', '{}']) {
    const {m, restore} = await load(raw);
    try { assert.equal(m.units.value.temp, 'F'); m.setUnits({temp: 'C'}); m.setUnits({temp: 'K'}); assert.equal(m.units.value.temp, 'C'); } finally { restore(); }
  }
  const {m, restore} = await load(null, true);
  try { assert.equal(m.units.value.temp, 'F'); assert.doesNotThrow(() => m.setUnits({temp: 'C'})); assert.equal(m.units.value.temp, 'C'); } finally { restore(); }
});
test('units_missing_reading and units_spanish_decimal: empty and numeric readings use the chosen unit', async () => {
  const {m, restore} = await load();
  try {
    for (const temp of ['F', 'C']) {
      m.setUnits({temp}); assert.equal(m.tileProps(water(null)).reading, '—');
      assert.equal(m.emptyTiles(false)[2].unit, `°${temp}`);
    }
    assert.equal(m.tileProps(water(59.9), false, false, 'es').reading, '15,5');
    assert.equal(m.tileProps(water(59.9)).reading, '15.5');
    m.language.value = 'es'; const html = m.render(m.h(m.UnitChoice));
    assert.ok(html.includes('Temperatura') && html.includes('aria-pressed="true"') && html.includes('°C'));
    const account = await readFile(join(ROOT, 'web/app/AccountMenu.tsx'), 'utf8');
    assert.match(account, /<LanguageChoice\s*\/>\s*<UnitChoice\s*\/>/);
  } finally { restore(); }
});

test('wind_tile_mph: stale readings convert in full and compact tiles; missing gusts stay unknown', async () => {
  const {m, restore} = await load();
  const wind = Object.freeze({...water(10, 'stale'), id: 'wind', unit: 'kt', detail: 'gust 15 kt · from NW',
    display: {parts: [{kind: 'gust', value: 15}, {kind: 'direction', value: 'NW'}]}});
  try {
    m.setUnits({wind: 'mph'});
    for (const compact of [false, true]) {
      const p = m.tileProps(wind, compact);
      assert.equal(`${p.reading} ${p.unit}`, '12 mph'); assert.equal(p.stale, true);
      assert.equal(p.detail, compact ? undefined : 'gust 17 mph · from NW');
    }
    assert.equal(m.tileProps(wind, false, false, 'es').detail, 'ráfaga 17 mph · desde NW');
    const missing = m.tileProps({...wind, value: null, display: {parts: [{kind: 'gust', value: null}]}});
    assert.equal(missing.reading, '—'); assert.equal(missing.detail, 'gust unknown');
    assert.equal(m.emptyTiles(false)[0].unit, 'mph');
    m.setUnits({wind: 'kt'}); assert.equal(m.tileProps(wind).detail, wind.detail);
  } finally { restore(); }
});

const windRow = Object.freeze({wind: 10, windFrom: 315, gust: 15, seas: 2, swell: {h: null}, second: {h: null},
  chop: {h: null}, tide: null, visibilityMi: null, score: null});
test('wind_hourly_kmh and wind_default_knots: only the wind and gust cells change', async () => {
  const {m, restore} = await load();
  try {
    assert.equal(m.hourlyCells(windRow).join('|'), '10 kt from NW|15 kt|2.0 ft|—|—|—|—|—|—');
    assert.equal(m.hourlyCells(windRow, 'en', 'kmh').join('|'), '19 km/h from NW|28 km/h|2.0 ft|—|—|—|—|—|—');
    assert.equal(m.hourlyCells({...windRow, wind: null, gust: null}, 'es', 'kmh').slice(0, 2).join('|'), '—|—');
  } finally { restore(); }
});

test('wind_limits_unchanged: 16 kt exceeds 15 kt in every display unit, but 15 kt does not', async () => {
  const {m, restore} = await load();
  try {
    for (const wind of ['kt', 'mph', 'kmh']) {
      m.setUnits({wind});
      assert.equal(m.overLimits({...windRow, wind: 16}, {wind: 15}).wind, true);
      assert.equal(m.overLimits({...windRow, wind: 15}, {wind: 15}).wind, false);
    }
  } finally { restore(); }
});

test('wind preference migration, invalid and duplicate choices, and the Spanish control', async () => {
  const {m, saved, restore} = await load('{"temp":"C"}');
  try {
    assert.equal(m.units.value.wind, 'kt');
    m.setUnits({wind: 'kmh'}); m.setUnits({wind: 'kmh'}); m.setUnits({wind: 'm/s'});
    assert.equal(m.units.value.wind, 'kmh'); assert.equal(m.units.value.temp, 'C');
    m.language.value = 'es';
    assert.match(m.render(m.h(m.UnitChoice)), /Velocidad del viento.*aria-pressed="true"[^>]*>km\/h/);
    const reloaded = await load(saved.get(KEY));
    try { assert.equal(reloaded.m.units.value.wind, 'kmh'); } finally { reloaded.restore(); }
    const bad = await load('{"temp":"C","wind":"m/s"}');
    try { assert.equal(bad.m.units.value.wind, 'kt'); assert.equal(bad.m.units.value.temp, 'C'); } finally { bad.restore(); }
  } finally { restore(); }
});

const heightTile = (id = 'swell', value = 4, state = 'stale') => Object.freeze({
  ...water(value, state), id, label: id === 'swell' ? 'Swell' : 'Tide', unit: 'ft',
});
const heightRow = Object.freeze({...windRow, seas: 3, swell: {h: 4, period: 12, from: 270},
  second: {h: 2, from: 270}, chop: {h: 1, period: 5}, tide: -0.5, score: 7});
test('height_tile_metres: stale, missing and negative readings; print retains feet', async () => {
  const {m, restore} = await load();
  try {
    const swell = heightTile();
    m.setUnits({height: 'm'});
    for (const compact of [false, true]) {
      const p = m.tileProps(swell, compact);
      assert.equal(`${p.reading} ${p.unit}`, '1.2 m'); assert.equal(p.stale, true);
    }
    assert.equal(m.tileProps(heightTile('tide', -0.5), false, false, 'es').reading, '-0,2');
    assert.equal(m.tileProps(heightTile('tide', null, 'unavailable')).reading, '—');
    assert.equal(m.emptyTiles(false)[3].unit, 'm');
    assert.match(m.render(m.h(m.Tiles, {tiles: [swell]})), /app-print-height[^>]*>[^]*?ui-reading">4<[^]*?ui-tile-unit">ft</);
  } finally { restore(); }
});
test('height_hourly_metres: converts only height cells and preserves blanks and feet limits', async () => {
  const {m, restore} = await load();
  try {
    assert.equal(m.hourlyCells(heightRow, 'en', 'kt', 'm').join('|'), '10 kt from NW|15 kt|0.9 m|1.2 m · 12 s · 270°|0.6 m · from W|0.3 m · 5 s|-0.2 m|—|7.0');
    assert.equal(m.hourlyCells({...windRow, seas: null, second: {h: 0, from: 270}}, 'en', 'kt', 'm').slice(2, 7).join('|'), '—|—|—|—|—');
    for (const [seas, expected] of [[4, false], [4.01, true], [null, false]]) {
      const row = {...heightRow, seas};
      assert.equal(m.hourlyCells(row, 'en', 'kt', 'm')[2], seas === null ? '—' : '1.2 m');
      assert.equal(m.overLimits(row, {seas: 4}).seas, expected);
    }
  } finally { restore(); }
});
test('height_default_feet: invalid saved value, repeated changes and reload', async () => {
  const {m, saved, restore} = await load('{"temp":"C","wind":"mph","height":"yards"}');
  try {
    assert.equal(m.units.value.height, 'ft');
    assert.equal(m.hourlyCells(heightRow).join('|'), '10 kt from NW|15 kt|3.0 ft|4.0 ft · 12 s · 270°|2.0 ft · from W|1.0 ft · 5 s|-0.5 ft|—|7.0');
    m.setUnits({height: 'm'}); m.setUnits({height: 'm'}); m.setUnits({height: 'yards'});
    assert.equal(saved.get(KEY), '{"temp":"C","wind":"mph","height":"m"}');
    m.language.value = 'es';
    assert.match(m.render(m.h(m.UnitChoice)), /Altura del oleaje y la marea.*aria-pressed="true"[^>]*>m</);
    const reloaded = await load(saved.get(KEY));
    try { assert.equal(reloaded.m.tileProps(heightTile()).unit, 'm'); } finally { reloaded.restore(); }
    m.setUnits({height: 'ft'});
    assert.equal(m.tileProps(heightTile()).reading, '4'); assert.equal(m.tileProps(heightTile()).unit, 'ft');
  } finally { restore(); }
});
