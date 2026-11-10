// SC0707-08: the time dock and the season strip follow the chosen language, as display only.
// web/hour.ts still computes every day key and hour in en-US, so ?day= and ?hour= are the same
// in Spanish and English, across the November DST change too; English output is unchanged.
import './helpers/spanish-ready.mjs';   // SC1407-09: the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const TZ = 'America/Los_Angeles';
const ORIGIN = 'https://s.test/map';
const region = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url))).region;
const committed = JSON.parse(readFileSync(new URL('../dist/data/regulations.json', import.meta.url)));

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'dock-i18n-')), 'm.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {TimeDock, dayOptions, dockState, hourText, readout, selectDay, selectHour} from './web/app/TimeDock.tsx';
      export {SeasonStrip} from './web/app/SeasonStrip.tsx';
      export {horizonDays} from './web/hour.ts';
      export {language} from './web/i18n.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}
/** A browser just big enough for setParams: an address and a history that records writes. */
function browser() {
  globalThis.location = {href: ORIGIN};
  globalThis.history = {state: null, pushState: () => {}, replaceState: (_s, _t, url) => { globalThis.location.href = new URL(url, ORIGIN).href; }};
}
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))}; };

test('English dock output is unchanged and Spanish reads the chosen language', async () => {
  const {dayOptions, hourText, readout, dockState, state} = await load();
  const now = new Date('2026-10-05T20:00:00Z');
  assert.deepEqual([hourText(0), hourText(12), hourText(14)], ['12 am', '12 pm', '2 pm']);
  assert.deepEqual([hourText(0, 'es'), hourText(12, 'es'), hourText(14, 'es')], ['0', '12', '14']);
  assert.deepEqual(dayOptions(now, TZ, null).map(o => o.label), ['Today', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon 12']);
  const es = dayOptions(now, TZ, '2026-10-20', 'es').map(o => o.label);
  assert.equal(es[0], 'Hoy');
  assert.match(es[1], /^mar/);
  assert.match(es[7], /^lun 12$/);
  assert.equal(es.at(-1), '10-20', 'a day outside the horizon keeps its numeric MM-DD');
  state.configureStore({storage: memory()});
  state.syncFromURL(`${ORIGIN}?hour=2026-09-01T20:00Z`);
  assert.equal(readout(dockState(now, TZ), TZ), '1 pm · outside the forecast');
  assert.equal(readout(dockState(now, TZ), TZ, 'es'), '13 · fuera del pronóstico');
});

test('?hour= values and day keys are identical in es and en across the November DST change', async () => {
  const {dayOptions, dockState, selectDay, selectHour, horizonDays, state} = await load();
  // Fall back on 2026-11-01 (a 25-hour day, 01:00 repeats); spring forward is 2026-03-08 (23 hours).
  for (const [iso, tz] of [['2026-10-30T20:00:00Z', TZ], ['2026-03-06T20:00:00Z', TZ], ['2026-10-30T20:00:00Z', 'UTC']]) {
    const now = new Date(iso);
    const days = horizonDays(now, tz);
    assert.equal(JSON.stringify(dayOptions(now, tz, null, 'es').map(o => o.value)), JSON.stringify(dayOptions(now, tz, null, 'en').map(o => o.value)));
    if (tz === TZ && iso.startsWith('2026-10')) {
      const fall = days.find(d => d.day === '2026-11-01');
      assert.equal(fall.hours.length, 25, 'the fall-back day keeps 25 distinct instants');
      assert.equal(new Set(fall.hours).size, 25);
    }
    if (tz === TZ && iso.startsWith('2026-03')) assert.equal(days.find(d => d.day === '2026-03-08').hours.length, 23);
    // Selecting every chip and every hour of every day writes the same URL values whatever the language.
    const written = lang => {
      const out = [];
      for (const opt of dayOptions(now, tz, null, lang)) {
        browser();
        state.configureStore({storage: memory()});
        state.syncFromURL(ORIGIN);
        selectDay(now, tz, opt.value, dockState(now, tz));
        out.push([opt.value, location.href, state.day.value, state.hour.value, dockState(now, tz).index]);
      }
      for (const d of days) for (const at of d.hours) {
        browser();
        state.configureStore({storage: memory()});
        state.syncFromURL(ORIGIN);
        selectHour(now, tz, at);
        const s = dockState(now, tz);
        out.push([at, location.href, state.day.value, state.hour.value, s.day, s.index]);
      }
      return JSON.stringify(out);
    };
    assert.equal(written('es'), written('en'));
    delete globalThis.location; delete globalThis.history;
  }
});

test('the dock renders Spanish labels and restores English exactly', async () => {
  const {TimeDock, language, render, h, state} = await load();
  const now = new Date('2026-10-05T20:00:00Z');
  state.configureStore({storage: memory()});
  state.syncFromURL(ORIGIN);
  const html = () => render(h(TimeDock, {now}));
  language.value = 'en';
  const en = html();
  assert.match(en, /aria-label="Time"/);
  assert.match(en, /aria-label="Day"/);
  assert.match(en, /aria-label="Play"/);
  assert.match(en, /aria-label="Hour"/);
  assert.match(en, />1 pm</);
  assert.match(en, />Today · Unknown</, 'the chip carries its day verdict word (SC2252-06)');
  language.value = 'es';
  const es = html();
  for (const word of ['aria-label="Tiempo"', 'aria-label="Día"', 'aria-label="Reproducir"', 'aria-label="Hora"', '>Hoy · Desconocido<', '>13<']) assert.ok(es.includes(word), word);
  assert.ok(!es.includes('Today') && !es.includes('Play') && !es.includes('Unknown'));
  language.value = 'en';
  assert.equal(html(), en, 'English restores byte for byte');
});

const calendar = year => {
  const d = structuredClone(committed);
  d.rules_review_status = 'reviewed';
  d.valid_from = `${year}-01-01`; d.valid_through = `${year}-12-31`;
  for (const p of Object.values(d.species)) p.windows = [{start: d.valid_from, end: d.valid_through}];
  return d;
};

test('season strip: every state and every run in Spanish, English unchanged, invalid data still null', async () => {
  const {SeasonStrip, language, render, h} = await load();
  const {seasonYear} = await import('../web/season.ts');
  const d = calendar(2026);
  // Three separate openings in January: two are spelled out, one counted; then a not-reviewed tail.
  d.species.lingcod.windows = [{start: '2026-01-02', end: '2026-01-04'}, {start: '2026-01-10', end: '2026-01-10'}, {start: '2026-01-20', end: '2026-01-25'}];
  const en = seasonYear(d, 'lingcod', region, 2026).months, es = seasonYear(d, 'lingcod', region, 2026, 'es').months;
  assert.equal(en[0].label, 'Part open: 2–4, 10–10 and 1 more');
  assert.equal(es[0].label, 'Abierto parcialmente: 2–4, 10–10 y 1 más');
  assert.equal(es[1].label, 'Cerrado');
  assert.deepEqual(es.map(m => [m.month, m.state]), en.map(m => [m.month, m.state]), 'only the labels differ');
  const all = seasonYear(committed, 'lingcod', region, 2026, 'es').months.map(m => m.label);
  assert.ok(all.includes('Sin revisar') && all.includes('Abierto'));
  assert.equal(seasonYear(d, 'lingcod', region, 99999, 'es'), null);
  assert.equal(seasonYear(d, 'nope', region, 2026, 'es'), null);
  const strip = () => render(h(SeasonStrip, {data: d, species: 'lingcod', region, year: 2026}));
  language.value = 'en';
  const enHtml = strip();
  assert.match(enHtml, /<h4>[^<]*season · 2026<\/h4>/);
  assert.match(enHtml, /<span>Jan<\/span> <span>Part open: 2–4, 10–10 and 1 more<\/span>/);
  assert.match(enHtml, /From the reviewed rules \(revision [^)]*\)\. Not legal advice; check the official page\. <a /);
  language.value = 'es';
  const esHtml = strip();
  assert.match(esHtml, /Temporada de [^<]* · 2026<\/h4>/);
  assert.match(esHtml, /aria-label="Temporada de [^"]* 2026"/);
  assert.match(esHtml, /<span>ene<\/span> <span>Abierto parcialmente: 2–4, 10–10 y 1 más<\/span>/);
  assert.match(esHtml, /No es asesoría legal; consulta la página oficial\. <a /);
  assert.equal(esHtml.match(/href="[^"]*"/)[0], enHtml.match(/href="[^"]*"/)[0], 'the official link is unchanged');
  language.value = 'en';
  assert.equal(strip(), enHtml, 'English restores byte for byte');
});
