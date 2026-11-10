// SC1722-12: Spanish pages write decimals with a comma in the brief tiles, the tide list and the distance line;
// the digits are the ones English prints, and English is unchanged. Real components, synthetic values.
import './helpers/spanish-ready.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'es-decimals-')), 'bundle.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {tileProps} from './web/brief/Tiles.tsx';
      export {TideSpark} from './web/brief/TideSpark.tsx';
      export {WhereToLook} from './web/brief/WhereToLook.tsx';
      export {language} from './web/i18n.ts';
      export {profile, region} from './web/state.ts';
      export {cruiseSpeed} from './web/limits.ts';
      export {reachRange} from './web/reach.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: preparedRendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const tile = (id, value) => ({id, label: id, value, unit: 'ft', detail: 'detail', source: 'NDBC 46042', sourceUrl: null,
  state: 'fresh', ageMs: 60_000, limitMs: 3 * 3_600_000, lastGood: false});

test('tiles: the reading uses a comma in Spanish in every mode, English is String(value), null stays a dash', async () => {
  const {tileProps} = await load();
  const cases = [[70.9, '70.9', '70,9'], [7.2, '7.2', '7,2'], [-1.2, '-1.2', '-1,2'], [0, '0', '0'], [-0, '0', '0'], [7, '7', '7'], [null, '—', '—']];
  for (const id of ['wind', 'swell', 'water', 'tide'])
    for (const [value, en, es] of cases)
      for (const [compact, dense] of [[false, false], [false, true], [true, false]]) {
        assert.equal(tileProps(tile(id, value), compact, dense, 'en').reading, en, `en ${id} ${value}`);
        assert.equal(tileProps(tile(id, value), compact, dense).reading, en, `default ${id} ${value}`);
        assert.equal(tileProps(tile(id, value), compact, dense, 'es').reading, es, `es ${id} ${value} ${compact}/${dense}`);
      }
});

const event = (at, type, heightFt) => ({at, type, heightFt});
const brief = heights => ({tideEvents: heights.map((h, i) => event(`2026-10-08T${String(8 + i * 2).padStart(2, '0')}:00:00.000Z`, i % 2 ? 'L' : 'H', h)),
  tideDatum: 'MLLW', tides: [], tideCurve: []});

test('tide list: one decimal in both languages, Spanish only swaps the separator, signs and ties follow toFixed', async () => {
  const m = await load();
  const heights = [7.2, 7, 0, -1, 1.15, -0.04, 12.34];
  const b = brief(heights), now = new Date('2026-10-08T12:00:00Z');
  const list = html => [...html.matchAll(/ · (-?\d+[.,]\d) ft MLLW/g)].map(x => x[1]);
  try {
    m.language.value = 'en';
    const en = list(m.render(m.h(m.TideSpark, {brief: b, now})));
    assert.deepEqual(en, heights.map(v => v.toFixed(1)), 'English is the toFixed text');
    m.language.value = 'es';
    const es = list(m.render(m.h(m.TideSpark, {brief: b, now})));
    assert.deepEqual(es, en.map(v => v.replace('.', ',')), 'same digits, comma');
    assert.deepEqual(es.slice(0, 4), ['7,2', '7,0', '0,0', '-1,0']);
  } finally { m.language.value = 'en'; }
});

test('distance line: Spanish comma with the same digit, English unchanged, a custom label stays as supplied', async () => {
  const m = await load();
  const spot = (id, nm, distance) => ({id, kind: 'spot', name: `Reef ${id}`, distance, nm, depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.', screen: {inside: false, name: null, distanceM: null, screened: false}});
  const r = {source: 'atlas', label: 'Survey reef atlas', basis: 'How it ranks.', empty: '', harbor: 'Morro Bay',
    picks: [spot('a', 7, '7.0 nm'), spot('b', 2.46, '2.5 nm'), spot('c', 3.1, 'about 3.1 nm out')]};
  try {
    m.profile.value = 'boat'; m.cruiseSpeed.value = 20; m.reachRange.value = {boat: 12};
    m.language.value = 'en'; const en = m.render(m.h(m.WhereToLook, {ranking: r}));
    m.language.value = 'es'; const es = m.render(m.h(m.WhereToLook, {ranking: r}));
    assert.ok(en.includes('7.0 nm') && en.includes('2.5 nm'));
    assert.ok(es.includes('7,0 nm en línea recta') && es.includes('2,5 nm en línea recta'), es);
    assert.ok(!es.includes('7.0 nm') && !es.includes('2.5 nm'));
    m.language.value = 'en';
    assert.ok(m.render(m.h(m.WhereToLook, {ranking: r})) === en, 'en to es to en is the same English page');
  } finally { m.language.value = 'en'; m.cruiseSpeed.value = null; m.reachRange.value = {}; }
});
