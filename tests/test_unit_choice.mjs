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
    m.setUnits({temp: 'C'}); m.setUnits({temp: 'C'}); assert.equal(saved.get(KEY), '{"temp":"C"}');
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
